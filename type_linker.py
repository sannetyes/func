#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
type_link.py  -  enum / struct tanimlarinin HEMEN USTUNE link yorumu ekler:  //[types_1]
Harici bagimlilik YOKTUR (sadece stdlib, Python 3.7+).

    typedef enum                         //[types_1]
    {                         ->         typedef enum
        MODE_OFF,                        {
        MODE_ON                              MODE_OFF,
    } Mode_t;                                MODE_ON
                                         } Mode_t;

LISTE DOSYASI  (.csv / .txt / .xlsx)

  1) ID, File, Tip  -  tip adi DOSYA ADINDAN turetilir (TYPE_SUFFIX ayari):
        ID, File, Tip
        types_1, LINEAR.h, Enumeration      -> LINEAR.h icinde  LINEARENUM   (enum)
        types_2, LINEAR.h, Structure        -> LINEAR.h icinde  LINEARSTRUCT (struct)
        types_3, LINEAR,   Type             -> LINEAR.h icinde  LINEARTYPE   (typedef / enum / struct)
     Dosya adinda .h olmasa da olur; harf farki (LinearEnum) tek aday varsa kabul edilir.

  2) Tip sutununda dogrudan tip adi da yazilabilir:
    Dosya;ID;Tip
    colors.h;types_1;Mode_t
    sensor.h;types_2;SensorData
    sensor.h;types_3;struct SensorConfig     <- 'enum' / 'struct' yazilirsa sadece o tur aranir
  * Ayirac otomatik bulunur ( ;  ,  TAB  | ).  Baslik satiri istege bagli; yoksa sira:
    dosya, id, tip  (.h ile biten sutun dosya sutunu sayilir).

PROJE TARAMASI
  * --dir ile verilen proje koku (varsayilan: liste dosyasinin klasoru) ALT KLASORLERIYLE
    taranir; Debug/Release/x64/.vs/.git ... atlanir (EXCLUDE_DIRS, --exclude).
  * Dosya sutunu sadece ad (LINEAR.h) ya da yol (core/LINEAR.h, core\\LINEAR.h) olabilir.
    Ayni adli birden fazla dosyada tanim varsa HATA verilir: listede klasoru yazin.
  * Tip listedeki dosyada yoksa projenin geri kalaninda aranir; tek yerde tanimliysa
    oraya eklenir ve raporda belirtilir (--no-search-all ile kapatilir).
  * Ad farki (LINEARSTRUCT ~ LINEAR_STRUCT ~ Linear_Struct_t) tek aday varsa kabul edilir.

TANINAN TANIMLAR
    enum Color { ... };                      enum class Level : uint8_t { ... };
    typedef enum { ... } Mode_t;             typedef enum State_tag { ... } State;
    struct Point { ... };                    typedef struct { ... } SensorData, *SensorDataPtr;
    struct __attribute__((packed)) H { };    struct MY_API Exported { };     union U { };
    typedef PACKED struct { } P;             typedef __packed struct { } Q;  typedef MY_ALIGN(4) struct { } R;
    typedef unsigned int LUINT32;            typedef void (*Cb)(int);        typedef int Arr[10];
    using Alias = unsigned short;            template <class T> using Vec = std::vector<T>;
  * 'Structure' istenip union ise, 'Enumeration' istenip sadece 'typedef LUINT8 X;' varsa
    da eklenir (raporda not dusulur).
    '{' ayni satirda ya da alt satirda olabilir; namespace / struct icindeki tanimlar da.
  * Tip adi olarak struct/enum etiketi (State_tag) ya da typedef adi (State) kullanilabilir.
  * Ileri bildirim (struct X;), fonksiyon donus tipi, yorum / string / #define icindekiler
    tanim SAYILMAZ.

GUVENLIK
  * Sadece yeni '//[id]' satirlari eklenir, baska hicbir byte degismez (kodlama, BOM,
    CRLF korunur).  Yazmadan once dogrulanir: yorumlar atildiginda kod birebir ayni olmali.
  * Ayni link zaten varsa tekrar eklenmez; tekrar calistirmak guvenlidir.

Kullanim:
    python type_link.py liste.csv                 # DRY-RUN: neyin eklenecegini goster
    python type_link.py liste.csv --apply         # ekle (.bak yedekli)
    python type_link.py liste.xlsx --dir D:\\Proje --apply
    python type_link.py liste.csv --dir .. --exclude "externals;tests" --apply
"""

from __future__ import annotations

import argparse
import bisect
import csv
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


# ============================== AYARLAR ==============================

LINK_FORMAT = "//[{id}]"          # eklenecek satir ('{id}' yerine id gelir)
DRY_RUN = True                    # True: hicbir dosya degismez  (--apply ile False)
MAKE_BACKUP = True                # yazmadan once .bak kopyasi (var olan .bak EZILMEZ)
REPORT_CSV = "type_link_report.csv"        # "" = rapor olusturma (--no-report)
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx")

# Proje taramasi: --dir (varsayilan: liste dosyasinin klasoru) ALT KLASORLERIYLE taranir.
SCAN_RECURSIVE = True
# Atlanacak klasorler: ad ("Debug") ya da koke gore yol ("externals/boost"); harf duyarsiz.
EXCLUDE_DIRS = [".git", ".vs", ".svn", "Debug", "Release", "x64", "Win32", "ARM", "ARM64",
                "bin", "obj", "build", "out", "ipch", "node_modules"]
# Tip listedeki dosyada yoksa TUM projede aranir; tek bir yerde tanimliysa oraya eklenir.
SEARCH_ALL_IF_MISSING = True
# 'enum' / 'struct' istenip sadece 'typedef X Y;' ya da 'using Y = X;' varsa ona eklenir.
ALIAS_FALLBACK = True
# Ad bulunamazsa harf / alt cizgi / _t _e _s eki farki gozardi edilir (TEK aday varsa):
#   LINEARSTRUCT ~ LINEAR_STRUCT ~ Linear_Struct_t
FUZZY_NAMES = True

# Tip sutununda bu kelimeler varsa tip adi DOSYA ADINDAN turetilir:
#   LINEAR.h + Enumeration -> LINEARENUM (enum),  + Structure -> LINEARSTRUCT,  + Type -> LINEARTYPE
# (kelime: (dosya adina eklenecek ek, aranacak tur;  "" = enum / struct / typedef hepsi))
TYPE_SUFFIX = {
    "enumeration": ("ENUM", "enum"), "enum": ("ENUM", "enum"),
    "structure": ("STRUCT", "struct"), "struct": ("STRUCT", "struct"),
    "record": ("STRUCT", "struct"),
    "type": ("TYPE", ""), "typedef": ("TYPE", ""),
}

# =====================================================================

SUFFIX_WORDS = tuple(sorted({v[0].lower() for v in TYPE_SUFFIX.values()} |
                            {"enumeration", "structure"}))

EKLENDI, ZATEN_VAR, UYARI, HATA = "EKLENDI", "ZATEN_VAR", "UYARI", "HATA"
BOM = b"\xef\xbb\xbf"

# ---------------------------------------------------------------- lexer
EOL_RE = re.compile(r"\r\n|\r|\n")
SPLICE_RE = re.compile(r"\\[ \t]*(?:\r\n|\r|\n)")
WS_SPLIT_RE = re.compile(r"[ \t\f\v]+")
NEXT_RE = re.compile(
    r"//|/\*|[\"']"
    r"|(?<![A-Za-z0-9_$])[A-Za-z_$][A-Za-z0-9_$]*(?=[\"'])"
    r"|(?<![A-Za-z0-9_$])\.?[0-9](?:[eEpP][+-]|'(?=[A-Za-z0-9_])|[A-Za-z0-9_$.])*")
STR_RE = {'"': re.compile(r'"(?:[^"\\\r\n]|\\(?:\r\n|[\s\S]))*"'),
          "'": re.compile(r"'(?:[^'\\\r\n]|\\(?:\r\n|[\s\S]))*'")}
RAW_OPEN_RE = re.compile(r'([^ ()\\\t\v\f\r\n"]{0,16})\(')
RAW_PREFIXES = {"R", "LR", "uR", "UR", "u8R"}
TOKEN_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\[\[|\]\]|::|\S")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*$")

KIND_WORDS = {"enum", "struct", "union", "class"}
ATTR_WORDS = {"__attribute__", "__attribute", "__declspec", "alignas", "_Alignas"}
SKIP_IDENTS = {"final", "const", "volatile", "typedef", "__extension__"}


def split_lines(text: str) -> list[tuple[int, int, int]]:
    out, pos = [], 0
    for m in EOL_RE.finditer(text):
        out.append((pos, m.start(), m.end()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text), len(text)))
    return out


def _line_comment_end(text: str, pos: int) -> int:
    while True:
        m = EOL_RE.search(text, pos)
        if not m:
            return len(text)
        j = m.start()
        while j > pos and text[j - 1] in " \t":
            j -= 1
        if j > pos and text[j - 1] == "\\":
            pos = m.end()
            continue
        return m.start()


def _string_end(text: str, q: int) -> int:
    m = STR_RE[text[q]].match(text, q)
    if m:
        return m.end()
    e = EOL_RE.search(text, q)
    return len(text) if not e else e.start()


def lex(text: str):
    """(yorumlar, stringler): [(bas, son)]"""
    comments, strings = [], []
    n, pos = len(text), 0
    while True:
        m = NEXT_RE.search(text, pos)
        if not m:
            break
        s, tok = m.start(), m.group()
        if tok == "//":
            pos = _line_comment_end(text, m.end())
            comments.append((s, pos))
        elif tok == "/*":
            e = text.find("*/", m.end())
            pos = n if e < 0 else e + 2
            comments.append((s, pos))
        elif tok in ('"', "'"):
            pos = _string_end(text, s)
            strings.append((s, pos))
        elif tok[0].isdigit() or tok[0] == ".":
            pos = m.end()
        else:
            q = m.end()
            if tok in RAW_PREFIXES and text[q] == '"':
                rm = RAW_OPEN_RE.match(text, q + 1)
                if rm:
                    close = ")" + rm.group(1) + '"'
                    e = text.find(close, rm.end())
                    pos = n if e < 0 else e + len(close)
                    strings.append((s, pos))
                    continue
            pos = _string_end(text, q)
            strings.append((s, pos))
    return comments, strings


def fingerprint(text: str) -> list[tuple[str, ...]]:
    """Yorumlar atildiktan sonraki kod (mantiksal satir basina token listesi)."""
    comments, strings = lex(text)
    events = sorted([(s, e, False) for s, e in comments] + [(s, e, True) for s, e in strings])
    lines: list[tuple[str, ...]] = []
    cur: list[str] = []

    def code(seg: str) -> None:
        seg = SPLICE_RE.sub("", seg)
        for i, part in enumerate(EOL_RE.split(seg)):
            if i and cur:
                lines.append(tuple(cur))
                cur.clear()
            cur.extend(t for t in WS_SPLIT_RE.split(part) if t)

    pos = 0
    for s, e, is_str in events:
        code(text[pos:s])
        if is_str:
            cur.append("\x00" + text[s:e])
        pos = e
    code(text[pos:])
    if cur:
        lines.append(tuple(cur))
    return lines


def masked_code(text: str, spans) -> str:
    """Yorum, string ve onislemci satirlari bosluk yapilir (konumlar / satirlar korunur)."""
    blank = lambda s: re.sub(r"[^\r\n]", " ", s)  # noqa: E731
    out, pos = [], 0
    for s, e in sorted(spans):
        out.append(text[pos:s])
        out.append(blank(text[s:e]))
        pos = e
    out.append(text[pos:])
    m = "".join(out)
    res, cont = [], False
    for ls, le, lee in split_lines(m):
        line = m[ls:le]
        if cont or line.lstrip(" \t\f\v").startswith("#"):
            cont = bool(re.search(r"\\[ \t]*$", line))
            res.append(" " * len(line) + m[le:lee])
        else:
            res.append(m[ls:lee])
    return "".join(res)


# ---------------------------------------------------------------- tanim bulma

@dataclass
class TypeDef:
    kind: str                 # enum / struct / union / class
    names: list[str]          # etiket + typedef adlari
    line: int                 # linkin eklenecegi satir (0-tabanli)
    pos: int                  # tanimin basladigi konum
    kwpos: int = 0            # struct / enum anahtar kelimesinin konumu


def _skip_group(toks, j, open_t, close_t):
    """toks[j] == open_t; eslesen close_t'nin bir sonrasini dondur"""
    depth = 0
    while j < len(toks):
        t = toks[j][0]
        if t == open_t:
            depth += 1
        elif t == close_t:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return j


MACRO_LIKE_RE = re.compile(r"(?:[A-Z_][A-Z0-9_]*|__[A-Za-z0-9_]+)$")   # PACKED, MY_ALIGN, __packed
QUALIFIERS = {"const", "volatile", "__extension__", "static", "extern", "inline"}


def _skip_back_macros(toks, k):
    """toks[k]'dan geriye: makro gibi adlar (PACKED, __packed), MACRO(...) gruplari,
    __attribute__((..)), [[..]] ve niteleyiciler atlanir. En fazla 8 adim."""
    steps = 0
    while k >= 0 and steps < 8:
        t = toks[k][0]
        if t == ")":                                   # MACRO( ... )  /  __attribute__(( ... ))
            depth, m = 0, k
            while m >= 0:
                if toks[m][0] == ")":
                    depth += 1
                elif toks[m][0] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                m -= 1
            if m <= 0 or not (IDENT_RE.match(toks[m - 1][0]) and
                              (toks[m - 1][0] in ATTR_WORDS or MACRO_LIKE_RE.match(toks[m - 1][0]))):
                return k                               # parantezin onu makro degil
            k = m - 2
        elif t == "]]":
            while k >= 0 and toks[k][0] != "[[":
                k -= 1
            k -= 1
        elif t in QUALIFIERS or t in ATTR_WORDS or (IDENT_RE.match(t) and MACRO_LIKE_RE.match(t)):
            k -= 1
        else:
            return k
        steps += 1
    return k


def find_typedefs(text: str) -> tuple[list[TypeDef], str, list]:
    comments, strings = lex(text)
    code = masked_code(text, comments + strings)
    toks = [(m.group(), m.start()) for m in TOKEN_RE.finditer(code)]
    starts = [ln[0] for ln in split_lines(text)]
    n = len(toks)
    defs: list[TypeDef] = []
    for i, (tok, pos) in enumerate(toks):
        if tok not in KIND_WORDS:
            continue
        if tok in ("struct", "class") and i and toks[i - 1][0] == "enum":
            continue                                   # enum class / enum struct
        j = i + 1
        if tok == "enum" and j < n and toks[j][0] in ("class", "struct"):
            j += 1
        idents: list[str] = []
        in_base = False
        is_def = False
        while j < n and j - i < 400:
            t = toks[j][0]
            if t == "{":
                is_def = True
                break
            if t in ATTR_WORDS:
                j += 1
                if j < n and toks[j][0] == "(":
                    j = _skip_group(toks, j, "(", ")")
                continue
            if t == "[[":
                j = _skip_group(toks, j, "[[", "]]")
                continue
            if in_base:                                # ': Base<T>, Other' / ': uint8_t'
                if t in (";", ")", "}"):
                    break
                j = _skip_group(toks, j, "(", ")") if t == "(" else j + 1
                continue
            if t == ":":
                in_base = True
            elif t == "::":
                pass
            elif IDENT_RE.match(t):
                if t in KIND_WORDS or t == "typedef":
                    break
                if t not in SKIP_IDENTS:
                    idents.append(t)
            elif t == "(" and len(idents) == 1:        # struct MACRO(8) Name {
                j = _skip_group(toks, j, "(", ")")
                continue
            else:                                      # ; = * & , ( ) < > ... -> tanim degil
                break
            j += 1
        if not is_def:
            continue
        names = [idents[-1]] if idents else []
        # baslangic: typedef / const / template<...> geriye dogru
        k, start = i - 1, pos
        while k >= 0 and toks[k][0] in ("const", "volatile", "__extension__"):
            k -= 1
        is_typedef = k >= 0 and toks[k][0] == "typedef"
        if not is_typedef:                             # typedef PACKED / __packed / MACRO(4) struct
            kk = _skip_back_macros(toks, k)
            if kk != k and kk >= 0 and toks[kk][0] == "typedef":
                k, is_typedef = kk, True
        if is_typedef:
            start = toks[k][1]
            k -= 1
            if k >= 0 and toks[k][0] == "__extension__":
                start = toks[k][1]
        elif k >= 0 and toks[k][0] == ">":             # template <...> (parantez ici atlanir)
            depth, paren, m = 0, 0, k
            while m >= 0:
                t = toks[m][0]
                if t == ")":
                    paren += 1
                elif t == "(":
                    paren -= 1
                elif paren == 0 and t == ">":
                    depth += 1
                elif paren == 0 and t == "<":
                    depth -= 1
                    if depth == 0:
                        break
                elif paren == 0 and t in (";", "{", "}"):
                    m = -1
                    break
                m -= 1
            if m > 0 and toks[m - 1][0] == "template":
                start = toks[m - 1][1]
        if is_typedef:                                 # } Name, *NamePtr;
            m = _skip_group(toks, j, "{", "}")
            while m < n and toks[m][0] != ";":
                t = toks[m][0]
                if t in ATTR_WORDS:
                    m += 1
                    if m < n and toks[m][0] == "(":
                        m = _skip_group(toks, m, "(", ")")
                    continue
                if t == "[":
                    m = _skip_group(toks, m, "[", "]")
                    continue
                if t in ("{", "("):
                    break
                if IDENT_RE.match(t) and t not in SKIP_IDENTS:
                    names.append(t)
                m += 1
        kind = "enum" if tok == "enum" else tok
        defs.append(TypeDef(kind, names, bisect.bisect_right(starts, start) - 1, start, pos))
    # duz typedef (suslu parantezsiz):  typedef unsigned int X;   typedef void (*X)(int);
    for i, (tok, pos) in enumerate(toks):
        if tok != "typedef":
            continue
        j, depth, body = i + 1, 0, []
        while j < n and j - i < 400:
            t = toks[j][0]
            if t in ("(", "["):
                depth += 1
            elif t in (")", "]"):
                depth -= 1
            elif t in ("{", "}") or (t == ";" and depth <= 0):
                break
            body.append((t, depth))
            j += 1
        if j >= n or toks[j][0] != ";" or not body:
            continue
        names = []
        for k, (t, d) in enumerate(body):             # fonksiyon isaretcisi: ( * AD )
            if t == "*" and k and body[k - 1][0] == "(" and k + 1 < len(body) \
                    and IDENT_RE.match(body[k + 1][0]):
                names.append(body[k + 1][0])
        if not names:                                  # , ya da ; oncesindeki ad (dizi atlanir)
            body.append((",", 0))
            for k, (t, d) in enumerate(body):
                if t == "," and d == 0:
                    m = k - 1
                    while m >= 0 and (body[m][1] > 0 or body[m][0] in ("]",)):
                        m -= 1
                    if m >= 1 and IDENT_RE.match(body[m][0]) and body[m][0] not in SKIP_IDENTS:
                        names.append(body[m][0])
        if names:
            defs.append(TypeDef("typedef", names, bisect.bisect_right(starts, pos) - 1, pos, pos))
    # C++ takma ad:  using X = unsigned int;   using Cb = void (*)(int);   template<..> using V = ..;
    for i, (tok, pos) in enumerate(toks):
        if tok != "using" or i + 2 >= n or toks[i + 2][0] != "=" or not IDENT_RE.match(toks[i + 1][0]):
            continue
        if toks[i + 1][0] in ("namespace", "enum"):
            continue
        start = pos
        if i and toks[i - 1][0] == ">":                # template <...> using
            depth, m = 0, i - 1
            while m >= 0:
                if toks[m][0] == ">":
                    depth += 1
                elif toks[m][0] == "<":
                    depth -= 1
                    if depth == 0:
                        break
                m -= 1
            if m > 0 and toks[m - 1][0] == "template":
                start = toks[m - 1][1]
        defs.append(TypeDef("typedef", [toks[i + 1][0]], bisect.bisect_right(starts, start) - 1,
                            start, pos))
    return defs, code, comments + strings


# ---------------------------------------------------------------- liste dosyasi

@dataclass
class Row:
    no: int                   # listedeki satir no
    file: str
    id: str
    type_raw: str
    name: str = ""
    kind: str = ""
    status: str = ""
    line: int = 0
    note: str = ""
    target: str = ""
    path: Path | None = None


def _norm_head(s: str) -> str:
    tr = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")
    return re.sub(r"[^a-z0-9]+", " ", s.translate(tr).lower()).strip()


HEAD_WORDS = {
    "file": {"dosya", "dosya adi", "dosya ismi", "dosyaadi", "file", "file name", "filename",
             "header", "header file", "h dosyasi", "kaynak"},
    "id": {"id", "link", "link id", "linkid", "req", "req id", "gereksinim", "gereksinim id",
           "requirement", "requirement id", "kimlik"},
    "type": {"tip", "tip adi", "tip ismi", "type", "type name", "typename", "tur", "isim", "ad",
             "name", "enum struct", "tanim"},
}


def _read_xlsx(path: Path) -> list[list[str]]:
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    with zipfile.ZipFile(str(path)) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(M + "si"):
                shared.append("".join(t.text or "" for t in si.iter(M + "t")))
        sheet = "xl/worksheets/sheet1.xml"
        try:                                           # ilk sayfa (workbook sirasina gore)
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rid = next(wb.iter(M + "sheet")).get(R + "id")
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels:
                if rel.get("Id") == rid:
                    tgt = rel.get("Target").lstrip("/")
                    sheet = tgt if tgt.startswith("xl/") else "xl/" + tgt
        except (KeyError, StopIteration, AttributeError, ET.ParseError):
            pass
        rows = []
        for row in ET.fromstring(z.read(sheet)).iter(M + "row"):
            cells: dict[int, str] = {}
            for c in row.iter(M + "c"):
                ref = re.match(r"[A-Z]+", c.get("r", "A"))
                col = 0
                for ch in ref.group() if ref else "A":
                    col = col * 26 + ord(ch) - 64
                t, v = c.get("t"), c.find(M + "v")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(M + "t"))
                else:
                    val = v.text if v is not None and v.text else ""
                    if re.fullmatch(r"-?\d+\.0", val):
                        val = val[:-2]
                cells[col - 1] = val
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def read_table(path: Path) -> list[list[str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    data = path.read_bytes()
    text = data.decode("latin-1")
    for enc in ("utf-8-sig", "cp1254"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    first = lines[0]
    delim = max(";\t,|", key=first.count)
    if first.count(delim) == 0:
        return [ln.split() for ln in lines]
    return [[c.strip() for c in r] for r in csv.reader(lines, delimiter=delim)]


def read_rows(path: Path) -> tuple[list[Row], list[str]]:
    table = [r for r in read_table(path)]
    msgs: list[str] = []
    rows: list[Row] = []
    if not table:
        return rows, ["liste bos"]
    cols = {"file": 0, "id": 1, "type": 2}
    head = [_norm_head(c) for c in table[0]]
    found = {}
    for idx, h in enumerate(head):
        for key, words in HEAD_WORDS.items():
            if h in words and key not in found:
                found[key] = idx
    start = 0
    if len(found) >= 2:
        start = 1
        rest = [i for i in range(len(head)) if i not in found.values()]
        for key in ("file", "id", "type"):
            if key not in found and rest:
                found[key] = rest.pop(0)
        cols = found
    else:                                              # baslik yok: .h ile biten sutun dosyadir
        body = [r for r in table if any(c.strip() for c in r)]
        width = max(len(r) for r in body)
        hcols = [c for c in range(width)
                 if all(c < len(r) and r[c].strip().lower().endswith(HEADER_EXTENSIONS) for r in body)]
        if len(hcols) == 1 and hcols[0] != 0:
            others = [c for c in range(width) if c != hcols[0]]
            cols = {"file": hcols[0], "id": others[0], "type": others[1] if len(others) > 1 else 2}
            msgs.append(f"baslik yok; sutunlar: dosya={hcols[0] + 1}, id={others[0] + 1}, "
                        f"tip={cols['type'] + 1}")
    for no, r in enumerate(table[start:], start + 1):
        get = lambda k: r[cols[k]].strip() if cols[k] < len(r) else ""  # noqa: E731
        f, i, t = get("file"), get("id"), get("type")
        if not (f or i or t) or f.startswith("#"):
            continue
        rows.append(Row(no, f, i, t))
    return rows, msgs


def parse_type(raw: str) -> tuple[str, str]:
    """'struct SensorConfig' -> ('SensorConfig', 'struct');  'Mode_t' -> ('Mode_t', '')"""
    words = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", raw)
    kinds = [w for w in words if w.lower() in KIND_WORDS]
    names = [w for w in words if w.lower() not in KIND_WORDS and w.lower() != "typedef"]
    kind = ""
    if kinds:
        k = kinds[0].lower()
        kind = "enum" if "enum" in (x.lower() for x in kinds) else ("struct" if k == "class" else k)
    return (names[0] if len(names) == 1 else ""), kind


# ---------------------------------------------------------------- ana is

@dataclass
class HFile:
    path: Path
    raw: bytes
    text: str
    had_bom: bool
    defs: list[TypeDef]
    code: str
    spans: list
    lines: list
    inserts: dict[int, list[Row]] = field(default_factory=dict)


def load(path: Path) -> HFile:
    raw = path.read_bytes()
    had_bom = raw.startswith(BOM)
    body = raw[3:] if had_bom else raw
    text = body.decode("latin-1")                      # byte-saydam
    defs, code, spans = find_typedefs(text)
    return HFile(path, raw, text, had_bom, defs, code, spans, split_lines(text))


def kind_ok(want: str, have: str) -> bool:
    return not want or want == have or (want == "struct" and have in ("class", "union"))


def fuzzy_key(name: str) -> str:
    k = name.lower()
    k = re.sub(r"_(t|e|s|type|tag)$", "", k)
    return k.replace("_", "")


def match_defs(hf: "HFile", name: str, kind: str, fuzzy: bool) -> tuple[list, str, str]:
    """(tanimlar, kullanilan_ad, not)"""
    def exact(nm):
        hits = [d for d in hf.defs if nm in d.names and kind_ok(kind, d.kind)]
        note = ""
        if not hits and kind and ALIAS_FALLBACK:
            hits = [d for d in hf.defs if nm in d.names and d.kind == "typedef"]
            if hits:
                note = f"'{nm}' {kind} degil typedef/using olarak tanimli; o satira eklendi"
        if any(d.kind != "typedef" for d in hits):     # gercek tanim varsa 'typedef X Y;' sayilmaz
            hits = [d for d in hits if d.kind != "typedef"]
        return hits, note
    hits, note = exact(name)
    if hits or not fuzzy:
        return hits, name, note
    key = fuzzy_key(name)
    cands = {nm for d in hf.defs for nm in d.names if fuzzy_key(nm) == key and nm != name}
    if len(cands) == 1:
        nm = cands.pop()
        hits, note2 = exact(nm)
        if hits:
            return hits, nm, f"listede '{name}', dosyada '{nm}' yaziyor" + (f"; {note2}" if note2 else "")
    return [], name, ""


def collect_headers(root: Path, excludes: list[str]) -> list[Path]:
    import os
    names = {e.strip().lower().replace("\\", "/").strip("/") for e in excludes if e.strip()}
    out = []
    if not SCAN_RECURSIVE:
        return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in HEADER_EXTENSIONS)
    for dp, dns, fns in os.walk(root):
        rel = Path(dp).relative_to(root).as_posix().lower()
        keep = []
        for d in dns:
            r = (d if rel == "." else f"{rel}/{d}").lower()
            if d.lower() in names or r in names:
                continue
            keep.append(d)
        dns[:] = sorted(keep)
        out += [Path(dp) / f for f in sorted(fns) if f.lower().endswith(HEADER_EXTENSIONS)]
    return out


def link_re() -> re.Pattern:
    a, _, b = LINK_FORMAT.partition("{id}")
    return re.compile(r"[ \t]*" + re.escape(a.strip()) + r"[ \t]*(.+?)[ \t]*" +
                      re.escape(b.strip()) + r"[ \t]*$")


def existing_links(hf: HFile, line: int) -> set[str]:
    """Tanimin ustundeki link id'leri: yukari dogru yorum / bos satirlar taranir,
    ilk kod ya da #direktif satirinda durulur."""
    rx, ids = link_re(), set()
    for k in range(line - 1, max(line - 200, 0) - 1, -1):
        ls, le, _ = hf.lines[k]
        orig = hf.text[ls:le]
        if hf.code[ls:le].strip() or orig.lstrip(" \t\f\v").startswith("#"):
            break
        m = rx.match(orig)
        if m:
            ids.update(x.strip() for x in m.group(1).split(","))
    return ids


def in_span(spans, pos: int) -> bool:
    return any(s < pos < e for s, e in spans)


def backup_path(path: Path) -> Path:
    b, i = path.with_name(path.name + ".bak"), 2
    while b.exists():
        b, i = path.with_name(f"{path.name}.bak{i}"), i + 1
    return b


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, MAKE_BACKUP, REPORT_CSV
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="enum/struct tanimlarinin ustune //[id] linki ekler.")
    ap.add_argument("liste", help="liste dosyasi (.csv / .txt / .xlsx): dosya, id, tip")
    ap.add_argument("--dir", help="proje koku; alt klasorleriyle taranir (varsayilan: liste dosyasinin klasoru)")
    ap.add_argument("--exclude", help="ek atlanacak klasorler, ';' ile: \"externals;tests/mock\"")
    ap.add_argument("--no-search-all", action="store_true",
                    help="tip listedeki dosyada yoksa projenin geri kalaninda arama")
    ap.add_argument("--apply", action="store_true", help="degisiklikleri dosyalara yaz")
    ap.add_argument("--no-backup", action="store_true", help=".bak kopyasi olusturma")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    ap.add_argument("--no-report", action="store_true", help="CSV raporu olusturma")
    args = ap.parse_args(argv)
    DRY_RUN = not args.apply
    MAKE_BACKUP = MAKE_BACKUP and not args.no_backup
    REPORT_CSV = "" if args.no_report else (args.report or REPORT_CSV)

    liste = Path(args.liste)
    if not liste.is_file():
        print(f"HATA: liste dosyasi bulunamadi: {liste}")
        return 2
    hdir = Path(args.dir) if args.dir else (liste.parent if str(liste.parent) else Path("."))
    if not hdir.is_dir():
        print(f"HATA: klasor bulunamadi: {hdir}")
        return 2
    try:
        rows, msgs = read_rows(liste)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, IndexError) as e:
        print(f"HATA: liste okunamadi: {e}")
        return 2
    for m in msgs:
        print(f"BILGI: {m}")
    excludes = EXCLUDE_DIRS + ((args.exclude or "").split(";"))
    search_all = SEARCH_ALL_IF_MISSING and not args.no_search_all
    headers = collect_headers(hdir, excludes)
    print(f"BILGI: {len(headers)} header dosyasi taraniyor: {hdir.resolve()}"
          f"{' (alt klasorler dahil)' if SCAN_RECURSIVE else ''}")
    by_name: dict[str, list[Path]] = {}
    for p in headers:
        by_name.setdefault(p.name.lower(), []).append(p)
    cache: dict[Path, HFile] = {}
    unreadable: dict[Path, str] = {}

    def get(p: Path):
        if p not in cache and p not in unreadable:
            try:
                cache[p] = load(p)
            except OSError as e:
                unreadable[p] = str(e)
        return cache.get(p)

    def rel(p: Path) -> str:
        try:
            return p.relative_to(hdir).as_posix()
        except ValueError:
            return str(p)

    def candidates(fcol: str) -> list[Path]:
        f = fcol.replace("\\", "/").strip().strip("/")
        parts = f.split("/")
        fname = parts[-1] if Path(parts[-1]).suffix.lower() in HEADER_EXTENSIONS else parts[-1] + ".h"
        cs = by_name.get(fname.lower(), [])
        if len(parts) > 1:                             # listede klasor de yazilmis: core/LINEAR.h
            tail = "/" + "/".join(parts[:-1] + [fname]).lower()
            cs = [p for p in cs if ("/" + rel(p).lower()).endswith(tail)]
        return cs

    def search(paths, r, fuzzy):
        res = []
        for p in paths:
            hf = get(p)
            if hf is None:
                continue
            hits, nm, note = match_defs(hf, r.name, r.kind, fuzzy)
            if hits:
                res.append((p, hf, hits, nm, note))
        return res

    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        r.name, r.kind = parse_type(r.type_raw)
        derived = TYPE_SUFFIX.get(_norm_head(r.type_raw))
        if derived and r.file:
            leaf = r.file.replace("\\", "/").split("/")[-1]
            stem = Path(leaf).stem if Path(leaf).suffix.lower() in HEADER_EXTENSIONS else leaf
            r.kind = derived[1]
            # dosya adi zaten ENUM / STRUCT / TYPE ile bitiyorsa ek tekrar eklenmez:
            #   LINEARENUM.h + Enumeration -> LINEARENUM  (LINEARENUMENUM degil)
            if fuzzy_key(stem).endswith(SUFFIX_WORDS):
                r.name, alt_name = stem, stem + derived[0]
            else:
                r.name, alt_name = stem + derived[0], ""
        else:
            alt_name = ""
        if not r.id or not r.file or not r.name:
            r.status, r.note = HATA, "eksik / anlasilamayan satir (dosya, id ve tek bir tip adi gerekli)"
            continue
        key = (r.file.lower(), r.id, r.name)
        if key in seen:
            r.status, r.note = UYARI, "listede tekrar eden satir, atlandi"
            continue
        seen.add(key)
        fuzzy = FUZZY_NAMES or bool(derived)
        cands = candidates(r.file)
        found = search(cands, r, fuzzy)
        if not found and alt_name:                     # yine de LINEARENUMENUM gibi bir ad varsa
            first, r.name = r.name, alt_name
            found = search(cands, r, fuzzy)
            if not found:
                r.name = first
        moved = ""
        if not found and search_all:                   # projenin geri kalaninda ara
            others = [p for p in headers if p not in cands]
            found = search(others, r, False) or search(others, r, fuzzy)
            if found:
                moved = f"listede '{r.file}' yaziyor, tanim baska dosyada bulundu"
        if len(found) > 1:
            r.status = HATA
            r.note = ("birden fazla dosyada tanimli: " + ", ".join(rel(f[0]) for f in found[:6]) +
                      " - listede klasoru de yazin (orn. " + rel(found[0][0]) + ")")
            continue
        if not found:
            r.status = HATA
            if not cands:
                r.note = f"dosya projede bulunamadi: {r.file}" + (
                    "; tip de projede tanimli degil" if search_all else "")
                continue
            p = cands[0]
            hf = get(p)
            r.target, r.path = rel(p), p
            if hf is None:
                r.note = f"dosya okunamadi: {unreadable.get(p)}"
                continue
            other_kind = [d for d in hf.defs if r.name in d.names]
            case = sorted({nm for d in hf.defs for nm in d.names
                           if nm.lower() == r.name.lower() and nm != r.name})
            if other_kind:
                note = f"'{r.name}' {other_kind[0].kind} olarak tanimli, {r.kind} degil"
            elif case:
                note = f"tanim yok; buyuk/kucuk harf farkli olan var: {', '.join(case)}"
            elif re.search(r"(?<![A-Za-z0-9_$])" + re.escape(r.name) + r"(?![A-Za-z0-9_$])", hf.code):
                note = "ad dosyada geciyor ama enum/struct/typedef TANIMI degil (ileri bildirim, " \
                       "kullanim ya da makro olabilir)"
            else:
                note = "dosyada bu adda enum / struct / typedef tanimi yok"
            if len(cands) > 1:
                note += f" (ayni adli {len(cands)} dosya var)"
            r.note = note
            continue
        p, hf, hits, nm, note = found[0]
        r.target, r.path = rel(p), p
        if nm != r.name:
            r.name = nm
        r.note = "; ".join(x for x in (moved, note) if x)
        bad = [d for d in hits if in_span(hf.spans, hf.lines[d.line][0])]
        if bad:
            r.status, r.line = HATA, bad[0].line + 1
            r.note = "tanim satiri bir yorumun icinden basliyor ('*/ struct ...'), link eklenemez - elle ekle"
            continue
        if len(hits) > 1:
            r.note = "; ".join(x for x in (r.note, f"{len(hits)} tanim bulundu (#ifdef dallari?), "
                                                    "hepsine eklendi") if x)
        r.status = ZATEN_VAR
        for d in hits:
            r.line = r.line or d.line + 1
            already = existing_links(hf, d.line) | {x.id for x in hf.inserts.get(d.line, [])}
            if r.id not in already:
                hf.inserts.setdefault(d.line, []).append(r)
                r.status = EKLENDI

    # ---- dosyalara uygula
    changed, verify_fail, write_fail = [], [], []
    for p, hf in cache.items():
        if not hf.inserts:
            continue
        crlf = hf.text.count("\r\n")
        eol_default = "\r\n" if crlf and crlf >= hf.text.count("\n") / 2 else "\n"
        out = []
        for L, (ls, le, lee) in enumerate(hf.lines):
            if L in hf.inserts:
                indent = re.match(r"[ \t]*", hf.text[ls:le]).group()
                eol = hf.text[le:lee] or eol_default          # tanim satirinin satir sonu
                for r in hf.inserts[L]:
                    out.append(indent + LINK_FORMAT.format(id=r.id) + eol)
            out.append(hf.text[ls:lee])
        new = "".join(out)
        if fingerprint(new) != fingerprint(hf.text):
            verify_fail.append(p)
            for rs in hf.inserts.values():
                for r in rs:
                    r.status, r.note = HATA, "DOGRULAMA BASARISIZ: kod degisirdi, dosyaya dokunulmadi"
            continue
        changed.append(p)
        if not DRY_RUN:
            try:
                if MAKE_BACKUP:
                    backup_path(p).write_bytes(hf.raw)
                payload = (BOM if hf.had_bom else b"") + new.encode("latin-1")
                p.write_bytes(payload)
                if p.read_bytes() != payload:
                    raise OSError("geri okunan icerik farkli")
            except OSError as e:
                write_fail.append(p)
                for rs in hf.inserts.values():
                    for r in rs:
                        r.status, r.note = HATA, f"yazilamadi: {e}"

    # ---- rapor  (--apply sonrasi satir numaralari yeni dosyaya gore)
    if not DRY_RUN:
        for r in rows:
            hf = cache.get(r.path) if r.path else None
            if r.line and hf and hf.path in changed and hf.path not in write_fail:
                r.line += sum(len(v) for k, v in hf.inserts.items() if k <= r.line - 1)
    label = {EKLENDI: "EKLENECEK" if DRY_RUN else "EKLENDI"}
    for r in rows:
        st = label.get(r.status, r.status)
        where = f"{r.target or r.file}:{r.line}" if r.line else (r.target or r.file)
        note = f"  <- {r.note}" if r.note else ""
        shown = r.type_raw if not r.name or r.name == r.type_raw else f"{r.type_raw} -> {r.name}"
        print(f"  [{st:<9}] {where:<24} {r.id:<14} {shown}{note}")
    cnt = {s: sum(1 for r in rows if r.status == s) for s in (EKLENDI, ZATEN_VAR, UYARI, HATA)}
    print("=" * 78)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  liste: {len(rows)} satir  |  "
          f"{'eklenecek' if DRY_RUN else 'eklendi'}: {cnt[EKLENDI]}, zaten var: {cnt[ZATEN_VAR]}, "
          f"UYARI: {cnt[UYARI]}, HATA: {cnt[HATA]}")
    print(f"dosya: {len(changed)} {'degisecek' if DRY_RUN else 'degisti'}; kod dogrulamasi: "
          f"{len(changed)}/{len(changed) + len(verify_fail)} dosyada kod birebir ayni "
          f"(sadece link satirlari ekleniyor)")
    print("=" * 78)
    if REPORT_CSV:
        try:
            with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["liste_satiri", "dosya", "id", "tip", "aranan_ad", "durum",
                            "dosya_satiri", "aciklama"])
                for r in rows:
                    w.writerow([r.no, r.target or r.file, r.id, r.type_raw, r.name,
                                label.get(r.status, r.status), r.line or "", r.note])
            print(f"Rapor: {REPORT_CSV}")
        except OSError as e:
            print(f"UYARI: rapor yazilamadi ({REPORT_CSV}): {e}")
    if DRY_RUN and changed:
        print("Eklemek icin:  --apply   (once commit et; geri almak icin: git checkout -- .)")
    return 1 if cnt[HATA] else 0


if __name__ == "__main__":
    sys.exit(main())
