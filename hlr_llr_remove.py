#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hlr_llr_remove.py  -  Requirement link bloklarinin notasyonlarini SILER.
Harici bagimlilik YOKTUR (sadece stdlib).

Verilen klasorlerdeki (alt klasorler dahil) kaynak dosyalarda:

    void func() {                          void func() {
    //#([HLR_MODULE_1, HLR_MODULE_2,          return x;
    //   HLR_MODULE_3]               ->    }
        return x;
    //#)
    }

  * '//#(' acilis satiri ve ID listesinin devam satirlari ('//   HLR_..., ...')
  * '//#)' kapanis satirlari
SATIR OLARAK silinir.  Aradaki kod ve diger yorumlar oldugu gibi kalir.
Ic ice (nested) bloklarin hepsi silinir.  Eslesmeyen (acilisi / kapanisi
olmayan) notasyonlar da silinir; raporda belirtilir.

Dokunulmayanlar (raporda gorunur):
  * /* ... */ blok yorumu ya da raw string icindeki notasyonlar
  * kod satirinin sonundaki notasyon      x = 1;  //#)       (satiri silmek kodu siler)
  * taninmayan / bozuk notasyon           //#[HLR_1]   #(   /#(
  * ID listesi yarim kalmis blok          ']' yok ve sonraki satir devam satiri gibi
    (hangi satirlarin silinecegi belirsiz).  SKIP_FILES_WITH_ERRORS = True iken
    boyle bir blok iceren dosyaya HIC dokunulmaz.

Tanidigi yazimlar  hlr_llr_fix.py ile aynidir:
    //#([A, B]   // #( [A, B ]   ///#([A]   //#(A, B]   //#([A, B   (eski formatlar)
    //#)   // #)   //# )

Kullanim:
    python hlr_llr_remove.py src/                    # DRY-RUN: neyin silinecegini goster
    python hlr_llr_remove.py src/ --apply            # sil (.bak yedekli)
    python hlr_llr_remove.py src/ ../externals --apply --exclude "third_party"
    python hlr_llr_remove.py --file-list files.txt --apply

Onemli: calistirmadan once commit et (git).  Geri almak icin:  git checkout -- .
Tekrar calistirmak guvenlidir (silinecek bir sey kalmadiysa dosyaya dokunulmaz).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

SOURCE_PATHS = [""]               # "" = calisilan dizin; komut satiri yollari bunu ezer
DRY_RUN = True                    # True: hicbir dosya degismez  (--apply ile False)
MAKE_BACKUP = True                # yazmadan once .bak kopyasi
REPORT_CSV = "hlr_llr_remove_report.csv"   # "" = rapor olusturma (--no-report)
SHOW_PREVIEW = True               # dry-run'da silinecek satirlari bas

SOURCE_EXTENSIONS = (".cpp", ".cc", ".cxx", ".c")
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx", ".inl")
ALLOWED_EXTENSIONS = set(SOURCE_EXTENSIONS) | set(HEADER_EXTENSIONS)
EXCLUDE_DIRS: set[str] = set()    # "third_party" (ad) ya da "middleware/legacy" (yol)
ENCODINGS = ["utf-8", "cp1254", "latin-1"]

SKIP_FILES_WITH_ERRORS = True     # yarim kalmis ID listesi olan dosyaya dokunma
MAX_LIST_LINES = 200

# =====================================================================

OPEN_RE = re.compile(r"^(?P<ws>[ \t]*)(?P<mk>/{2,}[ \t]*#[ \t]*\()")
CLOSE_RE = re.compile(r"^(?P<ws>[ \t]*)(?P<mk>/{2,}[ \t]*#[ \t]*\))")
SUSPECT_RE = re.compile(r"^[ \t]*(?:/+|/\*+)?[ \t]*#[ \t]*[\[\]()]")
TRAILING_MARKER_RE = re.compile(r"/{2,}[ \t]*#[ \t]*[()]")
ID_LIKE_RE = re.compile(r"^(?=.*[\d_])[\w.\-]+$")
VALID_ID_SEARCH = re.compile(r"\b(?:HLR|LLR)_\w")

HATA, UYARI, SILINDI = "HATA", "UYARI", "SILINDI"


@dataclass
class Item:
    line: int                 # 1-tabanli
    level: str                # SILINDI / UYARI / HATA
    kind: str                 # ACILIS / LISTE / KAPANIS / ...
    text: str
    note: str = ""


@dataclass
class FileResult:
    path: Path
    items: list[Item] = field(default_factory=list)
    removed: int = 0          # silinen satir sayisi
    opens: int = 0
    closes: int = 0
    ids: int = 0
    written: bool = False
    skipped: bool = False
    error: str = ""


# --------------------------------------------------------------------
# Dosya okuma / yazma  (BOM, kodlama, CRLF korunur)
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
    path.write_bytes(BOM + payload if had_bom else payload)


def split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


# --------------------------------------------------------------------
# ID listesi (hlr_llr_fix.py ile ayni kurallar)
# --------------------------------------------------------------------

def cont_content(line: str) -> str:
    return split_eol(line)[0].strip().lstrip("/").strip()


def is_cont_candidate(line: str) -> bool:
    s = split_eol(line)[0].strip()
    if not s.startswith("//") or OPEN_RE.match(s) or CLOSE_RE.match(s) or SUSPECT_RE.match(s):
        return False
    content = s.lstrip("/").strip()
    if not content:
        return False
    head, sep, _ = content.partition("]")
    toks = [t for t in re.split(r"[\s,;\[]+", head) if t]
    if not toks:
        return bool(sep)
    return all(ID_LIKE_RE.match(t) for t in toks)


def collect_list(lines: list[str], lo: int) -> tuple[int, bool]:
    """('//#(' dahil) liste satir sayisi, ']' ile kapandi mi"""
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
    return k - lo + 1, closed


def looks_dangling(line: str) -> bool:
    s = split_eol(line)[0].strip()
    if not s.startswith("//") or OPEN_RE.match(s) or CLOSE_RE.match(s):
        return False
    content = s.lstrip("/")
    return "]" in content or bool(VALID_ID_SEARCH.search(content))


def count_ids(lines: list[str]) -> int:
    text = " ".join(split_eol(ln)[0] for ln in lines)
    return len(re.findall(r"\b(?:HLR|LLR)_\w+", text))


# --------------------------------------------------------------------
# Tarama: hangi satirlar silinecek
# --------------------------------------------------------------------

class Scanner:
    """Satir basinin blok yorum / raw string icinde olup olmadigini izler."""

    def __init__(self) -> None:
        self.in_block = False
        self.raw_delim: str | None = None
        self.cont_comment = False

    def lex(self, text: str) -> bool:
        """Satiri isler; kod satirinin sonunda notasyon varsa True."""
        trailing = False
        j, n = 0, len(text)
        in_str: str | None = None
        while j < n:
            c = text[j]
            nxt = text[j + 1] if j + 1 < n else ""
            if self.in_block:
                e = text.find("*/", j)
                if e < 0:
                    return trailing
                self.in_block = False
                j = e + 2
                continue
            if self.raw_delim is not None:
                e = text.find(")" + self.raw_delim + '"', j)
                if e < 0:
                    return trailing
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
                    trailing = True
                self.cont_comment = text.rstrip().endswith("\\")
                return trailing
            if c == "/" and nxt == "*":
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
                k = j - 1
                while k >= 0 and (text[k].isalnum() or text[k] in "_."):
                    k -= 1
                tok = text[k + 1:j]
                if not (tok and tok[0].isdigit()):
                    in_str = "'"
                j += 1
                continue
            j += 1
        return trailing


def plan_removal(lines: list[str], res: FileResult) -> set[int]:
    remove: set[int] = set()
    sc = Scanner()
    open_stack: list[int] = []
    i = 0
    has_error = False
    while i < len(lines):
        text = split_eol(lines[i])[0]
        if sc.cont_comment:                     # '\' ile devam eden // yorumu
            sc.cont_comment = text.rstrip().endswith("\\")
            i += 1
            continue
        in_comment = sc.in_block or sc.raw_delim is not None
        if not in_comment and OPEN_RE.match(text):
            n, closed = collect_list(lines, i)
            nxt = i + n
            if not closed and nxt < len(lines) and looks_dangling(lines[nxt]):
                has_error = True
                res.items.append(Item(i + 1, HATA, "LISTE_BOZUK", text.strip(),
                                      f"ID listesi yarim kalmis: ']' yok ve satir {nxt + 1} "
                                      f"devam satiri gibi ('{split_eol(lines[nxt])[0].strip()}'). "
                                      f"Hangi satirlarin silinecegi belirsiz -> elle duzelt"))
                i += n
                continue
            block = lines[i:i + n]
            res.opens += 1
            res.ids += count_ids(block)
            open_stack.append(i)
            for k in range(i, i + n):
                remove.add(k)
                res.items.append(Item(k + 1, SILINDI, "ACILIS" if k == i else "LISTE",
                                      split_eol(lines[k])[0].strip()))
            i += n
            continue
        if not in_comment and CLOSE_RE.match(text):
            remove.add(i)
            res.closes += 1
            note = ""
            if open_stack:
                open_stack.pop()
            else:
                note = "acilisi olmayan kapanis (yine de silindi)"
            res.items.append(Item(i + 1, SILINDI, "KAPANIS", text.strip(), note))
            i += 1
            continue
        if in_comment and (OPEN_RE.match(text) or CLOSE_RE.match(text)):
            res.items.append(Item(i + 1, UYARI, "BLOK_YORUMDA", text.strip(),
                                  "/* ... */ icinde, dokunulmadi"))
        elif not in_comment and SUSPECT_RE.match(text):
            res.items.append(Item(i + 1, UYARI, "NOTASYON_TANINMADI", text.strip(),
                                  "bozuk notasyon, dokunulmadi - elle sil"))
        if sc.lex(text):
            res.items.append(Item(i + 1, UYARI, "NOTASYON_SATIR_SONU", text.strip(),
                                  "kod satirinin sonunda notasyon; satir kod icerdigi icin "
                                  "silinmedi - notasyonu elle sil"))
        i += 1
    for o in open_stack:
        for it in res.items:
            if it.line == o + 1 and it.kind == "ACILIS":
                it.note = "kapanisi olmayan acilis (yine de silindi)"
    if has_error and SKIP_FILES_WITH_ERRORS:
        res.skipped = True
    return remove


def process_file(path: Path) -> FileResult:
    res = FileResult(path)
    try:
        lines, enc, had_bom = read_lines(path)
    except Exception as e:                       # noqa: BLE001
        res.error = str(e)
        return res
    remove = plan_removal(lines, res)
    res.removed = len(remove)
    if not remove or res.skipped or DRY_RUN:
        return res
    new = [ln for k, ln in enumerate(lines) if k not in remove]
    try:
        write_lines(path, new, enc, had_bom)
        res.written = True
    except OSError as e:
        res.error = f"yazilamadi (salt okunur / kilitli olabilir): {e}"
    return res


# --------------------------------------------------------------------
# Dosya listesi
# --------------------------------------------------------------------

def dir_excluded(d: Path) -> bool:
    if not EXCLUDE_DIRS:
        return False
    parts = [x.replace("\\", "/").strip("/").casefold() for x in d.resolve().parts]
    parts = [x for x in parts if x]
    joined = "/" + "/".join(parts) + "/"
    for e in EXCLUDE_DIRS:
        e = e.replace("\\", "/").strip().strip("/").casefold()
        if e and (("/" in e and f"/{e}/" in joined) or ("/" not in e and e in parts)):
            return True
    return False


def read_file_list(list_path: str) -> list[str]:
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
        if s and not s.startswith("#"):
            f = Path(s)
            out.append(str(f if f.is_absolute() else p.parent / f))
    return out


def iter_files(paths: list[str], listed: list[str]):
    seen: set[Path] = set()
    cands: list[Path] = []
    for raw in listed:
        c = Path(raw)
        if c.is_file() and c.suffix.lower() in ALLOWED_EXTENSIONS and not dir_excluded(c.parent):
            cands.append(c)
    for raw in paths:
        p = Path(raw) if raw else Path(".")
        if p.is_file():
            if p.suffix.lower() in ALLOWED_EXTENSIONS:
                cands.append(p)
            else:
                print(f"UYARI: desteklenmeyen uzanti, atlandi: {p}")
        elif p.is_dir():
            if dir_excluded(p):
                print(f"BILGI: klasor EXCLUDE_DIRS'te, atlandi: {p}")
                continue
            for dp, dns, fns in os.walk(p):
                dns[:] = sorted(d for d in dns
                                if not d.startswith(".") and not dir_excluded(Path(dp) / d))
                cands += [Path(dp) / f for f in sorted(fns)
                          if Path(f).suffix.lower() in ALLOWED_EXTENSIONS]
        else:
            print(f"UYARI: yol bulunamadi: {p}")
    for c in cands:
        r = c.resolve()
        if r not in seen:
            seen.add(r)
            yield c


# --------------------------------------------------------------------
# Ana akis
# --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, MAKE_BACKUP, REPORT_CSV
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Requirement link bloklarinin notasyonlarini siler.")
    ap.add_argument("paths", nargs="*", help="dizin / dosya (bos: AYARLAR'daki SOURCE_PATHS)")
    ap.add_argument("--apply", action="store_true", help="degisiklikleri dosyalara yaz")
    ap.add_argument("--no-backup", action="store_true", help=".bak kopyasi olusturma")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    ap.add_argument("--no-report", action="store_true", help="CSV raporu olusturma")
    ap.add_argument("--exclude", action="append", default=[], metavar="KLASOR",
                    help="atlanacak klasor(ler); ';' ya da ',' ile ayrilabilir")
    ap.add_argument("--file-list", action="append", default=[], metavar="DOSYA",
                    help="islenecek dosyalarin listesi (satir basina bir yol)")
    args = ap.parse_args(argv)
    if args.apply:
        DRY_RUN = False
    if args.no_backup:
        MAKE_BACKUP = False
    if args.report:
        REPORT_CSV = args.report
    if args.no_report:
        REPORT_CSV = ""
    for e in args.exclude:
        EXCLUDE_DIRS.update(x.strip() for x in re.split(r"[;,]", e) if x.strip())

    t0 = time.perf_counter()
    listed = [f for lp in args.file_list for f in read_file_list(lp)]
    paths = args.paths or ([] if listed else SOURCE_PATHS)
    results = [process_file(p) for p in iter_files(paths, listed)]

    for r in results:
        shown = [it for it in r.items if it.level != SILINDI or (DRY_RUN and SHOW_PREVIEW)
                 or it.note]
        if not (r.removed or shown or r.error):
            continue
        status = ("ATLANDI (HATA var)" if r.skipped else
                  "silinecek" if DRY_RUN else "silindi" if r.written else "")
        print(f"--- {r.path}  ({r.opens} blok, {r.closes} kapanis, {r.removed} satir "
              f"{status}) ---")
        if r.error:
            print(f"  [HATA    ] {r.error}")
        for it in shown:
            note = f"  <- {it.note}" if it.note else ""
            print(f"  [{it.level:<8}] satir {it.line:<5} {it.kind:<20} {it.text}{note}")
        print()

    n_files_changed = sum(1 for r in results if r.removed and not r.skipped)
    n_err = sum(1 for r in results for it in r.items if it.level == HATA) + \
        sum(1 for r in results if r.error)
    n_warn = sum(1 for r in results for it in r.items if it.level == UYARI)
    print("=" * 78)
    print(f"{'DRY-RUN' if DRY_RUN else 'UYGULANDI'}  |  dosya: {len(results)} tarandi, "
          f"{n_files_changed} {'degisecek' if DRY_RUN else 'degisti'}, "
          f"{sum(r.skipped for r in results)} HATA yuzunden atlandi")
    print(f"silinen: {sum(r.opens for r in results)} acilis bloku "
          f"({sum(r.ids for r in results)} ID), {sum(r.closes for r in results)} kapanis, "
          f"toplam {sum(r.removed for r in results if not r.skipped)} satir  |  "
          f"HATA: {n_err}  UYARI: {n_warn}  ({time.perf_counter() - t0:.1f} sn)")
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
                        applied = ("" if it.level != SILINDI else
                                   "HAYIR (dosyada HATA var)" if r.skipped else
                                   "HAYIR (dry-run)" if DRY_RUN else
                                   "EVET" if r.written else "HAYIR")
                        w.writerow([str(r.path), it.line, it.level, it.kind, it.text,
                                    it.note, applied])
            print(f"Rapor: {REPORT_CSV}")
        except OSError as e:
            print(f"UYARI: rapor yazilamadi ({REPORT_CSV}): {e}")
    if DRY_RUN and n_files_changed:
        print("Silmek icin:  --apply   (once commit et; geri almak icin: git checkout -- .)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
