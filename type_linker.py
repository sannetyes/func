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

LISTE DOSYASI  (.csv / .txt / .xlsx)  -  her satir: dosya adi, id, tip adi
    Dosya;ID;Tip
    colors.h;types_1;Mode_t
    sensor.h;types_2;SensorData
    sensor.h;types_3;struct SensorConfig     <- 'enum' / 'struct' yazilirsa sadece o tur aranir
  * Ayirac otomatik bulunur ( ;  ,  TAB  | ).  Baslik satiri istege bagli; yoksa sira:
    dosya, id, tip  (.h ile biten sutun dosya sutunu sayilir).
  * Dosyalar liste dosyasiyla AYNI klasordeki .h dosyalaridir (--dir ile degistirilebilir).

TANINAN TANIMLAR
    enum Color { ... };                      enum class Level : uint8_t { ... };
    typedef enum { ... } Mode_t;             typedef enum State_tag { ... } State;
    struct Point { ... };                    typedef struct { ... } SensorData, *SensorDataPtr;
    struct __attribute__((packed)) H { };    struct MY_API Exported { };     union U { };
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
    python type_link.py liste.xlsx --dir inc/ --apply
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

# =====================================================================

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
    return not want or want == have or (want == "struct" and have == "class")


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
    ap.add_argument("--dir", help=".h dosyalarinin klasoru (varsayilan: liste dosyasinin klasoru)")
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
    by_lower = {p.name.lower(): p for p in hdir.iterdir()
                if p.is_file() and p.suffix.lower() in HEADER_EXTENSIONS}
    cache: dict[Path, HFile] = {}

    def get(p: Path) -> HFile:
        if p not in cache:
            cache[p] = load(p)
        return cache[p]

    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        r.name, r.kind = parse_type(r.type_raw)
        if not r.id or not r.file or not r.name:
            r.status, r.note = HATA, "eksik / anlasilamayan satir (dosya, id ve tek bir tip adi gerekli)"
            continue
        key = (r.file.lower(), r.id, r.name)
        if key in seen:
            r.status, r.note = UYARI, "listede tekrar eden satir, atlandi"
            continue
        seen.add(key)
        fname = Path(r.file).name if Path(r.file).suffix else Path(r.file).name + ".h"
        p = by_lower.get(fname.lower())
        if p is None:
            r.status, r.note = HATA, f"dosya bulunamadi: {hdir / fname}"
            continue
        r.target = p.name
        try:
            hf = get(p)
        except OSError as e:
            r.status, r.note = HATA, f"dosya okunamadi: {e}"
            continue
        hits = [d for d in hf.defs if r.name in d.names and kind_ok(r.kind, d.kind)]
        if not hits:
            other_kind = [d for d in hf.defs if r.name in d.names]
            case = sorted({nm for d in hf.defs for nm in d.names
                           if nm.lower() == r.name.lower() and nm != r.name})
            elsewhere = []
            if not other_kind and not case:
                for q in by_lower.values():
                    if q != p and any(r.name in d.names for d in get(q).defs):
                        elsewhere.append(q.name)
            if other_kind:
                note = f"'{r.name}' {other_kind[0].kind} olarak tanimli, {r.kind} degil"
            elif case:
                note = f"tanim yok; buyuk/kucuk harf farkli olan var: {', '.join(case)}"
            elif elsewhere:
                note = f"bu dosyada tanim yok; su dosyada var: {', '.join(elsewhere)}"
            elif re.search(r"(?<![A-Za-z0-9_$])" + re.escape(r.name) + r"(?![A-Za-z0-9_$])",
                           hf.code):
                note = "ad dosyada geciyor ama enum/struct TANIMI degil (ileri bildirim, " \
                       "kullanim ya da makro olabilir)"
            else:
                note = "dosyada bu adda enum/struct tanimi yok"
            r.status, r.note = HATA, note
            continue
        bad = [d for d in hits if in_span(hf.spans, hf.lines[d.line][0])]
        if bad:
            r.status, r.line = HATA, bad[0].line + 1
            r.note = "tanim satiri bir yorumun icinden basliyor ('*/ struct ...'), link eklenemez - elle ekle"
            continue
        if len(hits) > 1:
            r.note = f"{len(hits)} tanim bulundu (#ifdef dallari?), hepsine eklendi"
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
            hf = next((h for h in cache.values() if h.path.name == r.target), None)
            if r.line and hf and hf.path in changed and hf.path not in write_fail:
                r.line += sum(len(v) for k, v in hf.inserts.items() if k <= r.line - 1)
    label = {EKLENDI: "EKLENECEK" if DRY_RUN else "EKLENDI"}
    for r in rows:
        st = label.get(r.status, r.status)
        where = f"{r.target or r.file}:{r.line}" if r.line else (r.target or r.file)
        note = f"  <- {r.note}" if r.note else ""
        print(f"  [{st:<9}] {where:<24} {r.id:<14} {r.type_raw}{note}")
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
                w.writerow(["liste_satiri", "dosya", "id", "tip", "durum", "dosya_satiri", "aciklama"])
                for r in rows:
                    w.writerow([r.no, r.target or r.file, r.id, r.type_raw,
                                label.get(r.status, r.status), r.line or "", r.note])
            print(f"Rapor: {REPORT_CSV}")
        except OSError as e:
            print(f"UYARI: rapor yazilamadi ({REPORT_CSV}): {e}")
    if DRY_RUN and changed:
        print("Eklemek icin:  --apply   (once commit et; geri almak icin: git checkout -- .)")
    return 1 if cnt[HATA] else 0


if __name__ == "__main__":
    sys.exit(main())
