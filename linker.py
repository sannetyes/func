#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV'de listelenen HLR ID'lerini, ilgili .cpp dosyalarindaki fonksiyonlarin
etrafina yorum blogu olarak ekler.  Harici bagimlilik YOKTUR (sadece stdlib).

Uretilen format (varsayilan):

    //#([HLR_MODULE_1234,
    //	HLR_MODULE2_1234,
    //	HLR_MODULE3_1234,
    int func_name(param1){
        ...
    }
    //#)

Beklenen CSV sutunlari (basliklar ilk satirda, sirasi onemli degil):
    Directory Name | Class/File Name | Function Name | Line Number | HLR Ids

Notlar:
  * Sadece .cpp dosyalari islenir; digerleri atlanip rapora yazilir.
  * 'Function Name' sutunundaki isimlerde namespace onekleri silinmis olabilir
    (ornek: kodda  ns::Motor::start  , CSV'de  Motor::start  ya da  start ).
    Eslestirme son tanimlayiciya bakar, ustune ( parantezini de arar.
  * 'HLR Ids' hucresindeki ID'ler virgul / noktali virgul / satir sonu / boru
    ile ayrilmis olabilir; hepsi taninir.

Kullanim:
    1) Asagidaki AYARLAR bolumunu doldur.
    2) DRY_RUN = True ile calistir, onizlemeyi ve raporu incele.
    3) DRY_RUN = False yapip tekrar calistir.

Onemli: calistirmadan once projeyi commit et (git). Script dosyalari
yerinde degistirir ve CSV'deki satir numaralari degisiklikten sonra bayatlar,
bu yuzden temiz agac uzerinde BIR kez calistirilmalidir.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


# ============================== AYARLAR ==============================

CSV_PATH = "hlr.csv"             # CSV dosyasinin yolu
CSV_DELIMITER = None             # None = otomatik tespit;  ya da ";" / "," / "\t"

# CSV'deki 'Directory Name' sutunu goreli ise, projenin kok dizini.
# Mutlak yol yaziyorsa "" birak.
SOURCE_ROOT = ""

DRY_RUN = True                   # True iken hicbir dosya degismez
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = "hlr_link_report.csv"
SHOW_PREVIEW = True              # Dry-run'da eklenecek bloklari ekrana bas

# Sadece bu uzantilar islenir
ALLOWED_EXTENSIONS = {".cpp"}

# CSV'nin kendi kodlamasi icin denenecek sira
CSV_ENCODINGS = ["utf-8-sig", "utf-8", "cp1254", "latin-1"]

# Kaynak dosyalar icin denenecek kodlama sirasi
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

# CSV'deki satir numarasi tutmuyorsa, +/- kac satir icinde fonksiyon aransin
SEARCH_RADIUS = 15

# Fonksiyonun ustunde zaten //#( varsa atla (idempotent calisma)
SKIP_IF_ALREADY_TAGGED = True

# Fonksiyonun hemen ustundeki yorum blogunun da USTUNE yaz (True) ya da
# yorum ile fonksiyon arasina yaz (False)
INSERT_ABOVE_DOC_COMMENTS = True

# --- cikti formati ---
OPEN_PREFIX = "//#(["            # ilk satirin basi
CONT_PREFIX = "//"               # DEVAM satirlarinin yorum oneki.
                                 # "" yaparsan istedigin bire bir format cikar
                                 # AMA o hâlde kod DERLENMEZ.
CONT_INDENT = "\t"               # devam satirlarinin girintisi
TRAILING_COMMA_ON_LAST = True    # son ID'den sonra da virgul olsun mu
CLOSE_LIST_SUFFIX = ""           # son ID'den sonra "]" istersen "]" yaz
CLOSE_MARKER = "//#)"            # fonksiyonun } satirindan sonraki satir

# CSV basliklari. Karsilastirma icin basliklar kucuk harfe cevrilir ve
# harf/rakam disindaki her sey silinir:
#     "Class/File Name" -> "classfilename"
#     "HLR Ids"         -> "hlrids"
COLUMNS = {
    "directory": "directoryname",
    "filename":  "classfilename",
    "function":  "functionname",
    "line":      "linenumber",
    "hlr":       "hlrids",
}

# =====================================================================


def norm_header(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


@dataclass
class Task:
    row_no: int
    file: Path
    func: str
    line: int                 # CSV'deki 1-tabanli satir
    hlr_ids: list[str]
    status: str = "PENDING"
    detail: str = ""
    start_line: int = 0       # dogrulanmis 1-tabanli baslangic
    end_line: int = 0         # fonksiyonun } satiri (1-tabanli)
    preview: str = ""


# --------------------------------------------------------------------
# 1) CSV okuma
# --------------------------------------------------------------------

def decode_text(data: bytes, encodings: list[str]) -> str:
    for enc in encodings:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("hepsi", b"", 0, 1, "kodlama cozulemedi")


def detect_delimiter(sample: str) -> str:
    """Baslik satirina bakarak ayraci tahmin eder."""
    if CSV_DELIMITER:
        return CSV_DELIMITER
    lines = sample.splitlines()
    first = lines[0] if lines else ""
    try:
        return csv.Sniffer().sniff(first, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {d: first.count(d) for d in [";", ",", "\t", "|"]}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def read_csv_tasks(path: str) -> list[Task]:
    raw = Path(path).read_bytes()
    text = decode_text(raw, CSV_ENCODINGS)
    delim = detect_delimiter(text)
    print(f"CSV ayraci: {delim!r}")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)

    try:
        header = next(reader)
    except StopIteration:
        sys.exit("CSV bos.")

    headers = [norm_header(h) for h in header]

    idx: dict[str, int] = {}
    for key, wanted in COLUMNS.items():
        if wanted in headers:
            idx[key] = headers.index(wanted)

    missing = [COLUMNS[k] for k in COLUMNS if k not in idx]
    if missing:
        sys.exit(
            f"CSV'de bulunamayan sutun(lar): {missing}\n"
            f"Gorulen basliklar: {header}\n"
            f"Ayrac yanlis tespit edilmis olabilir -> CSV_DELIMITER'i elle ayarla."
        )

    hlr_is_last = idx["hlr"] == max(idx.values())

    tasks: list[Task] = []
    for r, row in enumerate(reader, start=2):
        if not any(str(c).strip() for c in row):
            continue

        def cell(key: str) -> str:
            i = idx[key]
            return str(row[i]).strip() if i < len(row) else ""

        raw_dir = cell("directory")
        raw_name = cell("filename")
        func = cell("function")
        raw_line = cell("line")
        raw_hlr = cell("hlr")

        # 'HLR Ids' son sutunsa ve satirda basliktan FAZLA hucre varsa, hucre
        # tirnaklanmamis ve ayrac yuzunden bolunmus demektir -> geri birlestir.
        if hlr_is_last and len(row) > len(headers):
            raw_hlr = ",".join(str(c).strip() for c in row[idx["hlr"]:])

        ids = [s.strip() for s in re.split(r"[,;\n\r|]+", raw_hlr) if s.strip()]

        d = raw_dir.replace("\\", "/").rstrip("/")
        n = raw_name.replace("\\", "/")
        joined = f"{d}/{n}" if (d and not d.endswith(n)) else (d or n)
        full = Path(SOURCE_ROOT) / joined if SOURCE_ROOT else Path(joined)

        t = Task(row_no=r, file=full, func=func, line=0, hlr_ids=ids)

        if full.suffix.lower() not in ALLOWED_EXTENSIONS:
            t.status = "ATLANDI"
            t.detail = f".cpp degil ({full.suffix or 'uzantisiz'})"
            tasks.append(t)
            continue

        try:
            t.line = int(float(raw_line))
        except ValueError:
            t.status = "HATA"
            t.detail = f"Satir numarasi okunamadi: {raw_line!r}"
            tasks.append(t)
            continue

        if not ids:
            t.status = "ATLANDI"
            t.detail = "HLR ID yok"
        tasks.append(t)

    return tasks


# --------------------------------------------------------------------
# 2) Kaynak dosya okuma / yazma
# --------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


def read_lines(path: Path) -> tuple[list[str], str, bool]:
    """Satir sonlarini (CRLF/LF) ve BOM durumunu koruyarak okur."""
    data = path.read_bytes()
    had_bom = data.startswith(BOM)
    if had_bom:
        data = data[len(BOM):]
    for enc in ENCODINGS:
        try:
            return data.decode(enc).splitlines(keepends=True), enc, had_bom
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("hepsi", b"", 0, 1, f"{path} cozulemedi")


def write_lines(path: Path, lines: list[str], enc: str, had_bom: bool) -> None:
    if MAKE_BACKUP:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    payload = "".join(lines).encode(enc)
    if had_bom:
        payload = BOM + payload
    path.write_bytes(payload)


# --------------------------------------------------------------------
# 3) C++ govde tarayicisi  (yorum / string / char literal farkindali)
# --------------------------------------------------------------------

def find_function_end(lines: list[str], start_idx: int) -> tuple[int | None, str]:
    """
    start_idx (0-tabanli) satirindan itibaren fonksiyon govdesinin acilis
    susulu parantezini bulur ve eslesen kapanisin satir indeksini dondurur.
    """
    depth = 0            # { } derinligi
    paren = 0            # ( ) derinligi -> parametre icindeki {} sayilmasin
    body_open = False
    in_block = False
    in_str: str | None = None
    raw_delim: str | None = None
    init_list = False    # ctor member-initializer listesi icinde miyiz
    params_closed = False
    last_code_char = ""

    i = start_idx
    while i < len(lines):
        line = lines[i]
        j, n = 0, len(line)
        while j < n:
            c = line[j]
            nxt = line[j + 1] if j + 1 < n else ""

            if in_block:                       # blok yorum
                if c == "*" and nxt == "/":
                    in_block = False
                    j += 2
                else:
                    j += 1
                continue

            if raw_delim is not None:          # R"delim( ... )delim"
                end = line.find(")" + raw_delim + '"', j)
                if end == -1:
                    j = n
                else:
                    j = end + len(raw_delim) + 2
                    raw_delim = None
                continue

            if in_str is not None:             # string / char literal
                if c == "\\":
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
                j += 1
                continue

            # --- kod ---
            if c == "/" and nxt == "/":
                break
            if c == "/" and nxt == "*":
                in_block = True
                j += 2
                continue

            if c == '"':
                if j > 0 and line[j - 1] == "R":
                    k = line.find("(", j + 1)
                    if k != -1:
                        raw_delim = line[j + 1:k]
                        j = k + 1
                        continue
                in_str = '"'
                j += 1
                continue

            if c == "'":
                if j > 0 and line[j - 1].isdigit():   # 1'000'000
                    j += 1
                    continue
                in_str = "'"
                j += 1
                continue

            if c == "(":
                paren += 1
            elif c == ")":
                paren -= 1
                if paren == 0 and not body_open:
                    params_closed = True
            elif c == ":" and paren == 0 and params_closed and not body_open and nxt != ":":
                init_list = True
            elif c == "{" and paren == 0:
                if not body_open and init_list and last_code_char not in (")", "}", ""):
                    depth += 1                 # ctor init listesi: x{0} -> govde degil
                    j += 1
                    last_code_char = c
                    continue
                depth += 1
                body_open = True
            elif c == "}" and paren == 0:
                depth -= 1
                if body_open and depth == 0:
                    return i, ""
            elif c == ";" and paren == 0 and not body_open:
                return None, "Govde yok (prototip / forward declaration olabilir)"

            if not c.isspace():
                last_code_char = c
            j += 1
        i += 1

    return None, "Kapanis susulu parantezi bulunamadi (dosya sonuna gelindi)"


# --------------------------------------------------------------------
# 4) Fonksiyon baslangicini bul  (namespace onekleri silinmis olabilir)
# --------------------------------------------------------------------

def func_base(name: str) -> str:
    """
    CSV'deki fonksiyon isminden son tanimlayiciyi cikarir.
        'ns::Motor::start'     -> 'start'
        'Motor::start'         -> 'start'
        'start(int, bool)'     -> 'start'
        'Buffer<T>::push'      -> 'push'
        'Motor::~Motor'        -> '~Motor'
        'Vec::operator=='      -> 'operator=='
    """
    n = name.strip()
    if "operator" not in n and "(" in n:
        n = n.split("(", 1)[0]
    n = re.sub(r"<[^<>]*>\s*$", "", n).strip()      # sondaki template argumanlari
    if "::" in n:
        n = n.rsplit("::", 1)[-1].strip()
    return n


def code_part(line: str) -> str:
    """Satirdaki // yorumunu atar (eslesme yorumdan gelmesin diye)."""
    return line.split("//", 1)[0]


def build_patterns(base: str):
    esc = re.escape(base)
    lead = r"(?<![\w~])" if (base[:1].isalnum() or base[:1] == "_") else ""
    trail = r"\b" if (base[-1:].isalnum() or base[-1:] == "_") else ""
    # GUCLU: isim  ->  (istege bagli <...>)  ->  (
    strong = re.compile(rf"{lead}{esc}\s*(<[^;{{}}]*>)?\s*\(")
    # GEVSEK: isim tek basina (imza sonraki satira sarkmis olabilir)
    loose = re.compile(rf"{lead}{esc}{trail}")
    return strong, loose


def locate_start(lines: list[str], task: Task) -> tuple[int | None, str]:
    """CSV satir numarasindan yola cikip fonksiyon tanimini dogrular."""
    base = func_base(task.func)
    if not base:
        return None, "Fonksiyon ismi bos"

    center = task.line - 1
    if not (0 <= center < len(lines)):
        return None, f"Satir {task.line} dosya disinda (dosya {len(lines)} satir)"

    strong, loose = build_patterns(base)

    # aday sirasi: once CSV'nin dedigi satir, sonra yakindan uzaga
    cands = [center]
    for d in range(1, SEARCH_RADIUS + 1):
        for c in (center - d, center + d):
            if 0 <= c < len(lines):
                cands.append(c)

    def note(c: int) -> str:
        return "" if c == center else f"Satir {task.line} -> {c + 1} olarak duzeltildi"

    # 1) isim + '(' eslesen VE govdesi olan ilk aday
    strong_hits = [c for c in cands if strong.search(code_part(lines[c]))]
    for c in strong_hits:
        if find_function_end(lines, c)[0] is not None:
            return c, note(c)

    # 2) isim tek basina gecen VE govdesi olan ilk aday (cok satirli imza)
    for c in cands:
        if loose.search(code_part(lines[c])) and find_function_end(lines, c)[0] is not None:
            return c, (note(c) + " (imza cok satirli olabilir)").strip()

    if strong_hits:
        return None, (f"'{base}' bulundu (satir {strong_hits[0] + 1}) ama govdesi yok "
                      f"- prototip olabilir")
    return None, f"Fonksiyon '{base}' satir {task.line} civarinda bulunamadi"


COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\*/)")
ATTR_LINE = re.compile(r"^\s*(template\s*<|__attribute__|\[\[|#\s*\w+)")

# Ayri satira yazilmis donus tipi:   "void"  /  "static int"  /  "std::vector<int>"
TYPE_ONLY_LINE = re.compile(r"^\s*[A-Za-z_][\w:<>,\*&\s]*$")
NOT_A_TYPE = {"else", "do", "try", "return", "break", "continue",
              "case", "default", "goto"}


def is_return_type_line(line: str) -> bool:
    s = line.strip()
    if not s or s.endswith((":", ";", ",", "{", "}", ")", "=")):
        return False
    if any(ch in s for ch in "(){};="):
        return False
    if not TYPE_ONLY_LINE.match(line):
        return False
    return s.split()[0] not in NOT_A_TYPE


def climb_above_comments(lines: list[str], idx: int) -> int:
    """Fonksiyonun ustundeki bitisik yorum / template / donus tipi satirlarina cikar."""
    k = idx
    while k - 1 >= 0:
        prev = lines[k - 1]
        if prev.strip() == "":
            break
        if COMMENT_LINE.match(prev) or ATTR_LINE.match(prev) or is_return_type_line(prev):
            k -= 1
            continue
        break
    return k


def find_tagged_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Dosyadaki mevcut //#( ... //#) bloklarinin (acilis, kapanis) indeksleri."""
    ranges: list[tuple[int, int]] = []
    open_idx: int | None = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("//#(") and not s.startswith(CLOSE_MARKER):
            if open_idx is None:
                open_idx = i
        elif s.startswith(CLOSE_MARKER) and open_idx is not None:
            ranges.append((open_idx, i))
            open_idx = None
    if open_idx is not None:
        ranges.append((open_idx, len(lines) - 1))
    return ranges


def in_tagged_range(ranges: list[tuple[int, int]], idx: int) -> bool:
    return any(lo <= idx <= hi for lo, hi in ranges)


# --------------------------------------------------------------------
# 5) Blok uretimi
# --------------------------------------------------------------------

def leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def detect_eol(lines: list[str]) -> str:
    for ln in lines:
        if ln.endswith("\r\n"):
            return "\r\n"
        if ln.endswith("\n"):
            return "\n"
    return "\n"


def build_open_block(ids: list[str], indent: str, eol: str) -> list[str]:
    out = []
    for i, hid in enumerate(ids):
        last = i == len(ids) - 1
        sep = "" if (last and not TRAILING_COMMA_ON_LAST) else ","
        tail = CLOSE_LIST_SUFFIX if last else ""
        if i == 0:
            out.append(f"{indent}{OPEN_PREFIX}{hid}{sep}{tail}{eol}")
        else:
            out.append(f"{indent}{CONT_PREFIX}{CONT_INDENT}{hid}{sep}{tail}{eol}")
    return out


# --------------------------------------------------------------------
# 6) Ana akis
# --------------------------------------------------------------------

def main() -> int:
    tasks = read_csv_tasks(CSV_PATH)
    print(f"CSV'den {len(tasks)} satir okundu.\n")

    groups: dict[Path, list[Task]] = {}
    for t in tasks:
        if t.status in ("HATA", "ATLANDI"):
            continue
        key = t.file.resolve() if t.file.is_absolute() else t.file
        groups.setdefault(key, []).append(t)

    for file, file_tasks in groups.items():
        if not file.exists():
            for t in file_tasks:
                t.status, t.detail = "HATA", f"Dosya bulunamadi: {file}"
            continue

        try:
            lines, enc, had_bom = read_lines(file)
        except Exception as e:
            for t in file_tasks:
                t.status, t.detail = "HATA", f"Dosya okunamadi: {e}"
            continue

        eol = detect_eol(lines)
        tagged = find_tagged_ranges(lines)

        # === once TUM gorevleri coz (henuz degistirmeden) ===
        planned = []
        for t in file_tasks:
            start, note = locate_start(lines, t)
            if start is None:
                t.status, t.detail = "HATA", note
                continue

            end, err = find_function_end(lines, start)
            if end is None:
                t.status, t.detail = "HATA", err
                continue

            if SKIP_IF_ALREADY_TAGGED and in_tagged_range(tagged, start):
                t.status, t.detail = "ATLANDI", "Zaten etiketli"
                continue

            insert_at = climb_above_comments(lines, start) if INSERT_ABOVE_DOC_COMMENTS else start

            if insert_at > 0 and lines[insert_at - 1].rstrip("\r\n").endswith("\\"):
                t.status, t.detail = "HATA", "Ust satir makro devami (\\) - elle yapilmali"
                continue

            t.start_line, t.end_line = start + 1, end + 1
            t.detail = note
            planned.append((t, insert_at, start, end))

        # ayni fonksiyona iki CSV satiri denk geldiyse ikincisini ele
        seen: set[int] = set()
        unique = []
        for item in planned:
            if item[2] in seen:
                item[0].status = "ATLANDI"
                item[0].detail = "Ayni fonksiyon icin baska bir CSV satiri zaten islendi"
                continue
            seen.add(item[2])
            unique.append(item)
        planned = unique

        # === asagidan yukariya uygula (satir numaralari kaymasin) ===
        planned.sort(key=lambda x: x[3], reverse=True)
        for t, insert_at, start, end in planned:
            indent = leading_ws(lines[start])
            open_block = build_open_block(t.hlr_ids, indent, eol)
            close_line = f"{indent}{CLOSE_MARKER}{eol}"

            if not lines[end].endswith(("\n", "\r")):
                lines[end] = lines[end] + eol

            lines.insert(end + 1, close_line)
            lines[insert_at:insert_at] = open_block

            t.status = "OK"
            t.preview = (
                "".join(open_block)
                + lines[insert_at + len(open_block)]
                + "    ...\n"
                + lines[end + len(open_block)]
                + close_line
            )

        if planned and not DRY_RUN:
            write_lines(file, lines, enc, had_bom)

        if planned and DRY_RUN and SHOW_PREVIEW:
            print(f"--- {file} ---")
            for t, *_ in sorted(planned, key=lambda x: x[2]):
                print(f"[satir {t.start_line}-{t.end_line}]  {t.func}")
                print(t.preview.rstrip())
                print()

    # === rapor ===
    ok = sum(1 for t in tasks if t.status == "OK")
    skip = sum(1 for t in tasks if t.status == "ATLANDI")
    err = sum(1 for t in tasks if t.status == "HATA")
    pend = sum(1 for t in tasks if t.status == "PENDING")

    print("=" * 60)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  "
          f"OK: {ok}  ATLANDI: {skip}  HATA: {err}  BEKLEYEN: {pend}")
    print("=" * 60)

    if err or pend:
        print("\nEl ile bakilmasi gerekenler:")
        for t in tasks:
            if t.status in ("HATA", "PENDING"):
                print(f"  CSV satir {t.row_no}: {t.file} :: {t.func} (L{t.line}) -> {t.detail}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["csv_row", "file", "function", "csv_line",
                    "found_start", "found_end", "hlr_count", "status", "detail"])
        for t in tasks:
            w.writerow([t.row_no, t.file, t.func, t.line, t.start_line,
                        t.end_line, len(t.hlr_ids), t.status, t.detail])
    print(f"\nRapor: {REPORT_CSV}")

    if DRY_RUN:
        print("\nDRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
