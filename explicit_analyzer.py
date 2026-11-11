#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
explicit_ctor_fix.py  -  Tek argumanla cagrilabilen constructor'lari bulur,
listeler ve (istenirse) basina 'explicit' ekler.
Harici bagimlilik YOKTUR (sadece stdlib).

Kural:  MISRA C++:2008 12-1-3 / AUTOSAR A12-1-4 / MISRA C++:2023 15.1.3
        "Tek argumanla cagrilabilen constructor'lar explicit olmali."

Ne yapar:
  * Header dosyalarindaki (SCAN_SOURCES = True ise .cpp'lerdeki de) her
    class / struct / union govdesini bulur (ic ice siniflar dahil).
  * Govdedeki constructor BILDIRIMLERINI bulur ve TEK ARGUMANLA
    CAGRILABILENLERI listeler:
        Foo(int a);                       -> tek parametre
        Foo(int a, bool b = false);       -> digerleri default'lu
        Foo(int a = 0);                   -> hepsi default'lu
        Foo(int a, ...);   template<class... A> Foo(A&&... a);
  * 'explicit' sadece SINIF ICINDEKI bildirime eklenir; .cpp'deki
    'Foo::Foo(...)' tanimlarina dokunulmaz (oraya yazmak derleme hatasidir).
  * Eklenen yer: constructor adinin hemen oncesi
        constexpr Foo(int)   ->  constexpr explicit Foo(int)

Dokunulmayanlar (raporda gorunur):
  ZATEN_EXPLICIT   'explicit' ya da 'explicit(...)' zaten var
  KOPYA_TASIMA     Foo(const Foo&) / Foo(Foo&&)  -> explicit KONMAZ
  SILINMIS         Foo(int) = delete;
  INIT_LIST        Foo(std::initializer_list<T>)  (SKIP_INITIALIZER_LIST)
  SADECE_LISTE     ONLY_FUNDAMENTAL = True iken temel tip olmayan parametre
  BELIRSIZ         bildirimin onunde tanimlanamayan kelime var -> elle bak

Rapordaki 'parametre_kategori':
  temel tip   int, double, bool, std::int32_t, uint8_t, size_t ...
              (+ PROJECT_FUNDAMENTAL_TYPEDEFS)
  isaretci    char*, const Foo* ...   (0 / NULL'dan da sessizce donusur)
  sinif/typedef/sablon   diger her sey

Kullanim:
    python explicit_ctor_fix.py                  # AYARLAR'daki SOURCE_PATHS, dry-run
    python explicit_ctor_fix.py include/ src/    # verilen dizin / dosyalar, dry-run
    python explicit_ctor_fix.py include/ --apply # 'explicit' ekle (.bak yedekli)

  1) Dry-run ile calistir, ekrani ve REPORT_CSV'yi incele.
  2) --apply ile uygula.
  3) Projeyi DERLE.  Cikan derleme hatalari, kodun o constructor ile SESSIZ
     donusum yaptigi yerlerdir (kuralin yakalamak istedigi yerler).  Oralarda
     donusumu acikca yaz:  f(10)  ->  f(Altitude(10)).

Onemli: calistirmadan once commit et (git).  Tekrar calistirmak guvenlidir
(zaten explicit olanlara dokunulmaz).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


# ============================== AYARLAR ==============================

SOURCE_PATHS = [""]               # "" = calisilan dizin; komut satiri yollari bunu ezer
DRY_RUN = True                    # True: hicbir dosya degismez  (--apply ile False)
MAKE_BACKUP = True                # yazmadan once .bak kopyasi
REPORT_CSV = "explicit_ctor_report.csv"

HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx")
SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx")
SCAN_SOURCES = False              # True: .cpp icinde tanimli siniflar da taranir
EXCLUDE_DIRS: set[str] = set()    # atlanacak dizin adlari ('.' ile baslayanlar zaten atlanir)
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

# False: tek argumanli TUM constructor'lar (MISRA C++:2023 15.1.3)
# True : sadece parametresi temel tip olanlar (MISRA C++:2008 12-1-3 / AUTOSAR A12-1-4);
#        digerleri sadece listelenir
ONLY_FUNDAMENTAL = False
SKIP_INITIALIZER_LIST = True      # Foo(std::initializer_list<T>) -> dokunma
                                  # (explicit, 'Foo f = {1, 2};' yazimini bozar)

# Projeye ozel, temel tipe karsilik gelen typedef'ler (kategori icin)
PROJECT_FUNDAMENTAL_TYPEDEFS: set[str] = set()   # ornek: {"LBOOL", "UINT32", "FLOAT64"}

# =====================================================================

ACCESS = {"public", "protected", "private", "signals", "slots", "Q_SIGNALS", "Q_SLOTS"}
SPECIFIERS = {"inline", "constexpr", "consteval", "constinit"}
REJECT_PREFIX = {"friend", "static", "virtual", "typedef", "using", "return", "new",
                 "delete", "operator", "typename", "template", "co_return", "throw"}
FUND_WORDS = {"bool", "char", "char8_t", "char16_t", "char32_t", "wchar_t", "short", "int",
              "long", "signed", "unsigned", "float", "double", "void", "size_t", "ptrdiff_t",
              "intptr_t", "uintptr_t", "intmax_t", "uintmax_t", "nullptr_t", "byte"}
FIXED_INT_RE = re.compile(r"u?int(_least|_fast)?(8|16|32|64)_t")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
MACRO_RE = re.compile(r"[A-Z_][A-Z0-9_]*")


@dataclass
class ClassInfo:
    name: str
    kind: str                 # class / struct / union
    open: int                 # '{' konumu (temizlenmis metinde)
    close: int                # eslesen '}'
    line: int


@dataclass
class Ctor:
    cls: str
    line: int
    name_pos: int             # constructor adinin metindeki konumu (ekleme yeri)
    signature: str
    param_type: str
    category: str
    status: str               # EKLENECEK / EKLENDI / ZATEN_EXPLICIT / ...
    note: str = ""


# --------------------------------------------------------------------
# Dosya okuma / yazma  (BOM, kodlama ve CRLF korunur)
# --------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


def read_text(path: Path) -> tuple[str, str, bool]:
    data = path.read_bytes()
    had_bom = data.startswith(BOM)
    if had_bom:
        data = data[len(BOM):]
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc, had_bom
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("hepsi", b"", 0, 1, f"{path} cozulemedi")


def write_text(path: Path, text: str, enc: str, had_bom: bool) -> None:
    if MAKE_BACKUP:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    payload = text.encode(enc)
    path.write_bytes(BOM + payload if had_bom else payload)


# --------------------------------------------------------------------
# Temizleme: yorum / string / char / raw string / onislemci satirlari
# bosluga cevrilir.  Uzunluk ve satir yapisi AYNEN korunur, boylece
# temiz metindeki konumlar orijinal metinde de gecerlidir.
# --------------------------------------------------------------------

def clean_code(text: str) -> str:
    out = list(text)
    n = len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] not in "\r\n":
                out[k] = " "

    i = 0
    line_start = True                      # satirda henuz sadece bosluk goruldu
    while i < n:
        c = text[i]
        if c == "\n":
            line_start = True
            i += 1
            continue
        if line_start and c in " \t\r\f\v":
            i += 1
            continue
        if line_start and c == "#":        # onislemci: '\' ile devam eden satirlar dahil
            e = i
            while True:
                nl = text.find("\n", e)
                if nl < 0:
                    e = n
                    break
                if text[e:nl].rstrip("\r").endswith("\\"):
                    e = nl + 1
                    continue
                e = nl
                break
            blank(i, e)
            i = e
            continue
        line_start = False
        nxt = text[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            e = text.find("\n", i)
            e = n if e < 0 else e
            blank(i, e)
            i = e
            continue
        if c == "/" and nxt == "*":
            e = text.find("*/", i + 2)
            e = n if e < 0 else e + 2
            blank(i, e)
            i = e
            continue
        if c == '"':
            if i > 0 and text[i - 1] == "R":
                k = text.find("(", i + 1)
                if k != -1:
                    delim = text[i + 1:k]
                    e = text.find(")" + delim + '"', k + 1)
                    e = n if e < 0 else e + len(delim) + 2
                    blank(i, e)
                    i = e
                    continue
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
            continue
        if c == "'":
            k = i - 1
            while k >= 0 and (text[k].isalnum() or text[k] in "_."):
                k -= 1
            tok = text[k + 1:i]
            if tok and tok[0].isdigit():   # 1'000'000 -> rakam ayirici
                i += 1
                continue
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
            continue
        i += 1
    return "".join(out)


# --------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------

def match_close(s: str, i: int, open_ch: str, close_ch: str) -> int:
    """s[i] == open_ch ise eslesen close_ch konumu (yoksa -1)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_ch:
            depth += 1
        elif s[j] == close_ch:
            depth -= 1
            if depth == 0:
                return j
    return -1


def strip_groups(s: str, pattern: str) -> str:
    """Ic ice gruplari (<...>, (...)) disaridan iceriye kadar siler."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(pattern, " ", s)
    return s


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def prev_nonspace(s: str, i: int) -> int:
    i -= 1
    while i >= 0 and s[i].isspace():
        i -= 1
    return i


def next_nonspace(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def split_top_level(s: str) -> list[str]:
    parts, cur = [], []
    depth = 0
    for ch in s:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


# --------------------------------------------------------------------
# Sinif govdeleri
# --------------------------------------------------------------------

CLASS_KW_RE = re.compile(r"\b(class|struct|union)\b")


def find_classes(clean: str) -> list[ClassInfo]:
    """
    'class X { ... }' tanimlari.  Elenenler: enum class, forward declaration
    (class X;), template parametreleri (template<class T>), 'class X* p' gibi
    tip kullanimlari, isimsiz struct'lar.
    """
    out: list[ClassInfo] = []
    n = len(clean)
    for m in CLASS_KW_RE.finditer(clean):
        before = clean[:m.start()].rstrip()
        pm = re.search(r"([A-Za-z_]\w*)$", before)
        if pm and pm.group(1) == "enum":
            continue
        j = m.end()
        paren = angle = 0
        base_at = None
        open_at = None
        while j < n:
            ch = clean[j]
            if ch == "(":
                paren += 1
            elif ch == ")":
                if paren == 0:
                    break
                paren -= 1
            elif paren == 0 and ch == "<":
                angle += 1
            elif paren == 0 and ch == ">":
                if angle == 0:
                    break
                angle -= 1
            elif paren == 0 and angle == 0:
                if ch == "{":
                    open_at = j
                    break
                if ch in ";=" or (ch in "*&" and base_at is None):
                    break
                if ch == "," and base_at is None:
                    break
                if ch == ":":
                    if clean[j + 1:j + 2] == ":":
                        j += 2
                        continue
                    if base_at is None:
                        base_at = j
            j += 1
        if open_at is None:
            continue
        head = clean[m.end():base_at if base_at is not None else open_at]
        head = re.sub(r"\[\[.*?\]\]", " ", head, flags=re.S)
        head = strip_groups(head, r"\([^()]*\)")
        head = strip_groups(head, r"<[^<>]*>")
        idents = [t for t in IDENT_RE.findall(head)
                  if t not in ("final", "alignas", "__declspec", "__attribute__")]
        if not idents:
            continue                        # isimsiz struct / union
        close = match_close(clean, open_at, "{", "}")
        if close < 0:
            continue
        out.append(ClassInfo(idents[-1], m.group(1), open_at, close,
                             line_of(clean, m.start())))
    return out


# --------------------------------------------------------------------
# Constructor bildirimleri
# --------------------------------------------------------------------

def analyze_prefix(prefix: str) -> tuple[str, str]:
    """
    Constructor adinin onundeki kisim (onceki ';' '{' '}' ya da 'public:'
    sonrasindan itibaren).  Donus: (durum, not)
        ("explicit", ...)  zaten explicit
        ("ok", ...)        temiz bildirim
        ("reject", ...)    constructor bildirimi degil (sessizce gec)
        ("unsure", ...)    tanimlanamayan kelime var -> elle bak
    """
    p = prefix
    explicit = False
    note = ""
    # template<...>
    while True:
        m = re.search(r"\btemplate\s*<", p)
        if not m:
            break
        e = match_close(p, m.end() - 1, "<", ">")
        if e < 0:
            return "unsure", "template<...> eslesmedi"
        p = p[:m.start()] + " " + p[e + 1:]
    p = re.sub(r"\[\[.*?\]\]", " ", p, flags=re.S)                 # [[nodiscard]]
    if re.search(r"\bexplicit\s*\(", p):
        explicit = True
        note = "explicit(...) kosullu"
        p = strip_groups(re.sub(r"\bexplicit\s*(?=\()", " ", p), r"\([^()]*\)")
    # MAKRO(...) gruplari:  DISALLOW_COPY(Foo)  __declspec(dllexport)
    p = strip_groups(p, r"\b(?:[A-Z_][A-Z0-9_]*|__declspec|__attribute__)\s*\([^()]*\)")
    toks = re.findall(r"[A-Za-z_]\w*|\S", p)
    unknown = []
    for t in toks:
        if not IDENT_RE.fullmatch(t):
            return "reject", ""
        if t == "explicit":
            explicit = True
        elif t in REJECT_PREFIX:
            return "reject", ""
        elif t in SPECIFIERS or MACRO_RE.fullmatch(t):
            continue
        else:
            unknown.append(t)
    if explicit:
        return "explicit", note
    if unknown:
        return "unsure", f"bildirimin onunde tanimlanamayan kelime: {' '.join(unknown)}"
    return "ok", note


def param_type(param: str) -> str:
    """'const std::string& name = x'  ->  'const std::string&'"""
    p = split_top_level(param.split("=", 1)[0])[0].strip()
    p = re.sub(r"\[[^\]]*\]\s*$", "", p).strip()
    toks = re.findall(r"[A-Za-z_]\w*|::|\.\.\.|[*&<>,]|\S", p)
    if (len(toks) >= 2 and IDENT_RE.fullmatch(toks[-1]) and toks[-2] != "::"
            and toks[-1] not in FUND_WORDS and toks[-1] not in ("const", "volatile")):
        p = p[:p.rstrip().rfind(toks[-1])].rstrip()
    return re.sub(r"\s+", " ", p)


def classify(ptype: str, cls_name: str) -> tuple[str, str]:
    """(kategori, ozel durum)  ozel durum: '' / 'copy' / 'copy_tpl' / 'init_list'"""
    base = re.sub(r"\b(const|volatile|struct|class|enum|typename)\b", " ", ptype)
    base_nr = re.sub(r"\s+", "", base.replace("&", "").replace("...", ""))
    if base_nr == cls_name and "&" in ptype:
        return "kopya/tasima", "copy"
    if re.fullmatch(re.escape(cls_name) + r"<.*>", base_nr) and "&" in ptype:
        return "kopya/tasima (sablon)", "copy_tpl"
    if "initializer_list" in ptype:
        return "sinif/typedef/sablon", "init_list"
    if "*" in ptype:
        return "isaretci", ""
    words = [w for w in IDENT_RE.findall(base.replace("std::", " ")) if w]
    if words and all(w in FUND_WORDS or FIXED_INT_RE.fullmatch(w)
                     or w in PROJECT_FUNDAMENTAL_TYPEDEFS for w in words) \
            and "<" not in base:
        return "temel tip", ""
    return "sinif/typedef/sablon", ""


def find_ctors(text: str, clean: str, cls: ClassInfo) -> list[Ctor]:
    out: list[Ctor] = []
    name = cls.name
    nlen = len(name)
    depth = paren = 0
    i = cls.open + 1
    end = cls.close
    while i < end:
        ch = clean[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        elif (depth == 0 and paren == 0 and clean.startswith(name, i)
              and (i == 0 or not (clean[i - 1].isalnum() or clean[i - 1] == "_"))
              and not (clean[i + nlen:i + nlen + 1].isalnum() or clean[i + nlen:i + nlen + 1] == "_")):
            c = parse_ctor(text, clean, cls, i)
            if c is not None:
                out.append(c)
            i += nlen
            continue
        i += 1
    return out


def parse_ctor(text: str, clean: str, cls: ClassInfo, pos: int) -> Ctor | None:
    name = cls.name
    lp = next_nonspace(clean, pos + len(name))
    if lp >= len(clean) or clean[lp] != "(":
        return None
    pv = prev_nonspace(clean, pos)
    if pv >= 0:
        c1 = clean[pv]
        c2 = clean[pv - 1:pv + 1] if pv >= 1 else ""
        if c1 in "~." or c2 in ("->", "::"):
            return None                       # yikici / cagri / nitelikli ad
        if c1 == ":":                          # 'public:' ya da delegating ctor ': Foo(1)'
            w = re.search(r"([A-Za-z_]\w*)\s*$", clean[:pv])
            if not (w and w.group(1) in ACCESS):
                return None

    # bildirimin baslangici: onceki ';' '{' '}' ya da erisim belirteci ':'
    k = pos - 1
    while k > cls.open:
        ch = clean[k]
        if ch in ";{}":
            break
        if ch == ":" and clean[k - 1] != ":" and clean[k + 1:k + 2] != ":":
            w = re.search(r"([A-Za-z_]\w*)\s*$", clean[:k])
            if w and w.group(1) in ACCESS:
                break
        k -= 1
    state, pnote = analyze_prefix(clean[k + 1:pos])
    if state == "reject":
        return None

    rp = match_close(clean, lp, "(", ")")
    if rp < 0:
        return None
    params_txt = clean[lp + 1:rp].strip()
    params = [] if params_txt in ("", "void") else [p.strip() for p in split_top_level(params_txt)]
    required = sum(1 for p in params
                   if "=" not in p.split("<")[0] and "=" not in strip_groups(p, r"<[^<>]*>")
                   and "..." not in p)
    if not ((required == 1) or (required == 0 and params)):
        return None                            # tek argumanla cagrilamaz

    after = clean[rp + 1:rp + 200]
    deleted = bool(re.match(r"[^;{]*=\s*delete\b", after))

    sig = re.sub(r"\s+", " ", clean[pos:rp + 1]).replace("( ", "(").replace(" )", ")")
    ptype = param_type(params[0]) if params else ""
    category, special = classify(ptype, name)
    if params and "..." in params[0] and params[0].strip() != "...":
        category = "sablon (variadic)"          # template<class... A> Foo(A&&... a)

    c = Ctor(cls=name, line=line_of(text, pos), name_pos=pos, signature=sig,
             param_type=ptype, category=category, status="", note=pnote)
    if state == "explicit":
        c.status = "ZATEN_EXPLICIT"
    elif deleted:
        c.status, c.note = "SILINMIS", "= delete (explicit gereksiz)"
    elif special in ("copy", "copy_tpl"):
        c.status = "KOPYA_TASIMA"
        c.note = ("kopya / tasima constructor'ina explicit KONMAZ" if special == "copy" else
                  "sablon kopya benzeri constructor - donusum constructor'i ise elle explicit yap")
    elif special == "init_list" and SKIP_INITIALIZER_LIST:
        c.status, c.note = "INIT_LIST", "initializer_list constructor'i (SKIP_INITIALIZER_LIST)"
    elif state == "unsure":
        c.status = "BELIRSIZ"
    elif ONLY_FUNDAMENTAL and category != "temel tip":
        c.status, c.note = "SADECE_LISTE", "ONLY_FUNDAMENTAL = True, parametre temel tip degil"
    else:
        c.status = "EKLENECEK" if DRY_RUN else "EKLENDI"
    if len(params) > 1 or required == 0:
        extra = ("diger parametreler default'lu" if required == 1 else "tum parametreler default'lu")
        if "..." in params_txt:
            extra = "variadic"
        c.note = "; ".join(x for x in (c.note, extra) if x)
    return c


# --------------------------------------------------------------------
# Dosya isleme
# --------------------------------------------------------------------

@dataclass
class FileResult:
    path: Path
    ctors: list[Ctor]
    classes: int = 0
    error: str = ""
    written: bool = False


def process_file(path: Path) -> FileResult:
    try:
        text, enc, had_bom = read_text(path)
    except Exception as e:                    # noqa: BLE001
        return FileResult(path, [], error=str(e))
    clean = clean_code(text)
    classes = find_classes(clean)
    ctors: list[Ctor] = []
    for cls in classes:
        ctors.extend(find_ctors(text, clean, cls))
    ctors.sort(key=lambda c: c.name_pos)
    res = FileResult(path, ctors, classes=len(classes))

    todo = [c for c in ctors if c.status in ("EKLENECEK", "EKLENDI")]
    if todo and not DRY_RUN:
        new = text
        for c in sorted(todo, key=lambda c: c.name_pos, reverse=True):
            new = new[:c.name_pos] + "explicit " + new[c.name_pos:]
        write_text(path, new, enc, had_bom)
        res.written = True
    return res


def iter_files(paths: list[str]):
    exts = set(HEADER_EXTENSIONS) | (set(SOURCE_EXTENSIONS) if SCAN_SOURCES else set())
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw) if raw else Path(".")
        if p.is_file():
            cands = [p]
        elif p.is_dir():
            cands = []
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames
                                     if not d.startswith(".") and d not in EXCLUDE_DIRS)
                cands += [Path(dirpath) / f for f in sorted(filenames)
                          if Path(f).suffix.lower() in exts]
        else:
            print(f"UYARI: yol bulunamadi: {p}")
            continue
        for c in cands:
            if c.suffix.lower() not in exts:
                print(f"UYARI: taranmayan uzanti, atlandi: {c}")
                continue
            if c.resolve() not in seen:
                seen.add(c.resolve())
                yield c


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, MAKE_BACKUP, REPORT_CSV
    ap = argparse.ArgumentParser(description="Tek argumanli constructor'lara 'explicit' ekler.")
    ap.add_argument("paths", nargs="*", help="dizin / dosya (bos: AYARLAR'daki SOURCE_PATHS)")
    ap.add_argument("--apply", action="store_true", help="degisiklikleri dosyalara yaz")
    ap.add_argument("--no-backup", action="store_true", help=".bak kopyasi olusturma")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    args = ap.parse_args(argv)
    if args.apply:
        DRY_RUN = False
    if args.no_backup:
        MAKE_BACKUP = False
    if args.report:
        REPORT_CSV = args.report

    results = [process_file(p) for p in iter_files(args.paths or SOURCE_PATHS)]

    for r in results:
        if r.error:
            print(f"--- {r.path} ---\n  HATA: dosya okunamadi: {r.error}\n")
            continue
        if not r.ctors:
            continue
        print(f"--- {r.path} ---")
        for c in r.ctors:
            note = f"  ({c.note})" if c.note else ""
            print(f"  satir {c.line:<5} [{c.status:<14}] {c.signature:<45} "
                  f"param: {c.param_type or '-'}  [{c.category}]{note}")
        print()

    allc = [c for r in results for c in r.ctors]
    cnt: dict[str, int] = {}
    for c in allc:
        cnt[c.status] = cnt.get(c.status, 0) + 1
    print("=" * 78)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  dosya: {len(results)}  sinif: "
          f"{sum(r.classes for r in results)}  tek argumanli ctor: {len(allc)}  |  "
          f"degisen dosya: {sum(1 for r in results if r.written) if not DRY_RUN else sum(1 for r in results if any(c.status == 'EKLENECEK' for c in r.ctors))}")
    print("  " + "  ".join(f"{k}: {v}" for k, v in sorted(cnt.items())))
    print("=" * 78)

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dosya", "satir", "sinif", "constructor", "parametre_tipi",
                    "parametre_kategori", "durum", "aciklama"])
        for r in results:
            if r.error:
                w.writerow([str(r.path), "", "", "", "", "", "HATA", r.error])
            for c in r.ctors:
                w.writerow([str(r.path), c.line, c.cls, c.signature, c.param_type,
                            c.category, c.status, c.note])
    print(f"Rapor: {REPORT_CSV}")
    if DRY_RUN and cnt.get("EKLENECEK"):
        print("Uygulamak icin:  --apply   (sonra projeyi derle; cikan hatalar sessiz "
              "donusum yapilan yerlerdir)")
    if cnt.get("BELIRSIZ"):
        print("BELIRSIZ olanlara elle bak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
