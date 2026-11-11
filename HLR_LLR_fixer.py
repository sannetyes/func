#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hlr_llr_fix.py  -  HLR / LLR link bloklarini duzelten ve denetleyen script.
Harici bagimlilik YOKTUR (sadece stdlib).

Kaynak kodda (.cpp / .h ...) su bicimdeki bloklari bulur:

    int func_name(param1){
    //#([HLR_MODULE_1234, HLR_MODULE2_1234,
    //   HLR_MODULE3_1234, HLR_MODULE4_1234,
    //   HLR_MODULE5_1234]
        ...
    //#)
    }

ve her blok icin:

  1) Ayni blokta tekrar eden (duplicate) ID'leri siler.
  2) Devam satirlarinin girintisi SABITTIR:  '//' + 3 bosluk  (tab yok).
  3) ID'leri alfabetik + sayisal (kucukten buyuge) siralar.  Karsilastirma
     '_' ile ayrilan parca parca yapilir, sayilar SAYI olarak karsilastirilir:
         HLR_MOD_2 < HLR_MOD_10 < HLR_MOD2_1 < HLR_MODB_1 < LLR_MOD_1
  4) Ilk satir haric butun satirlar ayni girintiyle yazilir.  '//' + 3 bosluk
     ile '//#([' ayni genislikte oldugu icin devam satirlarindaki ID'ler ilk
     satirdaki ilk ID ile AYNI SUTUNDAN baslar (hizali).
     Acilis, devam satirlari ve '//#)' kapanisi blogun SARDIGI KODUN
     girintisine alinir (ALIGN_WITH_CODE):

        void name_space::func_name(){          void name_space::func_name(){
        // #([HLR_1]                              //#([HLR_1]
           return xxx;               ->           return xxx;
              // #)                               //#)
        }                                      }

       * govde icindeki blok -> blok icindeki ilk kod satirinin girintisi
       * ic ice blok         -> kendi { } kapsamindaki kodun girintisi
       * eski format (fonksiyonun ustundeki blok) -> fonksiyon imzasinin girintisi
       * bos blok            -> ayni kapsamdaki en yakin kod satiri; yoksa korunur
     Label / 'case X:' / 'public:' / cok satirli ifadenin devam satirlari ve
     yorum satirlari hizalamada dikkate alinmaz.
  5) Format hatalarini raporlar (asagidaki liste).
  6) Ic ice (nested) bloklari destekler.  '//#(' / '//#)' eslestirmesi yigin
     (stack) ile ve { } kapsamina bakilarak yapilir.  Duplicate kontrolu SADECE
     blogun kendi listesi icindedir: bir ID hem dis hem ic blokta varsa
     duplicate SAYILMAZ.  Her blok (ic/dis) yukaridaki kurallarla ayri ayri
     duzenlenir.

Rapor seviyeleri:
  HATA     -> elle duzeltilmeli.  SKIP_FILES_WITH_ERRORS = True iken HATA olan
              dosyaya HIC dokunulmaz (sadece raporlanir).
  UYARI    -> bilgi; dosya yine duzeltilir.
  DUZELTME -> script'in yaptigi (DRY_RUN'da: yapacagi) degisiklik.

Kodlar:
  KAPANIS_YOK          HATA   '//#(' icin '//#)' yok (blogun { } kapsami bitti
                              ya da dosya sonuna gelindi)
  KAPANIS_ACILISSIZ    HATA   '//#)' icin '//#(' yok
  KAPANIS_DUPLICATE    HATA   ust uste iki '//#)' (aralarinda sadece bos satir)
                              REMOVE_DUPLICATE_CLOSE = True ise fazlasi silinir
  KAPANIS_KAPSAM       HATA   '//#)' acik bloktan daha ic bir { } kapsaminda;
                              o blogu kapatamaz (fazla kapanis / eksik acilis)
  NOTASYON_TANINMADI   HATA   '//#[', '#(', '/#(', '/*#(' gibi bozuk notasyon
  NOTASYON_SATIR_SONU  HATA   kod satirinin sonundaki yorumda '//#(' / '//#)'
  LISTE_BOZUK          HATA   listede beklenmeyen karakter, ya da ']' eksik ve
                              sonraki satir yarim kalmis bir devam satiri gibi
  LISTE_BOS            UYARI  blokta hic ID yok
  ID_GECERSIZ          UYARI  ID, ID_PREFIXES ile baslamiyor / formati bozuk
  ID_BITISIK           UYARI  iki ID bitisik yazilmis olabilir (virgul eksik)
  ID_LISTE_DISI        UYARI  ']' sonrasinda ID var, listeye dahil edilmedi
  BLOK_YORUMDA         UYARI  notasyon /* ... */ icinde, dikkate alinmadi
  PARANTEZ_DENGESIZ    UYARI  dosyada { } dengesiz; kapsam kontrolu kapatildi,
                              sadece sirali (stack) eslestirme yapildi
  LISTE                DUZELTME  duplicate silindi / siralandi / '[' ']' eklendi /
                                 girinti-hizalama duzeltildi
  KAPANIS              DUZELTME  '// #)' -> '//#)', girinti acilisla esitlendi

Taninan yazimlar (hepsi yukaridaki standart bicime cevrilir):
    //#([A, B]        // #( [A, B ]       ///#([A]
    //#(A, B]         //#([A, B           (eksik '[' / ']')
    //#([A,           //#(A,              (satir basina tek ID, eski format)
    //	B]            //B
  Eski format (blok fonksiyonun USTUNDE, '//#)' '}' sonrasinda) de taninir;
  bloklar oldugu yerde kalir.

Kullanim:
    python hlr_llr_fix.py                   # AYARLAR'daki SOURCE_PATHS, dry-run
    python hlr_llr_fix.py src/ lib/a.cpp    # verilen dizin / dosyalar
    python hlr_llr_fix.py src/ --apply      # degisiklikleri dosyalara yaz
    python hlr_llr_fix.py --file-list files.txt --apply
                                            # sadece listedeki dosyalar (satir basina
                                            # bir yol) - Visual Studio entegrasyonunda
                                            # Directory.Build.targets bunu kullanir

  1) DRY_RUN (varsayilan) ile calistir; ekrani ve REPORT_CSV'yi incele.
  2) HATA'lari elle duzelt (HATA olan dosyalara script dokunmaz).
  3) --apply ile (ya da DRY_RUN = False) tekrar calistir.

Onemli: calistirmadan once projeyi commit et (git).  Tekrar calistirmak
guvenlidir: duzgun bloklara dokunulmaz.
Rapordaki 'satir' dosyanin calistirma ONCESI halidir; 'yeni_satir' duzeltme
SONRASI halidir (degisiklik uygulanmadiysa ayni).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

# Taranacak dizinler / dosyalar.  Komut satirinda yol verilirse onlar kullanilir.
# "" = script'in calistirildigi dizin.
SOURCE_PATHS = [""]

DRY_RUN = True                   # True iken hicbir dosya degismez  (--apply ile False)
MAKE_BACKUP = True               # Yazmadan once .bak kopyasi olustur
REPORT_CSV = "hlr_llr_fix_report.csv"
SHOW_PREVIEW = True              # Dry-run'da duzeltmelerin once / sonra halini bas

SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c")
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx")
ALLOWED_EXTENSIONS = set(SOURCE_EXTENSIONS) | set(HEADER_EXTENSIONS)
EXCLUDE_DIRS: set[str] = set()   # atlanacak dizin adlari (ornek: {"build", "third_party"})
                                 # '.' ile baslayan dizinler (.git ...) zaten atlanir

ENCODINGS = ["utf-8", "cp1254", "latin-1"]   # kaynak dosyalar icin denenecek sira

# --- ID'ler ---
ID_PREFIXES = ("HLR", "LLR")     # gecerli ID onekleri  (HLR_..., LLR_...)
ID_BODY = r"[A-Za-z0-9_]+"       # onek + '_' sonrasi
SORT_IDS = True                  # alfabetik + sayisal sirala
REMOVE_DUPLICATES = True         # ayni blokta tekrar eden ID'yi sil

# --- cikti formati ---
IDS_PER_LINE = 2                 # satir basina kac ID
CONT_INDENT = "   "              # devam satiri: '//' + 3 bosluk  (= '//#([' genisligi
                                 #  -> ID'ler ilk satirdaki ID ile ayni sutunda)
ALIGN_COLUMNS = False            # True: 2., 3. ... sutundaki ID'ler de alt alta hizalanir
ALIGN_WITH_CODE = True           # acilis, devam satirlari ve '//#)' blogun sardigi KODUN
                                 # girintisine alinir (False: acilisin mevcut girintisi)
NORMALIZE_CLOSE = True           # eslesen '//#)' acilisla ayni girintiye, '// #)' -> '//#)'

# --- yapi kontrolu ---
SCOPE_CHECK = True               # '//#(' ile '//#)' ayni { } kapsaminda olmali
SKIP_FILES_WITH_ERRORS = True    # HATA olan dosyada HICBIR duzeltme yapma
REMOVE_DUPLICATE_CLOSE = False   # ust uste iki '//#)' -> fazlasini sil (False: sadece raporla)
MAX_LIST_LINES = 200             # bir ID listesi en fazla kac satir surebilir

# =====================================================================

OPEN_PREFIX = "//#(["
CONT_PREFIX = "//"
CLOSE_MARKER = "//#)"

HATA, UYARI, DUZELTME = "HATA", "UYARI", "DUZELTME"

# Acilis / kapanis isaretleri (bosluklara ve fazla '/' a toleransli)
OPEN_RE = re.compile(r"^(?P<ws>[ \t]*)(?P<mk>/{2,}[ \t]*#[ \t]*\()")
CLOSE_RE = re.compile(r"^(?P<ws>[ \t]*)(?P<mk>/{2,}[ \t]*#[ \t]*\))")
# Notasyona benzeyen ama taninmayan satirlar:  //#[  //#]  #(  /#(  /*#(
SUSPECT_RE = re.compile(r"^[ \t]*(?:/+|/\*+)?[ \t]*#[ \t]*[\[\]()]")
# Kod satirinin sonundaki yorumda notasyon:   foo();  //#)
TRAILING_MARKER_RE = re.compile(r"/{2,}[ \t]*#[ \t]*[()]")

_PFX = "|".join(re.escape(p) for p in ID_PREFIXES)
VALID_ID_RE = re.compile(rf"(?:{_PFX})_{ID_BODY}")
VALID_ID_SEARCH = re.compile(rf"\b(?:{_PFX})_\w")
JOINED_RE = re.compile(rf"(?<=[A-Za-z0-9])(?:{_PFX})_")   # HLR_A_1HLR_A_2
# Koda hizalamada kullanilmayan satirlar:  'public:'  'case X:'  'default:'  'etiket:'
LABEL_RE = re.compile(r"^\s*(?:case\b.*|default\s*|[A-Za-z_]\w*\s*):(?!:)\s*(?://.*)?$")
TOKEN_SPLIT_RE = re.compile(r"[\s,;]+")
TOKEN_OK_RE = re.compile(r"[\w.\-]+")
ID_LIKE_RE = re.compile(r"^(?=.*[\d_])[\w.\-]+$")    # rakam ya da '_' iceren kelime


# --------------------------------------------------------------------
# Veri yapilari
# --------------------------------------------------------------------

@dataclass
class Issue:
    line: int                 # 1-tabanli, dosyanin ORIJINAL hali
    level: str                # HATA / UYARI / DUZELTME
    code: str
    msg: str
    preview: str = ""
    new_line: int = 0
    applied: str = ""


@dataclass
class Block:
    open_line: int            # 0-tabanli '//#(' satiri
    n_lines: int              # ID listesinin satir sayisi ('//#(' dahil)
    depth: int                # acildigi { } seviyesi
    indent: str               # acilis satirinin girintisi
    ids: list[str]
    tail: str                 # ']' sonrasi aciklama (korunur)
    rewritable: bool
    notes: list[str] = field(default_factory=list)
    close_line: int | None = None
    parent: "Block | None" = None


@dataclass
class Change:
    start: int                # 0-tabanli, dahil
    end: int                  # haric
    new: list[str]            # satir sonu OLMADAN yeni satirlar


@dataclass
class FileResult:
    path: Path
    issues: list[Issue]
    blocks: int = 0
    fixed_blocks: int = 0
    removed_dups: int = 0
    changed: bool = False     # dosyada degisiklik var (DRY_RUN'da: olacak)
    written: bool = False
    skipped_for_errors: bool = False
    read_error: str = ""


# --------------------------------------------------------------------
# Dosya okuma / yazma  (linker script'i ile ayni: BOM, kodlama, CRLF korunur)
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


def leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def ws_desc(ws: str) -> str:
    """'   ' -> '3 bosluk',  '\\t  ' -> '1 tab + 2 bosluk',  '' -> 'girintisiz'"""
    tabs, spaces = ws.count("\t"), ws.count(" ")
    parts = ([f"{tabs} tab"] if tabs else []) + ([f"{spaces} bosluk"] if spaces else [])
    return " + ".join(parts) or "girintisiz"


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


# --------------------------------------------------------------------
# ID siralama
# --------------------------------------------------------------------

_NUM_SPLIT = re.compile(r"(\d+)")


def id_sort_key(hid: str):
    """
    '_' / '-' / '.' ile ayrilan her parca dogal siralanir (metin buyuk-kucuk
    harf duyarsiz, sayilar sayi olarak):
        HLR_MODULE_1234 < HLR_MODULE2_1234    ('MODULE' < 'MODULE2')
        HLR_A_2         < HLR_A_10
    """
    key = []
    for part in re.split(r"[_\-.]", hid):
        chunks = _NUM_SPLIT.split(part)
        key.append(tuple(int(c) if k % 2 else c.lower() for k, c in enumerate(chunks)))
    return (tuple(key), hid)


# --------------------------------------------------------------------
# ID listesi okuma
# --------------------------------------------------------------------

def cont_content(line: str) -> str:
    """Devam satirinin '//' sonrasindaki kismi."""
    return split_eol(line)[0].strip().lstrip("/").strip()


def is_cont_candidate(line: str) -> bool:
    """
    Satir bir ID listesinin devami olabilir mi:  '//' ile baslar, notasyon
    degildir ve ']' oncesindeki her kelime ID'ye benzer (rakam ya da '_'
    icerir).  Boylece govdedeki '// sayac' gibi yorumlar listeye katilmaz.
    """
    s = split_eol(line)[0].strip()
    if not s.startswith("//") or OPEN_RE.match(s) or CLOSE_RE.match(s) or SUSPECT_RE.match(s):
        return False
    content = s.lstrip("/").strip()
    if not content:
        return False
    head, sep, _ = content.partition("]")
    toks = [t for t in re.split(r"[\s,;\[]+", head) if t]
    if not toks:
        return bool(sep)                       # sadece ']'  (ve aciklama)
    return all(ID_LIKE_RE.match(t) for t in toks)


def collect_list(lines: list[str], lo: int) -> int:
    """
    lines[lo] ('//#(' satiri) ile baslayan ID listesinin satir sayisi.
    Liste alttaki '//' satirinda su durumlarda devam eder:
      * '[' acilmis, ']' henuz gelmemis
      * ust satir virgulle bitiyor
      * '//#(' satirinda ID yok (liste alt satirda basliyor)
      * alt satirda ']' var
    ']' gorulunce liste biter.
    """
    m = OPEN_RE.match(lines[lo])
    first = split_eol(lines[lo])[0][m.end():]
    opened = "[" in first.split("]", 1)[0]
    closed = "]" in first
    empty_first = not first.strip()
    k = lo
    while not closed and k + 1 < len(lines) and k - lo < MAX_LIST_LINES:
        nxt = lines[k + 1]
        if not is_cont_candidate(nxt):
            break
        prev = (first if k == lo else cont_content(lines[k])).rstrip()
        c = cont_content(nxt)
        if not (opened or prev.endswith(",") or (k == lo and empty_first) or "]" in c):
            break
        k += 1
        if "[" in c.split("]", 1)[0]:
            opened = True
        closed = "]" in c
    return k - lo + 1


def looks_dangling(line: str) -> bool:
    """Liste ']' olmadan bitti; bu satir yarim kalmis bir devam satiri mi."""
    s = split_eol(line)[0].strip()
    if not s.startswith("//") or OPEN_RE.match(s) or CLOSE_RE.match(s):
        return False
    content = s.lstrip("/")
    return "]" in content or bool(VALID_ID_SEARCH.search(content))


def parse_block(lines: list[str], lo: int, depth: int) -> tuple[Block, list[Issue]]:
    issues: list[Issue] = []
    n = collect_list(lines, lo)
    first_text = split_eol(lines[lo])[0]
    m = OPEN_RE.match(first_text)
    indent, marker = m.group("ws"), m.group("mk")
    parts = [first_text[m.end():]] + [cont_content(lines[k]) for k in range(lo + 1, lo + n)]
    text = " ".join(p.strip() for p in parts).strip()

    notes: list[str] = []
    ok = True
    if re.sub(r"[ \t]", "", marker) != "//#(":
        notes.append(f"acilis '{marker.strip()}' -> '//#('")
    elif marker != "//#(":
        notes.append("acilis notasyonundaki bosluklar silindi")

    head, sep, tail = text.partition("]")
    head, tail = head.strip(), tail.strip()
    has_open = head.startswith("[")
    if has_open:
        head = head[1:]
    toks = [t for t in TOKEN_SPLIT_RE.split(head) if t]

    bad = [t for t in toks if not TOKEN_OK_RE.fullmatch(t)]
    if bad:
        ok = False
        issues.append(Issue(lo + 1, HATA, "LISTE_BOZUK",
                            f"ID listesinde beklenmeyen karakter: {', '.join(bad[:5])}"))
    if not sep:
        nxt = lo + n
        if nxt < len(lines) and looks_dangling(lines[nxt]):
            ok = False
            issues.append(Issue(lo + 1, HATA, "LISTE_BOZUK",
                                f"']' yok ve sonraki satir ({nxt + 1}) yarim kalmis bir devam "
                                f"satiri gibi: '{split_eol(lines[nxt])[0].strip()}'"))
        else:
            notes.append("eksik ']' eklendi")
    if toks and not has_open:
        notes.append("eksik '[' eklendi")
    if not toks:
        ok = False
        issues.append(Issue(lo + 1, UYARI, "LISTE_BOS", "Blokta hic ID yok"))

    invalid = [t for t in toks if t not in bad and not VALID_ID_RE.fullmatch(t)]
    if invalid:
        issues.append(Issue(lo + 1, UYARI, "ID_GECERSIZ",
                            f"Gecersiz ID: {', '.join(invalid)} "
                            f"(beklenen: {' / '.join(p + '_...' for p in ID_PREFIXES)})"))
    joined = [t for t in toks if JOINED_RE.search(t)]
    if joined:
        issues.append(Issue(lo + 1, UYARI, "ID_BITISIK",
                            f"ID'ler bitisik yazilmis olabilir (virgul eksik?): {', '.join(joined)}"))
    if tail and VALID_ID_SEARCH.search(tail):
        issues.append(Issue(lo + n, UYARI, "ID_LISTE_DISI",
                            f"']' sonrasinda ID var, listeye dahil EDILMEDI: '{tail}'"))

    blk = Block(open_line=lo, n_lines=n, depth=depth, indent=indent, ids=toks,
                tail=tail, rewritable=ok, notes=notes)
    return blk, issues


# --------------------------------------------------------------------
# Dosya tarayici: notasyonlar + { } kapsami  (yorum / string / char /
# raw string / onislemci farkindali)
# --------------------------------------------------------------------

class Analyzer:
    def __init__(self, lines: list[str], use_scope: bool):
        self.lines = lines
        self.use_scope = use_scope
        self.issues: list[Issue] = []
        self.blocks: list[Block] = []
        self.stack: list[Block] = []
        self.dup_closes: list[int] = []
        self.depth = 0
        self.balanced = True
        self.imbalance_line = 0
        self.imbalance_note = ""
        # tarayici durumu
        self.in_block = False                 # /* ... */
        self.raw_delim: str | None = None     # R"delim( ... )delim"
        self.pp: list[list[bool]] = []        # #if yigini: [dal_secildi, aktif]
        self.in_directive = False             # '\' ile devam eden onislemci satiri
        self.prev_close: int | None = None    # ust uste kapanis tespiti
        self.paren = 0                        # ( ) derinligi (kapsam basina)
        self.paren_stack: list[int] = []
        # satir basi bilgileri (koda hizalama icin)
        self.depth_at: list[int] = []         # satir basindaki { } seviyesi
        self.paren_at: list[int] = []         # satir basindaki ( ) seviyesi
        self.is_code: list[bool] = []         # satir bir KOD satiri mi

    def add(self, line0: int, level: str, code: str, msg: str) -> None:
        self.issues.append(Issue(line0 + 1, level, code, msg))

    # ---------------- ana dongu ----------------
    def run(self) -> "Analyzer":
        list_end = -1
        for i, raw in enumerate(self.lines):
            text = split_eol(raw)[0]
            in_comment = self.in_block or self.raw_delim is not None
            self.depth_at.append(self.depth)
            self.paren_at.append(self.paren)
            self.is_code.append(False)

            if i > list_end and not in_comment:
                if OPEN_RE.match(text):
                    blk, iss = parse_block(self.lines, i, self.depth)
                    blk.parent = self.stack[-1] if self.stack else None
                    self.stack.append(blk)
                    self.blocks.append(blk)
                    self.issues.extend(iss)
                    list_end = i + blk.n_lines - 1
                    self.prev_close = None
                    self.in_directive = False
                    continue
                if CLOSE_RE.match(text):
                    self.close_block(i)
                    self.in_directive = False
                    continue
                if SUSPECT_RE.match(text):
                    self.add(i, HATA, "NOTASYON_TANINMADI",
                             f"Taninmayan notasyon (beklenen '//#([' ya da '//#)'): "
                             f"'{text.strip()}'")
            elif in_comment and (OPEN_RE.match(text) or CLOSE_RE.match(text)):
                self.add(i, UYARI, "BLOK_YORUMDA",
                         f"Notasyon /* ... */ icinde, dikkate alinmadi: '{text.strip()}'")

            if text.strip():
                self.prev_close = None
            self.lex(i, text, in_comment)

        if self.depth != 0 and self.balanced:
            self.balanced = False
            self.imbalance_line = len(self.lines)
            self.imbalance_note = f"dosya sonunda {self.depth} adet '{{' kapanmamis"
        for blk in reversed(self.stack):
            self.add(blk.open_line, HATA, "KAPANIS_YOK",
                     "'//#(' icin '//#)' yok (dosya sonuna kadar kapanmadi)")
        self.stack = []
        return self

    # ---------------- kapanis ----------------
    def close_block(self, i: int) -> None:
        top = self.stack[-1] if self.stack else None
        if top is not None and (not self.use_scope or top.depth == self.depth):
            self.stack.pop()
            top.close_line = i
        elif self.prev_close is not None:
            self.dup_closes.append(i)
            self.add(i, HATA, "KAPANIS_DUPLICATE",
                     f"Duplicate kapanis: ust uste iki '//#)' (satir {self.prev_close + 1} "
                     f"ve bu satir) - ikisinden biri fazla")
        elif top is not None:
            self.add(i, HATA, "KAPANIS_KAPSAM",
                     f"Bu '//#)' eslesmiyor: acik blok (satir {top.open_line + 1}) daha dis bir "
                     f"{{ }} kapsaminda acildi - fazla kapanis ya da eksik '//#(' olabilir")
        else:
            self.add(i, HATA, "KAPANIS_ACILISSIZ",
                     "Acilisi olmayan kapanis: bu '//#)' icin '//#(' yok")
        self.prev_close = i

    # ---------------- onislemci ----------------
    def directive(self, stripped: str) -> None:
        """
        #if / #ifdef / #ifndef ... sadece ILK aktif dalin { } leri sayilir
        (#if 0 dali atlanir), #elif / #else dallari sayilmaz.  Boylece

            #ifdef X
            void f(int a) {
            #else
            void f() {
            #endif

        tek '{' sayilir.
        """
        m = re.match(r"#\s*(\w+)(.*)", stripped)
        if not m:
            return
        name = m.group(1)
        rest = m.group(2).split("//", 1)[0].split("/*", 1)[0].strip()
        if name in ("if", "ifdef", "ifndef"):
            on = not (name == "if" and rest == "0")
            self.pp.append([on, on])
        elif name in ("elif", "else") and self.pp:
            if self.pp[-1][0]:
                self.pp[-1][1] = False
            else:
                on = not (name == "elif" and rest == "0")
                self.pp[-1] = [on, on]
        elif name == "endif" and self.pp:
            self.pp.pop()

    # ---------------- satir tarayici ----------------
    def lex(self, i: int, text: str, in_comment: bool) -> None:
        stripped = text.lstrip()
        is_dir = self.in_directive or (not in_comment and stripped.startswith("#"))
        if is_dir and not self.in_directive:
            self.directive(stripped)
        self.in_directive = is_dir and text.rstrip().endswith("\\")
        counting = not is_dir and all(active for _, active in self.pp)
        self.is_code[i] = (not in_comment and not is_dir and bool(stripped)
                           and not stripped.startswith(("//", "/*", "}"))
                           and not LABEL_RE.match(text))

        j, n = 0, len(text)
        in_str: str | None = None
        while j < n:
            c = text[j]
            nxt = text[j + 1] if j + 1 < n else ""

            if self.in_block:
                e = text.find("*/", j)
                if e < 0:
                    return
                self.in_block = False
                j = e + 2
                continue
            if self.raw_delim is not None:
                e = text.find(")" + self.raw_delim + '"', j)
                if e < 0:
                    return
                j = e + len(self.raw_delim) + 2
                self.raw_delim = None
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
                if text[:j].strip() and TRAILING_MARKER_RE.match(text, j):
                    self.add(i, HATA, "NOTASYON_SATIR_SONU",
                             f"Notasyon kod satirinin sonunda; kendi satirinda olmali: "
                             f"'{text.strip()}'")
                return
            if c == "/" and nxt == "*":
                e = text.find("*/", j + 2)
                if TRAILING_MARKER_RE.search(text[j + 2:e if e >= 0 else n]):
                    self.add(i, UYARI, "BLOK_YORUMDA",
                             f"Notasyon /* ... */ icinde, dikkate alinmadi: '{text.strip()}'")
                self.in_block = True
                j += 2
                continue
            if c == '"':
                if j > 0 and text[j - 1] == "R":
                    k = text.find("(", j + 1)
                    if k != -1:
                        self.raw_delim = text[j + 1:k]
                        j = k + 1
                        continue
                in_str = '"'
                j += 1
                continue
            if c == "'":
                if not self.digit_separator(text, j):
                    in_str = "'"
                j += 1
                continue

            if counting:
                if c == "(":
                    self.paren += 1
                elif c == ")":
                    self.paren = max(0, self.paren - 1)
                elif c == "{":
                    self.paren_stack.append(self.paren)
                    self.paren = 0
                    self.depth += 1
                elif c == "}":
                    self.paren = self.paren_stack.pop() if self.paren_stack else 0
                    self.depth -= 1
                    if self.depth < 0:
                        if self.balanced:
                            self.imbalance_line = i + 1
                            self.imbalance_note = f"eslesmeyen '}}', satir {i + 1}"
                        self.balanced = False
                        self.depth = 0
                    self.scope_end(i)
            j += 1

    @staticmethod
    def digit_separator(text: str, j: int) -> bool:
        """1'000'000 / 0xFF'FF  ->  ' rakam ayiricidir, char literal degil."""
        k = j - 1
        while k >= 0 and (text[k].isalnum() or text[k] in "_."):
            k -= 1
        tok = text[k + 1:j]
        return bool(tok) and tok[0].isdigit()

    # ---------------- koda hizalama ----------------
    def _stmt_line(self, k: int, depth: int) -> bool:
        """k. satir, bu { } seviyesinde baslayan bir kod satiri mi
        (devam satiri / label / yorum / onislemci degil)."""
        return self.is_code[k] and self.depth_at[k] == depth and self.paren_at[k] == 0

    def target_indent(self, blk: Block) -> str:
        """
        Blogun hizalanacagi girinti = blogun SARDIGI kodun girintisi:
          1) blok icindeki ilk kod satiri  (govde icindeki blok -> 'return x;'
             satiri; eski formatta fonksiyonun ustundeki blok -> imza satiri)
          2) blok bossa: ayni { } kapsamindaki en yakin kod satiri (once ust,
             sonra alt)
          3) o da yoksa mevcut girinti korunur
        """
        lines, d = self.lines, blk.depth
        hi = blk.close_line if blk.close_line is not None else len(lines)
        for k in range(blk.open_line + blk.n_lines, hi):
            if self.depth_at[k] < d:
                break
            if self._stmt_line(k, d):
                return leading_ws(lines[k])
        for k in range(blk.open_line - 1, -1, -1):
            if self.depth_at[k] < d:
                break
            if self._stmt_line(k, d):
                return leading_ws(lines[k])
        for k in range(hi + 1, len(lines)):
            if self.depth_at[k] < d:
                break
            if self._stmt_line(k, d):
                return leading_ws(lines[k])
        return blk.indent

    def scope_end(self, i: int) -> None:
        """'}' bir kapsami kapatti: o kapsamda acilip kapanmamis bloklar hatali."""
        if not self.use_scope:
            return
        while self.stack and self.stack[-1].depth > self.depth:
            blk = self.stack.pop()
            self.add(blk.open_line, HATA, "KAPANIS_YOK",
                     f"'//#(' icin '//#)' yok: blogun {{ }} kapsami bitti "
                     f"('}}' satir {i + 1})")


# --------------------------------------------------------------------
# Yeni blok metni
# --------------------------------------------------------------------

def build_list_lines(ids: list[str], indent: str, tail: str) -> list[str]:
    """
    IDS_PER_LINE = 2 ve 5 ID icin (satir sonu olmadan):
        //#([HLR_1, HLR_2,
        //   HLR_3, HLR_4,
        //   HLR_5]
    """
    per = max(1, int(IDS_PER_LINE))
    chunks = [ids[k:k + per] for k in range(0, len(ids), per)]
    rows: list[list[str]] = []
    for ci, ch in enumerate(chunks):
        last_chunk = ci == len(chunks) - 1
        rows.append([hid + ("" if (last_chunk and k == len(ch) - 1) else ",")
                     for k, hid in enumerate(ch)])

    if ALIGN_COLUMNS:
        widths: dict[int, int] = {}
        for row in rows:
            for k, p in enumerate(row[:-1]):
                widths[k] = max(widths.get(k, 0), len(p))
        rows = [[p.ljust(widths[k]) if k < len(row) - 1 else p for k, p in enumerate(row)]
                for row in rows]

    out: list[str] = []
    for ci, row in enumerate(rows):
        body = " ".join(row)
        if ci == len(rows) - 1:
            body += "]"
            if tail:
                body += " " + tail
        prefix = OPEN_PREFIX if ci == 0 else CONT_PREFIX + CONT_INDENT
        out.append(indent + prefix + body)
    return out


def dedupe(ids: list[str]) -> tuple[list[str], dict[str, int]]:
    seen: dict[str, int] = {}
    for x in ids:
        seen[x] = seen.get(x, 0) + 1
    return list(seen), {k: v for k, v in seen.items() if v > 1}


def diff_preview(old: list[str], new: list[str]) -> str:
    return "\n".join(["- " + ln for ln in old] + ["+ " + ln for ln in new])


# --------------------------------------------------------------------
# Dosya isleme
# --------------------------------------------------------------------

def plan_changes(lines: list[str], an: Analyzer, res: FileResult) -> list[Change]:
    changes: list[Change] = []
    issues: list[Issue] = []

    # her blogun hedef girintisi: sardigi kodun girintisi (bozuk blokta mevcut hali)
    target: dict[int, str] = {}
    for blk in an.blocks:
        target[blk.open_line] = (an.target_indent(blk) if (ALIGN_WITH_CODE and blk.rewritable)
                                 else blk.indent)

    for blk in an.blocks:
        if not blk.rewritable:
            continue
        lo, n = blk.open_line, blk.n_lines
        ind = target[lo]
        notes = list(blk.notes)
        if ind != blk.indent:
            notes.append(f"girinti koda hizalandi ({ws_desc(blk.indent)} -> {ws_desc(ind)})")
        ids = list(blk.ids)
        if REMOVE_DUPLICATES:
            ids, dups = dedupe(ids)
            if dups:
                res.removed_dups += sum(v - 1 for v in dups.values())
                notes.insert(0, "duplicate silindi: " + ", ".join(
                    f"{k} ({v} kez)" for k, v in dups.items()))
        if SORT_IDS:
            srt = sorted(ids, key=id_sort_key)
            if srt != ids:
                notes.append("siralandi")
            ids = srt
        new = build_list_lines(ids, ind, blk.tail)
        old = [split_eol(ln)[0] for ln in lines[lo:lo + n]]
        if new != old:
            if not notes:
                notes.append("girinti / hizalama / satir basina ID duzeltildi")
            changes.append(Change(lo, lo + n, new))
            issues.append(Issue(lo + 1, DUZELTME, "LISTE", "; ".join(notes),
                                preview=diff_preview(old, new)))
            res.fixed_blocks += 1

    if NORMALIZE_CLOSE:
        for blk in an.blocks:
            if blk.close_line is None:
                continue
            k = blk.close_line
            text = split_eol(lines[k])[0]
            m = CLOSE_RE.match(text)
            rest = text[m.end():].strip()
            ind = target[blk.open_line]
            want = ind + CLOSE_MARKER + (" " + rest if rest else "")
            if want != text:
                what = []
                if m.group("mk") != CLOSE_MARKER:
                    what.append(f"'{m.group('mk').strip()}' -> '{CLOSE_MARKER}'")
                if m.group("ws") != ind:
                    what.append(f"girinti acilisla (satir {blk.open_line + 1}) ve koda "
                                f"hizalandi ({ws_desc(m.group('ws'))} -> {ws_desc(ind)})")
                if not what:
                    what.append("sondaki bosluklar silindi")
                changes.append(Change(k, k + 1, [want]))
                issues.append(Issue(k + 1, DUZELTME, "KAPANIS", "; ".join(what),
                                    preview=diff_preview([text], [want])))

    if REMOVE_DUPLICATE_CLOSE and an.dup_closes:
        dup_set = set(an.dup_closes)
        for k in an.dup_closes:
            changes.append(Change(k, k + 1, []))
        for iss in an.issues:
            if iss.code == "KAPANIS_DUPLICATE" and iss.line - 1 in dup_set:
                iss.level = DUZELTME
                iss.msg = iss.msg.replace("- ikisinden biri fazla", "-> fazla olan silindi")
                iss.preview = diff_preview([split_eol(lines[iss.line - 1])[0]], [])

    res.issues.extend(issues)
    changes.sort(key=lambda c: c.start)
    return changes


def apply_changes(lines: list[str], changes: list[Change]) -> list[str]:
    out = list(lines)
    default_eol = detect_eol(lines)
    for ch in sorted(changes, key=lambda c: c.start, reverse=True):
        old = out[ch.start:ch.end]
        if not ch.new:
            out[ch.start:ch.end] = []
            continue
        eol_first = split_eol(old[0])[1] or default_eol
        eol_last = split_eol(old[-1])[1]
        new = [t + eol_first for t in ch.new[:-1]] + [ch.new[-1] + eol_last]
        out[ch.start:ch.end] = new
    return out


def map_line(x: int, changes: list[Change]) -> int:
    """Orijinal 0-tabanli satir -> degisiklik sonrasi 0-tabanli satir."""
    shift = 0
    for ch in changes:                      # start'a gore sirali
        if ch.end <= x:
            shift += len(ch.new) - (ch.end - ch.start)
        elif ch.start <= x < ch.end:
            return ch.start + shift + min(x - ch.start, max(len(ch.new) - 1, 0))
        else:
            break
    return x + shift


def process_file(path: Path) -> FileResult:
    res = FileResult(path=path, issues=[])
    try:
        lines, enc, had_bom = read_lines(path)
    except Exception as e:                  # noqa: BLE001
        res.read_error = str(e)
        res.issues.append(Issue(0, HATA, "DOSYA_OKUNAMADI", str(e)))
        return res

    an = Analyzer(lines, use_scope=SCOPE_CHECK).run()
    if SCOPE_CHECK and not an.balanced:
        note = an.imbalance_note
        line = an.imbalance_line
        an = Analyzer(lines, use_scope=False).run()
        an.issues.insert(0, Issue(max(line, 1), UYARI, "PARANTEZ_DENGESIZ",
                                  f"{{ }} dengesiz ({note}; makro / #if olabilir) - kapsam "
                                  f"kontrolu bu dosyada kapatildi, '//#(' / '//#)' sadece "
                                  f"sirayla eslestirildi"))
    res.issues.extend(an.issues)
    res.blocks = len(an.blocks)

    changes = plan_changes(lines, an, res)
    has_error = any(i.level == HATA for i in res.issues)
    blocked = has_error and SKIP_FILES_WITH_ERRORS
    res.changed = bool(changes) and not blocked
    res.skipped_for_errors = bool(changes) and blocked

    for iss in res.issues:
        iss.new_line = (map_line(iss.line - 1, changes) + 1) if (res.changed and iss.line) \
            else iss.line
        if iss.level == DUZELTME:
            iss.applied = ("HAYIR (dosyada HATA var)" if blocked
                           else "HAYIR (dry-run)" if DRY_RUN else "EVET")

    if res.changed and not DRY_RUN:
        write_lines(path, apply_changes(lines, changes), enc, had_bom)
        res.written = True
    return res


# --------------------------------------------------------------------
# Dosya listesi, rapor, ana akis
# --------------------------------------------------------------------

def read_file_list(list_path: str) -> list[str]:
    """
    --file-list dosyasi: her satirda bir dosya yolu (MSBuild'in yazdigi liste).
    Bos satirlar ve '#' ile baslayan satirlar atlanir, tirnaklar temizlenir.
    Goreli yollar liste dosyasinin klasorune gore cozulur.
    """
    p = Path(list_path)
    data = p.read_bytes()
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for ln in text.splitlines():
        s = ln.strip().strip('"').strip()
        if not s or s.startswith("#"):
            continue
        f = Path(s)
        out.append(str(f if f.is_absolute() else (p.parent / f)))
    return out


def iter_files(paths: list[str], listed: list[str] | None = None):
    """
    paths : dizinler (alt klasorlerle) ve dosyalar
    listed: --file-list ile gelen dosyalar.  Bunlarda desteklenmeyen uzanti
            (.rc, .inl ...) ve bulunamayan dosya SESSIZCE atlanir.
    """
    seen: set[Path] = set()
    for raw in listed or []:
        c = Path(raw)
        if c.suffix.lower() in ALLOWED_EXTENSIONS and c.is_file():
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                yield c
    for raw in paths:
        p = Path(raw) if raw else Path(".")
        if p.is_file():
            cands = [p]
        elif p.is_dir():
            cands = []
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames
                                     if not d.startswith(".") and d not in EXCLUDE_DIRS)
                for fn in sorted(filenames):
                    if Path(fn).suffix.lower() in ALLOWED_EXTENSIONS:
                        cands.append(Path(dirpath) / fn)
        else:
            print(f"UYARI: yol bulunamadi: {p}")
            continue
        for c in cands:
            if c.suffix.lower() not in ALLOWED_EXTENSIONS:
                print(f"UYARI: desteklenmeyen uzanti, atlandi: {c}")
                continue
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                yield c


def print_file(res: FileResult) -> None:
    shown = [i for i in res.issues if i.level != DUZELTME or SHOW_PREVIEW or not DRY_RUN]
    if not shown and not res.skipped_for_errors:
        return
    print(f"--- {res.path} ---")
    order = {HATA: 0, UYARI: 1, DUZELTME: 2}
    for iss in sorted(shown, key=lambda x: (x.line, order[x.level])):
        print(f"  [{iss.level:<8}] satir {iss.line:<5} {iss.code}: {iss.msg}")
        if iss.preview and DRY_RUN and SHOW_PREVIEW:
            for ln in iss.preview.splitlines():
                print("        " + ln)
    if res.skipped_for_errors:
        print("  !! Dosyada HATA var -> duzeltmeler UYGULANMADI (SKIP_FILES_WITH_ERRORS). "
              "Once HATA'lari duzelt.")
    print()


def write_report(results: list[FileResult]) -> None:
    with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["dosya", "satir", "yeni_satir", "seviye", "kod", "mesaj", "uygulandi"])
        for res in results:
            for iss in sorted(res.issues, key=lambda x: x.line):
                w.writerow([str(res.path), iss.line or "", iss.new_line or "", iss.level,
                            iss.code, iss.msg, iss.applied])


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, MAKE_BACKUP, REPORT_CSV
    ap = argparse.ArgumentParser(description="HLR / LLR link bloklarini duzeltir ve denetler.")
    ap.add_argument("paths", nargs="*", help="dizin / dosya (bos: AYARLAR'daki SOURCE_PATHS)")
    ap.add_argument("--apply", action="store_true", help="degisiklikleri dosyalara yaz")
    ap.add_argument("--no-backup", action="store_true", help=".bak kopyasi olusturma")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    ap.add_argument("--file-list", action="append", default=[], metavar="DOSYA",
                    help="islenecek dosyalarin listesi (satir basina bir yol); "
                         "Visual Studio / MSBuild entegrasyonu icin")
    args = ap.parse_args(argv)
    if args.apply:
        DRY_RUN = False
    if args.no_backup:
        MAKE_BACKUP = False
    if args.report:
        REPORT_CSV = args.report

    listed = [f for lp in args.file_list for f in read_file_list(lp)]
    paths = args.paths or ([] if args.file_list else SOURCE_PATHS)
    results = [process_file(p) for p in iter_files(paths, listed)]
    for res in results:
        print_file(res)

    all_issues = [i for r in results for i in r.issues]
    n_err = sum(1 for i in all_issues if i.level == HATA)
    n_warn = sum(1 for i in all_issues if i.level == UYARI)
    print("=" * 76)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  dosya: {len(results)} tarandi, "
          f"{sum(r.changed for r in results)} {'degisecek' if DRY_RUN else 'degisti'}, "
          f"{sum(r.skipped_for_errors for r in results)} HATA yuzunden atlandi")
    print(f"blok: {sum(r.blocks for r in results)}  |  duzeltilen liste: "
          f"{sum(r.fixed_blocks for r in results)}  |  silinen duplicate ID: "
          f"{sum(r.removed_dups for r in results)}  |  HATA: {n_err}  UYARI: {n_warn}")
    print("=" * 76)

    write_report(results)
    print(f"Rapor: {REPORT_CSV}")
    if DRY_RUN and any(r.changed for r in results):
        print("Degisiklikleri yazmak icin:  --apply  (ya da DRY_RUN = False)")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
