#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV'de listelenen HLR ID'lerini, ilgili .cpp / .h dosyalarindaki fonksiyonlarin
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

Header dosyalari (.h / .hpp):
  * Header'da GOVDESI olan fonksiyonlar (sinif icindeki inline metotlar,
    template tanimlari...) .cpp'dekiyle ayni sekilde etiketlenir.
  * Header'da sadece bildirimi (prototipi) olan fonksiyon etiketlenemez;
    raporda "tanim X.cpp satir N'de" diye ipucu verilir.

Hangi dosya?  (oncelik sirasiyla)
  1) Satirdaki 'Class/File Name' hucresi  (class.h / class.cpp)
  2) 'Function Name' sutununda DOSYA SATIRI:  Function Name = 'class.h' olan
     bir satir, ayni Directory Name'deki ALTINDAKI fonksiyonlarin o dosyada
     oldugunu belirtir (bir sonraki dosya satirina kadar):

         Directory Name   Function Name   HLR Ids
         database/Motor   Motor.h
         database/Motor   getSpeed        HLR_1
         database/Motor   Motor.cpp
         database/Motor   start           HLR_2, HLR_3

  3) Hicbiri yoksa: Directory Name'in son parcasi + DEFAULT_FILE_EXT
     (database/Motor -> Motor.cpp)
  Dosya 'SOURCE_ROOT / Directory Name / dosya' yolunda yoksa
  (FIND_FILES_BY_NAME) proje icinde AYNI ISIMLI dosya aranir; birden fazla
  varsa yolu Directory Name'e en cok benzeyen secilir.

Satir numaralari  ('Line Number' sutunu ARTIK ZORUNLU DEGIL):
  * Bos / yoksa fonksiyon TUM DOSYADA aranir.  Ayni isimde birden fazla
    tanim varsa sirayla su ipuclari denenir:
      - Function Name'deki parametreler      start(int speed)
      - sinif adi  (Function Name'deki 'Motor::' ya da Directory Name'in son
        parcasi) ile kodda 'Motor::start' / 'class Motor { ... }'
    Yine ayirt edilemezse fonksiyon ETIKETLENMEZ, rapora aday satirlar yazilir.
  * Doluysa once o satirin cevresine (+/- SEARCH_RADIUS) bakilir; orada yoksa
    tum dosyada aranir.
  * Daha once etiketlenmis dosyalarda CSV'deki satir numarasi, etiketler
    eklenmeden ONCEKI koda gore olabilir; bu da hesaba katilir.
  * Bulunan satirlar LINES_CSV'ye yazilir: girdi CSV'nin aynisi, 'Line Number'
    doldurulmus + 'Linker Durum' / 'Linker Not' sutunlari.  Belirsiz kalanlarin
    satirini elle yazip bu dosyayi CSV_PATH olarak tekrar kullanabilirsin.

Zaten etiketli fonksiyonlar  (MERGE_INTO_EXISTING):
  * True  -> CSV'deki ID'lerden blokta OLMAYANLAR mevcut blogun sonuna
             eklenir; ID satirlari ayni yerde, guncel formatla yeniden yazilir.
             Mevcut ID'ler silinmez, ayni ID iki kez yazilmaz, ikinci bir
             //#( blogu acilmaz.
  * False -> fonksiyon atlanir ("Zaten etiketli").
  Hem yeni format (govde icinde) hem de eski format (fonksiyonun ustunde
  //#( , } sonrasinda //#) ) taninir; eski formatta blok oldugu yerde kalir.
  Ayni fonksiyon CSV'de birden fazla satirda geciyorsa ID'ler birlestirilir.

CSV sutunlari (basliklar ilk satirda, sirasi onemli degil, fazlasi yok sayilir):
    Zorunlu :  Directory Name | Function Name | HLR Ids
    Istege bagli:  Class/File Name | Line Number

Notlar:
  * 'Function Name' sutunundaki isimlerde namespace onekleri silinmis olabilir
    (ornek: kodda  ns::Motor::start  , CSV'de  Motor::start  ya da  start ).
  * 'HLR Ids' hucresindeki ID'ler virgul / noktali virgul / satir sonu / boru
    ile ayrilmis olabilir; hepsi taninir.
  * Satir basina kac ID yazilacagi IDS_PER_LINE ile ayarlanir (varsayilan 2).

Kullanim:
    1) Asagidaki AYARLAR bolumunu doldur.
    2) DRY_RUN = True ile calistir; ekrandaki onizlemeyi, REPORT_CSV'yi ve
       LINES_CSV'yi (bulunan satir numaralari) incele.
    3) DRY_RUN = False yapip tekrar calistir.

Onemli: calistirmadan once projeyi commit et (git).  Script dosyalari yerinde
degistirir.  Tekrar calistirmak guvenlidir: etiketli fonksiyonlara sadece
eksik ID'ler eklenir, eksik yoksa dosyaya dokunulmaz.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

CSV_PATH = "hlr.csv"             # CSV dosyasinin yolu
CSV_DELIMITER = None             # None = otomatik tespit;  ya da ";" / "," / "\t"

# Kaynak kodun kok dizini.  CSV'deki 'Directory Name' buna gore cozulur;
# dosya o yolda yoksa bu dizinin altinda ayni isimli dosya aranir.
# "" = script'in calistirildigi dizin.
SOURCE_ROOT = ""

DRY_RUN = True                   # True iken hicbir kaynak dosya degismez
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = "hlr_link_report.csv"   # ayrintili islem raporu
LINES_CSV = "hlr_with_lines.csv"     # girdi CSV + bulunan satir numaralari
SHOW_PREVIEW = True              # Dry-run'da eklenecek bloklari ekrana bas

# Islenecek uzantilar
SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c")
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx")
ALLOWED_EXTENSIONS = set(SOURCE_EXTENSIONS) | set(HEADER_EXTENSIONS)

# Dosya 'SOURCE_ROOT / Directory Name / dosya' yolunda yoksa proje icinde
# ayni isimli dosya aransin mi (DOORS'taki yol diskteki yolla ayni degilse)
FIND_FILES_BY_NAME = True

# Satirda dosya adi yoksa (Class/File Name bos, ustte dosya satiri da yok):
# Directory Name'in son parcasi + bu uzanti   (database/Motor -> Motor.cpp)
DEFAULT_FILE_EXT = ".cpp"

# Ayni isimde birden fazla tanim varsa sinif adini ipucu olarak kullan
# (Function Name'deki 'Motor::' ya da Directory Name'in son parcasi)
USE_CLASS_HINT = True

# CSV'nin kendi kodlamasi icin denenecek sira
CSV_ENCODINGS = ["utf-8-sig", "utf-8", "cp1254", "latin-1"]

# Kaynak dosyalar icin denenecek kodlama sirasi
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

# CSV'deki satir numarasi doluysa, once +/- kac satir icinde aransin
SEARCH_RADIUS = 15

# Fonksiyon zaten etiketliyse:
#   True  -> CSV'deki YENI ID'leri mevcut bloga ekle (var olanlara dokunulmaz)
#   False -> fonksiyonu atla
# Iki durumda da ayni fonksiyona ikinci bir //#( blogu ACILMAZ.
MERGE_INTO_EXISTING = True

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
REQUIRED_COLUMNS = ("directory", "function", "hlr")

# =====================================================================


def norm_header(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# Function Name hucresi bir dosya adi mi (dosya satiri)
FILE_NAME_RE = re.compile(
    r"^[^\s()]+(" + "|".join(re.escape(e) for e in sorted(ALLOWED_EXTENSIONS)) + r")$",
    re.IGNORECASE)


@dataclass
class Task:
    row_no: int
    file: Path
    func: str
    line: int                 # CSV'deki 1-tabanli satir (0 = verilmemis)
    hlr_ids: list[str]
    status: str = "PENDING"
    detail: str = ""
    base: str = ""            # imzadan cikarilan fonksiyon adi
    params: list[str] | None = None   # Function Name'deki parametre tipleri
    class_hint: str = ""      # ayirt etmek icin sinif adi
    start_line: int = 0       # dogrulanmis 1-tabanli baslangic
    end_line: int = 0         # fonksiyonun } satiri (1-tabanli, degisiklik oncesi)
    cands: list[int] = field(default_factory=list)   # aday satirlar (1-tabanli)
    not_found: bool = False   # fonksiyon dosyada bulunamadi / belirsiz
    preview: str = ""
    action: str = ""          # "YENI" (yeni blok) / "EKLEME" (mevcut bloga ID)


@dataclass
class CsvTable:
    """LINES_CSV'yi yazmak icin girdi CSV'nin ham hali."""
    header: list[str]
    rows: list[tuple[int, list[str]]]
    delim: str
    idx: dict[str, int]


@dataclass
class BodySpan:
    """Fonksiyon govdesinin sinirlari (hepsi 0-tabanli)."""
    open_line: int            # govdeyi acan '{' satiri
    open_col: int             # ... ve sutunu
    close_line: int           # govdeyi kapatan '}' satiri
    close_col: int            # ... ve sutunu


@dataclass
class ExistingTag:
    """Fonksiyona ait mevcut //#( blogu (0-tabanli)."""
    open_line: int            # '//#(' satiri
    id_line_count: int        # '//#(' satiri dahil, ID iceren satir sayisi
    ids: list[str]


def join_detail(*parts: str) -> str:
    return " | ".join(p for p in parts if p)


# --------------------------------------------------------------------
# 1) Dosya bulma
# --------------------------------------------------------------------

_FILE_INDEX: dict[str, list[Path]] | None = None


def file_index() -> dict[str, list[Path]]:
    """SOURCE_ROOT altindaki tum kaynak/header dosyalari:  ad (kucuk harf) -> yollar."""
    global _FILE_INDEX
    if _FILE_INDEX is None:
        _FILE_INDEX = {}
        root = Path(SOURCE_ROOT) if SOURCE_ROOT else Path(".")
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if Path(fn).suffix.lower() in ALLOWED_EXTENSIONS:
                    _FILE_INDEX.setdefault(fn.lower(), []).append(Path(dirpath) / fn)
    return _FILE_INDEX


def pick_by_dir(cands: list[Path], raw_dir: str) -> list[Path]:
    """Yolu Directory Name parcalarini en cok iceren aday(lar)."""
    comps = [c.lower() for c in raw_dir.replace("\\", "/").split("/") if c]

    def score(p: Path) -> int:
        parts = [x.lower() for x in p.parent.parts]
        return sum(1 for c in comps if c in parts)

    best = max(score(p) for p in cands)
    return [p for p in cands if score(p) == best]


def resolve_file(raw_dir: str, raw_name: str) -> tuple[Path | None, str]:
    d = raw_dir.replace("\\", "/").strip().rstrip("/")
    n = raw_name.replace("\\", "/").strip()
    if not n:
        return None, "Dosya adi yok"
    joined = f"{d}/{n}" if (d and not d.endswith(n)) else (d or n)
    full = Path(SOURCE_ROOT) / joined if SOURCE_ROOT else Path(joined)
    if full.is_file():
        return full, ""
    # DOORS yolunun son parcasi genelde sinif adidir:  database/Motor + Motor.cpp
    # -> database/Motor.cpp
    if "/" in d:
        alt = f"{d.rsplit('/', 1)[0]}/{n}"
        alt_full = Path(SOURCE_ROOT) / alt if SOURCE_ROOT else Path(alt)
        if alt_full.is_file():
            return alt_full, ""
    if not FIND_FILES_BY_NAME:
        return full, ""

    name = Path(n).name
    cands = file_index().get(name.lower(), [])
    if not cands:
        return None, f"Dosya bulunamadi: {full} (proje icinde de '{name}' yok)"
    top = pick_by_dir(cands, d) if len(cands) > 1 else cands
    if len(top) == 1:
        return top[0], f"Dosya isimle bulundu: {top[0]}"
    return None, (f"'{name}' isminde {len(top)} dosya var, hangisi belirsiz: "
                  + ", ".join(str(p) for p in top[:5]))


def sibling_files(path: Path) -> list[Path]:
    """class.h <-> class.cpp  (once ayni dizinde, sonra proje icinde)."""
    exts = SOURCE_EXTENSIONS if path.suffix.lower() in HEADER_EXTENSIONS else HEADER_EXTENSIONS
    out = [path.with_suffix(e) for e in exts if path.with_suffix(e).is_file()]
    if not out and FIND_FILES_BY_NAME:
        for e in exts:
            out += file_index().get((path.stem + e).lower(), [])
    return out


# --------------------------------------------------------------------
# 2) CSV okuma
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


def read_csv_tasks(path: str) -> tuple[list[Task], CsvTable]:
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

    missing = [COLUMNS[k] for k in REQUIRED_COLUMNS if k not in idx]
    if missing:
        sys.exit(
            f"CSV'de bulunamayan zorunlu sutun(lar): {missing}\n"
            f"Gorulen basliklar: {header}\n"
            f"Ayrac yanlis tespit edilmis olabilir -> CSV_DELIMITER'i elle ayarla."
        )
    if "line" not in idx:
        print("Bilgi: 'Line Number' sutunu yok -> fonksiyonlar tum dosyada aranacak.")
    if "filename" not in idx:
        print("Bilgi: 'Class/File Name' sutunu yok -> dosya, Function Name'deki dosya "
              "satirlarindan (class.h / class.cpp) ya da Directory Name'den bulunacak.")

    hlr_is_last = idx["hlr"] == max(idx.values())

    marker: dict[str, str] = {}      # Directory Name -> son dosya satiri
    tasks: list[Task] = []
    table_rows: list[tuple[int, list[str]]] = []

    for r, row in enumerate(reader, start=2):
        table_rows.append((r, row))
        if not any(str(c).strip() for c in row):
            continue

        def cell(key: str) -> str:
            i = idx.get(key)
            if i is None:
                return ""
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
        dir_key = raw_dir.replace("\\", "/").strip().strip("/").lower()

        # --- dosya satiri:  Function Name = 'class.h' / 'class.cpp' ---
        if not raw_name and FILE_NAME_RE.match(func):
            marker[dir_key] = func
            t = Task(row_no=r, file=Path(func), func=func, line=0, hlr_ids=ids)
            t.status, t.action = "ATLANDI", "DOSYA"
            t.detail = "Dosya satiri - alttaki fonksiyonlar bu dosyada aranir"
            if ids:
                t.detail += " (bu satirdaki HLR ID'leri kullanilmadi)"
            tasks.append(t)
            continue

        note = ""
        if not raw_name:
            if dir_key in marker:
                raw_name = marker[dir_key]
            else:
                last = dir_key.split("/")[-1] if dir_key else ""
                if last:
                    last = raw_dir.replace("\\", "/").strip().strip("/").split("/")[-1]
                    raw_name = last + DEFAULT_FILE_EXT
                    note = f"Dosya adi yok, '{raw_name}' varsayildi"

        full, fnote = resolve_file(raw_dir, raw_name)
        t = Task(row_no=r, file=full if full is not None else Path(raw_name or "?"),
                 func=func, line=0, hlr_ids=ids)
        t.base = func_base(func)
        t.params = func_params(func)
        t.class_hint = class_hint(func, raw_dir)
        t.detail = join_detail(note, fnote)

        if full is None:
            t.status = "HATA"
            tasks.append(t)
            continue

        if full.suffix.lower() not in ALLOWED_EXTENSIONS:
            t.status = "ATLANDI"
            t.detail = join_detail(t.detail,
                                   f"Desteklenmeyen uzanti ({full.suffix or 'uzantisiz'})")
            tasks.append(t)
            continue

        if raw_line:
            try:
                t.line = int(float(raw_line))
            except ValueError:
                t.detail = join_detail(t.detail, f"Satir numarasi okunamadi ({raw_line!r}), "
                                                 f"tum dosyada arandi")

        if not ids:
            t.status = "ATLANDI"
            t.detail = join_detail(t.detail, "HLR ID yok")
        tasks.append(t)

    return tasks, CsvTable(header, table_rows, delim, idx)


# --------------------------------------------------------------------
# 3) Kaynak dosya okuma / yazma
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
# 4) C++ govde tarayicisi  (yorum / string / char literal farkindali)
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
# 5) Function Name hucresini cozumle
# --------------------------------------------------------------------

OPERATOR_RE = re.compile(r"\boperator\s*(\(\s*\)|\[\s*\]|[^\s(]+)")


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
    m = OPERATOR_RE.search(n)
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


def func_qualifier(name: str) -> str:
    """'void ns::Motor::start(int)' -> 'Motor'   (yoksa '')"""
    n = OPERATOR_RE.sub("operator", name.strip())
    n = n.split("(", 1)[0].strip()
    if not n.split():
        return ""
    n = n.split()[-1].lstrip("*&")
    parts = [p for p in re.sub(r"<[^<>]*>", "", n).split("::") if p]
    return parts[-2] if len(parts) >= 2 else ""


def class_hint(func: str, raw_dir: str) -> str:
    if not USE_CLASS_HINT:
        return ""
    q = func_qualifier(func)
    if q:
        return q
    parts = [p for p in raw_dir.replace("\\", "/").split("/") if p.strip()]
    return parts[-1].strip() if parts else ""


TYPE_WORDS = {"int", "char", "short", "long", "unsigned", "signed", "float", "double",
              "bool", "void", "wchar_t", "size_t", "auto"}


def split_top_level(s: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def norm_params(text: str) -> list[str]:
    """
    Parametre listesini sadece TIPLERE indirger (isimler, const, namespace,
    varsayilan degerler atilir) -> karsilastirma icin.
        'int a, const ns::Foo& f, char* p = 0'  ->  ['int', 'foo&', 'char*']
    """
    t = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    t = re.sub(r"//[^\n]*", " ", t).strip()
    if t in ("", "void"):
        return []
    out = []
    for p in split_top_level(t):
        p = p.split("=", 1)[0]
        p = re.sub(r"\b\w+\s*::\s*", "", p)
        p = re.sub(r"\b(const|volatile|struct|class|enum|typename)\b", " ", p)
        p = re.sub(r"\[[^\]]*\]", "*", p)
        toks = re.findall(r"[A-Za-z_]\w*|[*&]+|<|>|,|\.\.\.", p)
        if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
                and toks[-1] not in TYPE_WORDS and toks[-2] not in ("<", ",")):
            toks = toks[:-1]                     # parametre ismi
        out.append("".join(toks).lower())
    return out


def matching_paren(s: str, i: int) -> int:
    """s[i] == '(' ise eslesen ')' indeksi (yoksa -1)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def func_params(name: str) -> list[str] | None:
    """'start(int speed)' -> ['int'];  parantez yoksa None (bilgi yok)."""
    s = OPERATOR_RE.sub("operator_", name)
    i = s.find("(")
    if i < 0:
        return None
    j = matching_paren(s, i)
    return norm_params(s[i + 1:j] if j > 0 else s[i + 1:])


# --------------------------------------------------------------------
# 6) Fonksiyon tanimini bul
# --------------------------------------------------------------------

def code_part(line: str) -> str:
    """Satirdaki // yorumunu atar (eslesme yorumdan gelmesin diye)."""
    return line.split("//", 1)[0]


# Tamamen yorum olan satirlar ( // ... ,  /* ... ,  * ... ) aday sayilmaz;
# aksi halde Doxygen blogunda gecen 'func_name()' tanim sanilabilir.
COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*)")
# Onislemci satirlari (#define f(x) { ... }) aday sayilmaz
PREPROC_LINE = re.compile(r"^\s*#")

CONTROL_KW = {"if", "while", "for", "switch", "return", "else", "catch",
              "do", "case", "throw", "assert"}

# 'Bar::Bar() : foo(1), x(2) {'  -> foo bir tanim degil, init listesi
INIT_LIST_BEFORE = re.compile(r"\)\s*(const\s*)?(noexcept\s*)?:(?!:)")


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

    # kurucu init listesi:  ') : funcname('
    if INIT_LIST_BEFORE.search(before):
        return False

    # satir bir kontrol anahtar kelimesi ile basliyorsa tanim degildir
    words = re.findall(r"[A-Za-z_]\w*", before)
    if words and words[0] in CONTROL_KW:
        return False

    return True


def name_regex(base: str) -> str:
    if base.startswith("operator"):
        return r"operator\s*" + re.escape(base[len("operator"):])
    return re.escape(base)


def build_patterns(base: str):
    esc = name_regex(base)
    lead = r"(?<![\w~])" if (base[:1].isalnum() or base[:1] == "_") else ""
    trail = r"\b" if (base[-1:].isalnum() or base[-1:] == "_") else ""
    # GUCLU: isim  ->  (istege bagli <...>)  ->  (
    strong = re.compile(rf"{lead}{esc}\s*(<[^;{{}}]*>)?\s*\(")
    # GEVSEK: isim tek basina (imza sonraki satira sarkmis olabilir)
    loose = re.compile(rf"{lead}{esc}{trail}")
    return strong, loose


def skip_line(line: str) -> bool:
    return bool(COMMENT_LINE.match(line) or PREPROC_LINE.match(line))


def locate_start(lines: list[str], task: Task,
                 alt_center: int | None = None) -> tuple[int | None, str]:
    """
    CSV satir numarasinin cevresinde (+/- SEARCH_RADIUS) fonksiyon tanimini arar.

    alt_center: etiket satirlari dusulerek hesaplanan 0-tabanli satir.
    CSV numaralari etiketlerden ONCEKI koda goreyse fonksiyon bunun
    cevresindedir.  Iki merkezin cevresi birlikte, yakindan uzaga taranir.
    """
    base = task.base
    if not base:
        return None, "Fonksiyon ismi bos"

    center = task.line - 1
    centers: list[int] = []
    for c0 in (center, alt_center):
        if c0 is not None and 0 <= c0 < len(lines) and c0 not in centers:
            centers.append(c0)
    if not centers:
        return None, f"Satir {task.line} dosya disinda (dosya {len(lines)} satir)"

    strong, loose = build_patterns(base)

    # aday sirasi: once merkez(ler), sonra yakindan uzaga
    rank: dict[int, tuple[int, int, int]] = {}
    for ci, c0 in enumerate(centers):
        for d in range(SEARCH_RADIUS + 1):
            for side, c in ((0, c0 - d), (1, c0 + d)):
                if 0 <= c < len(lines):
                    key = (d, ci, side)
                    if c not in rank or key < rank[c]:
                        rank[c] = key
    cands = sorted(rank, key=rank.__getitem__)
    cands = [c for c in cands if not skip_line(lines[c])]

    def note(c: int) -> str:
        if c == center:
            return ""
        if c == alt_center:
            return (f"Satir {task.line} -> {c + 1} "
                    f"(onceki etiket satirlari dusulerek bulundu)")
        return f"Satir {task.line} -> {c + 1} olarak duzeltildi"

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

    return None, f"Fonksiyon '{base}' satir {task.line} civarinda bulunamadi"


def next_code_line(lines: list[str], i: int) -> str:
    for k in range(i + 1, min(i + 4, len(lines))):
        s = code_part(lines[k]).strip()
        if s:
            return s
    return ""


def signature_params(lines: list[str], start: int, base: str) -> list[str] | None:
    """Koddaki tanimin parametre tipleri (imza en fazla 15 satira yayilabilir)."""
    text = "".join(code_part(ln) + " " for ln in lines[start:start + 15])
    strong, _ = build_patterns(base)
    m = strong.search(text)
    if not m:
        return None
    i = m.end() - 1
    j = matching_paren(text, i)
    return norm_params(text[i + 1:j]) if j > 0 else None


def qualifier_at(line: str, base: str) -> str:
    """'void Motor::start(int)' -> 'Motor'"""
    m = re.search(rf"(\w+)\s*(?:<[^<>;{{}}]*>)?\s*::\s*{name_regex(base)}\s*(?:<[^;{{}}]*>)?\s*\(",
                  code_part(line))
    return m.group(1) if m else ""


# 'class Motor {'  /  'class EXPORT Motor : public Base\n{'  (satirlar arasi)
CLASS_OPEN = re.compile(
    r"(?P<cls>\b(?:class|struct)\s+(?:\w+\s+)*?(?P<name>\w+)\s*(?:final\s*)?(?::[^;{}]*)?\{)"
    r"|(?P<open>\{)|(?P<close>\})")


def clean_code(lines: list[str]) -> str:
    """Yorumlar ve string/char literal'leri atilmis kod (satir yapisi korunur)."""
    text = "".join(lines)
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r'"(\\.|[^"\\\n])*"' + r"|'(\\.|[^'\\\n])*'", '""', text)


def enclosing_class(lines: list[str], start: int) -> str:
    """Inline metot icin icinde bulundugu 'class X { ... }' adi (kaba tarama)."""
    stack: list[str] = []
    for m in CLASS_OPEN.finditer(clean_code(lines[:start])):
        if m.group("cls"):
            stack.append(m.group("name"))
        elif m.group("open"):
            stack.append("")
        elif stack:
            stack.pop()
    for name in reversed(stack):
        if name:
            return name
    return ""


def owner_class(lines: list[str], start: int, base: str) -> str:
    return qualifier_at(lines[start], base) or enclosing_class(lines, start)


def class_in_file(lines: list[str], cls: str) -> bool:
    """Dosyada 'class Motor {...}' ya da 'Motor::' geciyor mu."""
    esc = re.escape(cls)
    pat = re.compile(rf"\b(?:class|struct)\s+(?:\w+\s+)*?{esc}\b\s*(?:final\s*)?(?::[^;{{}}]*)?\{{"
                     rf"|\b{esc}\s*(?:<[^<>;{{}}]*>)?\s*::", re.IGNORECASE)
    return bool(pat.search(clean_code(lines)))


def locate_anywhere(lines: list[str], task: Task) -> tuple[int | None, str, list[int]]:
    """
    Fonksiyonu TUM DOSYADA arar.  Donus: (baslangic | None, not, adaylar).
    Birden fazla tanim varsa parametre / sinif / satir ipuclariyla daraltir.
    """
    base = task.base
    if not base:
        return None, "Fonksiyon ismi bos", []
    strong, loose = build_patterns(base)

    cands: list[int] = []
    protos: list[int] = []
    for c, ln in enumerate(lines):
        if skip_line(ln):
            continue
        cp = code_part(ln)
        mm = strong.search(cp)
        if mm and is_definition_site(cp, mm.start()):
            if find_function_body(lines, c)[0] is not None:
                cands.append(c)
            else:
                protos.append(c)
            continue
        # imza bolunmus:  'void Motor::start'  /  '(int speed) {'
        mm = loose.search(cp)
        if (mm and not cp[mm.end():].strip() and is_definition_site(cp, mm.start())
                and next_code_line(lines, c).startswith("(")
                and find_function_body(lines, c)[0] is not None):
            cands.append(c)

    all_cands = list(cands)
    notes: list[str] = []

    # Sinif ipucu: dosyada o sinif varsa, BASKA bir sinifa ait oldugu bilinen
    # tanimlar elenir (ornek: Motor.h'de Motor::start sadece prototip,
    # Helper::start() inline -> Helper'inki secilmemeli)
    if cands and task.class_hint and class_in_file(lines, task.class_hint):
        hint = task.class_hint.lower()
        owners = {c: owner_class(lines, c, base) for c in cands}
        kept = [c for c in cands if owners[c].lower() in ("", hint)]
        exact = [c for c in kept if owners[c].lower() == hint]
        if exact:
            kept = exact
        if len(kept) < len(cands):
            if kept:
                notes.append(f"sinif '{task.class_hint}' ile secildi")
            else:
                others = sorted({owners[c] for c in cands})
                msg = (f"'{base}' bu dosyada '{task.class_hint}' sinifinda tanimli degil "
                       f"(sadece: {', '.join(others)})")
                if protos:
                    msg += f" - satir {protos[0] + 1}'de bildirimi (prototipi) var"
                return None, msg, []
        cands = kept

    if not cands:
        if protos:
            return None, (f"'{base}' bu dosyada sadece bildirim (prototip) olarak var "
                          f"(satir {protos[0] + 1}), govdesi yok"), []
        return None, f"Fonksiyon '{base}' dosyada bulunamadi", []

    if len(cands) > 1 and task.params is not None:
        f = [c for c in cands if signature_params(lines, c, base) == task.params]
        if f:
            cands = f
            notes.append("parametrelerle secildi")

    if len(cands) > 1 and task.line > 0:
        cands = [min(cands, key=lambda c: abs(c - (task.line - 1)))]
        notes.append("CSV satirina en yakin tanim secildi")

    if len(cands) > 1:
        where = ", ".join(str(c + 1) for c in cands)
        return None, (f"BELIRSIZ: '{base}' {len(cands)} yerde tanimli (satir {where}) - "
                      f"Line Number yaz ya da Function Name'e parametreleri ekle"), \
            [c + 1 for c in all_cands]

    c = cands[0]
    if task.params is not None and len(all_cands) == 1:
        found = signature_params(lines, c, base)
        if found is not None and found != task.params:
            notes.append(f"UYARI: parametreler tutmuyor (kod: {', '.join(found) or '-'})")
    if len(all_cands) > 1:
        notes.insert(0, f"{len(all_cands)} tanim vardi")
    return c, join_detail(*notes), [x + 1 for x in all_cands]


def locate_function(lines: list[str], task: Task,
                    alt_center: int | None) -> tuple[int | None, str, list[int]]:
    """Satir numarasi varsa once cevresine, yoksa / bulunamazsa tum dosyaya bakar."""
    if task.line > 0:
        start, note = locate_start(lines, task, alt_center)
        if start is not None:
            return start, note, [start + 1]
        start, note2, cands = locate_anywhere(lines, task)
        if start is not None:
            return start, join_detail(f"Satir {task.line} civarinda yoktu, "
                                      f"tum dosyada {start + 1}. satirda bulundu", note2), cands
        return None, note2, cands
    return locate_anywhere(lines, task)


# --------------------------------------------------------------------
# 7) Mevcut etiket bloklari
# --------------------------------------------------------------------

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


# Bir devam satirinin yorum isaretinden sonraki kismi:  "HLR_3, HLR_4,"
ID_LINE = re.compile(r"^[^\s,;]+(\s*,\s*[^\s,;]+)*\s*,?\s*\]?\s*$")
ID_SPLIT = re.compile(r"[\s,;\[\]]+")


def tag_id_line_count(lines: list[str], lo: int, hi: int) -> int:
    """
    lines[lo] ('//#(' satiri) ile baslayan ID satirlarinin sayisi.
    Bir satir virgulle bitiyorsa liste alttaki '//' satirinda devam eder.
    Govdenin ilk satiri bir // yorumuysa ID sanilmamasi icin, devam satiri
    ID listesine benzemeli ve '//#(' satirindan daha derin girintili olmamali.
    """
    indent_len = len(leading_ws(lines[lo]))
    k = lo
    while k + 1 < hi:
        if not lines[k].rstrip().endswith(","):
            break
        nxt = lines[k + 1]
        s = nxt.strip()
        if not s.startswith("//") or s.startswith("//#"):
            break
        if len(leading_ws(nxt)) > indent_len:
            break
        if not ID_LINE.match(s[2:].strip()):
            break
        k += 1
    return k - lo + 1


def parse_tag_ids(id_lines: list[str]) -> list[str]:
    ids: list[str] = []
    for k, ln in enumerate(id_lines):
        s = ln.strip()
        s = s[len("//#("):] if k == 0 else s[2:]
        ids.extend(x for x in ID_SPLIT.split(s) if x)
    return ids


def merge_ids(existing: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """(birlesik liste, eklenenler) - sira korunur, tekrar yazilmaz."""
    seen = set(existing)
    merged = list(existing)
    added: list[str] = []
    for x in new:
        if x not in seen:
            seen.add(x)
            merged.append(x)
            added.append(x)
    return merged, added


def find_existing_tag(lines: list[str], ranges: list[tuple[int, int]],
                      start: int, span: BodySpan) -> ExistingTag | None:
    for lo, hi in ranges:
        if (span.open_line <= lo <= span.close_line    # yeni format: govdenin icinde
                or lo <= start <= hi):                  # eski format: fonksiyonu sariyor
            n = tag_id_line_count(lines, lo, hi)
            return ExistingTag(lo, n, parse_tag_ids(lines[lo:lo + n]))
    return None


def untagged_line_map(lines: list[str], ranges: list[tuple[int, int]]) -> list[int]:
    """
    Etiket satirlari (ID satirlari + //#) ) yokmus gibi sayildiginda
    'k. satir' -> simdiki 0-tabanli indeks.  map[k - 1] seklinde kullanilir.
    """
    skip: set[int] = set()
    for lo, hi in ranges:
        skip.update(range(lo, lo + tag_id_line_count(lines, lo, hi)))
        if lines[hi].strip().startswith(CLOSE_MARKER):
            skip.add(hi)
    return [i for i in range(len(lines)) if i not in skip]


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
# 8) Blok uretimi
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


def make_merge_preview(old: list[str], new: list[str]) -> str:
    """Mevcut bloktaki ID satirlarinin once / sonra hali."""
    return ("".join("  - " + ln for ln in old)
            + "".join("  + " + ln for ln in new)).replace("\r\n", "\n")


# --------------------------------------------------------------------
# 9) Raporlar
# --------------------------------------------------------------------

def add_sibling_hints(tasks: list[Task]) -> None:
    """Bulunamayan fonksiyon icin class.h <-> class.cpp'ye bakip ipucu ekler."""
    cache: dict[Path, list[str] | None] = {}
    for t in tasks:
        if not t.not_found or t.status != "HATA" or t.cands:
            continue
        for sib in sibling_files(t.file):
            if sib not in cache:
                try:
                    cache[sib] = read_lines(sib)[0]
                except Exception:
                    cache[sib] = None
            lines = cache[sib]
            if lines is None:
                continue
            probe = Task(row_no=t.row_no, file=sib, func=t.func, line=0, hlr_ids=[],
                         base=t.base, params=t.params, class_hint=t.class_hint)
            start, _, _ = locate_anywhere(lines, probe)
            if start is not None:
                t.detail = join_detail(t.detail, f"IPUCU: tanim {sib.name} satir {start + 1}'de "
                                                 f"-> dosyayi {sib.name} yap")
                break


def write_lines_csv(tasks: list[Task], table: CsvTable) -> None:
    """Girdi CSV'nin kopyasi: Line Number dolu + Linker Durum / Linker Not."""
    by_row = {t.row_no: t for t in tasks}
    width = len(table.header)
    header = list(table.header)
    line_i = table.idx.get("line")
    add_line_col = line_i is None
    if add_line_col:
        header.append("Line Number")
        line_i = len(header) - 1
    header += ["Linker Durum", "Linker Not"]
    hlr_i = table.idx["hlr"]

    with open(LINES_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=table.delim)
        w.writerow(header)
        for r, row in table.rows:
            if not any(str(c).strip() for c in row):
                continue
            row = [str(c) for c in row]
            if len(row) > width and hlr_i == width - 1:      # bolunmus HLR hucresi
                row = row[:hlr_i] + [",".join(row[hlr_i:])]
            row = (row + [""] * width)[:width]
            if add_line_col:
                row.append("")
            t = by_row.get(r)
            status, detail = "", ""
            if t is not None:
                if t.start_line:
                    row[line_i] = str(t.start_line)
                status = "DOSYA SATIRI" if t.action == "DOSYA" else t.status
                detail = t.detail
                if len(t.cands) > 1 and "BELIRSIZ" not in detail:
                    detail = join_detail(detail, "adaylar: " + ", ".join(map(str, t.cands)))
            w.writerow(row + [status, detail])


# --------------------------------------------------------------------
# 10) Ana akis
# --------------------------------------------------------------------

def main() -> int:
    tasks, table = read_csv_tasks(CSV_PATH)
    print(f"CSV'den {len(tasks)} satir okundu.\n")

    groups: dict[Path, list[Task]] = {}
    for t in tasks:
        if t.status in ("HATA", "ATLANDI"):
            continue
        groups.setdefault(t.file.resolve(), []).append(t)

    for file, file_tasks in groups.items():
        if not file.exists():
            for t in file_tasks:
                t.status = "HATA"
                t.detail = join_detail(t.detail, f"Dosya bulunamadi: {file}")
            continue

        try:
            lines, enc, had_bom = read_lines(file)
        except Exception as e:
            for t in file_tasks:
                t.status = "HATA"
                t.detail = join_detail(t.detail, f"Dosya okunamadi: {e}")
            continue

        eol = detect_eol(lines)
        unit = detect_indent_unit(lines)
        tagged = find_tagged_ranges(lines)
        # CSV satirlari etiketlerden ONCEKI koda goreyse kullanilacak esleme
        orig_map = untagged_line_map(lines, tagged) if tagged else []

        # === once TUM gorevleri coz (henuz degistirmeden) ===
        planned: list[tuple[Task, int, BodySpan, ExistingTag | None]] = []
        for t in file_tasks:
            alt = orig_map[t.line - 1] if 1 <= t.line <= len(orig_map) else None
            start, note, cands = locate_function(lines, t, alt)
            t.cands = cands
            if start is None:
                t.status, t.not_found = "HATA", True
                t.detail = join_detail(t.detail, note)
                continue

            span, err = find_function_body(lines, start)
            if span is None:
                t.status = "HATA"
                t.detail = join_detail(t.detail, err)
                continue

            t.start_line, t.end_line = start + 1, span.close_line + 1
            t.detail = join_detail(t.detail, note)

            existing = find_existing_tag(lines, tagged, start, span)
            if existing is not None and not MERGE_INTO_EXISTING:
                t.status = "ATLANDI"
                t.detail = join_detail(t.detail, "Zaten etiketli")
                continue

            if existing is None and touches_macro_continuation(lines, span):
                t.status = "HATA"
                t.detail = join_detail(t.detail, "Makro devam satiri (\\) - elle yapilmali")
                continue

            planned.append((t, start, span, existing))

        # ayni govdeye birden fazla CSV satiri denk geldiyse ID'leri ilkinde
        # birlestir; govdeleri ic ice / ayni satirda olanlari ele (guvenli degil)
        planned.sort(key=lambda p: (p[2].open_line, p[2].open_col, p[0].row_no))
        kept: list[tuple[Task, int, BodySpan, ExistingTag | None]] = []
        for item in planned:
            t, _, span, _ = item
            if kept:
                prev_t, _, prev, _ = kept[-1]
                if (span.open_line, span.open_col) == (prev.open_line, prev.open_col):
                    prev_t.hlr_ids, _ = merge_ids(prev_t.hlr_ids, t.hlr_ids)
                    t.status = "ATLANDI"
                    t.detail = join_detail(t.detail,
                                           f"Ayni fonksiyon CSV satir {prev_t.row_no}'de de var "
                                           f"- ID'ler oraya birlestirildi")
                    continue
                if span.open_line <= prev.close_line:
                    t.status = "HATA"
                    t.detail = join_detail(t.detail,
                                           f"'{prev_t.func}' govdesiyle cakisiyor "
                                           f"(ic ice / ayni satir) - elle yapilmali")
                    continue
            kept.append(item)
        planned = kept

        # === asagidan yukariya uygula (satir numaralari kaymasin) ===
        changed = False
        for t, start, span, existing in sorted(planned, key=lambda p: p[2].open_line,
                                               reverse=True):
            if existing is not None:
                # --- mevcut bloga yeni ID ekle ---
                merged, added = merge_ids(existing.ids, t.hlr_ids)
                if not added:
                    t.status = "ATLANDI"
                    t.detail = join_detail(t.detail, "Zaten etiketli, tum ID'ler mevcut")
                    continue
                lo, n = existing.open_line, existing.id_line_count
                new_block = build_open_block(merged, leading_ws(lines[lo]), eol)
                old_block = lines[lo:lo + n]
                lines[lo:lo + n] = new_block

                t.status, t.action = "OK", "EKLEME"
                t.detail = join_detail(t.detail,
                                       f"{len(added)} ID eklendi: {', '.join(added)}")
                t.preview = make_merge_preview(old_block, new_block)
                changed = True
                continue

            # --- yeni blok ---
            indent = leading_ws(lines[start])
            body_indent = guess_body_indent(lines, span, indent, unit)
            open_block = build_open_block(t.hlr_ids, indent, eol)
            close_line = f"{indent}{CLOSE_MARKER}{eol}"

            new, open_at, close_at = build_tagged_body(
                lines, span, indent, body_indent, open_block, close_line, eol
            )
            sig = lines[start:span.open_line]
            lines[span.open_line:span.close_line + 1] = new

            t.status, t.action = "OK", "YENI"
            t.preview = make_preview(sig, new, open_at + len(open_block), close_at)
            changed = True

        if changed and not DRY_RUN:
            write_lines(file, lines, enc, had_bom)

        if changed and DRY_RUN and SHOW_PREVIEW:
            print(f"--- {file} ---")
            for t, *_ in planned:
                if t.status != "OK":
                    continue
                what = "yeni blok" if t.action == "YENI" else "mevcut bloga ekleme"
                print(f"[satir {t.start_line}-{t.end_line}]  {t.func}   ({what})")
                print(t.preview.rstrip())
                print()

    add_sibling_hints(tasks)

    # === rapor ===
    real = [t for t in tasks if t.action != "DOSYA"]
    ok_new = sum(1 for t in real if t.status == "OK" and t.action == "YENI")
    ok_add = sum(1 for t in real if t.status == "OK" and t.action == "EKLEME")
    skip = sum(1 for t in real if t.status == "ATLANDI")
    err = sum(1 for t in real if t.status == "HATA")
    pend = sum(1 for t in real if t.status == "PENDING")
    found = sum(1 for t in real if t.start_line)
    ambiguous = sum(1 for t in real if "BELIRSIZ" in t.detail)

    print("=" * 72)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  "
          f"YENI BLOK: {ok_new}  ID EKLENEN: {ok_add}  ATLANDI: {skip}  "
          f"HATA: {err}  BEKLEYEN: {pend}")
    print(f"Satiri bulunan fonksiyon: {found} / {len(real)}   (belirsiz: {ambiguous})")
    print("=" * 72)

    if err or pend:
        print("\nEl ile bakilmasi gerekenler:")
        for t in real:
            if t.status in ("HATA", "PENDING"):
                print(f"  CSV satir {t.row_no}: {t.file.name} :: {t.func}"
                      f"  [aranan isim: '{t.base}']  (L{t.line or '-'}) -> {t.detail}")

    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["csv_row", "file", "function", "aranan_isim", "csv_line",
                    "found_start", "found_end", "adaylar", "hlr_count", "status", "islem",
                    "detail"])
        for t in tasks:
            w.writerow([t.row_no, t.file, t.func, t.base, t.line or "", t.start_line or "",
                        t.end_line or "", ", ".join(map(str, t.cands)) if len(t.cands) > 1 else "",
                        len(t.hlr_ids), t.status, t.action, t.detail])
    write_lines_csv(tasks, table)
    print(f"\nRapor: {REPORT_CSV}")
    print(f"Satir numarali CSV: {LINES_CSV}   (satirlar degisiklik ONCESI koda gore)")

    if DRY_RUN:
        print("\nDRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
