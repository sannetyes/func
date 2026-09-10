#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV'de listelenen HLR ID'lerini, ilgili .cpp dosyalarindaki fonksiyonlarin
GOVDESININ ICINE yorum blogu olarak ekler.  Harici bagimlilik YOKTUR (sadece stdlib).

Uretilen format (varsayilan: satir basina 2 ID, SON ID'den sonra VIRGUL YOK):

    // Fonksiyonun ustundeki yorumlara ve imzasina dokunulmaz
    int func_name(param1){
    //#([HLR_MODULE_1234, HLR_MODULE2_1234,
    //	HLR_MODULE3_1234, HLR_MODULE4_1234,
    //	HLR_MODULE5_1234
        ...
    //#)
    }

  * Acilis blogu, govdeyi acan '{' satirinin HEMEN ALTINA yazilir.
  * Kapanis isareti '//#)', govdeyi kapatan '}' satirinin HEMEN USTUNE yazilir.
  * Ikisi de fonksiyon imzasi ile ayni girintiyi kullanir.
  * '{' satirinin sonundaki // yorumu oldugu yerde kalir.
  * '{' ya da '}' ile ayni satirda KOD varsa satir bolunur, kod kendi
    satirina (govde girintisiyle) tasinir.  Ornek:

        int f() { return 1; }        ->     int f() {
                                            //#([HLR_1
                                                return 1;
                                            //#)
                                            }

Beklenen CSV sutunlari (basliklar ilk satirda, sirasi onemli degil):
    Directory Name | Class/File Name | Function Name | Line Number | HLR Ids

Notlar:
  * Sadece .cpp dosyalari islenir; digerleri atlanip rapora yazilir.
  * 'Function Name' sutunundaki isimlerde namespace onekleri silinmis olabilir
    (ornek: kodda  ns::Motor::start  , CSV'de  Motor::start  ya da  start ).
    Eslestirme son tanimlayiciya bakar, ustune ( parantezini de arar.
  * 'HLR Ids' hucresindeki ID'ler virgul / noktali virgul / satir sonu / boru
    ile ayrilmis olabilir; hepsi taninir.
  * Satir basina kac ID yazilacagi IDS_PER_LINE ile ayarlanir (varsayilan 2).
  * Son ID'den sonra virgul yazilmaz; istersen TRAILING_COMMA_ON_LAST = True.
  * Zaten etiketli fonksiyonlar atlanir.  Hem yeni format (govde icinde)
    hem de eski format (fonksiyonun ustunde //#( , } sonrasinda //#) ) taninir.

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

# Fonksiyon zaten etiketliyse atla (idempotent calisma)
SKIP_IF_ALREADY_TAGGED = True

# --- cikti formati ---
OPEN_PREFIX = "//#(["            # ilk satirin basi ( '{' satirinin hemen altina )
CONT_PREFIX = "//"               # DEVAM satirlarinin yorum oneki ("" yaparsan
                                 # kod DERLENMEZ)
CONT_INDENT = "\t"               # devam satirlarinin girintisi ("    " = 4 bosluk)
IDS_PER_LINE = 2                 # satir basina kac HLR ID yazilsin (1 = eski hali)
INLINE_SEPARATOR = " "           # ayni satirdaki ID'ler arasinda, virgulden SONRA
TRAILING_COMMA_ON_LAST = False   # False -> son ID'den sonra VIRGUL YOK
CLOSE_LIST_SUFFIX = ""           # son ID'den sonra "]" istersen "]" yaz
CLOSE_MARKER = "//#)"            # govdeyi kapatan '}' satirinin hemen ustune

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
    base: str = ""            # imzadan cikarilan fonksiyon adi
    start_line: int = 0       # dogrulanmis 1-tabanli baslangic
    end_line: int = 0         # fonksiyonun } satiri (1-tabanli, degisiklik oncesi)
    preview: str = ""


@dataclass
class BodySpan:
    """Fonksiyon govdesinin sinirlari (hepsi 0-tabanli)."""
    open_line: int            # govdeyi acan '{' satiri
    open_col: int             # ... ve sutunu
    close_line: int           # govdeyi kapatan '}' satiri
    close_col: int            # ... ve sutunu


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
        t.base = func_base(func)

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

def find_function_body(lines: list[str], start_idx: int) -> tuple[BodySpan | None, str]:
    """
    start_idx (0-tabanli) satirindan itibaren fonksiyon govdesini acan '{'
    ile onu kapatan '}' karakterinin konumlarini (satir + sutun) dondurur.
    """
    depth = 0            # { } derinligi
    paren = 0            # ( ) derinligi -> parametre icindeki {} sayilmasin
    body_open = False
    open_pos = (0, 0)    # govdeyi acan '{' (satir, sutun)
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
            prv = line[j - 1] if j > 0 else ""

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
                if prv == "R":
                    k = line.find("(", j + 1)
                    if k != -1:
                        raw_delim = line[j + 1:k]
                        j = k + 1
                        continue
                in_str = '"'
                j += 1
                continue

            if c == "'":
                if prv.isdigit():              # 1'000'000
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
            elif (c == ":" and paren == 0 and params_closed and not body_open
                  and nxt != ":" and prv != ":"):
                # '::' in iki karakteri de init listesi baslatmaz
                # ( auto f() -> std::string { ... } )
                init_list = True
            elif c == "{" and paren == 0:
                if not body_open and init_list and last_code_char not in (")", "}", ""):
                    depth += 1                 # ctor init listesi: x{0} -> govde degil
                    j += 1
                    last_code_char = c
                    continue
                depth += 1
                if not body_open:
                    body_open = True
                    open_pos = (i, j)
            elif c == "}" and paren == 0:
                depth -= 1
                if body_open and depth == 0:
                    return BodySpan(open_pos[0], open_pos[1], i, j), ""
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
    CSV'deki 'Function Name' hucresinden SADECE fonksiyon adini cikarir.
    Hucre tam imza icerebilir: donus tipi + (varsa) niteleyiciler + parametreler.

        'LBOOL funcname(paramNameSpace::param1)'   -> 'funcname'
        'LBOOL namespace1::funcname(ns::p1)'       -> 'funcname'
        'void* Foo::getPtr(int)'                   -> 'getPtr'
        'LBOOL *Foo::ptrStyle(int)'                -> 'ptrStyle'
        'const std::string& Foo::name() const'     -> 'name'
        'Foo::Foo(int)'                            -> 'Foo'
        'void Foo::~Foo()'                         -> '~Foo'
        'T Buffer<T>::push(T v)'                   -> 'push'
        'bool Foo::operator==(const Foo&)'         -> 'operator=='
        'funcname'                                 -> 'funcname'
    """
    n = name.strip()
    if not n:
        return ""

    # 1) operator asiri yuklemeleri ozel: parametre parantezi ile karisir
    m = re.search(r"\boperator\s*(\(\s*\)|\[\s*\]|[^\s(]+)", n)
    if m:
        return "operator" + re.sub(r"\s+", "", m.group(1))

    # 2) parametre listesini at
    if "(" in n:
        n = n.split("(", 1)[0]
    n = n.strip()

    # 3) donus tipi ve niteleyicileri at: son bosluk-ayrik parca isimdir
    #    ('const std::string& Foo::name' -> 'Foo::name')
    if n.split():
        n = n.split()[-1]

    # 4) 'LBOOL *funcname' gibi yazimlarda basa yapisan isaretler
    n = n.lstrip("*&")

    # 5) sondaki template argumanlari:  'push<int>' -> 'push'
    n = re.sub(r"<[^<>]*>\s*$", "", n).strip()

    # 6) namespace / sinif niteleyicileri (CSV'de silinmis olabilir, olmayabilir)
    if "::" in n:
        n = n.rsplit("::", 1)[-1]

    return n.strip()


def code_part(line: str) -> str:
    """Satirdaki // yorumunu atar (eslesme yorumdan gelmesin diye)."""
    return line.split("//", 1)[0]


# Tamamen yorum olan satirlar ( // ... ,  /* ... ,  * ... ) aday sayilmaz;
# aksi halde Doxygen blogunda gecen 'func_name()' tanim sanilabilir.
COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*)")

CONTROL_KW = {"if", "while", "for", "switch", "return", "else", "catch",
              "do", "case", "throw", "assert"}


def is_definition_site(line: str, pos: int) -> bool:
    """
    Eslesmenin bir TANIM satiri mi yoksa CAGRI satiri mi oldugunu ayirt eder.
    'if (funcname(x)) {'  ya da  'obj.funcname(x);'  gibi satirlar elenir.
    """
    before = line[:pos]

    # ismin oncesinde kapanmamis '(' varsa: baska bir ifadenin icindeyiz
    if before.count("(") > before.count(")"):
        return False

    # uye cagrisi:  obj.funcname(  /  ptr->funcname(
    stripped = before.rstrip()
    if stripped.endswith((".", "->")):
        return False

    # satir bir kontrol anahtar kelimesi ile basliyorsa tanim degildir
    words = re.findall(r"[A-Za-z_]\w*", before)
    if words and words[0] in CONTROL_KW:
        return False

    return True


def build_patterns(base: str):
    if base.startswith("operator"):
        esc = r"operator\s*" + re.escape(base[len("operator"):])
    else:
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
    cands = [c for c in cands if not COMMENT_LINE.match(lines[c])]

    def note(c: int) -> str:
        return "" if c == center else f"Satir {task.line} -> {c + 1} olarak duzeltildi"

    # 1) isim + '(' eslesen, CAGRI olmayan VE govdesi olan ilk aday
    strong_hits = []
    for c in cands:
        cp = code_part(lines[c])
        mm = strong.search(cp)
        if mm and is_definition_site(cp, mm.start()):
            strong_hits.append(c)
    for c in strong_hits:
        if find_function_body(lines, c)[0] is not None:
            return c, note(c)

    # 2) isim tek basina gecen, CAGRI olmayan VE govdesi olan ilk aday
    #    (cok satirli imza)
    for c in cands:
        cp = code_part(lines[c])
        mm = loose.search(cp)
        if (mm and is_definition_site(cp, mm.start())
                and find_function_body(lines, c)[0] is not None):
            return c, (note(c) + " (imza cok satirli olabilir)").strip()

    if strong_hits:
        return None, (f"'{base}' bulundu (satir {strong_hits[0] + 1}) ama govdesi yok "
                      f"- prototip olabilir")
    return None, f"Fonksiyon '{base}' satir {task.line} civarinda bulunamadi"


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


def is_already_tagged(ranges: list[tuple[int, int]], start: int, span: BodySpan) -> bool:
    for lo, hi in ranges:
        if span.open_line <= lo <= span.close_line:   # yeni format: blok govdenin icinde
            return True
        if lo <= start <= hi:                          # eski format: blok fonksiyonu sariyor
            return True
    return False


def touches_macro_continuation(lines: list[str], span: BodySpan) -> bool:
    """
    Eklenecek satirlarin komsusu '\\' ile bitiyorsa fonksiyon bir makronun
    icindedir; araya // satiri girmek makroyu bozar.
    """
    def cont(i: int) -> bool:
        return 0 <= i < len(lines) and lines[i].rstrip("\r\n").endswith("\\")
    return (cont(span.open_line - 1) or cont(span.open_line)
            or cont(span.close_line - 1))


# --------------------------------------------------------------------
# 5) Blok uretimi
# --------------------------------------------------------------------

def leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def split_eol(line: str) -> tuple[str, str]:
    """'abc\\r\\n' -> ('abc', '\\r\\n')"""
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def detect_eol(lines: list[str]) -> str:
    for ln in lines:
        if ln.endswith("\r\n"):
            return "\r\n"
        if ln.endswith("\n"):
            return "\n"
    return "\n"


def detect_indent_unit(lines: list[str]) -> str:
    """Dosya tab mi bosluk mu kullaniyor (sadece tasinan kod satirlari icin)."""
    tabs = sum(1 for ln in lines if ln.startswith("\t"))
    spaces = sum(1 for ln in lines if ln.startswith("  "))
    return "\t" if tabs > spaces else "    "


def guess_body_indent(lines: list[str], span: BodySpan, indent: str, unit: str) -> str:
    """Govdedeki ilk dolu satirin girintisi; yoksa imza girintisi + 1 seviye."""
    for k in range(span.open_line + 1, span.close_line):
        if lines[k].strip():
            ws = leading_ws(lines[k])
            if len(ws) > len(indent) and ws.startswith(indent):
                return ws
            break
    return indent + unit


def chunk_ids(ids: list[str], per_line: int) -> list[list[str]]:
    """ID listesini satir basina 'per_line' adet olacak sekilde boler."""
    n = max(1, int(per_line))
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def build_open_block(ids: list[str], indent: str, eol: str) -> list[str]:
    """
    IDS_PER_LINE adet ID'yi ayni satira yazar.
    TRAILING_COMMA_ON_LAST = False iken SON ID'den sonra virgul konmaz.

    IDS_PER_LINE = 2 ve 5 ID icin:
        //#([HLR_1, HLR_2,
        //	HLR_3, HLR_4,
        //	HLR_5
    """
    out: list[str] = []
    chunks = chunk_ids(ids, IDS_PER_LINE)

    for ci, chunk in enumerate(chunks):
        last_chunk = ci == len(chunks) - 1
        parts: list[str] = []

        for k, hid in enumerate(chunk):
            last_id = last_chunk and (k == len(chunk) - 1)
            sep = "" if (last_id and not TRAILING_COMMA_ON_LAST) else ","
            parts.append(f"{hid}{sep}")

        # virguller zaten parcalarin sonunda; aralara sadece bosluk konur
        body = INLINE_SEPARATOR.join(parts)
        if last_chunk:
            body += CLOSE_LIST_SUFFIX

        if ci == 0:
            out.append(f"{indent}{OPEN_PREFIX}{body}{eol}")
        else:
            out.append(f"{indent}{CONT_PREFIX}{CONT_INDENT}{body}{eol}")

    return out


def build_tagged_body(lines: list[str], span: BodySpan, indent: str, body_indent: str,
                      open_block: list[str], close_line: str,
                      eol: str) -> tuple[list[str], int, int]:
    """
    lines[span.open_line : span.close_line + 1] araliginin YERINE gececek
    satirlari uretir.

    Donus: (yeni_satirlar, acilis_blogunun_indeksi, kapanis_isaretinin_indeksi)
    """
    L, E = span.open_line, span.close_line
    out: list[str] = []

    if L == E:
        # tek satirlik govde:  int f() { return 1; }   /   void g() {}
        text, own_eol = split_eol(lines[L])
        head = text[:span.open_col + 1]
        middle = text[span.open_col + 1:span.close_col].strip()
        tail = text[span.close_col:]

        out.append(head + eol)
        open_at = len(out)
        out.extend(open_block)
        if middle:
            out.append(body_indent + middle + eol)
        close_at = len(out)
        out.append(close_line)
        out.append(indent + tail + own_eol)
        return out, open_at, close_at

    # --- acilis: '{' satiri ---
    text, own_eol = split_eol(lines[L])
    rest = text[span.open_col + 1:]
    if not rest.strip() or rest.lstrip().startswith("//"):
        # '{' satir sonunda (ya da arkasinda sadece // yorumu var) -> dokunma
        out.append(lines[L])
        open_at = len(out)
        out.extend(open_block)
    else:
        # '{' arkasinda kod var -> satiri bol, kodu govdeye tasi
        out.append(text[:span.open_col + 1] + eol)
        open_at = len(out)
        out.extend(open_block)
        out.append(body_indent + rest.lstrip() + own_eol)

    # --- govde ---
    out.extend(lines[L + 1:E])

    # --- kapanis: '}' satiri ---
    text, own_eol = split_eol(lines[E])
    before = text[:span.close_col]
    if not before.strip():
        # '}' satirin ilk karakteri -> hemen ustune //#)
        close_at = len(out)
        out.append(close_line)
        out.append(lines[E])
    else:
        # '}' onunde kod var -> satiri bol
        out.append(before.rstrip() + eol)
        close_at = len(out)
        out.append(close_line)
        out.append(indent + text[span.close_col:] + own_eol)

    return out, open_at, close_at


def make_preview(sig: list[str], new: list[str], body_at: int, close_at: int) -> str:
    """Imza + acilis blogu + govdenin ilk/son satiri + kapanis."""
    if close_at - body_at <= 3:
        shown = new
    else:
        shown = new[:body_at + 1] + ["    ...\n"] + new[close_at - 1:]
    return "".join(sig + shown).replace("\r\n", "\n")


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
        unit = detect_indent_unit(lines)
        tagged = find_tagged_ranges(lines)

        # === once TUM gorevleri coz (henuz degistirmeden) ===
        planned: list[tuple[Task, int, BodySpan]] = []
        for t in file_tasks:
            start, note = locate_start(lines, t)
            if start is None:
                t.status, t.detail = "HATA", note
                continue

            span, err = find_function_body(lines, start)
            if span is None:
                t.status, t.detail = "HATA", err
                continue

            if SKIP_IF_ALREADY_TAGGED and is_already_tagged(tagged, start, span):
                t.status, t.detail = "ATLANDI", "Zaten etiketli"
                continue

            if touches_macro_continuation(lines, span):
                t.status, t.detail = "HATA", "Makro devam satiri (\\) - elle yapilmali"
                continue

            t.start_line, t.end_line = start + 1, span.close_line + 1
            t.detail = note
            planned.append((t, start, span))

        # ayni govdeye iki CSV satiri denk geldiyse ilkini tut;
        # govdeleri ic ice / ayni satirda olanlari ele (guvenli degil)
        planned.sort(key=lambda p: (p[2].open_line, p[2].open_col, p[0].row_no))
        kept: list[tuple[Task, int, BodySpan]] = []
        for t, start, span in planned:
            if kept:
                prev_t, _, prev = kept[-1]
                if (span.open_line, span.open_col) == (prev.open_line, prev.open_col):
                    t.status = "ATLANDI"
                    t.detail = "Ayni fonksiyon icin baska bir CSV satiri zaten islendi"
                    continue
                if span.open_line <= prev.close_line:
                    t.status = "HATA"
                    t.detail = (f"'{prev_t.func}' govdesiyle cakisiyor "
                                f"(ic ice / ayni satir) - elle yapilmali")
                    continue
            kept.append((t, start, span))
        planned = kept

        # === asagidan yukariya uygula (satir numaralari kaymasin) ===
        for t, start, span in sorted(planned, key=lambda p: p[2].open_line, reverse=True):
            indent = leading_ws(lines[start])
            body_indent = guess_body_indent(lines, span, indent, unit)
            open_block = build_open_block(t.hlr_ids, indent, eol)
            close_line = f"{indent}{CLOSE_MARKER}{eol}"

            new, open_at, close_at = build_tagged_body(
                lines, span, indent, body_indent, open_block, close_line, eol
            )
            sig = lines[start:span.open_line]
            lines[span.open_line:span.close_line + 1] = new

            t.status = "OK"
            t.preview = make_preview(sig, new, open_at + len(open_block), close_at)

        if planned and not DRY_RUN:
            write_lines(file, lines, enc, had_bom)

        if planned and DRY_RUN and SHOW_PREVIEW:
            print(f"--- {file} ---")
            for t, *_ in planned:
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
                print(f"  CSV satir {t.row_no}: {t.file.name} :: {t.func}"
                      f"  [aranan isim: '{t.base}']  (L{t.line}) -> {t.detail}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["csv_row", "file", "function", "aranan_isim", "csv_line",
                    "found_start", "found_end", "hlr_count", "status", "detail"])
        for t in tasks:
            w.writerow([t.row_no, t.file, t.func, t.base, t.line, t.start_line,
                        t.end_line, len(t.hlr_ids), t.status, t.detail])
    print(f"\nRapor: {REPORT_CSV}")

    if DRY_RUN:
        print("\nDRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
