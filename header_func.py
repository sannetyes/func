#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
header_body_finder.py  -  Header dosyalarindaki FONKSIYON GOVDELERINI bulur.
Harici bagimlilik YOKTUR (sadece stdlib).  Dosyalari DEGISTIRMEZ, sadece raporlar.

Bulunanlar (hepsi ayri ayri listelenir):
  * sinif icinde govdesiyle yazilmis metotlar       void get() const { ... }
  * sinif DISINDA header'da tanimli uye fonksiyonlar  void Foo::bar() { ... }
  * serbest (namespace / dosya seviyesi) fonksiyonlar int helper(int x) { ... }
  * template fonksiyonlar / template sinif metotlari  template<class T> T max(T a, T b) { ... }
  * operatorler                                      bool operator==(const A&) const { ... }
                                                     operator bool() const { ... }
                                                     auto operator()(int x) -> int { ... }
  * constructor / destructor                         Foo(int x) : a_(x), b_{x} { ... }
  * friend fonksiyonlar (sinif icinde tanimli)        friend bool operator<(...) { ... }

Her govde icin ODR (One Definition Rule) degerlendirmesi yapilir.  Header
birden fazla .cpp'ye include edildiginde:
  OK           sinif icinde tanimli (otomatik inline), template, inline,
               constexpr / consteval
  IC_BAGLANTI  static ya da isimsiz namespace: hata vermez ama her .cpp
               kendi kopyasini alir
  RISK         inline DEGIL -> birden fazla .cpp include edince LNK2005
               (multiple definition).  Ayrica MISRA C++:2008 3-1-1 ihlali
               ("header, ODR ihlal edilmeden birden fazla TU'ya include
               edilebilmeli").  Tam template ozellestirmesi (template<>) de
               normal fonksiyon gibidir -> inline degilse RISK.

Bulunmayanlar (fonksiyon govdesi DEGIL):
  sinif / struct / enum / namespace / extern "C" govdeleri, '= default',
  '= delete', '= 0', degisken ilklendirmeleri (= { ... }, { ... }),
  yorumlar, string'ler, #define makrolari ve #if 0 / #else dallari.

Kullanim:
    python header_body_finder.py                    # calisilan dizin
    python header_body_finder.py include/ src/      # verilen dizin / dosyalar
    python header_body_finder.py . --odr-only       # sadece RISK / IC_BAGLANTI olanlar
    python header_body_finder.py . --exclude "externals;third_party"
    python header_body_finder.py . --report govdeler.csv   (varsayilan: header_bodies_report.csv)
    python header_body_finder.py . --no-report      # CSV olusturma

Sinirlar:
  * #if / #ifdef: sadece ILK aktif dal taranir (#if 0 atlanir, #else dali
    taranmaz).  #else dalindaki govdeler raporda gorunmez.
  * Makronun icine gizlenmis fonksiyonlar (DEFINE_GETTER(x) gibi) bulunamaz;
    'MAKRO(...) { ... }' seklinde kullanilanlar fonksiyon olarak raporlanir.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


# ============================== AYARLAR ==============================

SOURCE_PATHS = [""]                       # "" = calisilan dizin
HEADER_EXTENSIONS = (".h", ".hpp", ".hh", ".hxx", ".inl", ".ipp", ".tpp")
EXCLUDE_DIRS: set[str] = set()            # "third_party" (ad) ya da "middleware/legacy" (yol)
ENCODINGS = ["utf-8", "cp1254", "latin-1"]
REPORT_CSV = "header_bodies_report.csv"   # "" = rapor olusturma

# Projede 'inline' / 'template<...>' / 'constexpr' yerine gecen MAKROLAR.
# Script makrolari acamaz; buraya yazilanlar bildirimde gorulurse govde ODR
# acisindan guvenli (OK) sayilir.  Adinda INLINE / CONSTEXPR / CONSTEVAL gecen
# BUYUK HARFLI makrolar (FORCE_INLINE, ALWAYS_INLINE ...) zaten otomatik kabul edilir.
# Ornek: {"MY_TEMPLATE_DECL", "PB_DS_CLASS_T_DEC"}
ODR_SAFE_MACROS: set[str] = set()

# =====================================================================

ACCESS = {"public", "protected", "private", "signals", "slots", "Q_SIGNALS", "Q_SLOTS"}
QUAL_KW = {"noexcept", "throw", "__attribute__", "alignas", "requires", "__declspec"}
IDENT = re.compile(r"[A-Za-z_]\w*")

# operator isimleri (ozel karakterleri ayristirmayi bozmasin diye bosluga cevrilir)
OPERATOR_RE = re.compile(
    r"\boperator\b(\s*(?:\(\s*\)|\[\s*\]|new\s*\[\s*\]|delete\s*\[\s*\]|->\*?|<<=|>>=|<=>|"
    r"<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|[-+*/%^&|~!=<>,]=?|\"\"\s*_?\w+))")
TRAILING_WORDS = ("const", "volatile", "override", "final", "mutable", "noexcept")
INLINE_WORDS = {"inline", "__inline", "_inline", "__forceinline", "constexpr", "consteval"}


# --------------------------------------------------------------------
# Okuma ve temizleme
# --------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(BOM):
        data = data[len(BOM):]
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("hepsi", b"", 0, 1, f"{path} cozulemedi")


def clean_code(text: str) -> str:
    """
    Yorum, string, char, raw string, onislemci satirlari ve AKTIF OLMAYAN #if
    dallari bosluga cevrilir.  Uzunluk ve satir yapisi korunur (konumlar
    orijinal metinle ayni kalir).
    """
    out = list(text)
    n = len(text)
    pp: list[list[bool]] = []          # [dal_secildi, aktif]

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] not in "\r\n":
                out[k] = " "

    def directive(s: str) -> None:
        m = re.match(r"#\s*(\w+)(.*)", s, flags=re.S)
        if not m:
            return
        name = m.group(1)
        rest = re.sub(r"/\*.*?\*/|//.*", "", m.group(2)).strip()
        if name in ("if", "ifdef", "ifndef"):
            on = not (name == "if" and rest == "0")
            pp.append([on, on])
        elif name in ("elif", "else") and pp:
            if pp[-1][0]:
                pp[-1][1] = False
            else:
                on = not (name == "elif" and rest == "0")
                pp[-1] = [on, on]
        elif name == "endif" and pp:
            pp.pop()

    i = 0
    line_start = True
    while i < n:
        c = text[i]
        if c == "\n":
            line_start = True
            i += 1
            continue
        if line_start and c in " \t\r\f\v":
            i += 1
            continue
        if line_start:
            line_start = False
            if c == "#":                                   # onislemci (+ '\' devami)
                e = i
                while True:
                    nl = text.find("\n", e)
                    if nl < 0:
                        e = n
                        break
                    if text[e:nl].rstrip("\r").endswith("\\"):
                        e = nl + 1
                        continue
                    e = nl
                    break
                directive(text[i:e])
                blank(i, e)
                i = e
                continue
            if not all(a for _, a in pp):                  # aktif olmayan dal
                e = text.find("\n", i)
                e = n if e < 0 else e
                blank(i, e)
                i = e
                continue
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            e = i
            while True:                                    # '\' ile biten yorum devam eder
                nl = text.find("\n", e)
                if nl < 0:
                    e = n
                    break
                if text[e:nl].rstrip("\r").endswith("\\"):
                    e = nl + 1
                    continue
                e = nl
                break
            blank(i, e)
            i = e
            continue
        if c == "/" and nxt == "*":
            e = text.find("*/", i + 2)
            e = n if e < 0 else e + 2
            blank(i, e)
            i = e
            continue
        if c == '"':
            if i > 0 and text[i - 1] == "R":
                k = text.find("(", i + 1)
                if k != -1:
                    delim = text[i + 1:k]
                    e = text.find(")" + delim + '"', k + 1)
                    e = n if e < 0 else e + len(delim) + 2
                    blank(i, e)
                    i = e
                    continue
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, j)                                # tirnaklar kalir: "" (operator"" icin)
            i = j + 1
            continue
        if c == "'":
            k = i - 1
            while k >= 0 and (text[k].isalnum() or text[k] in "_."):
                k -= 1
            tok = text[k + 1:i]
            if tok and tok[0].isdigit():                   # 1'000'000
                i += 1
                continue
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
            continue
        i += 1
    return "".join(out)


# --------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------

def match_close(s: str, i: int, o: str, c: str) -> int:
    depth = 0
    for j in range(i, len(s)):
        if s[j] == o:
            depth += 1
        elif s[j] == c:
            depth -= 1
            if depth == 0:
                return j
    return -1


def match_open(s: str, i: int, o: str, c: str) -> int:
    """s[i] == c ise geriye dogru eslesen o konumu."""
    depth = 0
    for j in range(i, -1, -1):
        if s[j] == c:
            depth += 1
        elif s[j] == o:
            depth -= 1
            if depth == 0:
                return j
    return -1


def depth0_mask(s: str) -> str:
    """( ) [ ] < > icindeki karakterleri bosluk yapar; disarida kalanlar korunur."""
    out = []
    paren = angle = 0
    for ch in s:
        if ch in "([":
            paren += 1
            out.append(" " if paren > 1 or angle else ch)
            continue
        if ch in ")]":
            paren = max(0, paren - 1)
            out.append(" " if paren or angle else ch)
            continue
        if paren == 0 and ch == "<":
            angle += 1
            out.append(" ")
            continue
        if paren == 0 and ch == ">":
            angle = max(0, angle - 1)
            out.append(" ")
            continue
        out.append(ch if paren == 0 and angle == 0 else " ")
    return "".join(out)


def strip_templates(head: str) -> tuple[str, bool, bool]:
    """
    Bastaki template<...> gruplarini siler.
    Donus: (kalan, template_mi, tam_ozellestirme_mi (template<>))
    """
    is_tpl = full = False
    while True:
        m = re.match(r"\s*template\s*<", head)
        if not m:
            break
        e = match_close(head, m.end() - 1, "<", ">")
        if e < 0:
            break
        if head[m.end():e].strip():
            is_tpl = True
        else:
            full = True
        head = " " * (e + 1) + head[e + 1:]           # konumlar korunsun
        head = strip_leading_requires(head)
    return head, is_tpl, full


def strip_leading_requires(head: str) -> str:
    """template<...> sonrasindaki 'requires ...' kosulunu siler (konumlar korunur)."""
    m = re.match(r"\s*requires\b", head)
    if not m:
        return head
    j = m.end()
    while True:
        k = j
        while k < len(head) and head[k].isspace():
            k += 1
        if k < len(head) and head[k] == "(":
            e = match_close(head, k, "(", ")")
            if e < 0:
                return head
            j = e + 1
        else:
            im = re.match(r"(?:::)?[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*", head[k:])
            if not im:
                return head
            j = k + im.end()
            k2 = j
            while k2 < len(head) and head[k2].isspace():
                k2 += 1
            if k2 < len(head) and head[k2] == "<":
                e = match_close(head, k2, "<", ">")
                if e < 0:
                    return head
                j = e + 1
        om = re.match(r"\s*(&&|\|\|)", head[j:])
        if not om:
            break
        j += om.end()
    return " " * j + head[j:]


def strip_trailing_quals(t: str) -> str:
    """Sondaki const / noexcept / override / & ... kelimelerini siler (dogrusal)."""
    while True:
        t = t.rstrip()
        if t.endswith("&"):
            t = t[:-1]
            continue
        for w in TRAILING_WORDS:
            if t.endswith(w) and (len(t) == len(w) or not (t[-len(w) - 1].isalnum()
                                                          or t[-len(w) - 1] == "_")):
                t = t[:-len(w)]
                break
        else:
            return t


def blank_operators(s: str) -> str:
    """'operator==' -> 'operator  ' (ayni uzunluk)."""
    def rep(m: re.Match) -> str:
        return "operator" + " " * (len(m.group(0)) - len("operator"))
    return OPERATOR_RE.sub(rep, s)


# --------------------------------------------------------------------
# Tarayici
# --------------------------------------------------------------------

@dataclass
class Scope:
    kind: str                  # file / ns / class / extern
    name: str


@dataclass
class FuncBody:
    line: int
    end_line: int
    scope: str                 # ns::Sinif
    name: str
    where: str                 # sinif ici / sinif disi uye / serbest
    flags: list[str] = field(default_factory=list)
    odr: str = "OK"
    note: str = ""


def classify(head: str) -> tuple[str, dict]:
    """
    '{' oncesindeki bildirim basina gore bu '{' ne:
      ns / extern / class / func / initbrace / other
    """
    info: dict = {"decl_offset": 0}
    h = re.sub(r"\[\[.*?\]\]", lambda m: " " * len(m.group(0)), head, flags=re.S)
    # Noktali virgulsuz makro satirlari bildirimin basina yapisir:
    #   _GLIBCXX_BEGIN_NAMESPACE_VERSION / DECLARE_X(...)  +  template<...> ...
    # Sonradan gelen 'template<' gercek bildirimin baslangicidir.
    for tm in re.finditer(r"\btemplate\s*<", h):
        if tm.start() == 0 or not h[:tm.start()].strip():
            break
        pre = h[:tm.start()]
        if pre.rstrip().endswith("::") or pre.count("(") != pre.count(")") \
                or pre.count("<") != pre.count(">"):
            continue                                     # typename X::template Y  vb.
        h = " " * tm.start() + h[tm.start():]
        info["decl_offset"] = tm.start()
        break
    h, is_tpl, full = strip_templates(h)
    info.update(template=is_tpl, full_spec=full)
    h3 = blank_operators(h)
    d0 = depth0_mask(h3)

    nm = re.match(r"\s*(?:inline\s+)?namespace\b", d0)
    if nm:
        rest = re.sub(r"[A-Za-z_]\w*\s*\(", " ", d0[nm.end():])    # MAKRO(...) at
        names = [t for t in IDENT.findall(rest) if not re.fullmatch(r"_*[A-Z][A-Z0-9_]*", t)]
        return "ns", {"name": "::".join(names)}
    if re.fullmatch(r"\s*extern\s*(?:\"\s*\"\s*)?", d0):       # extern "C" / extern "C++"
        return "extern", {}
    if re.search(r"\benum\b", d0):
        return "other", {"keep_stmt": True}
    cm = None
    for cm in re.finditer(r"\b(class|struct|union)\b", d0):
        pass
    if cm and "(" not in d0[cm.end():]:
        rest = d0[cm.end():]
        rest = rest.split(":", 1)[0] if re.search(r"(?<!:):(?!:)", rest) else rest
        names = [t for t in IDENT.findall(rest) if t not in ("final", "alignas")]
        return "class", {"name": names[-1] if names else ""}
    if "=" in d0:
        return "other", {"keep_stmt": True}            # degisken ilklendirmesi
    if "(" not in d0:
        return "other", {"keep_stmt": True}            # Foo obj{1}; gibi

    # requires-ifadesinin govdesi:  ... requires requires { x.f(); } { govde }
    if re.search(r"\brequires\s*(?:\([^()]*\))?\s*$", h3):
        return "initbrace", {}                       # ayni bildirim devam ediyor

    # function-try-block:  int f(int x) try { ... } catch (...) { ... }
    tm = re.search(r"\btry\s*$", h3)
    if tm:
        info["try_block"] = True
        h3 = h3[:tm.start()] + " " * (len(h3) - tm.start())
        d0 = depth0_mask(h3)

    # constructor init list:  Foo(int x) : a_(x), b_{x} {
    colon = None
    first_close = d0.find(")")
    for m in re.finditer(r"(?<!:):(?!:)", d0):
        if first_close != -1 and m.start() > first_close:
            colon = m.start()
            break
    if colon is not None:
        tail = h3[:len(h3.rstrip())]
        if tail and (tail[-1].isalnum() or tail[-1] in "_>"):
            return "initbrace", {}                     # uye ilklendirme: b_{x}
        sig_end = h3.rfind(")", 0, colon)
        info.update(sig=(h, h3, sig_end))
        return "func", info

    t = h3.rstrip()
    t = re.sub(r"\s*\brequires\b.*$", "", t, flags=re.S)
    t = re.sub(r"\s*->[^;{}]*$", "", t, flags=re.S)     # trailing return type
    while True:
        t2 = strip_trailing_quals(t)
        if t2.endswith(")"):
            lp = match_open(t2, len(t2) - 1, "(", ")")
            pre = t2[:lp].rstrip() if lp > 0 else ""
            kw = re.search(r"([A-Za-z_]\w*)$", pre)
            if kw and kw.group(1) in QUAL_KW:           # noexcept(...) / __attribute__((..))
                t = pre[:kw.start()].rstrip()
                continue
        t = t2
        break
    if not t.endswith(")"):
        return "other", {}
    lp = match_open(t, len(t) - 1, "(", ")")
    if lp > 0 and t[:lp].rstrip().endswith("]"):
        return "other", {}                             # lambda
    info.update(sig=(h, h3, len(t) - 1))
    return "func", info


def func_name(h: str, h3: str, close: int) -> str:
    lp = match_open(h3, close, "(", ")")
    if lp <= 0:
        return "?"
    s3 = h3[:lp].rstrip()
    s = h[:lp]                                   # orijinal (operator sembolleri duruyor)
    m = None
    for m in re.finditer(r"\boperator\b", s3):
        pass
    if m and not re.search(r"[;{}]", s3[m.end():]):
        start = m.start()
        base = re.sub(r"\s+", " ", s[start:]).strip()
        base = re.sub(r"^operator\s+(?=[^\w\s])", "operator", base)
    else:
        end = len(s3)
        targs = ""
        if s3.endswith(">"):                     # max_of<int>(  -> sablon argumanlari
            o = match_open(s3, len(s3) - 1, "<", ">")
            if o < 0:
                return "?"
            targs = re.sub(r"\s+", "", s[o:end])
            end = o
        mm = re.search(r"(~\s*)?[A-Za-z_]\w*\s*$", s3[:end])
        if not mm:
            return "?"
        start = mm.start()
        base = re.sub(r"\s+", "", s[start:end]) + targs
    # Foo<T>::  Outer::Inner::  niteleyicilerini ekle
    k = start
    while True:
        pre = s3[:k].rstrip()
        if not pre.endswith("::"):
            break
        pre = pre[:-2].rstrip()
        j = len(pre)
        if pre.endswith(">"):
            o = match_open(pre, len(pre) - 1, "<", ">")
            if o < 0:
                break
            j = o
        im = re.search(r"[A-Za-z_]\w*$", pre[:j])
        if not im:
            break
        k = im.start()
    qual = re.sub(r"\s+", "", s[k:start])
    return qual + base


INLINE_DECL_WORDS = {"inline", "__inline", "_inline", "__forceinline"}


def norm_key(name: str) -> str:
    """'nav::Box<T>::get' -> 'nav::Box::get' (sablon argumanlari ve bosluklar atilir)."""
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"<[^<>]*>", "", name)
    return re.sub(r"\s+", "", name).replace("(isimsiz)::", "").strip(":")


def inline_decl_key(head: str, stack: list["Scope"]) -> str | None:
    """
    ';' ile biten bir bildirim 'inline' fonksiyon bildirimi mi?  Oyleyse
    tam nitelikli adini dondur ('nav::Foo::f').  C++: bildirimi inline olan
    fonksiyonun govdesi 'inline' yazilmasa da inline'dir.
    """
    h = re.sub(r"\[\[.*?\]\]", lambda m: " " * len(m.group(0)), head, flags=re.S)
    h, _, _ = strip_templates(h)
    h3 = blank_operators(h)
    words = set(IDENT.findall(depth0_mask(h3)))
    if not (words & INLINE_DECL_WORDS or words & ODR_SAFE_MACROS
            or any(re.fullmatch(r"_*[A-Z][A-Z0-9_]*", w) and "INLINE" in w for w in words)):
        return None
    t = re.sub(r"=\s*(?:0|default|delete)\s*$", "", h3.rstrip())
    t = re.sub(r"\s*\brequires\b.*$", "", t, flags=re.S)
    t = re.sub(r"\s*->[^;{}]*$", "", t, flags=re.S)
    while True:
        t2 = strip_trailing_quals(t)
        if t2.endswith(")"):
            lp = match_open(t2, len(t2) - 1, "(", ")")
            pre = t2[:lp].rstrip() if lp > 0 else ""
            kw = re.search(r"([A-Za-z_]\w*)$", pre)
            if kw and kw.group(1) in QUAL_KW:
                t = pre[:kw.start()].rstrip()
                continue
        t = t2
        break
    if not t.endswith(")") or "(" not in depth0_mask(t):
        return None
    name = func_name(h, h3, len(t) - 1)
    if name == "?":
        return None
    scope = [sc.name or "(isimsiz)" for sc in stack if sc.kind in ("ns", "class")]
    return norm_key("::".join(scope + [name]))


def scan(clean: str, text: str) -> tuple[list[FuncBody], list[str], set[str]]:
    bodies: list[FuncBody] = []
    warns: list[str] = []
    inline_decls: set[str] = set()
    stack = [Scope("file", "")]
    n = len(clean)
    stmt = 0
    i = 0

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    while i < n:
        c = clean[i]
        if c == ";":
            if "inline" in clean[stmt:i] or "INLINE" in clean[stmt:i] or ODR_SAFE_MACROS:
                k = inline_decl_key(clean[stmt:i], stack)
                if k:
                    inline_decls.add(k)
            stmt = i + 1
        elif c == ":" and stack[-1].kind == "class" and clean[i - 1:i] != ":" \
                and clean[i + 1:i + 2] != ":":
            w = re.search(r"([A-Za-z_]\w*)\s*$", clean[stmt:i])
            if w and w.group(1) in ACCESS:
                stmt = i + 1
        elif c == "}":
            if len(stack) > 1:
                stack.pop()
            else:
                warns.append(f"satir {line_of(i)}: eslesmeyen '}}'")
            stmt = i + 1
        elif c == "{":
            head = clean[stmt:i]
            if head.count("(") > head.count(")"):          # parantez icinde: f(T x = {})
                close = match_close(clean, i, "{", "}")
                if close < 0:
                    warns.append(f"satir {line_of(i)}: '{{' kapanmiyor, tarama durduruldu")
                    break
                i = close + 1
                continue
            kind, info = classify(head)
            if kind in ("ns", "extern", "class"):
                stack.append(Scope(kind, info.get("name", "")))
                stmt = i + 1
            else:
                close = match_close(clean, i, "{", "}")
                if close < 0:
                    warns.append(f"satir {line_of(i)}: '{{' kapanmiyor, tarama durduruldu")
                    break
                if kind == "func":
                    if info.get("try_block"):              # catch (...) { } bloklarini da atla
                        while True:
                            cm = re.match(r"\s*catch\s*\(", clean[close + 1:])
                            if not cm:
                                break
                            p = match_close(clean, close + cm.end(), "(", ")")
                            b = clean.find("{", p + 1) if p > 0 else -1
                            e = match_close(clean, b, "{", "}") if b > 0 else -1
                            if e < 0:
                                break
                            close = e
                    off = info.get("decl_offset", 0)
                    off += len(head[off:]) - len(head[off:].lstrip())
                    bodies.append(make_body(head, info, stack, line_of(stmt + off),
                                            line_of(close)))
                    stmt = close + 1
                elif kind == "initbrace":
                    pass                                   # ayni bildirim devam ediyor
                elif not info.get("keep_stmt"):
                    stmt = close + 1
                i = close + 1
                continue
        i += 1
    if len(stack) > 1:
        warns.append(f"dosya sonunda {len(stack) - 1} kapsam kapanmamis")
    return bodies, warns, inline_decls


def make_body(head: str, info: dict, stack: list[Scope], line: int, end: int) -> FuncBody:
    h, h3, close = info["sig"]
    name = func_name(h, h3, close)
    scope_names = [s.name or "(isimsiz)" for s in stack if s.kind in ("ns", "class")]
    in_class = stack[-1].kind == "class"
    anon_ns = any(s.kind == "ns" and not s.name for s in stack)
    words = set(IDENT.findall(depth0_mask(blank_operators(h))))

    flags: list[str] = []
    short = name.split("::")[-1]
    cls = stack[-1].name if in_class else (name.split("::")[-2] if name.count("::") else "")
    if "operator" in name:
        flags.append("operator")
    if cls and short.lstrip("~") == re.sub(r"<.*>$", "", cls.split("::")[-1]):
        flags.append("destructor" if short.startswith("~") else "constructor")
    if info.get("template"):
        flags.append("template")
    if info.get("full_spec"):
        flags.append("template<> (tam ozellestirme)")
    for w in ("inline", "__inline", "_inline", "__forceinline", "constexpr", "consteval",
              "static", "friend", "virtual"):
        if w in words:
            flags.append(w)
    safe_macros = sorted((words & ODR_SAFE_MACROS) | {
        w for w in words if re.fullmatch(r"_*[A-Z][A-Z0-9_]*", w)
        and any(k in w for k in ("INLINE", "CONSTEXPR", "CONSTEVAL"))})
    if safe_macros:
        flags.append("makro: " + ", ".join(safe_macros))

    if in_class:
        where = "sinif ici"
    elif "::" in name and not name.startswith("::"):
        where = "sinif disi uye"
    else:
        where = "serbest"

    if in_class:
        odr, note = "OK", "sinif icinde tanimli -> otomatik inline"
    elif info.get("template") and not info.get("full_spec"):
        odr, note = "OK", "template"
    elif words & INLINE_WORDS:
        odr, note = "OK", "inline / constexpr"
    elif safe_macros:
        odr, note = "OK", (f"makro: {', '.join(safe_macros)} (inline / constexpr kabul "
                           f"edildi; ODR_SAFE_MACROS ya da adinda INLINE/CONSTEXPR)")
    elif "static" in words or anon_ns:
        odr, note = "IC_BAGLANTI", ("static / isimsiz namespace: her .cpp kendi kopyasini "
                                    "alir (LNK hatasi yok)")
    else:
        odr = "RISK"
        note = ("inline DEGIL: header birden fazla .cpp'ye include edilirse LNK2005 "
                "(multiple definition) - 'inline' ekle ya da govdeyi .cpp'ye tasi")
    return FuncBody(line, end, "::".join(scope_names), name, where, flags, odr, note)


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


def iter_headers(paths: list[str]):
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw) if raw else Path(".")
        if p.is_file():
            cands = [p]
        elif p.is_dir():
            cands = []
            for dp, dns, fns in os.walk(p):
                dns[:] = sorted(d for d in dns
                                if not d.startswith(".") and not dir_excluded(Path(dp) / d))
                cands += [Path(dp) / f for f in sorted(fns)
                          if Path(f).suffix.lower() in HEADER_EXTENSIONS]
        else:
            print(f"UYARI: yol bulunamadi: {p}")
            continue
        for c in cands:
            r = c.resolve()
            if r not in seen:
                seen.add(r)
                yield c


# --------------------------------------------------------------------
# Ana akis
# --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    global REPORT_CSV
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Header'lardaki fonksiyon govdelerini bulur.")
    ap.add_argument("paths", nargs="*", help="dizin / dosya (bos: calisilan dizin)")
    ap.add_argument("--odr-only", action="store_true",
                    help="sadece RISK ve IC_BAGLANTI olanlari listele")
    ap.add_argument("--exclude", action="append", default=[], metavar="KLASOR",
                    help="atlanacak klasor(ler), ';' ile ayrilabilir")
    ap.add_argument("--report", help=f"rapor CSV yolu (varsayilan: {REPORT_CSV})")
    ap.add_argument("--no-report", action="store_true", help="CSV olusturma")
    ap.add_argument("--quiet", action="store_true", help="dosya dosya listeyi basma, sadece ozet")
    args = ap.parse_args(argv)
    for e in args.exclude:
        EXCLUDE_DIRS.update(x.strip() for x in re.split(r"[;,]", e) if x.strip())
    if args.report:
        REPORT_CSV = args.report
    if args.no_report:
        REPORT_CSV = ""

    t0 = time.perf_counter()
    rows: list[tuple[Path, FuncBody]] = []
    n_files = n_with = 0
    problems: list[str] = []
    scanned: list[tuple[Path, list[FuncBody]]] = []
    all_inline: set[str] = set()
    for path in iter_headers(args.paths or SOURCE_PATHS):
        n_files += 1
        try:
            text = read_text(path)
            bodies, warns, decls = scan(clean_code(text), text)
        except Exception as e:                       # noqa: BLE001
            problems.append(f"{path}: okunamadi / taranamadi ({type(e).__name__}: {e})")
            continue
        for w in warns:
            problems.append(f"{path}: {w}")
        scanned.append((path, bodies))
        all_inline |= decls

    # Bildirimi 'inline' olan fonksiyonun govdesi de inline'dir (baska dosyada olsa bile:
    # Foo.h'de 'inline void f();', Foo.inl'de 'void Foo::f() {}')
    for _, bodies in scanned:
        for b in bodies:
            if b.odr == "RISK":
                key = norm_key((b.scope + "::" if b.scope else "") + b.name)
                if key in all_inline:
                    b.odr = "OK"
                    b.flags.append("inline (bildirimde)")
                    b.note = "bildirimi 'inline' -> govde de inline (ayni isimli overload'lar ayirt edilmez)"

    for path, bodies in scanned:
        if args.odr_only:
            bodies = [b for b in bodies if b.odr != "OK"]
        if not bodies:
            continue
        n_with += 1
        rows += [(path, b) for b in bodies]
        if not args.quiet:
            risk = sum(1 for b in bodies if b.odr == "RISK")
            print(f"--- {path}  ({len(bodies)} govde" + (f", {risk} ODR RISKI" if risk else "")
                  + ") ---")
            for b in bodies:
                fl = f"  [{', '.join(b.flags)}]" if b.flags else ""
                mark = "  !! ODR RISKI" if b.odr == "RISK" else (
                    "  (ic baglanti)" if b.odr == "IC_BAGLANTI" else "")
                print(f"  satir {b.line:<5} {b.where:<15} {b.name}{fl}{mark}")
            print()

    by_where: dict[str, int] = {}
    by_odr: dict[str, int] = {}
    for _, b in rows:
        by_where[b.where] = by_where.get(b.where, 0) + 1
        by_odr[b.odr] = by_odr.get(b.odr, 0) + 1
    print("=" * 78)
    print(f"header: {n_files} tarandi, {n_with} tanesinde fonksiyon govdesi var  |  "
          f"toplam govde: {len(rows)}  ({time.perf_counter() - t0:.1f} sn)")
    print("  " + "  ".join(f"{k}: {v}" for k, v in sorted(by_where.items()))
          + "   |   ODR  " + "  ".join(f"{k}: {v}" for k, v in sorted(by_odr.items())))
    if problems:
        print(f"  tarama uyarisi: {len(problems)}")
        for p in problems[:20]:
            print(f"    {p}")
        if len(problems) > 20:
            print(f"    ... (+{len(problems) - 20})")
    print("=" * 78)

    if REPORT_CSV:
        try:
            with open(REPORT_CSV, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["dosya", "satir", "bitis_satir", "govde_satir_sayisi", "kapsam",
                            "fonksiyon", "yer", "ozellikler", "odr", "aciklama"])
                for path, b in rows:
                    w.writerow([str(path), b.line, b.end_line, b.end_line - b.line + 1,
                                b.scope, b.name, b.where, ", ".join(b.flags), b.odr, b.note])
            print(f"Rapor: {REPORT_CSV}")
        except OSError as e:
            print(f"UYARI: rapor yazilamadi ({REPORT_CSV}): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
