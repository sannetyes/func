#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV'de listelenen HLR ID'lerini, ilgili KAYNAK (.cpp) dosyasindaki
CONSTRUCTOR tanimlarinin etrafina yorum blogu olarak ekler.
Harici bagimlilik YOKTUR (sadece stdlib).

Uretilen format (son ID'den sonra VIRGUL YOKTUR):

    //#([HLR_MODULE_1234,
    //	HLR_MODULE2_1234,
    //	HLR_MODULE3_1234
    Motor::Motor(int pin)
        : m_pin(pin)
    {
        ...
    }
    //#)

Beklenen CSV sutunlari (basliklar ilk satirda, sirasi onemli degil,
fazladan sutun varsa yok sayilir):
    Directory Name | Class/File Name | HLR Ids

Calisma mantigi:
    'Class/File Name' sutununda  Motor.cpp  (ya da Motor.h) yaziyorsa
        -> ayni dizinde  Motor.cpp  (yoksa .cc / .cxx / .c++) aranir
        -> o dosyada  'Motor::Motor( ... )'  CONSTRUCTOR TANIMI bulunur
        -> tanimin ustune ve govdeyi kapatan  }  satirinin altina blok yazilir

    Satir numarasi YOKTUR; constructor dosyanin tamaminda aranir. Bu yuzden:
      * destructor  (Motor::~Motor)                 -> eslesmez
      * normal metotlar (void Motor::init())        -> eslesmez
      * '= default;' / '= delete;'                  -> govde yok, HATA raporlanir
      * 'MotorBase::MotorBase' gibi isimler         -> eslesmez

    Yorumlar ve string/char literal icerikleri taramadan once temizlenir,
    bu yuzden yorum icindeki 'Motor::Motor' gibi metinler eslesmez.

OVERLOAD (birden fazla constructor):
    Sinifin birden fazla constructor'i varsa DOSYADAKI ILK (en ustteki)
    constructor etiketlenir, digerlerine dokunulmaz. Bu durum hata degildir;
    "BIRDEN FAZLA CONSTRUCTOR" basligi altinda bilgi olarak raporlanir ve
    raporda ctor_count / ctor_lines / tagged_line sutunlarinda gorunur.

AYKIRI DOSYALAR (elle bakilmasi gerekenler) ayrica raporlanir:
      * kaynak dosya hic bulunamadi                 -> DOSYA_YOK
      * dosyada hic constructor yok                 -> CTOR_YOK
      * constructor var ama sinif adi tutmuyor      -> ISIM_FARKLI
        (ornek: Valve.cpp icinde CValve::CValve)
      * constructor bildirimi var ama govdesi yok   -> GOVDE_YOK
    Bunlarin listesi ekrana basilir ve MISSING_CTOR_CSV dosyasina yazilir.

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
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

CSV_PATH = "hlr_class.csv"       # CSV dosyasinin yolu
CSV_DELIMITER = None             # None = otomatik tespit;  ya da ";" / "," / "\t"

# CSV'deki 'Directory Name' sutunu goreli ise, projenin kok dizini.
SOURCE_ROOT = ""

DRY_RUN = True                   # True iken hicbir dosya degismez
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = "hlr_ctor_report.csv"
MISSING_CTOR_CSV = "hlr_ctor_missing.csv"   # aykiri dosyalarin listesi
SHOW_PREVIEW = True              # Dry-run'da eklenecek bloklari ekrana bas

# Kaynak dosya ararken denenecek uzantilar (sirayla)
SOURCE_EXTENSIONS = [".cpp", ".cc", ".cxx", ".c++", ".C"]

# Kaynagi once ayni dizinde ara; bulunamazsa bu alt/ust dizinlere de bak
# (proje kokune gore goreli, "" = SOURCE_ROOT'un kendisi). Bos birakilabilir.
EXTRA_SOURCE_DIRS: list[str] = []

CSV_ENCODINGS = ["utf-8-sig", "utf-8", "cp1254", "latin-1"]
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

SKIP_IF_ALREADY_TAGGED = True    # blok zaten varsa ustune ikinci blok yazilmaz

# Blok var AMA ID'ler CSV ile ayni degilse:
#   False -> dokunma, "FARKLI" diye raporla (guvenli varsayilan)
#   True  -> koddaki ID satirlarini CSV'dekilerle DEGISTIR
UPDATE_EXISTING_BLOCKS = False
INSERT_ABOVE_DOC_COMMENTS = True   # ctor'un ustundeki yorum blogunun da ustune yaz

# NOT: Ayni sinifin birden fazla constructor'i (overload) varsa, dosyadaki
# ILK (en ustteki) constructor etiketlenir; digerlerine dokunulmaz.

# Dosyada beklenen isimde ctor yok ama TEK bir baska sinifin ctor'u varsa
# (ornek: Valve.cpp icinde sadece CValve::CValve) onu kullan.
#   False -> kullanma, ISIM_FARKLI diye raporla (guvenli varsayilan)
FALLBACK_SINGLE_CTOR = False

# --- cikti formati ---
OPEN_PREFIX = "//#(["
CONT_PREFIX = "//"               # "" yaparsan derlenmez
CONT_INDENT = "\t"
TRAILING_COMMA_ON_LAST = False   # False -> son HLR ID'sinden sonra virgul YOK
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
    cls: str                  # cikarilan sinif adi        (ornek: Motor)
    directory: Path
    source: Path | None = None        # bulunan .cpp dosyasi
    hlr_ids: list[str] = None
    status: str = "PENDING"
    detail: str = ""
    issue: str = ""                   # DOSYA_YOK / CTOR_YOK / ISIM_FARKLI ...
    ctor_name: str = ""               # gercekte kullanilan ctor sinif adi
    ctor_count: int = 0
    ctor_lines: list[int] = field(default_factory=list)   # dosyadaki tum ctor satirlari
    tagged_line: int = 0                                  # etiketlenen ctor satiri
    overload_note: str = ""                               # overload bilgisi
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
# 2) Kaynak (.cpp) dosyasini bul
# --------------------------------------------------------------------

def find_source(task: Task) -> tuple[Path | None, str]:
    tried: list[str] = []
    dirs = [task.directory]
    for extra in EXTRA_SOURCE_DIRS:
        dirs.append(Path(SOURCE_ROOT) / extra if SOURCE_ROOT else Path(extra))

    given_ext = Path(task.src_name.replace("\\", "/")).suffix
    exts = list(SOURCE_EXTENSIONS)
    if given_ext and given_ext in exts:          # CSV zaten .cpp veriyorsa once onu dene
        exts.remove(given_ext)
        exts.insert(0, given_ext)

    for d in dirs:
        for ext in exts:
            cand = d / (task.cls + ext)
            tried.append(str(cand))
            if cand.exists():
                return cand, ""
    return None, f"Kaynak dosya bulunamadi. Denenen: {', '.join(tried[:4])}"


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
# 4) Kod gorunumu
#    Yorumlar ve string/char literal ICERIKLERI bosluga cevrilir.
#    Satir sayisi ve satir uzunluklari korunur -> indeksler orijinalle ayni.
# --------------------------------------------------------------------

def build_code_view(lines: list[str]) -> list[str]:
    view: list[str] = []
    in_block = False          # /* ... */ icinde miyiz
    in_str: str | None = None  # " ya da ' icinde miyiz
    raw_delim: str | None = None   # R"delim( ... )delim"

    for raw in lines:
        nl = ""
        line = raw
        while line.endswith(("\n", "\r")):
            nl = line[-1] + nl
            line = line[:-1]

        buf = list(line)
        i, n = 0, len(line)

        while i < n:
            c = line[i]
            nxt = line[i + 1] if i + 1 < n else ""

            if in_block:
                if c == "*" and nxt == "/":
                    in_block = False
                    buf[i] = " "
                    buf[i + 1] = " "
                    i += 2
                else:
                    buf[i] = " "
                    i += 1
                continue

            if raw_delim is not None:
                end = line.find(")" + raw_delim + '"', i)
                if end == -1:
                    for k in range(i, n):
                        buf[k] = " "
                    i = n
                else:
                    for k in range(i, end + 1 + len(raw_delim)):
                        buf[k] = " "
                    i = end + len(raw_delim) + 2
                    raw_delim = None
                continue

            if in_str is not None:
                if c == "\\":
                    buf[i] = " "
                    if i + 1 < n:
                        buf[i + 1] = " "
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
                    i += 1
                    continue
                buf[i] = " "
                i += 1
                continue

            # --- normal kod ---
            if c == "/" and nxt == "/":
                for k in range(i, n):
                    buf[k] = " "
                i = n
                continue

            if c == "/" and nxt == "*":
                in_block = True
                buf[i] = " "
                buf[i + 1] = " "
                i += 2
                continue

            if c == '"':
                if i > 0 and line[i - 1] == "R":          # ham string
                    k = line.find("(", i + 1)
                    if k != -1:
                        raw_delim = line[i + 1:k]
                        for m in range(i + 1, k + 1):
                            buf[m] = " "
                        i = k + 1
                        continue
                in_str = '"'
                i += 1
                continue

            if c == "'":
                if i > 0 and line[i - 1].isdigit():        # 1'000'000
                    i += 1
                    continue
                in_str = "'"
                i += 1
                continue

            i += 1

        view.append("".join(buf) + nl)

    return view


def iter_chars(view: list[str], i0: int, j0: int):
    for i in range(i0, len(view)):
        line = view[i]
        j = j0 if i == i0 else 0
        while j < len(line):
            yield i, j, line[j]
            j += 1


# --------------------------------------------------------------------
# 5) Constructor tanimini ve govdesini bul
# --------------------------------------------------------------------

TEMPLATE_ARGS = r"(?:\s*<[^<>;{}]*>)?"

# 'Sinif::Sinif('  ya da  'Sinif<T>::Sinif('  (destructor '~' KAPSAM DISI)
ANY_CTOR_RE = re.compile(
    rf"\b([A-Za-z_]\w*){TEMPLATE_ARGS}\s*::\s*([A-Za-z_]\w*){TEMPLATE_ARGS}\s*\("
)


def build_ctor_pattern(cls: str) -> re.Pattern:
    esc = re.escape(cls)
    # '(' ayni satirda olmayabilir -> satir sonu da kabul edilir
    return re.compile(rf"\b{esc}{TEMPLATE_ARGS}\s*::\s*{esc}{TEMPLATE_ARGS}\s*(?:\(|$)")


def find_ctor_body(view: list[str], start_idx: int, start_col: int):
    """
    Constructor imzasindan itibaren govdeyi bulur.
    Uye baslatma listesindeki  : a(1), b{2}  parantez/susluleri atlanir.

    Doner: (acilis (i,j) | None, kapanis (i,j) | None, aciklama)
    """
    state = "PARAMS"
    depth = 0
    init_open = init_close = ""
    open_pos = None

    for i, j, c in iter_chars(view, start_idx, start_col):
        if state == "PARAMS":
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    state = "AFTER_PARAMS"
            elif c == ";" and depth == 0:
                return None, None, "Govde yok (bildirim gibi gorunuyor)"
            continue

        if state == "AFTER_PARAMS":
            if c.isspace():
                continue
            if c == ":":
                state = "INIT_MEMBER"
                continue
            if c == "{":
                open_pos = (i, j)
                state = "BODY"
                depth = 1
                continue
            if c == ";":
                return None, None, "Govde yok ('= default' / '= delete' / bildirim)"
            continue   # noexcept, const, override ... atlanir

        if state == "INIT_MEMBER":
            if c in "({":
                init_open = c
                init_close = ")" if c == "(" else "}"
                depth = 1
                state = "INIT_ARGS"
            elif c == ";":
                return None, None, "Baslatma listesi yarim kalmis"
            continue

        if state == "INIT_ARGS":
            if c == init_open:
                depth += 1
            elif c == init_close:
                depth -= 1
                if depth == 0:
                    state = "INIT_AFTER"
            continue

        if state == "INIT_AFTER":
            if c.isspace():
                continue
            if c == ",":
                state = "INIT_MEMBER"
                continue
            if c == "{":
                open_pos = (i, j)
                state = "BODY"
                depth = 1
                continue
            if c == ";":
                return None, None, "Govde yok (baslatma listesinden sonra ';')"
            continue   # '...' paket acilimi vb.

        if state == "BODY":
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return open_pos, (i, j), ""
            continue

    return None, None, "Govde kapanisi bulunamadi (dosya sonuna gelindi)"


def is_call_context(line: str, pos: int) -> bool:
    """'new X::X(' / 'p->X::X(' gibi cagri gorunumlerini ele."""
    before = line[:pos].rstrip()
    if before.endswith((".", "->", "&", "*")):
        return True
    m = re.search(r"([A-Za-z_]\w*)\s*$", before)
    return bool(m and m.group(1) in ("new", "return", "delete", "sizeof", "throw"))


def locate_ctors(view: list[str], cls: str):
    """
    Doner: (hits, problems)
      hits     : [(start_idx, end_idx, end_col), ...]
      problems : govdesi bulunamayan eslesmelerin aciklamalari
    """
    pat = build_ctor_pattern(cls)
    hits = []
    problems: list[str] = []

    for i, raw in enumerate(view):
        line = raw.rstrip("\r\n")
        for m in pat.finditer(line):
            if is_call_context(line, m.start()):
                continue
            col = m.end() - 1 if line[m.end() - 1:m.end()] == "(" else len(line)
            if any(h[0] <= i <= h[1] for h in hits):     # baska bir ctor govdesi icinde
                continue
            _open, close, err = find_ctor_body(view, i, col)
            if close is None:
                problems.append(f"satir {i + 1}: {err}")
                continue
            hits.append((i, close[0], close[1]))
    return hits, problems


def find_any_ctors(view: list[str]) -> list[tuple[str, int]]:
    """Dosyadaki TUM constructor tanimlari: [(sinif_adi, satir_no), ...]"""
    out: list[tuple[str, int]] = []
    for i, raw in enumerate(view):
        line = raw.rstrip("\r\n")
        for m in ANY_CTOR_RE.finditer(line):
            if m.group(1) != m.group(2):
                continue
            if is_call_context(line, m.start()):
                continue
            out.append((m.group(1), i + 1))
    return out


# --------------------------------------------------------------------
# 6) Yerlestirme yardimcilari
# --------------------------------------------------------------------

COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\*/)")
# NOT: onisleyici satirlari (#if / #include) bilerek DISARIDA birakildi,
# blok #ifdef'in disina tasinmasin diye.
ATTR_LINE = re.compile(r"^\s*(template\s*<|__attribute__|\[\[)")


def climb_above_comments(lines: list[str], idx: int) -> int:
    """Ctor'un ustundeki bitisik yorum / template satirlarina cikar."""
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


def find_close_anchor(lines: list[str], end_idx: int, end_col: int) -> int:
    """
    Govde kapanisindan sonra ayri satirda ';' varsa (nadiren) onu da kapsa.
    Normalde fonksiyon govdesi ';' istemez -> kapanis '}' satiri dondurulur.
    """
    rest = lines[end_idx][end_col + 1:].split("//", 1)[0]
    if ";" in rest:
        return end_idx
    k = end_idx + 1
    while k < len(lines) and k <= end_idx + 2:
        s = lines[k].strip()
        if s == "":
            break
        if s.startswith(";"):
            return k
        break
    return end_idx


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


def find_tagged_ranges(lines: list[str]):
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

def resolve_targets(t: Task, view: list[str]) -> list[tuple[int, int, int]]:
    """
    Task icin etiketlenecek constructor'lari secer.
    Bulunamazsa t.status / t.detail / t.issue doldurulur ve [] doner.
    """
    hits, problems = locate_ctors(view, t.cls)
    t.ctor_name = t.cls

    if not hits:
        others = find_any_ctors(view)
        names = sorted({n for n, _ in others})

        if not others:
            t.status = "HATA"
            t.issue = "CTOR_YOK"
            t.detail = f"'{t.cls}::{t.cls}(...)' yok; dosyada hic constructor tanimi yok"
            if problems:
                t.detail += " | " + "; ".join(problems)
            return []

        if t.cls in names:                 # isim var ama govde yok (= default gibi)
            t.status = "HATA"
            t.issue = "GOVDE_YOK"
            t.detail = (f"'{t.cls}::{t.cls}' bulundu ama govdesi yok - "
                        + ("; ".join(problems) if problems else "'= default' olabilir"))
            return []

        listed = ", ".join(f"{n}::{n} (satir {ln})" for n, ln in others[:4])
        if FALLBACK_SINGLE_CTOR and len(names) == 1:
            alt = names[0]
            alt_hits, _ = locate_ctors(view, alt)
            if alt_hits:
                t.ctor_name = alt
                t.detail = f"Isim farkli: '{alt}::{alt}' kullanildi (dosya adi: {t.cls})"
                t.issue = "ISIM_FARKLI"
                hits = alt_hits
            else:
                t.status, t.issue = "HATA", "ISIM_FARKLI"
                t.detail = f"'{t.cls}::{t.cls}' yok. Dosyadaki ctor'lar: {listed}"
                return []
        else:
            t.status, t.issue = "HATA", "ISIM_FARKLI"
            t.detail = f"'{t.cls}::{t.cls}' yok. Dosyadaki ctor'lar: {listed}"
            return []

    # locate_ctors satirlari bastan sona tarar -> hits[0] dosyadaki ILK ctor'dur
    hits.sort(key=lambda h: h[0])
    t.ctor_count = len(hits)
    t.ctor_lines = [h[0] + 1 for h in hits]
    t.tagged_line = t.ctor_lines[0]

    if len(hits) > 1:
        digerleri = ", ".join(str(x) for x in t.ctor_lines[1:])
        t.overload_note = (f"{len(hits)} constructor var; ilki etiketlendi "
                           f"(satir {t.tagged_line}), dokunulmayanlar: satir {digerleri}")
        t.detail = (t.detail + " | " + t.overload_note) if t.detail else t.overload_note

    return hits[:1]        # overload olsa da SADECE ilk constructor etiketlenir


def main() -> int:
    tasks = read_csv_tasks(CSV_PATH)
    print(f"CSV'den {len(tasks)} satir okundu.\n")

    # kaynak dosyalari coz ve dosyaya gore grupla
    groups: dict[Path, list[Task]] = {}
    for t in tasks:
        if t.status in ("HATA", "ATLANDI"):
            continue
        src, err = find_source(t)
        if src is None:
            t.status, t.detail, t.issue = "HATA", err, "DOSYA_YOK"
            continue
        t.source = src
        groups.setdefault(src.resolve(), []).append(t)

    for file, file_tasks in groups.items():
        try:
            lines, enc, had_bom = read_lines(file)
        except Exception as e:
            for t in file_tasks:
                t.status, t.detail, t.issue = "HATA", f"Dosya okunamadi: {e}", "OKUNAMADI"
            continue

        view = build_code_view(lines)
        eol = detect_eol(lines)
        tagged = find_tagged_ranges(lines)

        planned = []     # (task, insert_at, start, anchor)
        updates = []     # (task, open_idx, id_satir_sayisi)

        for t in file_tasks:
            targets = resolve_targets(t, view)
            if not targets:
                continue

            for start, end_idx, end_col in targets:
                anchor = find_close_anchor(lines, end_idx, end_col)

                rng = range_for(tagged, start)
                if rng is not None and SKIP_IF_ALREADY_TAGGED:
                    code_ids = rng[2]
                    if set(code_ids) == set(t.hlr_ids):
                        t.status = "ATLANDI"
                        t.detail = f"Zaten etiketli - ID'ler ayni ({len(code_ids)} adet)"
                        continue
                    t.detail = diff_ids(t.hlr_ids, code_ids)
                    if not UPDATE_EXISTING_BLOCKS:
                        t.status = "FARKLI"
                        continue
                    updates.append((t, rng[0], rng[3]))
                    continue

                insert_at = climb_above_comments(lines, start) if INSERT_ABOVE_DOC_COMMENTS else start

                if insert_at > 0 and lines[insert_at - 1].rstrip("\r\n").endswith("\\"):
                    t.status = "HATA"
                    t.issue = "MAKRO"
                    t.detail = "Ust satir makro devami (\\) - elle yapilmali"
                    continue

                planned.append((t, insert_at, start, anchor))

        # ayni ctor'a iki CSV satiri denk geldiyse ikincisini ele
        seen: set[int] = set()
        unique = []
        for item in planned:
            if item[2] in seen:
                item[0].status = "ATLANDI"
                item[0].detail = "Ayni constructor icin baska bir CSV satiri zaten islendi"
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

            preview = (
                "".join(open_block)
                + lines[start]
                + f"{indent}    ...{eol}"
                + lines[anchor]
                + close_line
            )

            lines.insert(anchor + 1, close_line)
            lines[insert_at:insert_at] = open_block

            t.status = "OK"
            t.preview = (t.preview + "\n" + preview) if t.preview else preview

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
            for t, _ins, start, _anc in sorted(planned, key=lambda x: x[2]):
                print(f"[satir {start + 1}]  {t.ctor_name}::{t.ctor_name}(...)")
                print(t.preview.rstrip())
                print()
            for t, open_idx, _n in sorted(updates, key=lambda x: x[1]):
                print(f"[GUNCELLEME satir {open_idx + 1}]  {t.detail}")
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

    # --- bilgi: overload olan siniflar (hata degil) ---
    overloads = [t for t in tasks if t.overload_note]
    if overloads:
        print("\nBIRDEN FAZLA CONSTRUCTOR (ilki etiketlendi):")
        for t in overloads:
            src = t.source.name if t.source else t.src_name
            print(f"  CSV satir {t.row_no}: {src} -> {t.overload_note}")

    # --- aykiri dosyalar: ctor bulunamayan / eslesmeyen ---
    aykiri = [t for t in tasks
              if t.issue in ("DOSYA_YOK", "CTOR_YOK", "ISIM_FARKLI",
                             "GOVDE_YOK", "OKUNAMADI", "MAKRO")]
    if aykiri:
        print("\nAYKIRI DOSYALAR (constructor bulunamadi / eslesmedi):")
        for t in aykiri:
            src = t.source.name if t.source else t.src_name
            isaret = "*" if t.status == "HATA" else " "
            print(f" {isaret} CSV satir {t.row_no}: {src} [{t.issue}] -> {t.detail}")
        print("   ('*' = etiketlenmedi, elle bakilmali)")

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
                src = t.source.name if t.source else "(kaynak yok)"
                print(f"  CSV satir {t.row_no}: {t.src_name} -> {src} "
                      f"[sinif: '{t.cls}'] -> {t.detail}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["csv_row", "source_name", "class", "ctor_class", "source_file",
                    "ctor_count", "ctor_lines", "tagged_line",
                    "hlr_count", "status", "issue", "detail"])
        for t in tasks:
            w.writerow([t.row_no, t.src_name, t.cls, t.ctor_name, t.source or "",
                        t.ctor_count, ",".join(str(x) for x in t.ctor_lines),
                        t.tagged_line or "",
                        len(t.hlr_ids or []), t.status, t.issue, t.detail])
    print(f"\nRapor: {REPORT_CSV}")

    if aykiri:
        with open(MISSING_CTOR_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["csv_row", "source_name", "class", "source_file",
                        "issue", "status", "detail"])
            for t in aykiri:
                w.writerow([t.row_no, t.src_name, t.cls, t.source or "",
                            t.issue, t.status, t.detail])
        print(f"Aykiri dosyalar: {MISSING_CTOR_CSV}")

    if DRY_RUN:
        print("\nDRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
