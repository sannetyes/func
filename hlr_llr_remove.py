#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hlr_llr_remove.py  -  Requirement link notasyonlarini (HLR / LLR) kaynak koddan SILER.
Harici bagimlilik YOKTUR (sadece stdlib, Python 3.7+).

    void func() {                          void func() {
    //#([HLR_MODULE_1, HLR_MODULE_2,          return x;
    //   HLR_MODULE_3]               ->    }
        return x;
    //#)
    }

NE SILINIR  (sadece YORUMLAR - kod asla silinmez):
  * '//#(' acilis yorumu + ID listesinin devam satirlari   //   HLR_..., ...]
  * '//#)' kapanis yorumu
  * sadece ID'lerden olusan yorumlar                       // [HLR_1, LLR_2]
  * bozuk / eski yazimlar        //#[HLR_1]   // //#(   //#  HLR_3]   //# HLR_4
  * kod satirinin sonundaki notasyon      x = 1;  //#)          ->  x = 1;
  * baska yorumun sonuna eklenmis         return x; // tamam //#)  ->  return x; // tamam
  * /* ... */ ile yoruma alinmis kod icindeki notasyon satirlari
  * tamamen notasyon olan blok yorum      /*#([HLR_1]*/
Satirda notasyondan baska bir sey kalmiyorsa satir tamamen silinir.  Satirda kod
varsa satir KALIR, sadece yorum kismi kesilir.

GUVENLIK:
  * Dosya C/C++ kurallariyla taranir: string, char, raw string R"x(...)x",
    /* */, '\\' ile satir birlestirme, 1'000 gibi rakam ayiraclari.
    String icindeki metne dokunulmaz.
  * Her dosya yazilmadan once DOGRULANIR: yorumlar cikarildiginda kalan kod
    (token dizisi + mantiksal satir yapisi) eski ve yeni dosyada birebir ayni
    olmalidir.  Degilse dosya YAZILMAZ ve HATA olarak raporlanir.
  * Dokunulmayan satirlar byte byte ayni kalir (kodlama, BOM, CRLF korunur).
  * Satir sonu olarak sadece \\r\\n, \\n, \\r kabul edilir (form feed, \\x85 vb.
    satir bolmez).

KALAN RAPORU: islemden sonra hala HLR/LLR ya da notasyon geciyorsa (string
icinde, kodda, aciklama yorumunda, uzanti listesi disindaki dosyalarda) hepsi
'KALAN' olarak listelenir.  Hicbir sey sessizce geride kalmaz.

Kullanim:
    python hlr_llr_remove.py src/                    # DRY-RUN: neyin silinecegini goster
    python hlr_llr_remove.py src/ --apply            # sil (.bak yedekli)
    python hlr_llr_remove.py src/ ../externals --apply --exclude "third_party"
    python hlr_llr_remove.py --file-list files.txt --apply
    python hlr_llr_remove.py src/ --ext .inc         # ek uzanti isle
    python hlr_llr_remove.py src/ --verify-git       # git HEAD ile karsilastir:
                                                     # sadece yorumlar mi degismis?

Onemli: calistirmadan once commit et (git).  Geri almak icin:  git checkout -- .
Tekrar calistirmak guvenlidir (silinecek bir sey kalmadiysa dosyaya dokunulmaz).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

SOURCE_PATHS = [""]               # "" = calisilan dizin; komut satiri yollari bunu ezer
DRY_RUN = True                    # True: hicbir dosya degismez  (--apply ile False)
MAKE_BACKUP = True                # yazmadan once .bak kopyasi (var olan .bak EZILMEZ)
REPORT_CSV = "hlr_llr_remove_report.csv"   # "" = rapor olusturma (--no-report)
SHOW_PREVIEW = True               # silinen / kesilen satirlari da bas (--quiet: kapat)

STRIP_TRAILING = True             # kod satiri sonundaki notasyonu kes (--keep-trailing: kapat)
CLEAN_BLOCK_COMMENTS = True       # /* */ icindeki notasyon satirlarini sil (--no-block-comments)
REMOVE_ID_ONLY_COMMENTS = True    # sadece ID'den olusan yorumlari sil (--keep-id-comments)
SCAN_OTHER_FILES = True           # uzanti disi dosyalarda HLR/LLR ara (sadece rapor)

SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c", ".c++", ".cppm", ".ixx", ".cu")
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx", ".h++", ".inl", ".ipp", ".tpp",
                     ".tcc", ".txx", ".cuh")
ALLOWED_EXTENSIONS = set(SOURCE_EXTENSIONS) | set(HEADER_EXTENSIONS)
EXCLUDE_DIRS: set[str] = set()    # "third_party" (ad) ya da "middleware/legacy" (yol)
SKIP_DIR_NAMES = {".git", ".svn", ".hg", ".vs", ".vscode", ".idea", "__pycache__"}

MAX_LIST_LINES = 200
OTHER_FILE_MAX_BYTES = 5 * 1024 * 1024

# =====================================================================

SILINDI, KESILDI, UYARI, HATA, KALAN = "SILINDI", "KESILDI", "UYARI", "HATA", "KALAN"
WS = " \t\f\v"
BOM = b"\xef\xbb\xbf"

EOL_RE = re.compile(r"\r\n|\r|\n")
SPLICE_RE = re.compile(r"\\[ \t]*(?:\r\n|\r|\n)")
SPLICE_TAIL_RE = re.compile(r"\\[ \t]*$")
WS_SPLIT_RE = re.compile(r"[ \t\f\v]+")
NEXT_RE = re.compile(
    r"//|/\*|[\"']"
    r"|(?<![A-Za-z0-9_$])[A-Za-z_$][A-Za-z0-9_$]*(?=[\"'])"            # u8"..", R"(..)"
    r"|(?<![A-Za-z0-9_$])\.?[0-9](?:[eEpP][+-]|'(?=[A-Za-z0-9_])|[A-Za-z0-9_$.])*")  # 1'000
STR_RE = {'"': re.compile(r'"(?:[^"\\\r\n]|\\(?:\r\n|[\s\S]))*"'),
          "'": re.compile(r"'(?:[^'\\\r\n]|\\(?:\r\n|[\s\S]))*'")}
RAW_OPEN_RE = re.compile(r'([^ ()\\\t\v\f\r\n"]{0,16})\(')
RAW_PREFIXES = {"R", "LR", "uR", "UR", "u8R"}

MARK_RE = re.compile(r"#[ \t]*([()\[\]])")
NESTED_RE = re.compile(r"/{2,}[ \t]*#[ \t]*([()\[\]])")
ID_SPLIT_RE = re.compile(r"[ \t\f\v\r\n,;\[\]()]+")
LISTISH_SPLIT_RE = re.compile(r"[ \t\f\v\r\n,;\[\]()*/]+")
HLR_TOKEN_RE = re.compile(r"(?:HLR|LLR)(?![A-Za-z])[A-Za-z0-9_.\-:/#]*$", re.I)
ID_LIKE_RE = re.compile(r"(?=.*[0-9_])[A-Za-z0-9_.\-:]+$")
HLR_ANY_RE = re.compile(r"(?<![A-Za-z0-9])(?:HLR|LLR)(?![A-Za-z])", re.I)
MARK_ANY_RE = re.compile(r"/[/*][ \t/!<*]*#[ \t]*[()\[\]]")
HLR_ANY_BYTES_RE = re.compile(rb"(?<![A-Za-z0-9])(?:HLR|LLR)(?![A-Za-z])|//[ \t]*#[ \t]*[()]",
                              re.I)
LABEL = {"(": "ACILIS", ")": "KAPANIS", "[": "BOZUK", "]": "BOZUK"}


@dataclass
class Item:
    line: int                 # 1-tabanli
    level: str                # SILINDI / KESILDI / UYARI / HATA / KALAN
    kind: str
    text: str
    note: str = ""


@dataclass
class FileResult:
    path: Path
    items: list[Item] = field(default_factory=list)
    removed: int = 0          # tamamen silinen satir
    blanked: int = 0          # bos birakilan satir ('\' sonrasi)
    cut: int = 0              # yorumu kesilen (kod iceren) satir
    opens: int = 0
    closes: int = 0
    ids: int = 0
    kalan: int = 0
    verified: bool = False
    written: bool = False
    skipped: bool = False
    error: str = ""
    enc: str = "utf-8"

    @property
    def changed(self) -> bool:
        return bool(self.removed or self.blanked or self.cut) and not self.skipped


# --------------------------------------------------------------------
# C / C++ lexer:  yorum ve string araliklarini bulur
# --------------------------------------------------------------------

def split_lines(text: str) -> list[tuple[int, int, int]]:
    """[(baslangic, icerik_sonu, satir_sonu_dahil_son)]  - sadece \\r\\n, \\n, \\r"""
    out, pos = [], 0
    for m in EOL_RE.finditer(text):
        out.append((pos, m.start(), m.end()))
        pos = m.end()
    if pos < len(text):
        out.append((pos, len(text), len(text)))
    return out


def _line_comment_end(text: str, pos: int) -> tuple[int, bool]:
    spliced = False
    while True:
        m = EOL_RE.search(text, pos)
        if not m:
            return len(text), spliced
        j = m.start()
        while j > pos and text[j - 1] in " \t":
            j -= 1
        if j > pos and text[j - 1] == "\\":          # '\' + satir sonu: yorum devam eder
            spliced = True
            pos = m.end()
            continue
        return m.start(), spliced


def _string_end(text: str, q: int) -> int:
    m = STR_RE[text[q]].match(text, q)
    if m:
        return m.end()
    e = EOL_RE.search(text, q)                       # kapanmamis: satir sonuna kadar (GCC)
    return len(text) if not e else e.start()


def lex(text: str):
    """comments: [(bas, son, 'line'|'block', flag)]   flag: line->'\\' ile devam, block->kapanmamis
       strings : [(bas, son)]"""
    comments, strings = [], []
    n, pos = len(text), 0
    search = NEXT_RE.search
    while True:
        m = search(text, pos)
        if not m:
            break
        s, tok = m.start(), m.group()
        if tok == "//":
            end, spliced = _line_comment_end(text, m.end())
            comments.append((s, end, "line", spliced))
            pos = end
        elif tok == "/*":
            e = text.find("*/", m.end())
            end = n if e < 0 else e + 2
            comments.append((s, end, "block", e < 0))
            pos = end
        elif tok in ('"', "'"):
            end = _string_end(text, s)
            strings.append((s, end))
            pos = end
        elif tok[0].isdigit() or tok[0] == ".":
            pos = m.end()
        else:                                        # tanimlayici + tirnak (onek?)
            q = m.end()
            if tok in RAW_PREFIXES and text[q] == '"':
                rm = RAW_OPEN_RE.match(text, q + 1)
                if rm:
                    close = ")" + rm.group(1) + '"'
                    e = text.find(close, rm.end())
                    end = n if e < 0 else e + len(close)
                    strings.append((s, end))
                    pos = end
                    continue
            end = _string_end(text, q)
            strings.append((s if tok in ("u8", "u", "U", "L") else q, end))
            pos = end
    return comments, strings


def fingerprint(text: str, lexed=None) -> list[tuple[str, ...]]:
    """Yorumlar atildiktan sonra kalan KOD: mantiksal satir basina token listesi.
    Bos satirlar sayilmaz.  Eski / yeni dosyada ayni olmali."""
    comments, strings = lexed if lexed is not None else lex(text)
    events = sorted([(c[0], c[1], False) for c in comments] + [(s, e, True) for s, e in strings])
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


# --------------------------------------------------------------------
# Notasyon siniflandirma
# --------------------------------------------------------------------

def id_only(s: str) -> bool:
    toks = [t for t in ID_SPLIT_RE.split(s.strip(WS + "/*")) if t]
    return bool(toks) and all(HLR_TOKEN_RE.match(t) for t in toks)


class ListState:
    """'//#([HLR_1, HLR_2,' sonrasi devam satirlarini takip eder."""

    def __init__(self, rest: str) -> None:
        self.bracket = self.closed = self.expect = self.comma = False
        self.feed(rest)

    def feed(self, s: str) -> None:
        head, sep, _ = s.partition("]")
        if "[" in head:
            self.bracket = True
        if sep:
            self.closed = True
        t = s.strip(WS + "/*")
        self.comma = t.endswith(",")
        self.expect = not self.closed and (self.bracket or not t or self.comma)

    def accepts(self, body: str) -> str:
        head, sep, _ = body.partition("]")
        toks = [t for t in ID_SPLIT_RE.split(head) if t]
        if not toks:
            if sep or head.strip(WS):                # sadece  ]  ,  [
                return "yes"
            return "maybe" if self.bracket else "stop"
        idish = all(ID_LIKE_RE.match(t) or HLR_TOKEN_RE.match(t) for t in toks)
        has_id = any(HLR_TOKEN_RE.match(t) for t in toks)
        if self.bracket:
            return "yes" if (idish or has_id) else "stop"
        if self.comma:
            return "yes" if idish else "stop"
        return "yes" if idish and (has_id or "[" in head) else "stop"


def classify(text: str, c: "Cmt"):
    """(etiket, yorum_basindan_kesme_ofseti, kalan_metin) ya da None"""
    if c.kind == "block":
        body = text[c.start + 2:c.end - 2]
        norm = body.lstrip(WS + "*/!<")              # satir atlamaz: '/*' ile ayni satirda olmali
        m = MARK_RE.match(norm)
        if m:
            ch = m.group(1)
            rest = norm[m.end():] if ch in "()" else norm[m.start(1):]
            toks = [t for t in LISTISH_SPLIT_RE.split(rest) if t]
            # blok yorumun TAMAMI notasyon olmali: sadece HLR/LLR ID'leri (aciklama metni yok)
            return (LABEL[ch], 0, rest) if all(HLR_TOKEN_RE.match(t) for t in toks) else None
        if REMOVE_ID_ONLY_COMMENTS and id_only(body):
            return ("ID", 0, "")
        return None
    body = text[c.start + 2:c.end]
    norm = body.lstrip(WS + "/!<")
    m = MARK_RE.match(norm)
    if m:
        ch = m.group(1)
        return (LABEL[ch], 0, norm[m.end():] if ch in "()" else norm[m.start(1):])
    if norm.startswith("#") and id_only(norm[1:]):
        return ("BOZUK", 0, norm[1:])
    if REMOVE_ID_ONLY_COMMENTS and id_only(norm):
        return ("ID", 0, "")
    m = NESTED_RE.search(body)
    if m:
        ch = m.group(1)
        return (LABEL[ch], 2 + m.start(), body[m.end():] if ch in "()" else body[m.start(1):])
    return None


# --------------------------------------------------------------------
# Planlama: hangi araliklar silinecek
# --------------------------------------------------------------------

def _join(a: str, b: str) -> str:
    return f"{a}; {b}" if a else b


class Cmt:
    __slots__ = ("start", "end", "kind", "line", "last", "alone", "flag")

    def __init__(self, start, end, kind, line, last, alone, flag):
        self.start, self.end, self.kind = start, end, kind
        self.line, self.last, self.alone, self.flag = line, last, alone, flag


class Removal:
    __slots__ = ("start", "end", "line", "last", "label", "note", "ids")

    def __init__(self, start, end, line, last, label, note, ids):
        self.start, self.end, self.line, self.last = start, end, line, last
        self.label, self.note, self.ids = label, note, ids


class Planner:
    def __init__(self, text: str, res: FileResult) -> None:
        self.text, self.res = text, res
        self.lines = split_lines(text)
        self.starts = [ln[0] for ln in self.lines]
        self.lexed = lex(text)
        self.real = [(c[0], c[1]) for c in self.lexed[0]]
        self.real_starts = [r[0] for r in self.real]
        self.cm: list[Cmt] = []
        self.by_line: dict[int, list[int]] = {}
        self.used: set[int] = set()
        self.removals: list[Removal] = []
        self.issue_lines: set[int] = set()
        self._build_comments()

    # ---- yardimcilar
    def line_of(self, pos: int) -> int:
        return bisect.bisect_right(self.starts, pos) - 1

    def disp(self, s: str) -> str:
        return s.encode("latin-1").decode(self.res.enc, "replace").strip()

    def line_text(self, L: int) -> str:
        ls, le, _ = self.lines[L]
        return self.disp(self.text[ls:le])

    def add(self, L: int, level: str, kind: str, note: str = "", last: int = -1) -> None:
        if level in (HATA, UYARI):
            self.issue_lines.update(range(L, max(L, last) + 1))
        self.res.items.append(Item(L + 1, level, kind, self.line_text(L), note))

    def code_in(self, a: int, b: int) -> bool:
        """[a, b) araliginda yorum disinda bosluk olmayan karakter var mi"""
        i = max(bisect.bisect_right(self.real_starts, a) - 1, 0)
        pos = a
        while i < len(self.real) and self.real[i][0] < b:
            s, e = self.real[i]
            if e > pos:
                if s > pos and self.text[pos:s].strip(WS + "\r\n"):
                    return True
                pos = max(pos, e)
            i += 1
        return pos < b and bool(self.text[pos:b].strip(WS + "\r\n"))

    def _build_comments(self) -> None:
        text = self.text
        for s, e, kind, flag in self.lexed[0]:
            L = self.line_of(s)
            last = self.line_of(max(s, e - 1))
            self._push(Cmt(s, e, kind, L, last, not text[self.lines[L][0]:s].strip(WS), flag))
            if kind == "block" and CLEAN_BLOCK_COMMENTS and not flag:
                for k in range(L + 1, last):            # blok yorumun ic satirlari
                    ls, le, _ = self.lines[k]
                    seg = text[ls:le]
                    i = seg.find("//")
                    if i >= 0:
                        self._push(Cmt(ls + i, le, "pseudo", k, k, not seg[:i].strip(WS), False))

    def _push(self, c: Cmt) -> None:
        self.by_line.setdefault(c.line, []).append(len(self.cm))
        self.cm.append(c)

    # ---- plan
    def plan(self) -> None:
        stack: list[Removal] = []
        for ci, c in enumerate(self.cm):
            if ci in self.used:
                continue
            r = classify(self.text, c)
            if r is None:
                continue
            label, cut, rest = r
            rm = self.take(ci, label, cut)
            if rm is None:
                continue
            if c.kind == "block":                     # icindeki satirlar zaten gidiyor
                k = ci + 1
                while k < len(self.cm) and self.cm[k].kind == "pseudo" and self.cm[k].start < c.end:
                    self.used.add(k)
                    k += 1
            if label in ("ACILIS", "BOZUK") and c.kind != "block":
                st = ListState(rest)
                for nc in self.continue_list(c, st):
                    self.take(nc, "LISTE", 0)
                if st.bracket and not st.closed:
                    self.add(c.line, UYARI, "LISTE_KAPANMAMIS",
                             "ID listesi ']' ile kapanmamis; acilis silindi ama ID gibi "
                             "gorunmeyen sonraki yorum satirlari silinmedi - kontrol et")
            if label == "ACILIS":
                self.res.opens += 1
                stack.append(rm)
            elif label == "KAPANIS":
                self.res.closes += 1
                if stack:
                    stack.pop()
                else:
                    rm.note = _join(rm.note, "acilisi olmayan kapanis (yine de silindi)")
        for r in stack:
            r.note = _join(r.note, "kapanisi olmayan acilis (yine de silindi)")

    def continue_list(self, c: Cmt, st: ListState) -> list[int]:
        taken: list[int] = []
        pending: list[int] = []
        L, n = c.last + 1, 0
        while st.expect and L < len(self.lines) and n < MAX_LIST_LINES:
            idxs = self.by_line.get(L)
            if not idxs:
                break
            nc = idxs[0]
            cc = self.cm[nc]
            if (nc in self.used or not cc.alone or cc.kind == "block"
                    or (cc.kind == "line" and cc.flag) or (cc.kind == "pseudo") != (c.kind == "pseudo")):
                break
            body = self.text[cc.start + 2:cc.end].lstrip(WS + "/!<")
            if body.startswith("#"):
                after = body[1:].lstrip(WS)
                if after[:1] in ("(", ")"):           # yeni acilis / kapanis
                    break
                body = after
            d = st.accepts(body)
            if d == "stop":
                break
            if d == "maybe":
                pending.append(nc)
            else:
                taken += pending + [nc]
                pending = []
            st.feed(body)
            L, n = cc.last + 1, n + 1
        return taken

    def take(self, ci: int, label: str, cut: int):
        c = self.cm[ci]
        self.used.add(ci)
        text = self.text
        ls = self.lines[c.line][0]
        le_last = self.lines[c.last][1]
        start, end = c.start + cut, c.end
        if c.kind == "line" and c.flag:
            self.add(c.line, HATA, "YORUM_DEVAM_EDIYOR",
                     "yorum '\\' ile bitiyor: sonraki satir da bu yorumun parcasi; silmek o "
                     "satiri da siler -> elle duzelt", c.last)
            return None
        if c.kind == "block" and c.flag:
            self.add(c.line, HATA, "BLOK_KAPANMAMIS", "/* kapanmamis -> elle duzelt", c.last)
            return None
        if c.kind != "pseudo" and not STRIP_TRAILING and cut == 0 and self.code_in(ls, start):
            self.add(c.line, UYARI, "NOTASYON_SATIR_SONU",
                     "kod satirinin sonunda notasyon (--keep-trailing acik) - elle sil")
            return None
        reaches_eol = c.last > c.line or not text[end:self.lines[c.line][1]].strip(WS)
        if reaches_eol and SPLICE_TAIL_RE.search(text[ls:start].rstrip(WS)):
            self.add(c.line, HATA, "TERS_BOLU",
                     "yorum silinirse satir '\\' ile biter ve sonraki satirla birlesir -> elle duzelt")
            return None
        if (c.kind == "block" and c.last > c.line and self.code_in(ls, start)
                and self.code_in(end, le_last)):
            self.add(c.line, UYARI, "BLOK_KOD_ARASINDA",
                     "cok satirli blok yorumun iki yaninda da kod var - elle sil", c.last)
            return None
        note = "onceki yorum metni korundu, sadece notasyon kesildi" if cut else ""
        if c.kind == "pseudo":
            note = "/* */ icindeki satir"
        rm = Removal(start, end, c.line, c.last, label, note,
                     len(HLR_ANY_RE.findall(text[start:end])))
        self.removals.append(rm)
        self.res.ids += rm.ids
        return rm

    # ---- uygulama
    def build(self) -> tuple[str, list[int]]:
        text = self.text
        rem = sorted(self.removals, key=lambda r: r.start)
        out: list[str] = []
        omap: list[int] = []                 # yeni satir -> eski satir
        state: dict[int, str] = {}
        j = 0
        for L, (ls, le, lee) in enumerate(self.lines):
            while j < len(rem) and rem[j].end <= ls:
                j += 1
            segs = []
            k = j
            while k < len(rem) and rem[k].start < le:
                a, b = max(rem[k].start, ls), min(rem[k].end, le)
                if a < b:
                    segs.append((a, b))
                k += 1
            if not segs:
                out.append(text[ls:lee])
                omap.append(L)
                continue
            a0, b0 = segs[0]
            if not text[ls:a0].strip(WS):          # satir basi: girinti korunur, arkadaki bosluk gider
                while b0 < le and text[b0] in WS:
                    b0 += 1
                segs[0] = (a0, b0)
            new, pos = "", ls
            for a, b in segs + [(le, le)]:
                piece = text[pos:a]
                if new and piece:
                    if new[-1] not in WS and piece[0] not in WS:
                        new += " "                 # a/*x*/b -> a b  (token birlesmesin)
                    elif new[-1] in WS and piece[0] in WS:
                        piece = piece.lstrip(WS)   # a /*x*/ b -> a b  (cift bosluk olmasin)
                new += piece
                pos = b
            if not new.strip(WS):
                if out and SPLICE_TAIL_RE.search(out[-1].rstrip("\r\n")):
                    out.append(text[le:lee])     # onceki satir '\' ile bitiyor: bos birak
                    omap.append(L)
                    state[L] = "blank"
                else:
                    state[L] = "deleted"
                continue
            if segs[-1][1] == le:
                new = new.rstrip(WS)
            out.append(new + text[le:lee])
            omap.append(L)
            state[L] = "cut"
        for r in rem:
            st = state.get(r.line, "cut")
            level = KESILDI if st == "cut" else SILINDI
            note = r.note
            if st == "blank":
                note = _join(note, "satir bos birakildi (onceki satir '\\' ile bitiyor)")
            if r.last > r.line:
                note = _join(note, f"{r.last - r.line + 1} satirlik blok yorum")
            self.res.items.append(Item(r.line + 1, level, r.label, self.line_text(r.line), note))
        self.res.removed = sum(1 for v in state.values() if v == "deleted")
        self.res.blanked = sum(1 for v in state.values() if v == "blank")
        self.res.cut = sum(1 for v in state.values() if v == "cut")
        self.res.items.sort(key=lambda it: it.line)
        return "".join(out), omap


def residual(text: str, lexed=None) -> list[tuple[int, str]]:
    """Kalan HLR/LLR / notasyon: [(satir_indeksi, kategori)]"""
    comments, strings = lexed if lexed is not None else lex(text)
    starts = [ln[0] for ln in split_lines(text)]
    found: dict[int, str] = {}

    def hit(pos: int, cat: str) -> None:
        L = bisect.bisect_right(starts, pos) - 1
        found.setdefault(L, cat)

    spans = []
    for s, e, *_ in comments:
        seg = text[s:e]
        for m in HLR_ANY_RE.finditer(seg):
            hit(s + m.start(), "YORUMDA")
        for m in MARK_ANY_RE.finditer(seg):
            hit(s + m.start(), "YORUMDA")
        spans.append((s, e))
    for s, e in strings:
        seg = text[s:e]
        for m in HLR_ANY_RE.finditer(seg):
            hit(s + m.start(), "STRING_ICINDE")
        for m in MARK_ANY_RE.finditer(seg):
            hit(s + m.start(), "STRING_ICINDE")
        spans.append((s, e))
    pos = 0
    for s, e in sorted(spans) + [(len(text), len(text))]:
        if s > pos:
            for m in HLR_ANY_RE.finditer(text, pos, s):
                hit(m.start(), "KODDA")
        pos = max(pos, e)
    return sorted(found.items())


KALAN_NOTE = {
    "YORUMDA": "aciklama yorumu icinde (notasyon degil) - gerekiyorsa elle sil",
    "STRING_ICINDE": "string verisi - dokunulmadi",
    "KODDA": "kod icinde (identifier vb.) - dokunulmadi",
}


# --------------------------------------------------------------------
# Dosya isleme
# --------------------------------------------------------------------

def detect_display_enc(data: bytes) -> str:
    for enc in ("utf-8", "cp1254"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def backup_path(path: Path) -> Path:
    b, i = path.with_name(path.name + ".bak"), 2
    while b.exists():
        b, i = path.with_name(f"{path.name}.bak{i}"), i + 1
    return b


def first_diff(a: list, b: list) -> str:
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else ()
        y = b[i] if i < len(b) else ()
        if x != y:
            f = lambda t: " ".join(s.replace("\x00", "") for s in t)[:100]  # noqa: E731
            return f"eski: '{f(x)}'  yeni: '{f(y)}'"
    return ""


def process_file(path: Path) -> FileResult:
    res = FileResult(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        res.error = f"okunamadi: {e}"
        return res
    had_bom = raw.startswith(BOM)
    body = raw[len(BOM):] if had_bom else raw
    res.enc = detect_display_enc(body)
    text = body.decode("latin-1")                    # byte-saydam: her byte = 1 karakter
    try:
        p = Planner(text, res)
        p.plan()
        new_text, omap = p.build()
    except Exception as e:                           # noqa: BLE001
        res.error = f"islenemedi ({type(e).__name__}: {e}) - dosyaya dokunulmadi"
        res.items.clear()
        return res
    new_lexed = None
    if new_text != text:
        new_lexed = lex(new_text)
        old_fp, new_fp = fingerprint(text, p.lexed), fingerprint(new_text, new_lexed)
        if old_fp != new_fp:
            res.skipped = True
            res.error = ("DOGRULAMA BASARISIZ: kod degisirdi, dosyaya DOKUNULMADI -> "
                         + first_diff(old_fp, new_fp))
        else:
            res.verified = True
    if res.skipped:
        new_text, new_lexed, omap = text, p.lexed, list(range(len(p.lines)))
    if not DRY_RUN and res.changed:
        try:
            if MAKE_BACKUP:
                backup_path(path).write_bytes(raw)
            payload = (BOM if had_bom else b"") + new_text.encode("latin-1")
            path.write_bytes(payload)
            if path.read_bytes() != payload:
                raise OSError("geri okunan icerik farkli")
            res.written = True
        except OSError as e:
            res.error = f"yazilamadi (salt okunur / kilitli olabilir): {e}"
    new_lines = split_lines(new_text)
    for nl, cat in residual(new_text, new_lexed):
        ol = omap[nl] if nl < len(omap) else nl
        if ol in p.issue_lines:
            continue
        res.kalan += 1
        ls, le, _ = new_lines[nl]
        shown = nl if res.written else ol
        res.items.append(Item(shown + 1, KALAN, cat, p.disp(new_text[ls:le]), KALAN_NOTE[cat]))
    return res


def scan_other(path: Path) -> tuple[int, int]:
    """(eslesme sayisi, ilk satir)"""
    try:
        if path.stat().st_size > OTHER_FILE_MAX_BYTES:
            return 0, 0
        data = path.read_bytes()
    except OSError:
        return 0, 0
    if b"\x00" in data[:8192]:
        return 0, 0
    hits = list(HLR_ANY_BYTES_RE.finditer(data))
    if not hits:
        return 0, 0
    return len(hits), data.count(b"\n", 0, hits[0].start()) + 1


# --------------------------------------------------------------------
# Dosya listesi
# --------------------------------------------------------------------

def is_excluded(parts) -> bool:
    if not EXCLUDE_DIRS:
        return False
    parts = [x.replace("\\", "/").strip("/").casefold() for x in parts]
    parts = [x for x in parts if x and x != "."]
    joined = "/" + "/".join(parts) + "/"
    for e in EXCLUDE_DIRS:
        e = e.replace("\\", "/").strip().strip("/").casefold()
        if e and (("/" in e and f"/{e}/" in joined) or ("/" not in e and e in parts)):
            return True
    return False


def read_file_list(list_path: str) -> list[str]:
    p = Path(list_path)
    data = p.read_bytes()
    text = data.decode("latin-1")
    for enc in ("utf-8-sig", "cp1254"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for ln in text.splitlines():
        s = ln.strip().strip('"').strip()
        if s and not s.startswith("#"):
            f = Path(s)
            out.append(str(f if f.is_absolute() else p.parent / f))
    return out


def is_backup_or_report(f: Path) -> bool:
    n = f.name.lower()
    return bool(re.search(r"\.bak\d*$", n)) or n.endswith("_report.csv") or n == "hlr_llr_remove.py"


def collect_files(paths: list[str], listed: list[str]) -> tuple[list[Path], list[Path]]:
    seen: set[Path] = set()
    cands: list[Path] = []
    others: list[Path] = []

    def add(c: Path, lst: list[Path]) -> None:
        try:
            r = c.resolve()
        except OSError:
            r = c
        if r not in seen:
            seen.add(r)
            lst.append(c)

    for raw in listed:
        c = Path(raw)
        if not c.is_file():
            print(f"UYARI: --file-list: dosya bulunamadi: {c}")
        elif c.suffix.lower() not in ALLOWED_EXTENSIONS:
            print(f"UYARI: --file-list: desteklenmeyen uzanti, atlandi (--ext ile ekle): {c}")
        elif is_excluded(c.parent.parts):
            print(f"BILGI: --file-list: EXCLUDE_DIRS'te, atlandi: {c}")
        else:
            add(c, cands)
    for raw in paths:
        p = Path(raw) if raw else Path(".")
        if p.is_file():
            if p.suffix.lower() in ALLOWED_EXTENSIONS:
                add(p, cands)
            else:
                print(f"UYARI: desteklenmeyen uzanti, atlandi (--ext ile ekle): {p}")
        elif p.is_dir():
            visited: set[str] = set()
            for dp, dns, fns in os.walk(p, followlinks=True):
                try:
                    real = os.path.realpath(dp)
                except OSError:
                    real = dp
                if real in visited:                       # sembolik link dongusu
                    dns[:] = []
                    continue
                visited.add(real)
                rel = Path(dp).relative_to(p).parts if Path(dp) != p else ()
                dns[:] = sorted(d for d in dns
                                if d not in SKIP_DIR_NAMES and not is_excluded(rel + (d,)))
                for f in sorted(fns):
                    fp = Path(dp) / f
                    if fp.suffix.lower() in ALLOWED_EXTENSIONS:
                        add(fp, cands)
                    elif not is_backup_or_report(fp):
                        add(fp, others)
        else:
            print(f"UYARI: yol bulunamadi: {p}")
    return cands, others


# --------------------------------------------------------------------
# git dogrulama:  HEAD ile calisma kopyasi arasinda sadece yorum mu degismis?
# --------------------------------------------------------------------

def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True)


def verify_git(paths: list[str]) -> int:
    total = ok = 0
    bad: list[tuple[str, str]] = []
    info: list[str] = []
    for raw in paths or SOURCE_PATHS:
        p = Path(raw) if raw else Path(".")
        cwd = str(p if p.is_dir() else p.parent)
        try:
            r = _git(["rev-parse", "--show-toplevel"], cwd)
        except OSError as e:
            print(f"HATA: git calistirilamadi: {e}")
            return 2
        if r.returncode:
            print(f"HATA: git deposu degil: {p}")
            continue
        top = r.stdout.decode("utf-8", "replace").strip()
        rel = os.path.relpath(str(p.resolve()), top)
        r = _git(["diff", "--name-only", "-z", "HEAD", "--", rel], top)
        for name in (n for n in r.stdout.decode("utf-8", "replace").split("\0") if n):
            f = Path(top) / name
            if f.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            if not f.exists():
                bad.append((name, "dosya silinmis"))
                continue
            old = _git(["show", "HEAD:" + name], top)
            if old.returncode:
                info.append(f"{name}: HEAD'de yok (yeni dosya), atlandi")
                continue
            a, b = old.stdout, f.read_bytes()
            a = a[3:] if a.startswith(BOM) else a
            b = b[3:] if b.startswith(BOM) else b
            ta, tb = a.decode("latin-1"), b.decode("latin-1")
            total += 1
            fa, fb = fingerprint(ta), fingerprint(tb)
            if fa == fb:
                ok += 1
            else:
                bad.append((name, "KOD FARKLI -> " + first_diff(fa, fb)))
    print("=" * 78)
    print(f"GIT DOGRULAMA (HEAD <-> calisma kopyasi): {total} degismis kaynak dosya")
    print(f"  sadece yorum farki (kod birebir ayni): {ok}")
    print(f"  KOD FARKI olan: {len(bad)}")
    for name, why in bad:
        print(f"    [HATA] {name}: {why}")
    for s in info:
        print(f"    [BILGI] {s}")
    print("=" * 78)
    return 1 if bad else 0


# --------------------------------------------------------------------
# Ana akis
# --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, MAKE_BACKUP, REPORT_CSV, SHOW_PREVIEW, STRIP_TRAILING
    global CLEAN_BLOCK_COMMENTS, REMOVE_ID_ONLY_COMMENTS
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Requirement link (HLR/LLR) notasyonlarini siler.")
    ap.add_argument("paths", nargs="*", help="dizin / dosya (bos: AYARLAR'daki SOURCE_PATHS)")
    ap.add_argument("--apply", action="store_true", help="degisiklikleri dosyalara yaz")
    ap.add_argument("--no-backup", action="store_true", help=".bak kopyasi olusturma")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    ap.add_argument("--no-report", action="store_true", help="CSV raporu olusturma")
    ap.add_argument("--exclude", action="append", default=[], metavar="KLASOR",
                    help="atlanacak klasor(ler); ';' ya da ',' ile ayrilabilir")
    ap.add_argument("--file-list", action="append", default=[], metavar="DOSYA",
                    help="islenecek dosyalarin listesi (satir basina bir yol)")
    ap.add_argument("--ext", action="append", default=[], metavar=".UZANTI",
                    help="ek islenecek uzanti(lar), orn. --ext .inc")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="silinen satirlari listeleme; sadece HATA / UYARI / KALAN")
    ap.add_argument("--keep-trailing", action="store_true",
                    help="kod satiri sonundaki notasyonlara dokunma (sadece uyar)")
    ap.add_argument("--no-block-comments", action="store_true",
                    help="/* */ icindeki notasyon satirlarina dokunma")
    ap.add_argument("--keep-id-comments", action="store_true",
                    help="sadece ID iceren yorumlari ( // HLR_1 ) silme")
    ap.add_argument("--verify-git", action="store_true",
                    help="dosyalari degistirme; git HEAD ile karsilastirip sadece yorumlarin "
                         "degistigini dogrula")
    args = ap.parse_args(argv)
    for e in args.ext:
        for x in re.split(r"[;,]", e):
            x = x.strip().lower()
            if x:
                ALLOWED_EXTENSIONS.add(x if x.startswith(".") else "." + x)
    if args.verify_git:
        return verify_git(args.paths)
    DRY_RUN = not args.apply
    MAKE_BACKUP = MAKE_BACKUP and not args.no_backup
    if args.report:
        REPORT_CSV = args.report
    if args.no_report:
        REPORT_CSV = ""
    SHOW_PREVIEW = SHOW_PREVIEW and not args.quiet
    STRIP_TRAILING = STRIP_TRAILING and not args.keep_trailing
    CLEAN_BLOCK_COMMENTS = CLEAN_BLOCK_COMMENTS and not args.no_block_comments
    REMOVE_ID_ONLY_COMMENTS = REMOVE_ID_ONLY_COMMENTS and not args.keep_id_comments
    for e in args.exclude:
        EXCLUDE_DIRS.update(x.strip() for x in re.split(r"[;,]", e) if x.strip())

    t0 = time.perf_counter()
    listed = [f for lp in args.file_list for f in read_file_list(lp)]
    paths = args.paths or ([] if listed else SOURCE_PATHS)
    files, others = collect_files(paths, listed)
    results = [process_file(p) for p in files]
    other_hits = []
    if SCAN_OTHER_FILES:
        rep = Path(REPORT_CSV).resolve() if REPORT_CSV else None
        for o in others:
            if rep is not None and o.resolve() == rep:
                continue
            cnt, first = scan_other(o)
            if cnt:
                other_hits.append((o, cnt, first))

    for r in results:
        shown = [it for it in r.items
                 if it.level not in (SILINDI, KESILDI) or SHOW_PREVIEW or it.note]
        if not (shown or r.error):
            continue
        status = ("DOKUNULMADI (HATA)" if r.skipped else
                  ("silinecek" if DRY_RUN else "silindi" if r.written else "YAZILAMADI")
                  if r.changed else "degisiklik yok")
        print(f"--- {r.path}  ({r.opens} acilis, {r.closes} kapanis, {r.removed} satir silme, "
              f"{r.cut} satir kesme; {status}"
              f"{'; kod dogrulandi' if r.verified and not r.skipped else ''}) ---")
        if r.error:
            print(f"  [HATA    ] {r.error}")
        for it in shown:
            note = f"  <- {it.note}" if it.note else ""
            print(f"  [{it.level:<8}] satir {it.line:<5} {it.kind:<19} {it.text}{note}")
        print()
    if other_hits:
        print("--- Uzanti listesi DISINDAKI dosyalarda HLR/LLR geciyor (islenmedi) ---")
        for o, cnt, first in other_hits:
            print(f"  [KALAN   ] {o}  ({cnt} eslesme, ilk satir {first})"
                  f"  <- kaynak koddaysa --ext {o.suffix or '<uzanti>'} ile ekle")
        print()

    changed = [r for r in results if r.changed]
    n_err = sum(1 for r in results for it in r.items if it.level == HATA) + \
        sum(1 for r in results if r.error)
    n_warn = sum(1 for r in results for it in r.items if it.level == UYARI)
    n_kalan = sum(r.kalan for r in results)
    print("=" * 78)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  dosya: {len(results)} tarandi, "
          f"{len(changed)} {'degisecek' if DRY_RUN else 'degisti'}, "
          f"{sum(r.skipped for r in results)} dogrulama HATASI yuzunden dokunulmadi")
    print(f"notasyon: {sum(r.opens for r in results)} acilis "
          f"({sum(r.ids for r in results)} ID), {sum(r.closes for r in results)} kapanis  |  "
          f"{sum(r.removed for r in results)} satir silme, {sum(r.cut for r in results)} "
          f"satirda yorum kesme, {sum(r.blanked for r in results)} satir bos birakma")
    print(f"kod dogrulamasi: {sum(r.verified for r in changed)}/{len(changed)} dosyada kod "
          f"birebir ayni (sadece yorumlar degisiyor)")
    print(f"KALAN HLR/LLR: {n_kalan} satir (kaynak dosyalarda), "
          f"{len(other_hits)} uzanti disi dosya  |  HATA: {n_err}  UYARI: {n_warn}  "
          f"({time.perf_counter() - t0:.1f} sn)")
    print("=" * 78)

    if REPORT_CSV:
        try:
            with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["dosya", "satir", "seviye", "tur", "satir_icerigi", "aciklama",
                            "uygulandi"])
                for r in results:
                    if r.error:
                        w.writerow([str(r.path), "", HATA, "DOSYA", "", r.error, ""])
                    for it in r.items:
                        applied = ("" if it.level not in (SILINDI, KESILDI) else
                                   "HAYIR (dosyada HATA)" if r.skipped else
                                   "HAYIR (dry-run)" if DRY_RUN else
                                   "EVET" if r.written else "HAYIR")
                        w.writerow([str(r.path), it.line, it.level, it.kind, it.text,
                                    it.note, applied])
                for o, cnt, first in other_hits:
                    w.writerow([str(o), first, KALAN, "UZANTI_DISI", "",
                                f"{cnt} eslesme; dosya islenmedi (--ext ile eklenebilir)", ""])
            print(f"Rapor: {REPORT_CSV}")
        except OSError as e:
            print(f"UYARI: rapor yazilamadi ({REPORT_CSV}): {e}")
    if DRY_RUN and changed:
        print("Silmek icin:  --apply   (once commit et; geri almak icin: git checkout -- .)")
    elif not DRY_RUN and changed:
        print("Kontrol icin:  --verify-git   (HEAD ile karsilastirir, sadece yorum farki olmali)")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main())
