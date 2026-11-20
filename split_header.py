#!/usr/bin/env python3
"""
header_to_cpp.py - Secilen alt klasorlerdeki header'lardan .cpp uretir ve
hepsini Visual Studio projesine (.vcxproj + .vcxproj.filters) ekler.
Sadece Python standart kutuphanesi kullanir (Python 3.7+).

Beklenen klasor yapisi:
    Kok_Klasor\\                        <- --root (vars.: bulunulan klasor)
        Proje.vcxproj
        Proje.vcxproj.filters
        Alt_Klasor_1\\   *.h  (+ varsa alt klasorleri)
        Alt_Klasor_2\\   *.h
        Alt_Klasor_3\\   *.h

Sadece komut satirinda adi verilen alt klasorler islenir; digerlerine dokunulmaz.

ADIM 1 - CPP URETIMI (.cpp'si olmayan header'lar)
  * Template olmayan fonksiyon govdelerini .cpp'ye tasir, header'da ';' birakir.
  * .cpp'nin basina header'in copyright/doxygen blogunu kopyalar ("Foo.h" -> "Foo.cpp").
  * #include <Kok_Klasor/Alt_Klasor/Foo.h> ekler. Proje precompiled header
    kullaniyorsa once #include "pch.h" (veya projedeki adi) gelir.
  * Namespace'leri girintili yazar; tanimlari Sinif::metot(...) seklinde yazar,
    sinif icindeki tipleri (enum, struct, typedef) donus tipinde Sinif::Tip yapar.
  * #if / #ifdef icindeki fonksiyonlari .cpp'de ayni kosulla sarar.
  * Header'da birakilanlar: template, constexpr, consteval, friend, donus tipi
    'auto', static serbest fonksiyon, anonim namespace/sinif icindekiler.
  * Ayni isimli .cpp zaten varsa o header'a dokunulmaz.

ADIM 2 - PROJE (.vcxproj ve .vcxproj.filters)
  Solution Explorer'da gorunum:
      Proje
      |-- Alt_Klasor_1
      |   |-- Header Files     <- klasordeki tum header'lar
      |   `-- Source Files     <- klasordeki .cpp'ler
      `-- (verilmeyen klasorler oldugu gibi kalir)
  * Projede olmayanlari ekler, baska filtrede olanlari tasir, eksik filtreleri olusturur.
  * Onceden var olan ama projede olmayan .cpp'ler eklenmez (uyari verir);
    --add-existing-cpp ile eklenir. Yaninda Foo.h.bak olanlar eklenir.

Kullanim (Kok_Klasor icinde, cmd):
    python header_to_cpp.py --dry-run ControllerInterface RadioInterface
    python header_to_cpp.py --backup ControllerInterface RadioInterface
    python header_to_cpp.py --root C:\\Proje\\InterfaceDefinitions --backup --report rapor.txt ControllerInterface
"""
import argparse
import bisect
import os
import re
import shutil
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"


# =============================================================================
#  0) Cikti (ekran + istege bagli rapor dosyasi)
# =============================================================================
class Log:
    def __init__(self):
        self.lines = []

    def __call__(self, msg=""):
        self.lines.append(msg)
        print(msg)
        sys.stdout.flush()


log = Log()


# =============================================================================
#  1) Tokenizer: yorumlari atlar, preprocessor satirlarini ayrica kaydeder,
#     string/char literallerini tek token yapar.
# =============================================================================
PUNCTS = sorted("""
    ->* <<= >>= <=> ... :: -> ++ -- << >> <= >= == != && || += -= *= /= %= &= |= ^= ## .*
""".split(), key=len, reverse=True)

RE_IDENT = re.compile(r"[A-Za-z_]\w*")
RE_NUMBER = re.compile(r"\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.']|)*")
RE_RAW = re.compile(r'(?:u8|u|U|L)?R"([^()\\\s]{0,16})\(')
RE_STRPFX = re.compile(r'(?:u8|u|U|L)?["\']')


class Tok:
    __slots__ = ("text", "start", "end", "raw")

    def __init__(self, text, start, end, raw=False):
        self.text, self.start, self.end, self.raw = text, start, end, raw

    def __repr__(self):
        return f"Tok({self.text!r})"


def tokenize(s):
    """(tokenlar, direktifler) dondurur. Direktif: (bas, son, metin)."""
    toks, dirs, i, n = [], [], 0, len(s)
    line_start = True
    while i < n:
        c = s[i]
        if c == "\n":
            i += 1
            line_start = True
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if c == "\\" and s.startswith("\n", i + 1):
            i += 2
            continue
        if s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j == -1 else j
            continue
        if s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "#" and line_start:                      # preprocessor satiri
            start = i
            while i < n:
                if s.startswith("/*", i):
                    j = s.find("*/", i + 2)
                    i = n if j == -1 else j + 2
                elif s.startswith("//", i) or s[i] == "\n":
                    break
                elif s.startswith("\\\n", i):
                    i += 2
                else:
                    i += 1
            dirs.append((start, i, s[start:i].rstrip()))
            continue
        line_start = False
        m = RE_RAW.match(s, i)
        if m:                                            # R"delim( ... )delim"
            close = ")" + m.group(1) + '"'
            j = s.find(close, m.end())
            j = n if j == -1 else j + len(close)
            toks.append(Tok(s[i:j], i, j, raw=True))
            i = j
            continue
        m = RE_STRPFX.match(s, i)
        if m:                                            # "..." veya '...'
            q = s[m.end() - 1]
            j = m.end()
            while j < n and s[j] != q and s[j] != "\n":
                j += 2 if s[j] == "\\" else 1
            j = min(j + 1, n)
            toks.append(Tok(s[i:j], i, j))
            i = j
            continue
        m = RE_IDENT.match(s, i) or RE_NUMBER.match(s, i)
        if m:
            toks.append(Tok(m.group(0), i, m.end()))
            i = m.end()
            continue
        for p in PUNCTS:
            if s.startswith(p, i):
                toks.append(Tok(p, i, i + len(p)))
                i += len(p)
                break
        else:
            toks.append(Tok(c, i, i + 1))
            i += 1
    return toks, dirs


def directive_name(text):
    m = re.match(r"#\s*(\w+)", text)
    return m.group(1) if m else ""


class CondMap:
    """Her ofset icin acik #if bloklarini bilir (include guard haric)."""
    OPEN = {"if", "ifdef", "ifndef"}
    MID = {"elif", "else", "elifdef", "elifndef"}

    def __init__(self, toks, dirs):
        self.offsets, self.snaps, self.dir_starts = [], [], [d[0] for d in dirs]
        stack, nid, first, guard_end = [], 0, None, None
        for s, e, text in dirs:
            name = directive_name(text)
            if name in self.OPEN:
                if first is None:
                    first = (nid, s, name, text)
                stack.append((nid, [text]))
                nid += 1
            elif name in self.MID:
                if not stack:
                    continue
                stack[-1][1].append(text)
            elif name == "endif":
                if not stack:
                    continue
                bid, _ = stack.pop()
                if first is not None and bid == first[0]:
                    guard_end = e
            else:
                continue
            self.offsets.append(e)
            self.snaps.append(tuple((bid, tuple(ch)) for bid, ch in stack))

        # include guard: dosyanin ilk #ifndef'i butun kodu sariyorsa yok sayilir
        self.guard = None
        if first is not None and guard_end is not None:
            is_guard_kw = first[2] == "ifndef" or (first[2] == "if" and "defined" in first[3])
            if is_guard_kw and all(first[1] < t.start < guard_end for t in toks):
                self.guard = first[0]

    def at(self, off):
        k = bisect.bisect_right(self.offsets, off) - 1
        snap = self.snaps[k] if k >= 0 else ()
        return tuple(x for x in snap if x[0] != self.guard)

    def directive_between(self, a, b):
        k = bisect.bisect_left(self.dir_starts, a)
        return k < len(self.dir_starts) and self.dir_starts[k] < b


def cond_key(cond):
    return tuple((bid, len(chain)) for bid, chain in cond)


# =============================================================================
#  2) Yardimcilar
# =============================================================================
OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {")", "]", "}"}
CLASS_KEYS = {"class", "struct", "union"}
ACCESS = {"public", "private", "protected", "signals", "slots", "Q_SIGNALS", "Q_SLOTS"}
NOT_PARAM_LIST = {"noexcept", "throw", "alignas", "decltype", "__attribute__",
                  "__declspec", "requires", "sizeof", "alignof"}


def is_ident(t):
    return RE_IDENT.fullmatch(t) is not None


def match(T, i):
    """T[i] bir acma parantezi; eslesen kapama parantezinin indeksi."""
    depth = 0
    for j in range(i, len(T)):
        t = T[j].text
        if t in OPEN:
            depth += 1
        elif t in CLOSE:
            depth -= 1
            if depth == 0:
                return j
    return len(T) - 1


def top_level(T, s, e):
    """[s, e) araliginda derinlik-0 token indeksleri ve (acilis, kapanis) gruplari."""
    flat, groups, i = [], [], s
    while i < e:
        if T[i].text in OPEN:
            j = min(match(T, i), e - 1)
            groups.append((i, j))
            flat.append(i)
            i = j + 1
        else:
            flat.append(i)
            i += 1
    return flat, groups


def find_param_group(T, s, e):
    """Fonksiyonun parametre listesi olan '( ... )' grubunu bulur."""
    flat, groups = top_level(T, s, e)
    stop = e
    for k in flat:                       # bildirgecin bittigi yer: '=' veya '->'
        if T[k].text in ("=", "->"):
            stop = k
            break
    best = None
    for o, c in groups:
        if o >= stop or T[o].text != "(":
            continue
        prev = T[o - 1].text if o > s else ""
        if prev in NOT_PARAM_LIST:
            continue
        if best is not None and any(T[k].text == ":" for k in flat if best[1] < k < o):
            break                        # ':' sonrasi ctor init listesi
        best = (o, c)
    return best, flat


def collapse(text, limit=80):
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= limit else t[:limit - 3] + "..."


# =============================================================================
#  3) Ayristirici
# =============================================================================
class HeaderParser:
    def __init__(self, src):
        self.src = src
        self.T, self.dirs = tokenize(src)
        self.cond = CondMap(self.T, self.dirs)
        self.found = []          # tasinacak fonksiyonlar
        self.kept = []           # (ad, neden) header'da kalanlar

    # ---------------------------------------------------------------- tarama
    def scan(self):
        T, n = self.T, len(self.T)
        scopes = []              # {"kind": ns|cls|link, "names"/"name", "types"}
        i, st = 0, 0
        while i < n:
            t = T[i].text
            if t == ";":
                self.note_types(st, i, scopes)
                i += 1
                st = i
            elif t in ("(", "["):
                i = match(T, i) + 1
            elif t == "}":
                if scopes:
                    scopes.pop()
                i += 1
                st = i
            elif t == ":" and st < i and all(T[k].text in ACCESS for k in range(st, i)):
                i += 1
                st = i
            elif t == "{":
                i, st = self.on_brace(st, i, scopes)
            else:
                i += 1
        return self

    def note_types(self, st, e, scopes):
        """Sinif icindeki 'using X = ..;', 'typedef .. X;', 'class X;' bildirimleri."""
        if not scopes or scopes[-1]["kind"] != "cls" or st >= e:
            return
        T = self.T
        flat, groups = top_level(T, st, e)
        texts = [T[j].text for j in flat]
        types = scopes[-1]["types"]
        if not texts or texts[0] == "friend":
            return
        if texts[0] == "using" and len(texts) >= 3 and is_ident(texts[1]) and texts[2] == "=":
            types.add(texts[1])
        elif texts[0] == "typedef":
            for o, c in groups:          # typedef void (*Cb)(int);
                if T[o].text == "(" and c - o >= 3 and T[o + 1].text in ("*", "&") \
                        and is_ident(T[o + 2].text):
                    types.add(T[o + 2].text)
                    return
            ids = [x for x in texts if is_ident(x)]
            if ids:
                types.add(ids[-1])
        elif texts[0] in CLASS_KEYS or texts[0] == "enum":
            rest = [x for x in texts[1:] if x not in ("class", "struct")]
            if len(rest) == 1 and is_ident(rest[0]):
                types.add(rest[0])

    def on_brace(self, st, bi, scopes):
        T = self.T

        def skip():
            j = match(T, bi) + 1
            return j, j

        if st >= bi:
            return skip()
        first = T[st].text
        if first == "template":
            self.kept.append((collapse(self.src[T[st].start:T[bi].start]), "template"))
            return skip()

        k = st + 1 if first == "inline" else st
        if T[k].text == "namespace":
            names = "".join(T[j].text for j in range(k + 1, bi)).split("::")
            scopes.append({"kind": "ns", "names": names})
            return bi + 1, bi + 1
        if first == "extern" and st + 1 < bi and T[st + 1].text.startswith('"'):
            scopes.append({"kind": "link"})
            return bi + 1, bi + 1

        flat, groups = top_level(T, st, bi)
        texts = [T[j].text for j in flat]
        if "enum" in texts:
            if scopes and scopes[-1]["kind"] == "cls":
                after = texts[texts.index("enum") + 1:]
                after = [x for x in after if x not in ("class", "struct")]
                if after and is_ident(after[0]):
                    scopes[-1]["types"].add(after[0])
            return skip()

        ck = next((j for j in flat if T[j].text in CLASS_KEYS), None)
        if ck is not None and "=" not in texts:
            paren_after = [o for o, c in groups
                           if o > ck and T[o].text == "(" and T[o - 1].text not in NOT_PARAM_LIST]
            if not paren_after:
                name = None
                for j in flat:
                    if j <= ck:
                        continue
                    if T[j].text == ":":
                        break
                    if is_ident(T[j].text) and T[j].text != "final":
                        name = T[j].text
                if name and scopes and scopes[-1]["kind"] == "cls":
                    scopes[-1]["types"].add(name)
                scopes.append({"kind": "cls", "name": name, "types": set()})
                return bi + 1, bi + 1

        if "=" in texts:
            return skip()

        pg, flat = find_param_group(T, st, bi)
        if pg is None:
            return skip()

        colon = next((j for j in flat if j > pg[1] and T[j].text == ":"), None)
        if colon is not None and bi - 1 > colon and (is_ident(T[bi - 1].text) or T[bi - 1].text == ">"):
            return match(T, bi) + 1, st      # uye{...} initializer, bildirim suruyor

        be = match(T, bi)
        self.record(st, pg, flat, colon, bi, be, scopes)
        return be + 1, be + 1

    # ---------------------------------------------------------------- kayit
    def record(self, st, pg, flat, colon, bi, be, scopes):
        T = self.T
        po, pc = pg
        op = next((j for j in flat if j < po and T[j].text == "operator"), None)
        if op is not None:
            name_i = op
        else:
            name_i = po - 1
            if name_i - 1 >= st and T[name_i - 1].text == "~":
                name_i -= 1
        classes = [s for s in scopes if s["kind"] == "cls"]
        namespaces = [x for s in scopes if s["kind"] == "ns" for x in s["names"]]

        q0 = name_i                                  # Later::get -> 'Later::' de ada dahil
        while q0 - 2 >= st and T[q0 - 1].text == "::" and is_ident(T[q0 - 2].text):
            q0 -= 2
        fname = ""
        for j in range(q0, po):
            if fname and is_ident(fname[-1]) and is_ident(T[j].text[0]):
                fname += " "
            fname += T[j].text
        display = "::".join([x or "<anonim>" for x in namespaces] +
                            [c["name"] or "<anonim>" for c in classes] + [fname])

        def keep(reason):
            self.kept.append((display, reason))

        before = {T[j].text for j in flat if j < po}
        cut = T[colon].start if colon is not None else T[bi].start
        cond0 = self.cond.at(T[st].start)

        if not (is_ident(T[name_i].text) or T[name_i].text in ("~", "operator")):
            return keep("fonksiyon adi cozulemedi")
        if any(c["name"] is None for c in classes):
            return keep("anonim sinif")
        if any(x == "" for x in namespaces):
            return keep("anonim namespace")
        for kw in ("constexpr", "consteval", "friend"):
            if kw in before:
                return keep(kw)
        if not classes and "static" in before:
            return keep("static serbest fonksiyon")
        if "auto" in before and not any(T[j].text == "->" for j in flat if j > pc):
            return keep("donus tipi auto")
        if self.cond.directive_between(T[st].start, cut):
            return keep("imzada # direktifi var")
        if cond0 != self.cond.at(T[be].end):
            return keep("#if blogu fonksiyonu boluyor")

        inline_toks = [(T[j].start, T[j + 1].start) for j in flat if j < po and T[j].text == "inline"]
        verbatim = any(T[j].raw and "\n" in T[j].text for j in range(bi, be))
        # sinif disi tanim (inline int Later::get() {..}): header'da bildirim kalamaz, tamamen silinir
        qualified = not classes and name_i > st and T[name_i - 1].text == "::"
        self.found.append(dict(
            st=st, start=T[st].start, qualified=qualified,
            po=po, pc=pc, flat=flat, name_i=name_i, cut=cut, inline_toks=inline_toks,
            bstart=T[bi].start, bend=T[be].end, classes=classes, namespaces=namespaces,
            has_colon=colon is not None, cond=cond0, display=display, verbatim=verbatim))


# =============================================================================
#  4) .cpp metni uretimi
# =============================================================================
def default_end(T, k, pc, use_angle):
    angle = 0
    while k < pc:
        tk = T[k].text
        if tk in OPEN:
            k = match(T, k) + 1
            continue
        if use_angle:
            if tk == "<" and is_ident(T[k - 1].text):
                angle += 1
            elif tk == ">" and angle:
                angle -= 1
            elif tk == ">>" and angle:
                angle = max(0, angle - 2)
        if tk == "," and angle == 0:
            break
        k += 1
    return k, angle


def build_signature(src, T, f):
    st, po, pc, flat, name_i = f["st"], f["po"], f["pc"], f["flat"], f["name_i"]
    classes = f["classes"]
    edits = []                                       # (bas, son, yeni_metin)
    drop = {"virtual", "explicit", "inline"} | ({"static"} if classes else set())

    for j in flat:
        tk = T[j]
        if j < po and tk.text in drop:
            e = tk.end
            while src[e:e + 1] in (" ", "\t", "\n"):
                e += 1
            edits.append((tk.start, e, ""))
        elif j > pc and tk.start < f["cut"] and tk.text in ("override", "final"):
            b = tk.start
            while b > 0 and src[b - 1] in " \t":
                b -= 1
            edits.append((b, tk.end, ""))
        elif st <= j < name_i and classes and is_ident(tk.text) and \
                (j == st or T[j - 1].text not in ("::", ".", "->")):
            # donus tipindeki sinif ici tip:  State  ->  Radio::State
            for lvl in range(len(classes) - 1, -1, -1):
                if tk.text in classes[lvl]["types"]:
                    q = "::".join(c["name"] for c in classes[:lvl + 1]) + "::"
                    edits.append((tk.start, tk.start, q))
                    break

    # varsayilan argumanlari sil:  (int a = 1, Map<int, int> b = {})
    j = po + 1
    while j < pc:
        tx = T[j].text
        if tx in OPEN:
            j = match(T, j) + 1
            continue
        if tx == "=":
            b = T[j].start
            while src[b - 1] in " \t":
                b -= 1
            k, angle = default_end(T, j + 1, pc, True)
            if angle:                                # '<' karsilastirma imiymis
                k, _ = default_end(T, j + 1, pc, False)
            edits.append((b, T[k - 1].end, ""))
            j = k
            continue
        j += 1

    qual = "".join(c["name"] + "::" for c in classes)
    if qual:
        p = T[name_i].start
        edits.append((p, p, qual))

    out, pos = [], T[st].start
    for b, e, rep in sorted(edits, key=lambda x: (x[0], x[1])):
        if b < pos:
            continue
        out.append(src[pos:b])
        out.append(rep)
        pos = e
    out.append(src[pos:f["cut"]])
    return re.sub(r"[ \t]*\n[ \t]*", "\n", "".join(out).strip())


def dedent(lines, tab):
    """Ortak girintiyi siler. (metin, sutun0_mi) listesi dondurur."""
    norm_ = []
    for ln in lines:
        stripped = ln.lstrip(" \t")
        lead = ln[:len(ln) - len(stripped)].expandtabs(tab)
        norm_.append((lead, stripped.rstrip()))
    ws = [len(lead) for lead, txt in norm_ if txt and not txt.startswith("#")]
    m = min(ws) if ws else 0
    out = []
    for lead, txt in norm_:
        if not txt:
            out.append(("", False))
        elif txt.startswith("#") and not lead:
            out.append((txt, True))                  # sutun 0'daki direktif oyle kalir
        else:
            out.append((lead[m:] + txt, False))
    return out


def format_definition(src, T, f, base, ind, tab):
    sig_lines = [ln.strip() for ln in build_signature(src, T, f).split("\n")]
    out = [base + sig_lines[0]] + [base + ind + ln for ln in sig_lines[1:] if ln]
    if f["has_colon"]:
        init = src[f["cut"]:f["bstart"]].strip()
        out += [base + ind + ln.strip() for ln in init.split("\n") if ln.strip()]

    inner = src[f["bstart"] + 1:f["bend"] - 1]
    out.append(base + "{")
    if f["verbatim"]:                                # cok satirli raw string: dokunma
        out.append(inner.lstrip("\n").rstrip())
    else:
        lines = inner.split("\n")
        if len(lines) == 1:
            content = [(lines[0].strip(), False)] if lines[0].strip() else []
        else:
            first, last = lines[0].strip(), lines[-1].strip()
            content = ([(first, False)] if first else []) + dedent(lines[1:-1], tab) + \
                      ([(last, False)] if last else [])
        while content and not content[0][0]:
            content.pop(0)
        while content and not content[-1][0]:
            content.pop()
        for txt, col0 in content:
            out.append(txt if col0 else (base + ind + txt if txt else ""))
    out.append(base + "}")
    return "\n".join(out)


def leading_comment_block(text):
    """Dosyanin basindaki // ve /* */ yorumlari."""
    i, n, last = 0, len(text), 0
    while i < n:
        j = i
        while j < n and text[j] in " \t\r\n":
            j += 1
        if text.startswith("//", j):
            k = text.find("\n", j)
            k = n if k == -1 else k + 1
        elif text.startswith("/*", j):
            k = text.find("*/", j)
            k = n if k == -1 else k + 2
            nl = text.find("\n", k)
            k = n if nl == -1 else nl + 1
        else:
            break
        last = i = k
    return text[:last]


# =============================================================================
#  5) Dosya G/C
# =============================================================================
def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    return raw.decode("utf-8", errors="surrogateescape").replace("\r\n", "\n"), eol, bom


def write_text(path, text, eol, bom):
    data = text.replace("\n", eol).encode("utf-8", errors="surrogateescape")
    with open(path, "wb") as fh:
        fh.write((b"\xef\xbb\xbf" if bom else b"") + data)


def backup(path):
    """path.bak (varsa path.bak2, .bak3 ...) olarak yedekler; eski yedegi ezmez."""
    k, dst = 1, path + ".bak"
    while os.path.exists(dst):
        k += 1
        dst = f"{path}.bak{k}"
    shutil.copy2(path, dst)
    return dst


def norm(p):
    return os.path.normcase(os.path.normpath(p.replace("\\", os.sep).replace("/", os.sep)))


def walk(folder, exts, recursive):
    out = []
    if recursive:
        for d, dirs, files in os.walk(folder):
            dirs.sort()
            out += [os.path.join(d, fn) for fn in sorted(files) if fn.lower().endswith(exts)]
    else:
        out = [os.path.join(folder, fn) for fn in sorted(os.listdir(folder))
               if fn.lower().endswith(exts) and os.path.isfile(os.path.join(folder, fn))]
    return out


# =============================================================================
#  6) ADIM 1: header -> cpp
# =============================================================================
def split_header(path, root, opt, pch):
    src, eol, bom = read_text(path)
    p = HeaderParser(src).scan()
    T, found = p.T, p.found
    res = dict(path=path, cpp=os.path.splitext(path)[0] + ".cpp", moved=[f["display"] for f in found],
               kept=p.kept, eol=eol, bom=bom)
    if not found:
        res["status"] = "nobody"
        return res

    # --- yeni header: (cut .. govde sonu [+ ';']) -> ';'
    new_hdr, pos = [], 0
    for f in found:
        end = f["bend"]
        m = re.match(r"[ \t]*;", src[end:])
        if m:
            end += m.end()
        if f["qualified"]:                           # sinif disi tanim: tamamen kaldir
            a = f["start"]
            ls = src.rfind("\n", 0, a) + 1
            if src[ls:a].strip() == "":
                a = ls
            m = re.match(r"[ \t]*\n", src[end:])
            if m and a == ls:
                end += m.end()
            new_hdr.append(src[pos:a])
            pos = end
            continue
        cs = f["cut"]
        while cs > 0 and src[cs - 1] in " \t\n":
            cs -= 1
        for a, b in f["inline_toks"]:
            new_hdr.append(src[pos:a])
            pos = b
        new_hdr.append(src[pos:cs])
        new_hdr.append(";")
        pos = end
    new_hdr.append(src[pos:])

    # --- #include satirlari
    hname = os.path.basename(path)
    base = os.path.splitext(hname)[0]
    cpp_name = base + ".cpp"
    prefix = os.path.basename(root) if opt.include_prefix is None else opt.include_prefix
    rel_dir = os.path.relpath(os.path.dirname(path), root)
    parts = [x for x in re.split(r"[\\/]+", prefix) + re.split(r"[\\/]+", rel_dir) if x and x != "."]
    inc_path = "/".join(parts + [hname])
    includes = ([f'#include "{pch}"'] if pch else []) + \
               [f'#include "{inc_path}"' if opt.quotes else f"#include <{inc_path}>"]

    # --- cpp metni
    block = leading_comment_block(src)
    block = re.sub(re.escape(base) + r"\.(h|hpp|hh|hxx|H)\b", cpp_name, block)
    lines = ([block.rstrip("\n"), ""] if block.strip() else []) + includes + [""]

    ind = " " * opt.indent
    groups = []
    for f in found:
        if groups and groups[-1][0] == f["namespaces"]:
            groups[-1][1].append(f)
        else:
            groups.append((f["namespaces"], [f]))
    for ns, fs in groups:
        for d, x in enumerate(ns):
            lines.append(ind * d + f"namespace {x}")
            lines.append(ind * d + "{")
        level = ind * len(ns)
        chunks, i = [], 0
        while i < len(fs):                           # ayni #if kosulundakileri birlikte sar
            key = cond_key(fs[i]["cond"])
            j = i
            while j < len(fs) and cond_key(fs[j]["cond"]) == key:
                j += 1
            body = "\n\n".join(format_definition(src, T, f, level, ind, opt.indent) for f in fs[i:j])
            cond = fs[i]["cond"]
            if cond:
                pre = "\n".join(text for _, chain in cond for text in chain)
                body = pre + "\n" + body + "\n" + "\n".join("#endif" for _ in cond)
            chunks.append(body)
            i = j
        lines.append("\n\n".join(chunks))
        for d in range(len(ns) - 1, -1, -1):
            lines.append(ind * d + "} // namespace " + ns[d])
        lines.append("")

    res.update(status="split", new_header="".join(new_hdr), cpp_text="\n".join(lines),
               include=includes[-1])
    return res


# =============================================================================
#  7) ADIM 2: .vcxproj / .vcxproj.filters
# =============================================================================
STD_FILTERS = {
    "Source Files": ("{4FC737F1-C7A5-4376-A066-2A32D752A2FF}",
                     "cpp;c;cc;cxx;c++;cppm;ixx;def;odl;idl;hpj;bat;asm;asmx"),
    "Header Files": ("{93995380-89BD-4b04-88EB-625FBE52EBFB}",
                     "h;hh;hpp;hxx;h++;hm;inl;inc;ipp;xsd"),
}


def q(s):
    return escape(s, {'"': "&quot;"})


def entries(text, tag, proj_dir):
    """{mutlak_normalize_yol: filtre_adi_veya_None}"""
    out = {}
    for el in ET.fromstring(text).iter(NS + tag):
        inc = el.get("Include")
        if inc:
            f = el.find(NS + "Filter")
            out[norm(os.path.join(proj_dir, inc))] = f.text.strip() if f is not None and f.text else None
    return out


def filter_names(text):
    return {el.get("Include") for el in ET.fromstring(text).iter(NS + "Filter") if el.get("Include")}


def canonical_filter(name, known):
    """Var olan filtre adini buyuk/kucuk harf farkini yok sayarak bulur."""
    lower = {k.lower(): k for k in known}
    parts, out = name.split("\\"), []
    for p in parts:
        cand = "\\".join(out + [p])
        out = lower.get(cand.lower(), cand).split("\\")
    return "\\".join(out)


def insert_entries(text, tag, lines):
    """lines'i son <tag Include=...> girdisinin ItemGroup'una ekler; yoksa yeni ItemGroup."""
    if not lines:
        return text
    last = None
    for m in re.finditer(r"^([ \t]*)<" + tag + r"\s+Include=", text, re.M):
        last = m
    if last:
        indent = last.group(1)
        close = text.find("</ItemGroup>", last.end())
        pos = text.rfind("\n", 0, close) + 1
        return text[:pos] + "".join(indent + ln + "\n" for ln in lines) + text[pos:]
    m = re.search(r"^[ \t]*<Import\s+Project=\"[^\"]*Microsoft\.Cpp\.targets\"", text, re.M) \
        or re.search(r"^[ \t]*</Project>", text, re.M)
    ind = "  "
    block = ind + "<ItemGroup>\n" + "".join(ind * 2 + ln + "\n" for ln in lines) + ind + "</ItemGroup>\n"
    return text[:m.start()] + block + text[m.start():]


def set_filters(text, tag, proj_dir, targets):
    """Var olan <tag Include="X"> girdilerinin filtresini targets[X] yapar."""
    rx = re.compile(r"^([ \t]*)<" + tag + r'\s+Include="([^"]*)"\s*(?:/>|>.*?</' + tag + r">)",
                    re.M | re.S)

    def repl(m):
        indent, inc = m.group(1), m.group(2)
        key = norm(os.path.join(proj_dir, inc.replace("&amp;", "&")))
        if key not in targets:
            return m.group(0)
        return (f'{indent}<{tag} Include="{inc}">\n'
                f"{indent}  <Filter>{q(targets[key])}</Filter>\n"
                f"{indent}</{tag}>")
    return rx.sub(repl, text) if targets else text


def filter_def(name):
    guid, ext = STD_FILTERS.get(name, (None, None))
    guid = guid or "{" + str(uuid.uuid4()).upper() + "}"
    lines = [f'<Filter Include="{q(name)}">', f"  <UniqueIdentifier>{guid}</UniqueIdentifier>"]
    if ext:
        lines.append(f"  <Extensions>{ext}</Extensions>")
    return lines + ["</Filter>"]


def detect_pch(ptext, root):
    r = ET.fromstring(ptext)
    if not any((el.text or "").strip() == "Use" for el in r.iter(NS + "PrecompiledHeader")):
        return None
    for el in r.iter(NS + "PrecompiledHeaderFile"):
        if (el.text or "").strip():
            return el.text.strip()
    for c in ("pch.h", "stdafx.h"):
        if os.path.exists(os.path.join(root, c)):
            return c
    return "pch.h"


def update_project(root, proj, subdirs, generated, opt, exts, stats):
    proj_dir = os.path.dirname(proj)
    fpath = proj + ".filters"
    has_f = os.path.exists(fpath)

    ptext, peol, pbom = read_text(proj)
    p_cpp, p_hdr = entries(ptext, "ClCompile", proj_dir), entries(ptext, "ClInclude", proj_dir)
    if has_f:
        ftext, feol, fbom = read_text(fpath)
        f_cpp, f_hdr = entries(ftext, "ClCompile", proj_dir), entries(ftext, "ClInclude", proj_dir)
        known = filter_names(ftext)
    else:
        f_cpp = f_hdr = {}
        known = set()

    def rel(p):
        return os.path.relpath(p, proj_dir).replace("/", "\\")

    add = {"ClCompile": [], "ClInclude": []}         # .vcxproj'a eklenecek
    add_f = {"ClCompile": [], "ClInclude": []}       # .filters'a eklenecek (yol, filtre)
    move = {"ClCompile": {}, "ClInclude": {}}        # filtresi degisecek
    used_filters = []

    def plan(path, tag, proj_map, filt_map, want):
        key = norm(path)
        changed = False
        in_proj = key in proj_map
        if not in_proj:
            add[tag].append(path)
            log(f"[EKLE]    {rel(path)}  -> {want}")
            changed = True
        if has_f:
            if key not in filt_map:
                add_f[tag].append((path, want))
                if in_proj:
                    log(f"[TASI]    {rel(path)}  (filtresiz) -> {want}")
                changed = True
            elif filt_map[key] != want:
                move[tag][key] = want
                log(f"[TASI]    {rel(path)}  {filt_map[key] or '(filtresiz)'} -> {want}")
                changed = True
        if changed and want not in used_filters:
            used_filters.append(want)
        if not changed:
            stats["proj_ok"] += 1
        else:
            stats["proj_changed"] += 1

    gen_set = {norm(p) for p in generated}
    for sd in subdirs:
        sub_rel = os.path.relpath(sd, root).replace("/", "\\")
        base_f = canonical_filter(sub_rel, known)
        hf = canonical_filter(base_f + "\\" + opt.header_filter, known)
        sf = canonical_filter(base_f + "\\" + opt.source_filter, known)

        for h in walk(sd, exts, not opt.no_recursive):
            plan(h, "ClInclude", p_hdr, f_hdr, hf)

        cpps = {norm(c): c for c in walk(sd, (".cpp",), not opt.no_recursive)}
        for g in generated:
            if norm(g).startswith(norm(sd) + os.sep):
                cpps.setdefault(norm(g), g)
        for key in sorted(cpps):
            c = cpps[key]
            stem = os.path.splitext(c)[0]
            ours = key in gen_set or any(os.path.exists(stem + e + ".bak") for e in exts)
            if key in p_cpp or ours or opt.add_existing_cpp:
                plan(c, "ClCompile", p_cpp, f_cpp, sf)
            else:
                log(f"[UYARI]   {rel(c)} projede degil, eklenmedi (eklemek icin --add-existing-cpp)")
                stats["warnings"] += 1

    if not any(add.values()) and not any(add_f.values()) and not any(move.values()):
        log("Projede degisecek bir sey yok.")
        return

    new_p = ptext
    for tag in ("ClCompile", "ClInclude"):
        new_p = insert_entries(new_p, tag, [f'<{tag} Include="{q(rel(p))}" />' for p in add[tag]])
    ET.fromstring(new_p)                             # dogrulama

    if has_f:
        need = []
        lower_known = {k.lower() for k in known}
        for f in used_filters:                       # ust filtreler de olusturulur
            parts = f.split("\\")
            for i in range(1, len(parts) + 1):
                name = "\\".join(parts[:i])
                if name.lower() not in lower_known and name not in need:
                    need.append(name)
        for name in need:
            log(f"[FILTRE]  '{name}' olusturuldu")
        new_f = insert_entries(ftext, "Filter", sum((filter_def(n) for n in need), []))
        for tag in ("ClCompile", "ClInclude"):
            new_f = set_filters(new_f, tag, proj_dir, move[tag])
            new_f = insert_entries(new_f, tag, sum(
                ([f'<{tag} Include="{q(rel(p))}">', f"  <Filter>{q(w)}</Filter>", f"</{tag}>"]
                 for p, w in add_f[tag]), []))
        ET.fromstring(new_f)
    else:
        log(f"[UYARI]   {os.path.basename(fpath)} yok; sadece .vcxproj guncellenir "
            "(Solution Explorer'da filtresiz gorunur).")
        stats["warnings"] += 1

    if opt.dry_run:
        return
    if opt.backup:
        backup(proj)
        if has_f:
            backup(fpath)
    write_text(proj, new_p, peol, pbom)
    if has_f:
        write_text(fpath, new_f, feol, fbom)


# =============================================================================
#  8) Ana akis
# =============================================================================
def fatal(msg):
    log(f"[HATA] {msg}")
    sys.exit(2)


def find_project(root, given):
    if given:
        p = given if os.path.isabs(given) else os.path.join(root, given)
        if not os.path.isfile(p):
            fatal(f"proje dosyasi bulunamadi: {p}")
        return os.path.abspath(p)
    found = sorted(fn for fn in os.listdir(root) if fn.lower().endswith(".vcxproj"))
    if len(found) == 1:
        return os.path.join(root, found[0])
    if not found:
        fatal(f"{root} icinde .vcxproj yok (--proj ile verin ya da --no-project kullanin)")
    fatal(f"birden fazla .vcxproj var: {', '.join(found)} (--proj ile secin)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subdirs", nargs="+", metavar="ALT_KLASOR",
                    help="islenecek alt klasor(ler), kok klasore gore (orn. ControllerInterface)")
    ap.add_argument("--root", default=".", help="vcxproj'un bulundugu kok klasor (vars.: bulunulan klasor)")
    ap.add_argument("--proj", help="kok klasorde birden fazla .vcxproj varsa hangisi")
    ap.add_argument("--no-project", action="store_true", help="sadece cpp uret, vcxproj'a dokunma")
    ap.add_argument("--dry-run", action="store_true", help="hicbir dosyaya yazmadan ne yapilacagini goster")
    ap.add_argument("--print", action="store_true", help="--dry-run ile: uretilecek dosyalarin icerigini bas")
    ap.add_argument("--backup", action="store_true",
                    help="degisen header'larin ve vcxproj/filters'in .bak kopyasini al")
    ap.add_argument("--report", metavar="DOSYA", help="ekran ciktisini bu dosyaya da yaz")
    ap.add_argument("-v", "--verbose", action="store_true", help="tasinan/kalan her fonksiyonu listele")
    ap.add_argument("--ext", default=".h,.hpp", help="header uzantilari (vars.: .h,.hpp)")
    ap.add_argument("--no-recursive", action="store_true", help="alt klasorun alt klasorlerine inme")
    ap.add_argument("--include-prefix", default=None,
                    help="#include <PREFIX/AltKlasor/x.h> icin PREFIX (vars.: kok klasorun adi; "
                         'bos icin --include-prefix "")')
    ap.add_argument("--quotes", action="store_true", help='#include <...> yerine "..." kullan')
    ap.add_argument("--pch", default="auto",
                    help='precompiled header: auto (vcxproj\'dan), none, ya da dosya adi (orn. pch.h)')
    ap.add_argument("--indent", type=int, default=4, help="girinti bosluk sayisi (vars.: 4)")
    ap.add_argument("--header-filter", default="Header Files", help='vars.: "Header Files"')
    ap.add_argument("--source-filter", default="Source Files", help='vars.: "Source Files"')
    ap.add_argument("--add-existing-cpp", action="store_true",
                    help="onceden var olup projede olmayan .cpp'leri de ekle")
    opt = ap.parse_args()

    try:
        run(opt)
    finally:
        if opt.report:
            with open(opt.report, "w", encoding="utf-8") as fh:
                fh.write("\n".join(log.lines) + "\n")


def run(opt):
    root = os.path.abspath(opt.root)
    if not os.path.isdir(root):
        fatal(f"kok klasor bulunamadi: {root}")
    exts = tuple(("." + e.strip().lstrip(".")).lower() for e in opt.ext.split(",") if e.strip())

    # --- alt klasorleri dogrula (hicbir sey yazmadan once)
    subdirs = []
    for s in opt.subdirs:
        p = os.path.abspath(s if os.path.isabs(s) else os.path.join(root, s))
        if not os.path.isdir(p):
            fatal(f"alt klasor bulunamadi: {p}")
        if os.path.normcase(p) == os.path.normcase(root):
            fatal("kok klasorun kendisi verilemez; alt klasor adlarini yazin")
        if not norm(p).startswith(norm(root) + os.sep):
            fatal(f"{p} kok klasorun ({root}) icinde degil")
        if p not in subdirs:
            subdirs.append(p)

    # --- proje dosyasi ve precompiled header
    proj = None
    pch = None if opt.pch.lower() == "none" else (opt.pch if opt.pch.lower() != "auto" else None)
    if not opt.no_project:
        proj = find_project(root, opt.proj)
        try:
            ptext = read_text(proj)[0]
            ET.fromstring(ptext)
            if os.path.exists(proj + ".filters"):
                ET.fromstring(read_text(proj + ".filters")[0])
        except ET.ParseError as exc:
            fatal(f"proje dosyasi okunamadi (XML hatasi): {exc}")
        if opt.pch.lower() == "auto":
            pch = detect_pch(ptext, root)

    def rel(p):
        return os.path.relpath(p, root)

    log(f"Kok klasor : {root}")
    log(f"Proje      : {os.path.basename(proj) if proj else '(yok, --no-project)'}")
    log(f"Klasorler  : {', '.join(rel(s) for s in subdirs)}")
    if pch:
        log(f"PCH        : uretilen cpp'lerin basina #include \"{pch}\" eklenecek")
    if opt.dry_run:
        log("DRY-RUN    : hicbir dosyaya yazilmayacak")

    stats = dict(split=0, funcs=0, kept=0, nobody=0, cpp_exists=0, errors=0,
                 proj_changed=0, proj_ok=0, warnings=0)

    # ======================= ADIM 1
    log("\n=== ADIM 1: CPP URETIMI ===")
    results = []
    for sd in subdirs:
        for h in walk(sd, exts, not opt.no_recursive):
            cpp = os.path.splitext(h)[0] + ".cpp"
            if os.path.exists(cpp):
                log(f"[CPP VAR]       {rel(h)}  ({os.path.basename(cpp)} zaten var, header'a dokunulmadi)")
                stats["cpp_exists"] += 1
                continue
            try:
                r = split_header(h, root, opt, pch)
            except Exception as exc:                   # bir dosya digerlerini durdurmasin
                log(f"[HATA]          {rel(h)}: {exc}")
                stats["errors"] += 1
                continue
            stats["kept"] += len(r["kept"])
            if r["status"] == "nobody":
                log(f"[GOVDE YOK]     {rel(h)}" + (f"  ({len(r['kept'])} fonksiyon header'da kaldi)"
                                                     if r["kept"] else ""))
                stats["nobody"] += 1
            else:
                log(f"[CPP URETILDI]  {rel(h)} -> {os.path.basename(r['cpp'])}  "
                    f"({len(r['moved'])} tasindi" + (f", {len(r['kept'])} header'da kaldi" if r["kept"] else "")
                    + f")  {r['include']}")
                results.append(r)
                stats["split"] += 1
                stats["funcs"] += len(r["moved"])
            if opt.verbose:
                for nm in r["moved"]:
                    log(f"                   tasindi : {nm}")
                for nm, why in r["kept"]:
                    log(f"                   kaldi   : {nm}  [{why}]")
            if opt.dry_run and opt.print and r["status"] == "split":
                log(f"----- {rel(h)} (yeni) -----\n{r['new_header']}")
                log(f"----- {rel(r['cpp'])} -----\n{r['cpp_text']}")

    if not opt.dry_run:
        for r in results:
            if opt.backup:
                backup(r["path"])
            write_text(r["path"], r["new_header"], r["eol"], r["bom"])
            write_text(r["cpp"], r["cpp_text"], r["eol"], r["bom"])

    # ======================= ADIM 2
    if proj:
        log(f"\n=== ADIM 2: PROJE ({os.path.basename(proj)}) ===")
        update_project(root, proj, subdirs, [r["cpp"] for r in results], opt, exts, stats)

    # ======================= OZET
    log("\n=== OZET ===")
    log(f"  cpp uretilen header      : {stats['split']}  ({stats['funcs']} fonksiyon tasindi)")
    log(f"  header'da kalan fonksiyon: {stats['kept']}  (ayrinti icin -v)")
    log(f"  govdesi olmayan header   : {stats['nobody']}")
    log(f"  cpp'si zaten olan header : {stats['cpp_exists']}")
    if proj:
        log(f"  projede degisen dosya    : {stats['proj_changed']}  (zaten dogru: {stats['proj_ok']})")
    log(f"  uyari / hata             : {stats['warnings']} / {stats['errors']}")
    if opt.dry_run:
        log("  [DRY-RUN: hicbir dosya degistirilmedi]")
    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
