#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV'de listelenen HLR ID'lerini, ilgili HEADER dosyasindaki SINIF taniminin
etrafina yorum blogu olarak ekler.  Harici bagimlilik YOKTUR (sadece stdlib).

Uretilen format:

    //#([HLR_MODULE_1234,
    //	HLR_MODULE2_1234,
    //	HLR_MODULE3_1234,
    class className {
        ...
    };
    //#)

Beklenen CSV sutunlari (basliklar ilk satirda, sirasi onemli degil,
fazladan sutun varsa yok sayilir):
    Directory Name | Class/File Name | HLR Ids

Calisma mantigi:
    'Class/File Name' sutununda  Motor.cpp  yaziyorsa
        -> ayni dizinde  Motor.h  (yoksa .hpp / .hxx / .hh) aranir
        -> o dosyada  'class Motor'  ya da  'struct Motor'  TANIMI bulunur
        -> tanimin ustune ve kapanis  };  satirinin altina blok yazilir
    Sinif bir (ya da ic ice) namespace icinde olabilir; blok namespace'in
    icinde, sinifin hemen ustunde olusur.

    Satir numarasi YOKTUR; sinif dosyanin tamaminda aranir. Bu yuzden:
      * ileri bildirimler  (class Motor;)          -> govdesi yok, elenir
      * taban sinif gecisleri (: public Motor)     -> eslesmez
      * 'enum class Motor'                         -> elenir
      * 'MotorBase' gibi benzer isimler            -> eslesmez

Kullanim:
    1) Asagidaki AYARLAR bolumunu doldur.
    2) DRY_RUN = True ile calistir, onizlemeyi ve raporu incele.
    3) DRY_RUN = False yapip tekrar calistir.

Onemli: calistirmadan once projeyi commit et (git).
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

CSV_PATH = "hlr_class.csv"       # CSV dosyasinin yolu
CSV_DELIMITER = None             # None = otomatik tespit;  ya da ";" / "," / "\t"

# CSV'deki 'Directory Name' sutunu goreli ise, projenin kok dizini.
SOURCE_ROOT = ""

DRY_RUN = True                   # True iken hicbir dosya degismez
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = "hlr_class_report.csv"
SHOW_PREVIEW = True              # Dry-run'da eklenecek bloklari ekrana bas

# .cpp -> header ararken denenecek uzantilar (sirayla)
HEADER_EXTENSIONS = [".h", ".hpp", ".hxx", ".hh"]

# Header'i once ayni dizinde ara; bulunamazsa bu alt/ust dizinlere de bak
# (proje kokune gore goreli, "" = SOURCE_ROOT'un kendisi). Bos birakilabilir.
EXTRA_HEADER_DIRS: list[str] = []

CSV_ENCODINGS = ["utf-8-sig", "utf-8", "cp1254", "latin-1"]
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

SKIP_IF_ALREADY_TAGGED = True    # blok zaten varsa ustune ikinci blok yazilmaz

# Blok var AMA ID'ler CSV ile ayni degilse:
#   False -> dokunma, "FARKLI" diye raporla (guvenli varsayilan)
#   True  -> koddaki ID satirlarini CSV'dekilerle DEGISTIR
UPDATE_EXISTING_BLOCKS = False
INSERT_ABOVE_DOC_COMMENTS = True   # sinifin ustundeki yorum blogunun da ustune yaz

# --- cikti formati ---
OPEN_PREFIX = "//#(["
CONT_PREFIX = "//"               # "" yaparsan derlenmez
CONT_INDENT = "\t"
TRAILING_COMMA_ON_LAST = True
CLOSE_LIST_SUFFIX = ""
CLOSE_MARKER = "//#)"

# CSV basliklari (kucuk harf + harf/rakam disi silinmis hali)
COLUMNS = {
    "directory": "directoryname",
    "filename":  "classfilename",
    "hlr":       "hlrids",
}

# =====================================================================


def norm_header(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


@dataclass
class Task:
    row_no: int
    src_name: str             # CSV'deki 'Class/File Name' (ornek: Motor.cpp)
    cls: str                  # cikarilan sinif adi   (ornek: Motor)
    directory: Path
    header: Path | None = None
    hlr_ids: list[str] = None
    status: str = "PENDING"
    detail: str = ""
    start_line: int = 0
    end_line: int = 0
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
    text = decode_text(Path(path).read_bytes(), CSV_ENCODINGS)
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

    hlr_is_last = idx["hlr"] == len(headers) - 1

    tasks: list[Task] = []
    for r, row in enumerate(reader, start=2):
        if not any(str(c).strip() for c in row):
            continue

        def cell(key: str) -> str:
            i = idx[key]
            return str(row[i]).strip() if i < len(row) else ""

        raw_dir = cell("directory")
        raw_name = cell("filename")
        raw_hlr = cell("hlr")

        # HLR sutunu son sutunsa ve satirda basliktan FAZLA hucre varsa,
        # hucre tirnaklanmamis ve ayrac yuzunden bolunmus demektir.
        if hlr_is_last and len(row) > len(headers):
            raw_hlr = ",".join(str(c).strip() for c in row[idx["hlr"]:])

        ids = [s.strip() for s in re.split(r"[,;\n\r|]+", raw_hlr) if s.strip()]

        d = raw_dir.replace("\\", "/").rstrip("/")
        directory = Path(SOURCE_ROOT) / d if SOURCE_ROOT else Path(d)

        # 'Motor.cpp' -> sinif adi 'Motor'
        cls = Path(raw_name.replace("\\", "/")).stem

        t = Task(row_no=r, src_name=raw_name, cls=cls,
                 directory=directory, hlr_ids=ids)

        if not cls:
            t.status, t.detail = "HATA", "Dosya/sinif adi bos"
        elif not ids:
            t.status, t.detail = "ATLANDI", "HLR ID yok"

        tasks.append(t)

    return tasks


# --------------------------------------------------------------------
# 2) Header dosyasini bul
# --------------------------------------------------------------------

def find_header(task: Task) -> tuple[Path | None, str]:
    tried: list[str] = []
    dirs = [task.directory]
    for extra in EXTRA_HEADER_DIRS:
        dirs.append(Path(SOURCE_ROOT) / extra if SOURCE_ROOT else Path(extra))

    for d in dirs:
        for ext in HEADER_EXTENSIONS:
            cand = d / (task.cls + ext)
            tried.append(str(cand))
            if cand.exists():
                return cand, ""
    return None, f"Header bulunamadi. Denenen: {', '.join(tried[:4])}"


# --------------------------------------------------------------------
# 3) Dosya okuma / yazma
# --------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


def read_lines(path: Path) -> tuple[list[str], str, bool]:
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
# 4) Blok tarayici (yorum / string / char literal farkindali)
# --------------------------------------------------------------------

def find_block_end(lines: list[str], start_idx: int) -> tuple[int | None, int, str]:
    """
    start_idx satirindan itibaren ilk '{' i bulur ve eslesen '}' in
    (satir indeksi, sutun) degerini dondurur.

    Doner: (satir_idx | None, sutun, aciklama)
    """
    depth = 0
    paren = 0
    body_open = False
    in_block = False
    in_str: str | None = None
    raw_delim: str | None = None

    i = start_idx
    while i < len(lines):
        line = lines[i]
        j, n = 0, len(line)
        while j < n:
            c = line[j]
            nxt = line[j + 1] if j + 1 < n else ""

            if in_block:
                if c == "*" and nxt == "/":
                    in_block = False
                    j += 2
                else:
                    j += 1
                continue

            if raw_delim is not None:
                end = line.find(")" + raw_delim + '"', j)
                if end == -1:
                    j = n
                else:
                    j = end + len(raw_delim) + 2
                    raw_delim = None
                continue

            if in_str is not None:
                if c == "\\":
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
                j += 1
                continue

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
                if j > 0 and line[j - 1].isdigit():
                    j += 1
                    continue
                in_str = "'"
                j += 1
                continue

            if c == "(":
                paren += 1
            elif c == ")":
                paren -= 1
            elif c == "{" and paren == 0:
                depth += 1
                body_open = True
            elif c == "}" and paren == 0:
                depth -= 1
                if body_open and depth == 0:
                    return i, j, ""
            elif c == ";" and paren == 0 and not body_open:
                return None, 0, "Govde yok (ileri bildirim / forward declaration)"

            j += 1
        i += 1

    return None, 0, "Kapanis susulu parantezi bulunamadi (dosya sonuna gelindi)"


def find_semicolon_anchor(lines: list[str], end_idx: int, end_col: int) -> int:
    """
    Sinif kapanisindaki  };  noktali virgulunun bulundugu satiri dondurur.
    '}' ile ';' ayri satirlarda olabilir.
    """
    rest = lines[end_idx][end_col + 1:]
    if ";" in rest.split("//")[0]:
        return end_idx
    k = end_idx + 1
    while k < len(lines) and k <= end_idx + 3:
        s = lines[k].strip()
        if s == "":
            k += 1
            continue
        if s.startswith(";"):
            return k
        break
    return end_idx


# --------------------------------------------------------------------
# 5) Sinif tanimini bul
# --------------------------------------------------------------------

def code_part(line: str) -> str:
    return line.split("//", 1)[0]


def build_class_pattern(cls: str) -> re.Pattern:
    """
    'class X' / 'struct X' TANIMINI yakalar, su durumlari ELEMEK icin:
      * 'class XBase'            -> \\b ile eslesmez
      * 'class Y : public X'     -> ':' den once isim aranir, gecemez
      * 'class X;'               -> ';' den once, ama govde kontrolu eler
      * 'typedef class X Alias;' -> ardindan ':' / '{' / satir sonu gelmez
    Izin verilenler:
        class X {                       struct X {
        class MY_API X final : Base {   class X
        template <typename T> class X { class X : public Base<int, char> {
    """
    esc = re.escape(cls)
    return re.compile(
        rf"\b(?:class|struct)\b[^;{{:]*?\b{esc}\b\s*(?:final\b\s*)?(?::|\{{|$)"
    )


def locate_class(lines: list[str], cls: str) -> tuple[int | None, str]:
    pat = build_class_pattern(cls)
    seen_without_body: list[int] = []

    for i, raw in enumerate(lines):
        line = code_part(raw).rstrip("\r\n")
        if "enum" in line:                      # 'enum class X' eleme
            continue
        if not pat.search(line):
            continue
        end, _, _ = find_block_end(lines, i)
        if end is not None:
            return i, ""
        seen_without_body.append(i)

    if seen_without_body:
        satirlar = ", ".join(str(i + 1) for i in seen_without_body[:3])
        return None, (f"'{cls}' bulundu (satir {satirlar}) ama govdesi yok "
                      f"- ileri bildirim olabilir")
    return None, f"'class {cls}' / 'struct {cls}' tanimi bulunamadi"


# --------------------------------------------------------------------
# 6) Yerlestirme yardimcilari
# --------------------------------------------------------------------

COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\*/)")
ATTR_LINE = re.compile(r"^\s*(template\s*<|__attribute__|\[\[|#\s*\w+)")


def climb_above_comments(lines: list[str], idx: int) -> int:
    """Sinifin ustundeki bitisik yorum / template satirlarina cikar.
    'namespace X {' gibi satirlarda durur, boylece blok namespace'in ICINDE kalir."""
    k = idx
    while k - 1 >= 0:
        prev = lines[k - 1]
        if prev.strip() == "":
            break
        if COMMENT_LINE.match(prev) or ATTR_LINE.match(prev):
            k -= 1
            continue
        break
    return k


def parse_tag_ids(lines: list[str], open_idx: int) -> tuple[list[str], int]:
    """
    Mevcut bir //#( blogunun ID'lerini ve ID satiri sayisini dondurur.
    CONT_PREFIX = "" (yorumsuz) bicimini de tanir.
    """
    ids: list[str] = []
    m = re.match(r"^//#\(\[?\s*(.*)$", lines[open_idx].strip())
    if not m:
        return [], 0
    tok = m.group(1).strip().rstrip(",").rstrip("]").strip()
    if tok:
        ids.append(tok)

    i = open_idx + 1
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("//#"):
            break
        body = s[2:].strip() if s.startswith("//") else s
        body = body.rstrip(",").rstrip("]").strip()
        if not re.fullmatch(r"[A-Za-z_][\w.\-]*", body):
            break
        ids.append(body)
        i += 1
    return ids, i - open_idx


def diff_ids(csv_ids: list[str], code_ids: list[str]) -> str:
    """CSV ile koddaki ID'ler arasindaki farki insan okunur bicimde anlatir."""
    eksik = [x for x in csv_ids if x not in code_ids]     # CSV'de var, kodda yok
    fazla = [x for x in code_ids if x not in csv_ids]     # kodda var, CSV'de yok
    parts = []
    if eksik:
        parts.append("kodda EKSIK: " + ", ".join(eksik))
    if fazla:
        parts.append("kodda FAZLA: " + ", ".join(fazla))
    if not parts and csv_ids != code_ids:
        parts.append("ayni ID'ler, sirasi farkli")
    return " | ".join(parts)


def find_tagged_ranges(lines: list[str]) -> list[tuple[int, int, list[str], int]]:
    """Mevcut //#( ... //#) bloklari: (acilis, kapanis, ID listesi, ID satir sayisi)."""
    ranges = []
    open_idx = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("//#(") and not s.startswith(CLOSE_MARKER):
            if open_idx is None:
                open_idx = i
        elif s.startswith(CLOSE_MARKER) and open_idx is not None:
            ids, n = parse_tag_ids(lines, open_idx)
            ranges.append((open_idx, i, ids, n))
            open_idx = None
    if open_idx is not None:
        ids, n = parse_tag_ids(lines, open_idx)
        ranges.append((open_idx, len(lines) - 1, ids, n))
    return ranges


def range_for(ranges, idx: int):
    """idx satirini kapsayan blogu dondurur, yoksa None."""
    for rng in ranges:
        if rng[0] <= idx <= rng[1]:
            return rng
    return None


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
# 7) Ana akis
# --------------------------------------------------------------------

def main() -> int:
    tasks = read_csv_tasks(CSV_PATH)
    print(f"CSV'den {len(tasks)} satir okundu.\n")

    # header'lari coz ve dosyaya gore grupla
    groups: dict[Path, list[Task]] = {}
    for t in tasks:
        if t.status in ("HATA", "ATLANDI"):
            continue
        hdr, err = find_header(t)
        if hdr is None:
            t.status, t.detail = "HATA", err
            continue
        t.header = hdr
        groups.setdefault(hdr.resolve(), []).append(t)

    for file, file_tasks in groups.items():
        try:
            lines, enc, had_bom = read_lines(file)
        except Exception as e:
            for t in file_tasks:
                t.status, t.detail = "HATA", f"Dosya okunamadi: {e}"
            continue

        eol = detect_eol(lines)
        tagged = find_tagged_ranges(lines)

        planned = []
        updates = []
        for t in file_tasks:
            start, note = locate_class(lines, t.cls)
            if start is None:
                t.status, t.detail = "HATA", note
                continue

            end, col, err = find_block_end(lines, start)
            if end is None:
                t.status, t.detail = "HATA", err
                continue

            anchor = find_semicolon_anchor(lines, end, col)

            rng = range_for(tagged, start)
            if rng is not None:
                code_ids = rng[2]
                if set(code_ids) == set(t.hlr_ids):
                    t.status = "ATLANDI"
                    t.detail = f"Zaten etiketli - ID'ler ayni ({len(code_ids)} adet)"
                    continue
                t.detail = diff_ids(t.hlr_ids, code_ids)
                if not UPDATE_EXISTING_BLOCKS:
                    t.status = "FARKLI"
                    continue
                t.start_line, t.end_line = start + 1, rng[1] + 1
                updates.append((t, rng[0], rng[3]))
                continue

            insert_at = climb_above_comments(lines, start) if INSERT_ABOVE_DOC_COMMENTS else start

            if insert_at > 0 and lines[insert_at - 1].rstrip("\r\n").endswith("\\"):
                t.status, t.detail = "HATA", "Ust satir makro devami (\\) - elle yapilmali"
                continue

            t.start_line, t.end_line = start + 1, anchor + 1
            planned.append((t, insert_at, start, anchor))

        # ayni sinifa iki CSV satiri denk geldiyse ikincisini ele
        seen: set[int] = set()
        unique = []
        for item in planned:
            if item[2] in seen:
                item[0].status = "ATLANDI"
                item[0].detail = "Ayni sinif icin baska bir CSV satiri zaten islendi"
                continue
            seen.add(item[2])
            unique.append(item)
        planned = unique

        # asagidan yukariya uygula
        planned.sort(key=lambda x: x[3], reverse=True)
        for t, insert_at, start, anchor in planned:
            indent = leading_ws(lines[start])
            open_block = build_open_block(t.hlr_ids, indent, eol)
            close_line = f"{indent}{CLOSE_MARKER}{eol}"

            if not lines[anchor].endswith(("\n", "\r")):
                lines[anchor] = lines[anchor] + eol

            lines.insert(anchor + 1, close_line)
            lines[insert_at:insert_at] = open_block

            t.status = "OK"
            t.preview = (
                "".join(open_block)
                + lines[insert_at + len(open_block)]
                + "    ...\n"
                + lines[anchor + len(open_block)]
                + close_line
            )

        # === mevcut bloklarin ID'lerini guncelle (asagidan yukariya) ===
        updates.sort(key=lambda x: x[1], reverse=True)
        for t, open_idx, n_id_lines in updates:
            indent = leading_ws(lines[open_idx])
            new_block = build_open_block(t.hlr_ids, indent, eol)
            eski = "".join(lines[open_idx:open_idx + n_id_lines])
            lines[open_idx:open_idx + n_id_lines] = new_block
            t.status = "GUNCELLENDI"
            t.preview = "- eski -\n" + eski + "- yeni -\n" + "".join(new_block)

        if (planned or updates) and not DRY_RUN:
            write_lines(file, lines, enc, had_bom)

        if (planned or updates) and DRY_RUN and SHOW_PREVIEW:
            print(f"--- {file} ---")
            for t, *_ in sorted(planned, key=lambda x: x[2]):
                print(f"[satir {t.start_line}-{t.end_line}]  class {t.cls}")
                print(t.preview.rstrip())
                print()
            for t, *_ in sorted(updates, key=lambda x: x[1]):
                print(f"[GUNCELLEME satir {t.start_line}]  {t.detail}")
                print(t.preview.rstrip())
                print()

    # === rapor ===
    ok = sum(1 for t in tasks if t.status == "OK")
    upd = sum(1 for t in tasks if t.status == "GUNCELLENDI")
    dif = sum(1 for t in tasks if t.status == "FARKLI")
    skip = sum(1 for t in tasks if t.status == "ATLANDI")
    err = sum(1 for t in tasks if t.status == "HATA")
    pend = sum(1 for t in tasks if t.status == "PENDING")

    print("=" * 60)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  "
          f"OK: {ok}  GUNCELLENDI: {upd}  FARKLI: {dif}  "
          f"ATLANDI: {skip}  HATA: {err}  BEKLEYEN: {pend}")
    print("=" * 60)

    if dif:
        print("\nID'leri CSV ile UYUSMAYAN bloklar (dokunulmadi):")
        for t in tasks:
            if t.status == "FARKLI":
                print(f"  CSV satir {t.row_no}: {t.detail}")
        print("  -> UPDATE_EXISTING_BLOCKS = True yaparsan bunlari CSV'ye gore duzeltir.")

    if err or pend:
        print("\nEl ile bakilmasi gerekenler:")
        for t in tasks:
            if t.status in ("HATA", "PENDING"):
                hdr = t.header.name if t.header else "(header yok)"
                print(f"  CSV satir {t.row_no}: {t.src_name} -> {hdr} "
                      f"[sinif: '{t.cls}'] -> {t.detail}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["csv_row", "source_name", "class", "header",
                    "class_start", "class_end", "hlr_count", "status", "detail"])
        for t in tasks:
            w.writerow([t.row_no, t.src_name, t.cls, t.header or "",
                        t.start_line, t.end_line, len(t.hlr_ids or []),
                        t.status, t.detail])
    print(f"\nRapor: {REPORT_CSV}")

    if DRY_RUN:
        print("\nDRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
