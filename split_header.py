#!/usr/bin/env python3
"""
split_header.py - Header icindeki fonksiyon govdelerini .cpp dosyasina tasir.
Sadece Python standart kutuphanesi kullanir (libclang / ctags / clang gerekmez).

  * Header'daki (template olmayan) metot/ctor/dtor/operator/serbest fonksiyon
    govdelerini bulur; header'da govdeyi silip yerine ';' koyar
    (ctor initializer listesi de cpp'ye gider).
  * Ayni isimli .cpp dosyasini uretir:
      - Header'in en ustundeki yorum blogunu (copyright + doxygen) kopyalar,
        icindeki "xxx.h" -> "xxx.cpp" yapar.
      - #include <InterfaceDefinitions/ControllerInterface/xxx.h> ekler
        (--include-prefix ile degistirilebilir).
      - Ayni namespace yapisi icinde, her seviye girintili olarak
        Sinif::metot(...) { ... }  tanimlarini yazar.
      - virtual/static/explicit/inline/override/final ve varsayilan argumanlari temizler.
  * Header'da birakilanlar: template'ler (ve template sinif icindekiler), constexpr,
    consteval, friend, donus tipi 'auto' olanlar, static serbest fonksiyonlar,
    anonim namespace icindekiler, = default / = delete.

Kullanim (Windows cmd / PowerShell / Linux ayni):
    python split_header.py --dry-run Foo.h
    python split_header.py --backup -r src
    python split_header.py --backup --out-dir src -r include\\ContollerInterface
"""
import argparse
import glob

# Uretilen cpp'lerde:  #include <InterfaceDefinitions/ControllerInterface/xxx.h>
DEFAULT_INCLUDE_PREFIX = "InterfaceDefinitions/ControllerInterface"
import os
import re
import shutil
import sys

# =============================================================================
#  1) Tokenizer: yorumlari, preprocessor satirlarini atlar; string/char
#     literallerini tek token yapar. Her token: (metin, bas_ofset, son_ofset)
# =============================================================================
PUNCTS = sorted("""
    ->* <<= >>= <=> ... :: -> ++ -- << >> <= >= == != && || += -= *= /= %= &= |= ^= ## .*
""".split(), key=len, reverse=True)

RE_IDENT = re.compile(r"[A-Za-z_]\w*")
RE_NUMBER = re.compile(r"\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.']|)*")
RE_RAW = re.compile(r'(?:u8|u|U|L)?R"([^()\\\s]{0,16})\(')
RE_STRPFX = re.compile(r'(?:u8|u|U|L)?["\']')


class Tok:
    __slots__ = ("text", "start", "end")

    def __init__(self, text, start, end):
        self.text, self.start, self.end = text, start, end

    def __repr__(self):
        return f"Tok({self.text!r})"


def tokenize(s):
    toks, i, n = [], 0, len(s)
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
            continue
        line_start = False
        m = RE_RAW.match(s, i)
        if m:                                            # R"delim( ... )delim"
            close = ")" + m.group(1) + '"'
            j = s.find(close, m.end())
            j = n if j == -1 else j + len(close)
            toks.append(Tok(s[i:j], i, j))
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
    return toks


# =============================================================================
#  2) Yardimcilar
# =============================================================================
OPEN = {"(": ")", "[": "]", "{": "}"}
CLOSE = {")", "]", "}"}
CLASS_KEYS = {"class", "struct", "union"}
ACCESS = {"public", "private", "protected", "signals", "slots", "Q_SIGNALS", "Q_SLOTS"}
NOT_PARAM_LIST = {"noexcept", "throw", "alignas", "decltype", "__attribute__",
                  "__declspec", "requires", "sizeof", "alignof"}
SKIP_FUNC = {"constexpr", "consteval", "friend"}


def is_ident(t):
    return RE_IDENT.fullmatch(t) is not None


def match(T, i):
    """T[i] bir acma parantezi; eslesen kapama parantezinin indeksini dondurur."""
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
    flat_set = set(flat)
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
        if best is not None:
            # parametre listesinden sonra gelen ilk ':' ctor init listesidir
            if any(T[k].text == ":" for k in flat if best[1] < k < o):
                break
        best = (o, c)
    return best, flat, flat_set


# =============================================================================
#  3) Ayristirici: namespace / sinif kapsamlarini izler, fonksiyon govdelerini toplar
# =============================================================================
def scan(src):
    T = tokenize(src)
    scopes = []            # ("ns", [isimler]) | ("cls", isim|None) | ("link", None)
    found = []
    i, st = 0, 0           # st: o anki bildirimin ilk token indeksi
    n = len(T)

    while i < n:
        t = T[i].text
        if t == ";":
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
            i += 1                       # public: / private slots: vb.
            st = i
        elif t == "{":
            i, st = on_brace(T, st, i, scopes, found)
        else:
            i += 1
    return T, found


def on_brace(T, st, bi, scopes, found):
    """bi indeksindeki '{' icin karar verir. (yeni_i, yeni_st) dondurur."""
    def skip():
        j = match(T, bi) + 1
        return j, j

    if st >= bi:
        return skip()
    first = T[st].text
    if first == "template":
        return skip()

    # namespace X {   /  inline namespace X {   /  namespace a::b {
    k = st + 1 if first == "inline" else st
    if T[k].text == "namespace":
        names = "".join(T[j].text for j in range(k + 1, bi)).split("::")
        scopes.append(("ns", names))
        return bi + 1, bi + 1
    if first == "extern" and st + 1 < bi and T[st + 1].text.startswith('"'):
        scopes.append(("link", None))
        return bi + 1, bi + 1

    flat, groups = top_level(T, st, bi)
    texts = [T[j].text for j in flat]
    if "enum" in texts:
        return skip()

    # class / struct / union tanimi mi?
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
            scopes.append(("cls", name))
            return bi + 1, bi + 1

    if "=" in texts:                     # int a[] = { ... };
        return skip()

    pg, flat, flat_set = find_param_group(T, st, bi)
    if pg is None:                       # int x{5};  veya bilinmeyen makro
        return skip()

    # ctor init listesi: ':' sonrasindaki  uye{...}  suslu parantezlerini atla
    colon = next((j for j in flat if j > pg[1] and T[j].text == ":"), None)
    if colon is not None and bi - 1 > colon and (is_ident(T[bi - 1].text) or T[bi - 1].text == ">"):
        return match(T, bi) + 1, st      # ayni bildirim devam ediyor

    be = match(T, bi)
    record(T, st, pg, flat, colon, bi, be, scopes, found)
    return be + 1, be + 1


def record(T, st, pg, flat, colon, bi, be, scopes, found):
    po, pc = pg
    classes = [nm for kind, nm in scopes if kind == "cls"]
    namespaces = [x for kind, nm in scopes if kind == "ns" for x in nm]
    if any(c is None for c in classes) or any(x == "" for x in namespaces):
        return
    before = [T[j].text for j in flat if j < po]
    if SKIP_FUNC & set(before):
        return
    if not classes and "static" in before:
        return
    if "auto" in before and not any(T[j].text == "->" for j in flat if j > pc):
        return

    # fonksiyon adinin basladigi token
    op = next((j for j in flat if j < po and T[j].text == "operator"), None)
    if op is not None:
        name_i = op
    else:
        name_i = po - 1
        if name_i - 1 >= st and T[name_i - 1].text == "~":
            name_i -= 1
    if not (is_ident(T[name_i].text) or T[name_i].text in ("~", "operator")):
        return

    cut = T[colon].start if colon is not None else T[bi].start
    end = T[be].end
    # header'daki bildirimde 'inline' kalirsa tanim cpp'de oldugu icin link hatasi olur
    inline_toks = [(T[j].start, T[j + 1].start) for j in flat if j < po and T[j].text == "inline"]
    found.append(dict(st=st, po=po, pc=pc, flat=flat, name_i=name_i, cut=cut, inline_toks=inline_toks,
                      bend=end, bstart=T[bi].start, classes=classes, namespaces=namespaces,
                      has_colon=colon is not None))


# =============================================================================
#  4) Metin uretimi
# =============================================================================
def build_signature(src, T, f):
    st, po, pc, flat = f["st"], f["po"], f["pc"], f["flat"]
    edits = []                                       # (bas, son, yeni_metin)
    drop = {"virtual", "explicit", "inline"} | ({"static"} if f["classes"] else set())

    for j in flat:
        tk = T[j]
        if j < po and tk.text in drop:
            e = tk.end
            while src[e:e + 1] in (" ", "\t", "\n", "\r"):
                e += 1
            edits.append((tk.start, e, ""))
        elif j > pc and tk.start < f["cut"] and tk.text in ("override", "final"):
            b = tk.start
            while b > 0 and src[b - 1] in " \t":
                b -= 1
            edits.append((b, tk.end, ""))

    # varsayilan argumanlari sil:  (int a = 1, Foo<int, int> b = {})
    j, depth, angle = po + 1, 0, 0
    while j < pc:
        tx = T[j].text
        if tx in OPEN:
            j = match(T, j) + 1
            continue
        if tx == "=":
            b = T[j].start
            while src[b - 1] in " \t":
                b -= 1
            k, angle = j + 1, 0
            while k < pc:
                tk = T[k].text
                if tk in OPEN:
                    k = match(T, k) + 1
                    continue
                if tk == "<" and is_ident(T[k - 1].text):
                    angle += 1
                elif tk == ">" and angle:
                    angle -= 1
                elif tk == ">>" and angle:
                    angle = max(0, angle - 2)
                elif tk == "," and angle == 0:
                    break
                k += 1
            edits.append((b, T[k - 1].end, ""))
            j = k
            continue
        j += 1

    qual = "".join(c + "::" for c in f["classes"])
    if qual:
        p = T[f["name_i"]].start
        edits.append((p, p, qual))

    out, pos = [], T[st].start
    for b, e, rep in sorted(edits, key=lambda x: (x[0], x[1])):
        if b < pos:
            continue
        out.append(src[pos:b])
        out.append(rep)
        pos = e
    out.append(src[pos:f["cut"]])
    sig = "".join(out).strip()
    return re.sub(r"[ \t]*\n[ \t]*", "\n", sig)


def dedent(lines, tab):
    """Ortak bas girintiyi siler (tab'lar 'tab' bosluga cevrilir)."""
    norm = []
    for ln in lines:
        stripped = ln.lstrip(" \t")
        lead = ln[:len(ln) - len(stripped)].expandtabs(tab)
        norm.append((lead, stripped.rstrip()))
    ws = [len(lead) for lead, txt in norm if txt]
    m = min(ws) if ws else 0
    return [(lead[m:] + txt) if txt else "" for lead, txt in norm]


def format_signature(sig, base, ind):
    lines = [ln.strip() for ln in sig.split("\n")]
    return [base + lines[0]] + [base + ind + ln for ln in lines[1:] if ln]


def format_init(src, f, base, ind):
    """Ctor initializer listesi:  ': a(1), b(2)'  -> fonksiyonun bir altinda."""
    if not f["has_colon"]:
        return []
    text = src[f["cut"]:f["bstart"]].strip()
    return [base + ind + ln.strip() for ln in text.split("\n") if ln.strip()]


def format_body(src, f, base, ind, tab):
    """Govdeyi '{' ve '}' ayri satirda, icerik bir seviye iceride olacak sekilde yazar."""
    inner = src[f["bstart"] + 1:f["bend"] - 1]
    lines = inner.split("\n")
    if len(lines) == 1:
        content = [lines[0].strip()] if lines[0].strip() else []
    else:
        first, last = lines[0].strip(), lines[-1].strip()
        content = ([first] if first else []) + dedent(lines[1:-1], tab) + ([last] if last else [])
    while content and not content[0]:
        content.pop(0)
    while content and not content[-1]:
        content.pop()
    out = [base + "{"]
    out += [(base + ind + ln) if ln else "" for ln in content]
    out.append(base + "}")
    return out


def format_definition(src, T, f, base, ind, tab):
    sig = build_signature(src, T, f)
    return "\n".join(format_signature(sig, base, ind) +
                     format_init(src, f, base, ind) +
                     format_body(src, f, base, ind, tab))


def leading_comment_block(text):
    """Dosyanin basindaki // ve /* */ yorumlarini (aradaki bos satirlarla) dondurur."""
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


def func_name(T, f):
    """Rapor icin okunabilir ad:  acme::hw::Sensor::value"""
    name = ""
    for j in range(f["name_i"], f["po"]):
        if name and is_ident(name[-1]) and is_ident(T[j].text[0]):
            name += " "
        name += T[j].text
    return "::".join(f["namespaces"] + f["classes"] + [name])


def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    text = raw.decode("utf-8", errors="surrogateescape").replace("\r\n", "\n")
    return text, eol, bom


def write_text(path, text, eol, bom):
    data = text.replace("\n", eol).encode("utf-8", errors="surrogateescape")
    with open(path, "wb") as fh:
        fh.write((b"\xef\xbb\xbf" if bom else b"") + data)


def process(path, root, out, opt, stats):
    src, eol, bom = read_text(path)
    T, found = scan(src)

    hname = os.path.basename(path)
    base = os.path.splitext(hname)[0]
    cpp_name = base + ".cpp"
    cpp_path = os.path.join(out, cpp_name)

    if not found:
        print(f"[ATLANDI] {path}: tasinacak govde yok")
        stats["skipped"] += 1
        return
    if os.path.exists(cpp_path) and not opt.dry_run:
        print(f"[DOKUNULMADI] {path}: {cpp_path} zaten var")
        stats["exists"] += 1
        return

    ind = " " * opt.indent

    # --- yeni header: (cut .. govde sonu [+ ';']) -> ';'
    new_hdr, pos, defs = [], 0, []
    for f in found:
        cs = f["cut"]
        while cs > 0 and src[cs - 1] in " \t\n":
            cs -= 1
        end = f["bend"]
        m = re.match(r"[ \t]*;", src[end:])
        if m:
            end += m.end()
        for a, b in f["inline_toks"]:
            new_hdr.append(src[pos:a])
            pos = b
        new_hdr.append(src[pos:cs])
        new_hdr.append(";")
        pos = end
        defs.append((f["namespaces"], f))
    new_hdr.append(src[pos:])
    new_header = "".join(new_hdr)

    # --- #include satiri
    hdr_dir = os.path.dirname(os.path.abspath(path))
    if opt.include_prefix == "auto":
        # varsayilan: taranan kok klasorun adi (+ alt klasorler), yoksa header'in klasoru
        prefix = os.path.basename(os.path.abspath(root)) if root else os.path.basename(hdr_dir)
    else:
        prefix = opt.include_prefix
    sub = os.path.relpath(hdr_dir, os.path.abspath(root)) if root else "."
    parts = [p for p in re.split(r"[\\/]+", prefix) + re.split(r"[\\/]+", sub) if p and p != "."]
    inc_path = "/".join(parts + [hname])
    include = f'#include "{inc_path}"' if opt.quotes else f"#include <{inc_path}>"

    # --- cpp metni
    block = leading_comment_block(src)
    block = re.sub(re.escape(base) + r"\.(h|hpp|hh|hxx|H)\b", cpp_name, block)
    lines = ([block.rstrip("\n"), ""] if block.strip() else []) + [include, ""]

    groups = []
    for ns, f in defs:
        if groups and groups[-1][0] == ns:
            groups[-1][1].append(f)
        else:
            groups.append((ns, [f]))
    for ns, fs in groups:
        for d, x in enumerate(ns):
            lines.append(ind * d + f"namespace {x}")
            lines.append(ind * d + "{")
        level = ind * len(ns)
        lines.append("\n\n".join(format_definition(src, T, f, level, ind, opt.indent) for f in fs))
        for d in range(len(ns) - 1, -1, -1):
            lines.append(ind * d + "} // namespace " + ns[d])
        lines.append("")
    cpp_text = "\n".join(lines)

    names = [func_name(T, f) for f in found]
    if opt.dry_run:
        print(f"===== {hname} (yeni) =====\n{new_header}")
        print(f"===== {cpp_path} =====\n{cpp_text}")
    else:
        if opt.backup:
            shutil.copy2(path, path + ".bak")
        write_text(path, new_header, eol, bom)
        os.makedirs(out, exist_ok=True)
        write_text(cpp_path, cpp_text, eol, bom)
    print(f"[TAMAM] {path}: {len(found)} govde -> {cpp_path}   ({include})")
    if opt.verbose:
        for nm in names:
            print(f"         - {nm}")
    stats["done"] += 1
    stats["funcs"] += len(found)


def collect(inputs, recursive, exts):
    """Dosya, klasor veya joker (*.h, src/**/*.h) kabul eder -> (dosya, kok_klasor)."""
    seen = set()
    for a in inputs:
        if os.path.isdir(a):
            if recursive:
                walker = os.walk(a)
            else:
                walker = [(a, [], os.listdir(a))]
            for d, _, files in walker:
                for fn in sorted(files):
                    if fn.lower().endswith(exts):
                        p = os.path.join(d, fn)
                        if p not in seen:
                            seen.add(p)
                            yield p, a
        else:
            matches = sorted(glob.glob(a, recursive=True)) or ([a] if os.path.isfile(a) else [])
            if not matches:
                print(f"[HATA] bulunamadi: {a}", file=sys.stderr)
            for p in matches:
                if os.path.isfile(p) and p not in seen:
                    seen.add(p)
                    yield p, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", metavar="DOSYA_VEYA_KLASOR",
                    help="header dosyasi, klasor veya joker (orn. src\\*.h)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="klasor verildiyse alt klasorleri de tara")
    ap.add_argument("--ext", default=".h",
                    help="klasor taranirken alinacak uzantilar, virgulle (vars.: .h  orn: .h,.hpp)")
    ap.add_argument("--include-prefix", default=DEFAULT_INCLUDE_PREFIX,
                    help="#include <PREFIX/xxx.h> icin PREFIX (vars.: " + DEFAULT_INCLUDE_PREFIX +
                         "; prefix'siz icin --include-prefix \"\", klasor adindan otomatik icin "
                         "--include-prefix auto)")
    ap.add_argument("--quotes", action="store_true", help='#include <...> yerine #include "..." kullan')
    ap.add_argument("--indent", type=int, default=4, help="girinti bosluk sayisi (vars.: 4)")
    ap.add_argument("--out-dir", help="cpp'lerin yazilacagi klasor (vars.: header'in yani). "
                                      "-r ile kullanilirsa alt klasor yapisi korunur")
    ap.add_argument("--dry-run", action="store_true", help="hicbir dosyaya yazmadan sonucu ekrana bas")
    ap.add_argument("--backup", action="store_true", help="degistirmeden once header'in .bak kopyasini al")
    ap.add_argument("-v", "--verbose", action="store_true", help="tasinan her fonksiyonu listele")
    opt = ap.parse_args()

    exts = tuple(e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
                 for e in opt.ext.split(",") if e.strip())
    stats = dict(done=0, skipped=0, exists=0, funcs=0, errors=0)
    for path, root in collect(opt.inputs, opt.recursive, exts):
        hdr_dir = os.path.dirname(os.path.abspath(path))
        if opt.out_dir:
            rel = os.path.relpath(hdr_dir, os.path.abspath(root)) if root else "."
            out = os.path.normpath(os.path.join(opt.out_dir, rel))
        else:
            out = hdr_dir
        try:
            process(path, root, out, opt, stats)
        except Exception as exc:                       # bir dosya hatasi digerlerini durdurmasin
            print(f"[HATA] {path}: {exc}", file=sys.stderr)
            stats["errors"] += 1

    print(f"\nOzet: {stats['done']} dosya donusturuldu ({stats['funcs']} fonksiyon), "
          f"{stats['skipped']} atlandi, {stats['exists']} dosyanin cpp'si zaten vardi, "
          f"{stats['errors']} hata." + ("  [DRY-RUN: hicbir sey yazilmadi]" if opt.dry_run else ""))


if __name__ == "__main__":
    main()
