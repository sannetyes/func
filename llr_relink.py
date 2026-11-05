#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLR RE-LINK  (hlr linker script'inin uzerine kurulu)

  1) SIL  : SOURCE_ROOTS'taki (or. 3 klasor) TUM .cpp / .h dosyalarindan mevcut
            link bloklarini ( //#( ... ID satirlari ... ve //#) ) siler.
            CSV'de olsun olmasin, her fonksiyondaki link kaldirilir.
  2) YAZ  : DOORS'tan alinan CSV'deki (llr_export.dxl ciktisi) isterleri, asagida
            anlatilan formatta fonksiyonlara yeniden yazar.

  CSV sutunlari (llr_export.dxl):   Sinif Konumu ; Fonksiyon ; Isterler
      Sinif Konumu = Lib/Modul/sinif  -> dosya: <sinif>.cpp / <sinif>.h
                     (SOURCE_ROOTS altinda isimle aranir; ayni isimde birden fazla
                     dosya varsa yolu 'Sinif Konumu'na en cok benzeyen secilir)
      Fonksiyon    = fonksiyon adi (imza da olabilir)
      Isterler     = ID'ler ( , ; | satir sonu ile ayrilmis)
  Fonksiyon <sinif>.cpp'de yoksa <sinif>.h (ve diger uzantilar) denenir; tanim
  hangi dosyadaysa link oraya yazilir.

  DRY_RUN = True iken diske HICBIR SEY yazilmaz: silme + yazma bellekte yapilir,
  sonuclar ekrana ve rapor dosyalarina yazilir.

--- Asagisi orijinal linker aciklamasidir (format / fonksiyon bulma kurallari) ---

CSV'de listelenen HLR ID'lerini, ilgili .cpp / .h dosyalarindaki fonksiyonlarin
GOVDESININ ICINE yorum blogu olarak ekler.  Harici bagimlilik YOKTUR (sadece stdlib).

Uretilen format (varsayilan: satir basina 2 ID, son ID'den sonra virgul yok, ']' var):

    // Fonksiyonun ustundeki yorumlara ve imzasina dokunulmaz
    int func_name(param1){
    //#([HLR_MODULE_1234, HLR_MODULE2_1234,
    //	HLR_MODULE3_1234, HLR_MODULE4_1234,
    //	HLR_MODULE5_1234]
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
                                            //#([HLR_1]
                                                return 1;
                                            //#)
                                            }

Header dosyalari (.h / .hpp):
  * Header'da GOVDESI olan fonksiyonlar (sinif icindeki inline metotlar,
    template tanimlari...) .cpp'dekiyle ayni sekilde etiketlenir.
  * Header'da sadece bildirimi (prototipi) olan fonksiyon etiketlenemez;
    raporda "tanim X.cpp satir N'de" diye ipucu verilir.

Hangi dosya?
  * 'Class/File Name' hucresi:  class.h  ya da  class.cpp
  * Dosya 'SOURCE_ROOT / Directory Name / dosya' yolunda yoksa once
    'Directory Name'in ust dizini / dosya' denenir (database/Motor + Motor.cpp
    -> database/Motor.cpp), o da yoksa (FIND_FILES_BY_NAME) proje icinde AYNI
    ISIMLI dosya aranir; birden fazla varsa yolu Directory Name'e en cok
    benzeyen secilir, esitlik varsa satir HATA olur.
  * (Yedek) 'Class/File Name' bossa: Function Name'i 'class.h' olan bir ust
    satir (dosya satiri) ya da Directory Name'in son parcasi + DEFAULT_FILE_EXT.

Fonksiyonu bulma  ('Line Number' sutunu ZORUNLU DEGIL):
  * Fonksiyon TUM DOSYADA aranir (cagrilar, yorumlar, string'ler, #define'lar,
    kurucu init listeleri, sadece bildirimi olan prototipler elenir).
    Ayni isimde birden fazla tanim varsa sirayla:
      1) sinif adi:  Function Name'deki 'Motor::' ya da Directory Name'in son
         parcasi; kodda 'Motor::start(' ya da 'class Motor { ... }' icindeki
         inline tanim.  Dosyada o sinif varsa BASKA sinifin ayni isimli
         metodu asla secilmez.
      2) Function Name'deki parametreler:   log(const char* msg)
      3) Line Number (varsa): kalan adaylardan bu satira en yakini.  Satir,
         dosyanin hem simdiki hem de etiketsiz haline gore degerlendirilir.
    Yine ayirt edilemezse fonksiyon ETIKETLENMEZ, rapora aday satirlar yazilir.
  * Hic tanim bulunamazsa ve Line Number verilmisse, o satirin cevresinde
    (+/- SEARCH_RADIUS) daha gevsek kurallarla aranir.
  * Header'da sadece prototip varsa ipucu verilir: "tanim X.cpp satir N'de".
  * Bulunan satirlar LINES_CSV'ye yazilir: girdi CSV'nin aynisi, 'Line Number'
    doldurulmus + 'Linker Durum' / 'Linker Not' sutunlari.  Satirlar
    dosyalarin SU ANKI haline goredir (DRY_RUN'da degisiklik oncesi, uygulamada
    degisiklik sonrasi).  Belirsiz kalanlarin satirini elle yazip bu dosyayi
    CSV_PATH olarak tekrar kullanabilirsin.

Kodda zaten link olan fonksiyonlar  (MERGE_INTO_EXISTING):
  Fonksiyonun mevcut link blogu su sirayla aranir:
    1) govdenin ICINDE - basta, ortada, nerede olursa olsun - ilk '//#(' satiri
    2) fonksiyonun hemen USTUNDE duran blok (eski format)
  Isaretlerdeki bosluklar ('// #( [A, B ]', '// #)'), satir basina tek ID,
  ']' kapanisi taninir.  '//#)' kapanisi eksik bir blok, sonraki fonksiyonun
  blogu SANILMAZ.  Blok yoksa '{' altina sifirdan yeni blok acilir.
  * True  -> CSV'deki ID'lerden blokta OLMAYANLAR mevcut blogun sonuna
             eklenir; ID satirlari ayni yerde, guncel formatla yeniden yazilir.
             Mevcut ID'ler silinmez, ayni ID iki kez yazilmaz, ikinci bir
             //#( blogu acilmaz.
             REFORMAT_EXISTING = True ise yeni ID olmasa da formata uymayan
             blok (ornek: sonunda ']' olmayan eski blok) yeniden yazilir.
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
from dataclasses import dataclass, field, replace
from pathlib import Path


# ============================== AYARLAR ==============================

SCRIPT_DIR = Path(__file__).resolve().parent   # bu script'in bulundugu klasor

CSV_PATH = SCRIPT_DIR / "llr_export.csv"   # DOORS'tan alinan CSV (llr_export.dxl ciktisi)
CSV_DELIMITER = None             # None = otomatik tespit;  ya da ";" / "," / "\t"

# Kaynak kodun kok dizinleri (linkleri silinecek ve yeniden yazilacak klasorler).
# Windows yollarini r"..." ile yazin.
# Script'in yanindaki klasorler; gercek klasor adlarini yazin.
SOURCE_ROOTS = [
    SCRIPT_DIR / "Lib1",
    SCRIPT_DIR / "Lib2",
    SCRIPT_DIR / "Lib3",
]

# 1. adim: SOURCE_ROOTS'taki tum dosyalardan mevcut linkleri sil
STRIP_EXISTING = True
STRIP_EXTENSIONS = (".cpp", ".h")    # linkleri silinecek dosya uzantilari
STRIP_REPORT_CSV = SCRIPT_DIR / "llr_strip_report.csv"
STRIP_DETAIL_CSV = SCRIPT_DIR / "llr_strip_detail.csv"   # silinen HER satir (DRY_RUN'da kontrol)
# Onceki calismalardan kalan yetim ID satirlari ( '//   HLR_18,' ) da silinsin mi.
# Sadece TAMAMI bilinen onekli ID'lerden olusan yorum satirlari silinir.
STRIP_ORPHAN_ID_LINES = True
# Bilinen ID onekleri.  CSV'deki ve mevcut link bloklarindaki onekler otomatik eklenir.
ID_PREFIXES = ("HLR", "LLR")   # dosya basina silinen blok / satir sayisi

DRY_RUN = True                   # True iken hicbir kaynak dosya degismez
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = SCRIPT_DIR / "llr_link_report.csv"   # ayrintili islem raporu
LINES_CSV = SCRIPT_DIR / "llr_with_lines.csv"     # girdi CSV + bulunan satir numaralari
SHOW_PREVIEW = False             # Dry-run'da eklenecek bloklari ekrana bas
                                 # (cok fonksiyon varsa ekran dolar)

# Islenecek uzantilar
SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c")
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx")
ALLOWED_EXTENSIONS = set(SOURCE_EXTENSIONS) | set(HEADER_EXTENSIONS)

# Dosya 'SOURCE_ROOT / Directory Name / dosya' yolunda yoksa proje icinde
# ayni isimli dosya aransin mi (DOORS'taki yol diskteki yolla ayni degilse)
FIND_FILES_BY_NAME = True

# 'Sinif Konumu'nun son parcasi sinif adidir ve UZANTISIZDIR (Lib1/Mod1/classx).
# Dosya adi, sinif adina su uzantilar SIRAYLA eklenerek bulunur:
#   classx.cpp varsa o, yoksa classx.h, yoksa sonrakiler...
# Fonksiyonun tanimi secilen dosyada yoksa (or. inline metot .h'de) ayni
# sinifin diger uzantili dosyalari da denenir; link tanimin oldugu dosyaya yazilir.
# Sinif adinin sonunda zaten bir uzanti varsa (classx.h) o aynen kullanilir.
CLASS_FILE_EXTS = (".cpp", ".h", ".hpp", ".cc", ".cxx", ".c", ".hh", ".hxx")
DEFAULT_FILE_EXT = CLASS_FILE_EXTS[0]   # hicbiri bulunamazsa raporda gorunecek ad

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

# Ayni isimde birden fazla tanim (function overloading) sinif / parametre /
# satir ipuclariyla ayirt EDILEMEZSE:
#   True  -> AYNI SINIFA (ya da ayni serbest kapsama) ait TUM tanimlara link yazilir;
#            <sinif>.cpp ve <sinif>.h'ye bolunmus overload'lar da dahil.
#   False -> hicbirine yazilmaz, rapora BELIRSIZ olarak dusulur (eski davranis).
# Farkli siniflara ait ayni isimli metotlar overload sayilmaz: her zaman BELIRSIZ.
LINK_ALL_OVERLOADS = True

# Sinif adindan dosya bulunamazsa (dosya adi DOORS'taki sinif basligindan farkli):
# '<Sinif>::<fonksiyon>' tanimi TUM kok klasorlerdeki dosyalarda aranir.
# Sadece tanimin sahibi sinif DOORS'taki sinifla ayniysa kabul edilir.
CONTENT_SEARCH = True
OVERLOAD_TAG = "OVERLOAD"

# --- cikti formati ---
OPEN_PREFIX = "//#(["            # ilk satirin basi ( '{' satirinin hemen altina )
CONT_PREFIX = "//"               # DEVAM satirlarinin yorum oneki ("" yaparsan
                                 # kod DERLENMEZ)
CONT_INDENT = "\t"               # devam satirlarinin girintisi ("    " = 4 bosluk)
IDS_PER_LINE = 2                 # satir basina kac HLR ID yazilsin (1 = eski hali)
INLINE_SEPARATOR = " "           # ayni satirdaki ID'ler arasinda, virgulden SONRA
TRAILING_COMMA_ON_LAST = False   # False -> son ID'den sonra VIRGUL YOK
CLOSE_LIST_SUFFIX = "]"          # son ID'den sonra gelen kapanis ( "" = koyma )

# Etiketli fonksiyonda yeni ID olmasa bile mevcut blok bu formata uymuyorsa
# (ornek: eski calistirmadan kalma, sonunda "]" yok) yeniden yazilsin mi.
# Sadece CSV'de bulunan fonksiyonlarin bloklarina dokunulur; ID'ler korunur.
REFORMAT_EXISTING = True
CLOSE_MARKER = "//#)"            # govdeyi kapatan '}' satirinin hemen ustune

# CSV basliklari. Karsilastirma icin basliklar kucuk harfe cevrilir ve
# harf/rakam disindaki her sey silinir:
#     "Class/File Name" -> "classfilename"
#     "HLR Ids"         -> "hlrids"
#     "Sinif Konumu"    -> "sinifkonumu"   (Turkce harfler de cevrilir)
# Her anahtar icin kabul edilen basliklar (ilk bulunan kullanilir):
COLUMNS = {
    "directory": ("sinifkonumu", "directoryname"),
    "filename":  ("classfilename", "dosyaadi", "dosya"),
    "function":  ("fonksiyon", "functionname"),
    "line":      ("linenumber", "satirno"),
    "hlr":       ("isterler", "ister", "hlrids"),
}
REQUIRED_COLUMNS = ("directory", "function", "hlr")

# =====================================================================


_TR = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                     "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})


def norm_header(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").translate(_TR).lower())


def roots() -> list[Path]:
    return [Path(r) for r in SOURCE_ROOTS if str(r).strip()] or [Path(".")]


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
    start_line: int = 0       # dogrulanmis 1-tabanli baslangic (degisiklik oncesi)
    end_line: int = 0         # fonksiyonun } satiri (1-tabanli, degisiklik oncesi)
    final_line: int = 0       # baslangicin degisiklik SONRASI yeri (dosya yazildiysa)
    cands: list[int] = field(default_factory=list)   # aday satirlar (1-tabanli)
    not_found: bool = False   # fonksiyon dosyada bulunamadi / belirsiz
    preview: str = ""
    action: str = ""          # "YENI" (yeni blok) / "EKLEME" (mevcut bloga ID)
    raw_dir: str = ""         # CSV'deki 'Sinif Konumu'
    raw_name: str = ""        # dosya adi (verilen ya da varsayilan <sinif>.cpp)


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
    tail: str = ""            # ']' sonrasindaki aciklama (yeniden yazarken korunur)


def join_detail(*parts: str) -> str:
    return " | ".join(p for p in parts if p)


# --------------------------------------------------------------------
# 1) Dosya bulma
# --------------------------------------------------------------------

_FILE_INDEX: dict[str, list[Path]] | None = None


def file_index() -> dict[str, list[Path]]:
    """SOURCE_ROOTS altindaki tum kaynak/header dosyalari:  ad (kucuk harf) -> yollar."""
    global _FILE_INDEX
    if _FILE_INDEX is None:
        _FILE_INDEX = {}
        for root in roots():
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


def class_stem(name: str) -> str:
    """'classx' -> 'classx' ;  'classx.h' -> 'classx'  (bilinen uzanti varsa atilir)"""
    p = Path(name.strip())
    return p.stem if p.suffix.lower() in ALLOWED_EXTENSIONS else name.strip()


def class_file_name(cls: str) -> str:
    """
    Sinif adindan dosya adi:  uzanti verilmisse aynen; verilmemisse
    CLASS_FILE_EXTS sirasiyla SOURCE_ROOTS'ta VAR OLAN ilk  <sinif><uzanti>.
    """
    cls = cls.strip()
    if Path(cls).suffix.lower() in ALLOWED_EXTENSIONS:
        return cls
    for ext in CLASS_FILE_EXTS:
        if (cls + ext).lower() in file_index():
            return cls + ext
    return cls + DEFAULT_FILE_EXT


def resolve_file(raw_dir: str, raw_name: str) -> tuple[Path | None, str]:
    d = raw_dir.replace("\\", "/").strip().rstrip("/")
    n = raw_name.replace("\\", "/").strip()
    if not n:
        return None, "Dosya adi yok"
    joined = f"{d}/{n}" if (d and not d.endswith(n)) else (d or n)
    for root in roots():
        full = root / joined
        if full.is_file():
            return full, ""
        # DOORS yolunun son parcasi genelde sinif adidir:  database/Motor + Motor.cpp
        # -> database/Motor.cpp
        if "/" in d:
            alt_full = root / f"{d.rsplit('/', 1)[0]}/{n}"
            if alt_full.is_file():
                return alt_full, ""
    full = roots()[0] / joined
    if not FIND_FILES_BY_NAME:
        return full, ""

    name = Path(n).name
    cands = file_index().get(name.lower(), [])
    if not cands:
        stem = class_stem(name)
        return None, (f"Dosya bulunamadi: '{stem}' (.cpp/.h/...) kok klasorlerin hicbirinde yok "
                      f"[{', '.join(str(r) for r in roots())}]")
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


def repair_row(row: list[str], delim: str) -> tuple[list[str], bool]:
    """
    Satirin TAMAMI tek hucreye tirnaklanmissa yeniden boler.

    Neden olur: ';' ayracli CSV, ayraci ',' olan bir Excel'de acilip CSV olarak
    tekrar kaydedilince her satir tek hucre olur; Excel icinde VIRGUL gecen
    satirlari (birden fazla ID: "LLR_1, LLR_2") tirnak icine alir:
        Sinif Konumu;Fonksiyon;Isterler                 <- tirnaksiz, 3 kolon
        "Lib1/Mod1/classx;func1;LLR_1, LLR_2"           <- tirnakli, 1 kolon!
        Lib1/Mod1/classx;func2;LLR_3                    <- tirnaksiz, 3 kolon
    csv modulu tirnakli satiri TEK hucre okur; bolunmezse sinif adi
    'classx;func1;LLR_1, LLR_2' olur.
    """
    filled = [c for c in row if str(c).strip()]
    if len(filled) == 1 and delim in filled[0]:
        inner = next(csv.reader([filled[0]], delimiter=delim))
        if len(inner) > 1:
            return inner, True
    return row, False


def read_csv_tasks(path: str) -> tuple[list[Task], CsvTable]:
    raw = Path(path).read_bytes()
    text = decode_text(raw, CSV_ENCODINGS)

    # Excel'in 'sep=;' ilk satiri varsa ayraci oradan al, satiri atla
    first = text.split("\n", 1)[0].strip().strip('"')
    if first.lower().startswith("sep=") and len(first) >= 5:
        delim = first[4]
        text = text.split("\n", 1)[1] if "\n" in text else ""
        skipped_lines = 1
    else:
        delim = detect_delimiter(text)
        skipped_lines = 0
    print(f"CSV ayraci: {delim!r}")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)

    try:
        header = next(reader)
    except StopIteration:
        sys.exit("CSV bos.")
    header, _ = repair_row(header, delim)

    headers = [norm_header(h) for h in header]

    idx: dict[str, int] = {}
    for key, wanted in COLUMNS.items():
        for w in wanted:
            if w in headers:
                idx[key] = headers.index(w)
                break

    missing = [COLUMNS[k][0] for k in REQUIRED_COLUMNS if k not in idx]
    if missing:
        sys.exit(
            f"CSV'de bulunamayan zorunlu sutun(lar): {missing}\n"
            f"Gorulen basliklar: {header}\n"
            f"Ayrac yanlis tespit edilmis olabilir -> CSV_DELIMITER'i elle ayarla."
        )

    hlr_is_last = idx["hlr"] == max(idx.values())

    marker: dict[str, str] = {}      # Directory Name -> son dosya satiri
    tasks: list[Task] = []
    table_rows: list[tuple[int, list[str]]] = []

    n_repaired = 0
    need = max(idx[k] for k in REQUIRED_COLUMNS) + 1     # en az bu kadar kolon olmali
    for r, row in enumerate(reader, start=2 + skipped_lines):
        row, fixed = repair_row(row, delim)
        n_repaired += fixed
        table_rows.append((r, row))
        if not any(str(c).strip() for c in row):
            continue

        # Kolonlara bolunemeyen satir: sinif adi diger kolonlari yutmasin
        if len(row) < need:
            t = Task(row_no=r, file=Path("?"), func="", line=0, hlr_ids=[])
            t.status = "HATA"
            t.detail = (f"Satir {len(row)} kolon, en az {need} bekleniyordu "
                        f"(ayrac {delim!r}): {delim.join(row)[:120]}")
            tasks.append(t)
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
                    last = raw_dir.replace("\\", "/").strip().strip("/").split("/")[-1].strip()
                    raw_name = class_file_name(last)

        full, fnote = resolve_file(raw_dir, raw_name)
        t = Task(row_no=r, file=full if full is not None else Path(raw_name or "?"),
                 func=func, line=0, hlr_ids=ids, raw_dir=raw_dir, raw_name=raw_name)
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

    if n_repaired:
        print(f"UYARI: {n_repaired} satirin tamami tek hucreye tirnaklanmisti ve yeniden "
              f"kolonlara bolundu.\n       (CSV muhtemelen Excel'de farkli ayracla acilip "
              f"kaydedildi; DOORS'tan gelen dosyayi dogrudan kullanmak daha guvenli.)")
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

def find_function_body(lines: list[str], start_idx: int,
                       start_col: int = 0) -> tuple[BodySpan | None, str]:
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

    # start_col: tarama fonksiyon ADININ oldugu sutundan baslar.  Satirin
    # basindan baslamak, 'class X { public: void f(); };' gibi tek satirlik
    # bildirimlerde SINIFIN '{' karakterini fonksiyon govdesi sandirir.
    i = start_idx
    while i < len(lines):
        line = lines[i]
        j, n = (start_col if i == start_idx else 0), len(line)
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
    return class_stem(parts[-1]) if parts else ""


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


def name_col(line: str, base: str) -> int:
    """Fonksiyon adinin satirdaki sutunu (tanim yeri olan ilk eslesme; yoksa 0)."""
    cp = code_part(line)
    strong, loose = build_patterns(base)
    for pat in (strong, loose):
        for mm in pat.finditer(cp):
            if is_definition_site(cp, mm.start()):
                return mm.start()
    return 0


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
            strong_hits.append((c, mm.start()))
    for c, col in strong_hits:
        if find_function_body(lines, c, col)[0] is not None:
            return c, note(c)

    # 2) isim tek basina gecen, CAGRI olmayan VE govdesi olan ilk aday
    #    (cok satirli imza)
    for c in cands:
        cp = code_part(lines[c])
        mm = loose.search(cp)
        if (mm and is_definition_site(cp, mm.start())
                and find_function_body(lines, c, mm.start())[0] is not None):
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


NOT_FOUND = "dosyada bulunamadi"


def locate_anywhere(lines: list[str], task: Task,
                    tag_pos: list[int] | None = None) -> tuple[int | None, str, list[int]]:
    """
    Fonksiyonu TUM DOSYADA arar.  Donus: (baslangic | None, not, adaylar).
    Birden fazla tanim varsa sirayla sinif / parametre ipuclariyla daraltir;
    satir numarasi SADECE en son, kalan adaylar arasinda secim icin kullanilir.

    tag_pos[i]: i. satirin, dosyadaki etiket satirlari yokmus gibi sayildigindaki
    yeri.  CSV'deki satir numarasi hem simdiki koda hem etiketsiz koda gore
    yorumlanir.
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
            if find_function_body(lines, c, mm.start())[0] is not None:
                cands.append(c)
            else:
                protos.append(c)
            continue
        # imza bolunmus:  'void Motor::start'  /  '(int speed) {'
        mm = loose.search(cp)
        if (mm and not cp[mm.end():].strip() and is_definition_site(cp, mm.start())
                and next_code_line(lines, c).startswith("(")
                and find_function_body(lines, c, mm.start())[0] is not None):
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
        return None, f"Fonksiyon '{base}' {NOT_FOUND}", []

    if len(cands) > 1 and task.params is not None:
        f = [c for c in cands if signature_params(lines, c, base) == task.params]
        if f:
            cands = f
            notes.append("parametrelerle secildi")

    want = task.line - 1

    def dist(c: int) -> int:
        d = abs(c - want)
        if tag_pos:
            d = min(d, abs(tag_pos[c] - want))
        return d

    if len(cands) > 1 and task.line > 0:
        ranked = sorted(cands, key=dist)
        if dist(ranked[0]) == dist(ranked[1]):
            notes.append(f"CSV satiri {task.line} iki tanima esit uzaklikta")
        else:
            cands = ranked[:1]
            notes.append(f"CSV satiri {task.line}'e en yakin tanim secildi")

    if len(cands) > 1:
        where = ", ".join(str(c + 1) for c in cands)
        owners = {owner_class(lines, c, base).lower() for c in cands}
        if LINK_ALL_OVERLOADS and len(owners) == 1:
            notes.insert(0, f"{OVERLOAD_TAG}: '{base}' {len(cands)} tanim (satir {where}) "
                            f"ayirt edilemedi - hepsine link")
            return cands[0], join_detail(*notes), [c + 1 for c in cands]
        why = (f"farkli siniflarda ({', '.join(sorted(o or '-' for o in owners))})"
               if len(owners) > 1 else "")
        return None, (f"BELIRSIZ: '{base}' {len(cands)} yerde tanimli (satir {where}) "
                      f"{why} - Function Name'e sinif ya da parametreleri ekle").replace("  ", " "), \
            [c + 1 for c in all_cands]

    c = cands[0]
    if task.line > 0 and dist(c) > SEARCH_RADIUS:
        notes.append(f"UYARI: CSV satiri {task.line}, tanim {c + 1}. satirda")
    if task.params is not None and len(all_cands) == 1:
        found = signature_params(lines, c, base)
        if found is not None and found != task.params:
            notes.append(f"UYARI: parametreler tutmuyor (kod: {', '.join(found) or '-'})")
    if len(all_cands) > 1:
        notes.insert(0, f"{len(all_cands)} tanim vardi")
    return c, join_detail(*notes), [x + 1 for x in all_cands]


def locate_function(lines: list[str], task: Task, tag_pos: list[int] | None,
                    alt_center: int | None) -> tuple[int | None, str, list[int]]:
    """
    Once tum dosyada (sinif / parametre / satir ipuclariyla) arar.  Hic tanim
    bulunamazsa ve satir numarasi verilmisse o satirin cevresine daha gevsek
    bir kuralla bakar (alisilmadik imza yazimlari icin).
    """
    start, note, cands = locate_anywhere(lines, task, tag_pos)
    if start is None and not cands and task.line > 0 and NOT_FOUND in note:
        s2, n2 = locate_start(lines, task, alt_center)
        if s2 is not None:
            return s2, join_detail(n2, "sadece satir cevresinde bulundu"), [s2 + 1]
    return start, note, cands


# --------------------------------------------------------------------
# 7) Mevcut etiket bloklari
# --------------------------------------------------------------------

# Acilis / kapanis isaretleri (bosluklara toleransli):
#     //#([A, B]     // #( [A, B ]     //#)     // #)
OPEN_RE = re.compile(r"^\s*//\s*#\s*\(")
CLOSE_RE = re.compile(r"^\s*//\s*#\s*\)")
TEMPLATE_LINE = re.compile(r"^\s*template\s*<")


def find_tag_opens(lines: list[str]) -> list[int]:
    """
    Dosyadaki tum '//#(' acilis satirlarinin indeksleri.  Kapanislarla
    eslestirme YAPILMAZ: '//#)' satiri eksik bir blok, sonraki fonksiyonlarin
    blogu sanilmasin.
    """
    return [i for i, ln in enumerate(lines) if OPEN_RE.match(ln)]


# Bir devam satirinin yorum isaretinden sonraki kismi:  "HLR_3, HLR_4,"  /  "HLR_5]"
ID_LINE = re.compile(r"^([^\s,;\]]+(\s*,\s*[^\s,;\]]+)*\s*,?)?\s*(\].*)?$")
ID_SPLIT = re.compile(r"[\s,;\[\]]+")


def tag_id_line_count(lines: list[str], lo: int) -> int:
    """
    lines[lo] ('//#(' satiri) ile baslayan ID satirlarinin sayisi.  Liste
    alttaki '//' satirinda su durumlarda devam eder:
      * ust satir virgulle bitiyorsa
      * '[' acilmis, ']' henuz gelmemis ve devam satirinda ']' varsa
    ']' gorulunce liste biter.  Devam satiri ID listesine benzemeli; govdedeki
    '// sayac' gibi yorumlar ID sanilmaz.
    """
    first = OPEN_RE.sub("", lines[lo], count=1)
    bracket = "[" in first
    closed = "]" in first
    indent_len = len(leading_ws(lines[lo]))
    k = lo
    while k + 1 < len(lines) and k - lo < 200 and not closed:
        nxt = lines[k + 1]
        s = nxt.strip()
        if not s.startswith("//") or OPEN_RE.match(nxt) or CLOSE_RE.match(nxt):
            break
        content = s[2:].strip()
        if not content or not ID_LINE.match(content):
            break
        comma = lines[k].rstrip().endswith(",")
        if not ((comma and (bracket or len(leading_ws(nxt)) <= indent_len))
                or (bracket and "]" in content)):
            break
        k += 1
        closed = "]" in content
    return k - lo + 1


def parse_tag_ids(id_lines: list[str]) -> list[str]:
    parts = [OPEN_RE.sub("", ln, count=1) if k == 0 else ln.strip()[2:]
             for k, ln in enumerate(id_lines)]
    text = " ".join(parts)
    if "]" in text:
        text = text.split("]", 1)[0]          # ']' sonrasi aciklama ID degil
    return [x for x in ID_SPLIT.split(text) if x]


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


def find_existing_tag(lines: list[str], opens: list[int],
                      start: int, span: BodySpan) -> ExistingTag | None:
    """
    Fonksiyona ait mevcut link blogu:
      1) govdenin ICINDE (basta, ortada, nerede olursa olsun) ilk '//#(' satiri
      2) yoksa fonksiyonun hemen USTUNDEKI blok (eski format); blok ile imza
         arasinda sadece bos satir / yorum / 'template<...>' olabilir
    """
    lo = next((o for o in opens if span.open_line <= o <= span.close_line), None)
    if lo is None:
        above = [o for o in opens if o < start]
        if above:
            cand = above[-1]
            between = lines[cand + tag_id_line_count(lines, cand):start]
            if all(not code_part(b).strip() or COMMENT_LINE.match(b) or TEMPLATE_LINE.match(b)
                   for b in between):
                lo = cand
    if lo is None:
        return None
    n = tag_id_line_count(lines, lo)
    tail = ""
    for ln in lines[lo:lo + n]:
        if "]" in ln:
            tail = ln.rstrip("\r\n").split("]", 1)[1].strip()
            break
    return ExistingTag(lo, n, parse_tag_ids(lines[lo:lo + n]), tail)


def bad_close_lines(lines: list[str], lo: int, span: BodySpan) -> list[int]:
    """Blogun kapanis isaretlerinden formata uymayanlar ('// #)' gibi)."""
    if lo >= span.open_line:                     # govde icindeki blok(lar)
        rng = range(span.open_line, span.close_line + 1)
    else:                                        # eski format: '}' sonrasi ilk dolu satir
        k = span.close_line + 1
        while k < len(lines) and not lines[k].strip():
            k += 1
        rng = range(k, min(k + 1, len(lines)))
    return [k for k in rng if CLOSE_RE.match(lines[k]) and lines[k].strip() != CLOSE_MARKER]


def tag_line_set(lines: list[str], opens: list[int]) -> set[int]:
    """Etiket satirlarinin (ID satirlari + //#) ) indeksleri."""
    skip: set[int] = set()
    for lo in opens:
        skip.update(range(lo, lo + tag_id_line_count(lines, lo)))
    skip.update(i for i, ln in enumerate(lines) if CLOSE_RE.match(ln))
    return skip


def untagged_line_map(lines: list[str], opens: list[int]) -> list[int]:
    """
    Etiket satirlari yokmus gibi sayildiginda 'k. satir' -> simdiki 0-tabanli
    indeks.  map[k - 1] seklinde kullanilir.
    """
    skip = tag_line_set(lines, opens)
    return [i for i in range(len(lines)) if i not in skip]


def untagged_positions(lines: list[str], opens: list[int]) -> list[int]:
    """Her satirin, etiket satirlari yokmus gibi sayildigindaki 0-tabanli yeri."""
    skip = tag_line_set(lines, opens)
    out, n = [], 0
    for i in range(len(lines)):
        out.append(n)
        if i not in skip:
            n += 1
    return out


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
        //	HLR_5]
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
                if t.final_line or t.start_line:
                    row[line_i] = str(t.final_line or t.start_line)
                status = "DOSYA SATIRI" if t.action == "DOSYA" else t.status
                detail = t.detail
                if len(t.cands) > 1 and "BELIRSIZ" not in detail:
                    detail = join_detail(detail, "adaylar: " + ", ".join(map(str, t.cands)))
            w.writerow(row + [status, detail])


# --------------------------------------------------------------------
# 9b) Bellekteki dosyalar, link silme, dosya secimi
# --------------------------------------------------------------------

@dataclass
class FileState:
    lines: list[str]
    enc: str
    had_bom: bool
    dirty: bool = False           # diske yazilmasi gerekiyor mu
    strip_blocks: int = 0         # silinen //#( blogu
    strip_lines: int = 0          # silinen satir (ID satirlari + //#) )


_FILES: dict[Path, FileState] = {}


def load_file(path: Path) -> FileState:
    """Dosyayi bir kez okur; sonraki tum adimlar ayni (bellekteki) kopyayi kullanir."""
    key = path.resolve()
    if key not in _FILES:
        lines, enc, bom = read_lines(key)
        _FILES[key] = FileState(lines, enc, bom)
    return _FILES[key]


# ---------------- link silme (sadece silme adimi icin, genis tanima) ----------------
#
# Taninan isaretler (bosluk / tab / girinti fark etmez):
#     //#(   // #(   ///#(   //!#(   /*#( ... */      -> acilis
#     //#)   // #)   ///#)   //!#)   /*#)*/           -> kapanis
#   * satirin tamami isaretse satir silinir
#   * isaret kod satirinin SONUNDAYSA ( 'void f() { //#([HLR_1]' ) sadece yorum
#     kismi silinir, kod kalir
#   * acilistan sonraki ID devam satirlari ( '//   HLR_2,'  '//  HLR_3]' ) girinti,
#     virgul, koseli parantez durumundan bagimsiz silinir; ID'ye benzemeyen ilk
#     yorum satirinda ( '// sayac' ) durulur
#   * onceki calismalardan YETIM kalan ID satirlari (sadece bilinen onekli ID'ler
#     iceren yorum satirlari:  '//   HLR_18,') da silinir (STRIP_ORPHAN_ID_LINES)

_CMT = r"(?://[/!]*|/\*[*!]*)"
S_OPEN = re.compile(r"^" + _CMT + r"\s*#\s*\(")
S_CLOSE = re.compile(r"^" + _CMT + r"\s*#\s*\)")
S_LINE_CMT = re.compile(r"^\s*//[/!]*(.*)$")
ID_TOKEN = re.compile(r"(?:[A-Za-z][\w.\-/:]*\d[\w.\-/:]*|\d+)")


def comment_start(line: str) -> int:
    """Satirdaki ilk //  ya da  /*  yorumunun yeri (string / char icindekiler sayilmaz)."""
    q = ""
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if q:
            if c == "\\":
                i += 2
                continue
            if c == q:
                q = ""
        elif c in "\"'":
            q = c
        elif c == "/" and i + 1 < n and line[i + 1] in "/*":
            return i
        i += 1
    return -1


def id_tokens(text: str) -> list[str] | None:
    """'[HLR_1, HLR_2] aciklama' -> ['HLR_1','HLR_2'];  ID'ye benzemeyen varsa None."""
    text = text.split("]", 1)[0].replace("[", " ")
    toks = [x for x in re.split(r"[\s,;]+", text) if x]
    return toks if all(ID_TOKEN.fullmatch(x) for x in toks) else None


def id_prefix(tok: str) -> str:
    m = re.match(r"[A-Za-z]+", tok)
    return m.group(0).upper() if m else ""


def strip_links(lines: list[str], prefixes: set[str] | None = None,
                found_prefixes: set[str] | None = None,
                log: list[tuple[int, str, str]] | None = None) -> tuple[list[str], int, int]:
    """
    Tum link bloklarini siler.  Doner: (yeni satirlar, silinen blok, degisen satir).
    prefixes       : yetim ID satirlari icin bilinen ID onekleri (HLR, LLR ...)
    found_prefixes : bloklarda gorulen ID onekleri buraya eklenir
    log            : (satir no, tur, satirin eski hali) kayitlari
    """
    n = len(lines)
    drop: set[int] = set()
    repl: dict[int, str] = {}
    blocks = 0

    def eol(ln: str) -> str:
        return ln[len(ln.rstrip("\r\n")):]

    def note(i: int, kind: str) -> None:
        if log is not None:
            log.append((i + 1, kind, lines[i].rstrip("\r\n")))

    def seen_ids(text: str) -> None:
        if found_prefixes is not None:
            for t in id_tokens(text) or []:
                if id_prefix(t):
                    found_prefixes.add(id_prefix(t))

    def consume_ids(i: int, rest: str) -> None:
        """Acilis satiri i'den sonraki ID devam satirlarini sil."""
        seen_ids(rest)
        closed = "]" in rest
        k = i
        while not closed and k + 1 < n and k - i < 200:
            nxt = lines[k + 1]
            m = S_LINE_CMT.match(nxt)
            if not m or S_OPEN.match(nxt.lstrip()) or S_CLOSE.match(nxt.lstrip()):
                break
            content = m.group(1).strip()
            if not content or id_tokens(content) is None:
                break
            k += 1
            drop.add(k)
            note(k, "ID SATIRI")
            seen_ids(content)
            closed = "]" in content

    def block_comment_end(i: int, col: int) -> tuple[int, int] | None:
        """/* ile baslayan yorumun bittigi (satir, '*/' sonrasi sutun)."""
        for k in range(i, min(i + 50, n)):
            j = lines[k].find("*/", col + 2 if k == i else 0)
            if j >= 0:
                return k, j + 2
        return None

    i = 0
    while i < n:
        if i in drop:
            i += 1
            continue
        ln = lines[i]
        body = ln.rstrip("\r\n")
        st = body.lstrip()
        col = comment_start(body)
        if col < 0:
            i += 1
            continue
        cmt = body[col:]
        is_open, is_close = bool(S_OPEN.match(cmt)), bool(S_CLOSE.match(cmt))
        if not (is_open or is_close):
            i += 1
            continue
        whole = not body[:col].strip()             # satirda yorumdan once kod yok

        if cmt.startswith("/*"):
            end = block_comment_end(i, col)
            if end is None:                        # kapanmayan /* : dokunma
                i += 1
                continue
            ek, ecol = end
            after = lines[ek].rstrip("\r\n")[ecol:]
            inner = " ".join(x.rstrip("\r\n") for x in lines[i:ek + 1])
            seen_ids(re.sub(r"^.*?#\s*[()]", "", inner).replace("*/", " "))
            if whole and not after.strip():
                for k in range(i, ek + 1):
                    drop.add(k)
                    note(k, "ACILIS" if is_open and k == i else
                         ("KAPANIS" if is_close else "ID SATIRI"))
            else:
                note(i, "SATIR SONU ISARET")
                repl[i] = (body[:col].rstrip() + (" " + after.strip() if after.strip() else "")
                           ) + eol(lines[ek])
                for k in range(i + 1, ek + 1):
                    drop.add(k)
            blocks += is_open
            i = ek + 1
            continue

        if whole:
            drop.add(i)
            note(i, "ACILIS" if is_open else "KAPANIS")
        else:
            note(i, "SATIR SONU ISARET")
            repl[i] = body[:col].rstrip() + eol(ln)
        if is_open:
            blocks += 1
            consume_ids(i, S_OPEN.sub("", cmt, count=1))
        i += 1

    # yetim ID satirlari (onceki silmelerden kalan '//   HLR_18,' gibi)
    if STRIP_ORPHAN_ID_LINES and prefixes:
        for i, ln in enumerate(lines):
            if i in drop or i in repl:
                continue
            m = S_LINE_CMT.match(ln.rstrip("\r\n"))
            if not m:
                continue
            content = m.group(1).strip()
            if content[:1] in ("#",):
                continue
            toks = id_tokens(content)
            if toks and all(id_prefix(t) in prefixes for t in toks):
                drop.add(i)
                note(i, "YETIM ID SATIRI")

    if not drop and not repl:
        return lines, 0, 0
    out = []
    for i, ln in enumerate(lines):
        if i in drop:
            continue
        out.append(repl.get(i, ln))
    return out, blocks, len(drop) + len(repl)


def strip_all_roots(prefixes: set[str]) -> list[tuple[Path, int, int, str]]:
    """
    SOURCE_ROOTS'taki tum STRIP_EXTENSIONS dosyalarindan linkleri siler (bellekte).
    Iki gecis: once bloklardaki ID onekleri toplanir, sonra yetim ID satirlari da
    bu oneklerle (+ CSV'deki ve ID_PREFIXES'teki onekler) temizlenir.
    """
    exts = {e.lower() for e in STRIP_EXTENSIONS}
    files: list[Path] = []
    out: list[tuple[Path, int, int, str]] = []
    for root in roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if Path(fn).suffix.lower() in exts:
                    files.append(Path(dirpath) / fn)

    known = {x.upper() for x in prefixes} | {x.upper() for x in ID_PREFIXES}
    for p in files:                                 # 1. gecis: onekleri topla
        try:
            strip_links(load_file(p).lines, None, known)
        except Exception:
            pass
    known.discard("")

    with open(STRIP_DETAIL_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dosya", "satir", "tur", "silinen / degisen satir"])
        for p in files:                             # 2. gecis: sil
            try:
                st = load_file(p)
            except Exception as e:
                out.append((p, 0, 0, f"okunamadi: {e}"))
                continue
            log: list[tuple[int, str, str]] = []
            new, nb, nl = strip_links(st.lines, known, None, log)
            if nl:
                st.lines = new
                st.dirty = True
                st.strip_blocks, st.strip_lines = nb, nl
                out.append((p, nb, nl, ""))
                for lno, kind, text in log:
                    w.writerow([p.resolve(), lno, kind, text])
    print("ID onekleri (yetim satir temizligi icin): " + (", ".join(sorted(known)) or "-"))
    return out


def norm_stem(s: str) -> str:
    """Karsilastirma icin:  'Class_X' -> 'classx'   (harf/rakam disi atilir)"""
    return re.sub(r"[^a-z0-9]", "", str(s or "").translate(_TR).lower())


def stem_variants(name: str) -> list[str]:
    """
    DOORS sinif basligindan olasi dosya/sinif adlari:
        'classx'              -> classx
        'class classx'        -> class classx, classx
        'ns::classx'          -> ns::classx, classx
        'classx (abstract)'   -> classx (abstract), classx
    Her kelime de aday olur; yanlis eslesme olmaz cunku dosya ancak icinde
    fonksiyonun TANIMI bulunursa secilir.
    """
    s = class_stem(name or "")
    out = [s]
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    out.append(t.split("::")[-1].strip())
    words = [w for w in re.findall(r"[A-Za-z_]\w*", t)
             if w.lower() not in ("class", "struct", "sinif", "sinifi", "the")]
    out += list(reversed(words))
    return [v for v in dict.fromkeys(x.strip() for x in out) if v]


_NORM_INDEX: dict[str, list[Path]] | None = None


def norm_index() -> dict[str, list[Path]]:
    """normalize govde ad ('classx') -> dosyalar  ('Class_X.cpp', 'classx.h' ...)"""
    global _NORM_INDEX
    if _NORM_INDEX is None:
        _NORM_INDEX = {}
        for paths in file_index().values():
            for p in paths:
                _NORM_INDEX.setdefault(norm_stem(p.stem), []).append(p)
    return _NORM_INDEX


def all_source_files() -> list[Path]:
    return list(dict.fromkeys(p.resolve() for ps in file_index().values() for p in ps))


def hint_variants(t: Task) -> list[str]:
    return list(dict.fromkeys([t.class_hint] + stem_variants(t.class_hint))) or [""]


def probe_file(t: Task, p: Path, require_owner: bool = False) -> str | None:
    """
    p dosyasinda fonksiyonun TANIMI var mi?  Varsa eslesen sinif ipucunu doner.
    require_owner: tanimin sahibi sinif, ipucuyla ayni olmali (icerik aramasi icin).
    """
    try:
        lines = load_file(p).lines
    except Exception:
        return None
    if not any(t.base in ln for ln in lines):
        return None
    for hint in hint_variants(t):
        probe = Task(row_no=t.row_no, file=p, func=t.func, line=t.line, hlr_ids=[],
                     base=t.base, params=t.params, class_hint=hint)
        start = locate_anywhere(lines, probe)[0]
        if start is None:
            continue
        if require_owner:
            if not hint or norm_stem(owner_class(lines, start, t.base)) != norm_stem(hint):
                continue
        return hint
    return None


def candidate_files(t: Task) -> list[Path]:
    """<sinif>.cpp / .h / ... : SOURCE_ROOTS icindeki ayni govdeli tum dosyalar
    (CLASS_FILE_EXTS sirasiyla)."""
    stems = stem_variants(t.raw_name or t.class_hint)
    if not stems:
        return []
    found: list[Path] = []
    exts = list(CLASS_FILE_EXTS) + [e for e in sorted(ALLOWED_EXTENSIONS)
                                    if e not in CLASS_FILE_EXTS]
    for stem in stems:                       # 1) tam ad (her kok klasorde)
        for ext in exts:
            found += file_index().get((stem + ext).lower(), [])
    for stem in stems:                       # 2) buyuk/kucuk harf, _ - bosluk farki
        found += norm_index().get(norm_stem(stem), [])
    return list(dict.fromkeys(p.resolve() for p in found))


def refine_files(tasks: list[Task]) -> None:
    """
    Fonksiyonun tanimi hangi dosyadaysa gorevi oraya yonlendirir:
    <sinif>.cpp'de yoksa <sinif>.h (vb.) denenir.  Birden fazla dosyada varsa
    yolu 'Sinif Konumu'na en cok benzeyen, o da esitse kaynak (.cpp) dosyasi secilir.
    """
    for t in list(tasks):
        if t.action == "DOSYA" or not t.hlr_ids or not t.base:
            continue
        if t.status not in ("PENDING", "HATA"):
            continue
        hits: list[Path] = []
        hint_of: dict[Path, str] = {}
        how = ""
        for p in candidate_files(t):         # 1-2) sinif adina benzeyen dosyalar
            h = probe_file(t, p)
            if h is not None:
                hits.append(p)
                hint_of[p] = h
        if not hits and CONTENT_SEARCH and t.class_hint:
            # 3) dosya adi tutmuyor: '<Sinif>::<fonksiyon>' tanimini TUM kok
            #    klasorlerdeki dosyalarda ara (sahibi sinif ayni olmali)
            for p in all_source_files():
                h = probe_file(t, p, require_owner=True)
                if h is not None:
                    hits.append(p)
                    hint_of[p] = h
            how = "icerik aramasiyla"
        if not hits:
            if t.status == "HATA" and CONTENT_SEARCH and t.class_hint:
                t.detail = join_detail(t.detail, f"'{t.class_hint}::{t.base}' tanimi kok "
                                                 f"klasorlerdeki hicbir dosyada da yok")
            continue                       # mevcut cozum + hata mesaji kalsin
        for p in hits:
            if hint_of.get(p) and hint_of[p] != t.class_hint:
                how = join_detail(how, f"sinif adi '{hint_of[p]}' olarak eslesti")
                t.class_hint = hint_of[p]
                break
        best = hits
        if len(best) > 1:
            best = pick_by_dir(best, t.raw_dir)
        if len(best) > 1 and LINK_ALL_OVERLOADS and len({p.parent for p in best}) == 1:
            # ayni klasorde <sinif>.cpp + <sinif>.h: overload'lar iki dosyaya bolunmus
            names = ", ".join(p.name for p in best)
            note = f"{OVERLOAD_TAG}: '{t.base}' {len(best)} dosyada tanimli ({names}) - hepsine link"
            if t.status == "HATA":
                t.status, t.detail = "PENDING", (f"Dosya fonksiyon aranarak bulundu {how}"
                                                 .strip() if how else "")
            for k, p in enumerate(best):
                tt = t if k == 0 else replace(t, hlr_ids=list(t.hlr_ids), cands=[])
                tt.file = p
                tt.detail = join_detail(tt.detail, note)
                if k > 0:
                    tasks.append(tt)
            continue
        if len(best) > 1:
            src = [p for p in best if p.suffix.lower() in SOURCE_EXTENSIONS]
            if len(src) == 1:
                best = src
        if len(best) > 1:
            t.status = "HATA"
            t.detail = (f"BELIRSIZ dosya: '{t.base}' {len(best)} dosyada tanimli: "
                        + ", ".join(str(p) for p in best[:5]))
            continue
        chosen = best[0]
        if t.status == "HATA":
            t.status = "PENDING"
            t.detail = f"Dosya fonksiyon aranarak bulundu{' ' + how if how else ''}: {chosen}"
        elif chosen != t.file.resolve():
            t.detail = join_detail(t.detail, f"Tanim {chosen.name} dosyasinda bulundu")
        t.file = chosen


# --------------------------------------------------------------------
# 10) Ana akis
# --------------------------------------------------------------------

def main() -> int:
    bad_roots = [str(r) for r in roots() if not r.is_dir()]
    if bad_roots:
        sys.exit("SOURCE_ROOTS'ta bulunamayan klasor(ler):\n  " + "\n  ".join(bad_roots))
    print("Kok klasorler:\n  " + "\n  ".join(str(r) for r in roots()) + "\n")

    # === 1) mevcut linkleri sil (bellekte) ===
    # CSV once okunur: icindeki ID onekleri yetim satir temizliginde kullanilir
    tasks, table = read_csv_tasks(CSV_PATH)
    print(f"CSV'den {len(tasks)} satir okundu.\n")
    csv_prefixes = {id_prefix(x) for t in tasks for x in t.hlr_ids} - {""}

    strip_rows: list[tuple[Path, int, int, str]] = []
    if STRIP_EXISTING:
        strip_rows = strip_all_roots(csv_prefixes)
        n_files = sum(1 for _, nb, nl, err in strip_rows if nl)
        n_blocks = sum(nb for _, nb, _, _ in strip_rows)
        n_lines = sum(nl for _, _, nl, _ in strip_rows)
        n_err = sum(1 for *_, err in strip_rows if err)
        print(f"SILME: {n_files} dosyada {n_blocks} link blogu ({n_lines} satir) silindi"
              + (f", {n_err} dosya okunamadi" if n_err else "") + ".\n")

    # === 2) CSV'deki linkleri yaz ===
    refine_files(tasks)

    groups: dict[Path, list[Task]] = {}
    for t in tasks:
        if t.status in ("HATA", "ATLANDI"):
            continue
        groups.setdefault(t.file.resolve(), []).append(t)

    extra_tasks: list[Task] = []          # overload kopyalari (rapor icin)
    for file, file_tasks in groups.items():
        if not file.exists():
            for t in file_tasks:
                t.status = "HATA"
                t.detail = join_detail(t.detail, f"Dosya bulunamadi: {file}")
            continue

        try:
            fstate = load_file(file)
            lines = fstate.lines
        except Exception as e:
            for t in file_tasks:
                t.status = "HATA"
                t.detail = join_detail(t.detail, f"Dosya okunamadi: {e}")
            continue

        eol = detect_eol(lines)
        unit = detect_indent_unit(lines)
        tagged = find_tag_opens(lines)
        # CSV satirlari etiketlerden ONCEKI koda goreyse kullanilacak eslemeler
        orig_map = untagged_line_map(lines, tagged) if tagged else []
        tag_pos = untagged_positions(lines, tagged) if tagged else None

        # === once TUM gorevleri coz (henuz degistirmeden) ===
        planned: list[tuple[Task, int, BodySpan, ExistingTag | None]] = []

        def plan_one(t: Task, start: int, note: str) -> None:
            span, err = find_function_body(lines, start, name_col(lines[start], t.base))
            if span is None:
                t.status = "HATA"
                t.detail = join_detail(t.detail, err)
                return

            t.start_line, t.end_line = start + 1, span.close_line + 1
            t.detail = join_detail(t.detail, note)

            existing = find_existing_tag(lines, tagged, start, span)
            if existing is not None and not MERGE_INTO_EXISTING:
                t.status = "ATLANDI"
                t.detail = join_detail(t.detail, "Zaten etiketli")
                return

            if existing is None and touches_macro_continuation(lines, span):
                t.status = "HATA"
                t.detail = join_detail(t.detail, "Makro devam satiri (\\) - elle yapilmali")
                return

            planned.append((t, start, span, existing))

        for t0 in file_tasks:
            alt = orig_map[t0.line - 1] if 1 <= t0.line <= len(orig_map) else None
            start0, note, cands = locate_function(lines, t0, tag_pos, alt)
            t0.cands = cands
            if start0 is None:
                t0.status, t0.not_found = "HATA", True
                t0.detail = join_detail(t0.detail, note)
                continue

            starts = [start0]
            if OVERLOAD_TAG in note and len(cands) > 1:
                starts = [c - 1 for c in cands]          # tum overload tanimlari
            for k, start in enumerate(starts):
                t = t0
                if k > 0:
                    t = replace(t0, hlr_ids=list(t0.hlr_ids), cands=list(cands))
                    extra_tasks.append(t)
                plan_one(t, start, note)

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
        shifts: list[tuple[int, int]] = []    # (degisikligin basladigi satir, eklenen satir)
        for t, start, span, existing in sorted(planned, key=lambda p: p[2].open_line,
                                               reverse=True):
            if existing is not None:
                # --- mevcut bloga yeni ID ekle ---
                merged, added = merge_ids(existing.ids, t.hlr_ids)
                lo, n = existing.open_line, existing.id_line_count
                new_block = build_open_block(merged, leading_ws(lines[lo]), eol)
                if existing.tail:                          # ']' sonrasi notu koru
                    new_block[-1] = new_block[-1].rstrip("\r\n") + " " + existing.tail + eol
                old_block = lines[lo:lo + n]
                bad_closes = bad_close_lines(lines, lo, span) if REFORMAT_EXISTING else []
                same_format = ([ln.rstrip("\r\n") for ln in new_block]
                               == [ln.rstrip("\r\n") for ln in old_block]) and not bad_closes
                if not added and (same_format or not REFORMAT_EXISTING):
                    t.status = "ATLANDI"
                    t.detail = join_detail(t.detail, "Zaten etiketli, tum ID'ler mevcut")
                    continue
                for k in bad_closes:                       # '// #)'  ->  '//#)'
                    lines[k] = leading_ws(lines[k]) + CLOSE_MARKER + split_eol(lines[k])[1]
                lines[lo:lo + n] = new_block
                shifts.append((lo, len(new_block) - n))

                if added:
                    t.status, t.action = "OK", "EKLEME"
                    t.detail = join_detail(t.detail,
                                           f"{len(added)} ID eklendi: {', '.join(added)}")
                else:
                    t.status, t.action = "OK", "FORMAT"
                    t.detail = join_detail(t.detail, "Mevcut blok yeni formata cevrildi")
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
            shifts.append((span.open_line, len(new) - (span.close_line - span.open_line + 1)))

            t.status, t.action = "OK", "YENI"
            t.preview = make_preview(sig, new, open_at + len(open_block), close_at)
            changed = True

        if changed:
            fstate.lines = lines
            fstate.dirty = True
        if changed and not DRY_RUN:
            # LINES_CSV icin: fonksiyon baslangicinin yazilan dosyadaki yeri
            for t in file_tasks:
                if t.start_line:
                    t.final_line = t.start_line + sum(d for pos, d in shifts
                                                      if pos < t.start_line - 1)

        if changed and DRY_RUN and SHOW_PREVIEW:
            print(f"--- {file} ---")
            for t, *_ in planned:
                if t.status != "OK":
                    continue
                what = {"YENI": "yeni blok", "EKLEME": "mevcut bloga ekleme",
                        "FORMAT": "mevcut blok yeni formata"}.get(t.action, t.action)
                print(f"[satir {t.start_line}-{t.end_line}]  {t.func}   ({what})")
                print(t.preview.rstrip())
                print()

    tasks.extend(extra_tasks)

    # === degisen dosyalari yaz (silme ve/veya yeni link) ===
    n_written = 0
    write_errors: list[str] = []
    if not DRY_RUN:
        for path, st in _FILES.items():
            if not st.dirty:
                continue
            try:
                write_lines(path, st.lines, st.enc, st.had_bom)
                n_written += 1
            except Exception as e:
                write_errors.append(f"{path}: {e}")

    linked_per_file: dict[Path, int] = {}
    for t in tasks:
        if t.status == "OK":
            k = t.file.resolve()
            linked_per_file[k] = linked_per_file.get(k, 0) + 1
    with open(STRIP_REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dosya", "silinen_blok", "silinen_satir", "yazilan_link", "not"])
        listed = set()
        for p, nb, nl, err in strip_rows:
            k = p.resolve()
            listed.add(k)
            w.writerow([k, nb, nl, linked_per_file.get(k, 0), err])
        for k, n in linked_per_file.items():
            if k not in listed:
                w.writerow([k, 0, 0, n, ""])

    add_sibling_hints(tasks)

    # === rapor ===
    real = [t for t in tasks if t.action != "DOSYA"]
    ok_new = sum(1 for t in real if t.status == "OK" and t.action == "YENI")
    ok_add = sum(1 for t in real if t.status == "OK" and t.action == "EKLEME")
    ok_fmt = sum(1 for t in real if t.status == "OK" and t.action == "FORMAT")
    skip = sum(1 for t in real if t.status == "ATLANDI")
    err = sum(1 for t in real if t.status == "HATA")
    pend = sum(1 for t in real if t.status == "PENDING")
    found = sum(1 for t in real if t.start_line)
    ambiguous = sum(1 for t in real if "BELIRSIZ" in t.detail)

    print("=" * 72)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  "
          f"YENI BLOK: {ok_new}  ID EKLENEN: {ok_add}  FORMAT: {ok_fmt}  ATLANDI: {skip}  "
          f"HATA: {err}  BEKLEYEN: {pend}")
    print(f"Satiri bulunan fonksiyon: {found} / {len(real)}   (belirsiz: {ambiguous})")
    ovl_rows = {t.row_no for t in real if OVERLOAD_TAG in t.detail and t.status == "OK"}
    if ovl_rows:
        n_ovl = sum(1 for t in real if t.row_no in ovl_rows and t.status == "OK")
        print(f"Overload: {len(ovl_rows)} CSV satiri ayirt edilemedi -> {n_ovl} tanimin "
              f"hepsine link yazildi (raporda '{OVERLOAD_TAG}')")
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
    print(f"Silme raporu: {STRIP_REPORT_CSV}   (silinen her satir: {STRIP_DETAIL_CSV})")
    print(f"Satir numarali CSV: {LINES_CSV}")

    n_dirty = sum(1 for st in _FILES.values() if st.dirty)
    if DRY_RUN:
        print(f"\nDRY-RUN: {n_dirty} dosya degisecekti, diske hicbir sey yazilmadi.")
        print("DRY_RUN = False yapip tekrar calistirarak degisiklikleri uygulayabilirsin.")
    else:
        print(f"\nDiske yazilan dosya: {n_written}")
        for e in write_errors:
            print(f"  YAZMA HATASI: {e}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
