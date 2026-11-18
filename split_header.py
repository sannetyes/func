#!/usr/bin/env python3
"""
add_to_vcxproj.py - .cpp dosyalarini (ve eslesen header'larini) .vcxproj ve
.vcxproj.filters dosyalarina ekler. Sadece Python standart kutuphanesi kullanir.

Solution Explorer'da gorunum (diskteki klasor yapisindan bagimsiz):
    Header Files   ->  tum eslesen .h dosyalari
    Source Files   ->  tum .cpp dosyalari

  * Projede zaten olan .cpp'leri tekrar eklemez; Source Files disinda bir
    filtredeyseler Source Files'a tasir.
  * Her Foo.cpp icin ayni klasordeki Foo.h'yi bulur: projede yoksa ekler,
    Header Files disinda bir filtredeyse Header Files'a tasir.
  * "Header Files" / "Source Files" filtreleri yoksa olusturur.
  * Dosyanin bicimini (girinti, CRLF, UTF-8 BOM) bozmaz; yazmadan once XML'i dogrular.

Kullanim:
    python add_to_vcxproj.py --dry-run --only-with-bak -r .
    python add_to_vcxproj.py --backup  --only-with-bak -r .
"""
import argparse
import glob
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

NS = "{http://schemas.microsoft.com/developer/msbuild/2003}"
HEADER_EXTS = (".h", ".hpp", ".hh", ".hxx")
# Visual Studio'nun yeni projede kullandigi standart filtre tanimlari
STD_FILTERS = {
    "Source Files": ("{4FC737F1-C7A5-4376-A066-2A32D752A2FF}",
                     "cpp;c;cc;cxx;c++;cppm;ixx;def;odl;idl;hpj;bat;asm;asmx"),
    "Header Files": ("{93995380-89BD-4b04-88EB-625FBE52EBFB}",
                     "h;hh;hpp;hxx;h++;hm;inl;inc;ipp;xsd"),
}


def q(s):
    return escape(s, {'"': "&quot;"})


# ----------------------------------------------------------------------------- dosya G/C
def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    eol = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), eol, bom


def write_text(path, text, eol, bom):
    with open(path, "wb") as fh:
        fh.write((b"\xef\xbb\xbf" if bom else b"") + text.replace("\n", eol).encode("utf-8"))


def norm(p):
    return os.path.normcase(os.path.normpath(p.replace("\\", os.sep).replace("/", os.sep)))


# ----------------------------------------------------------------------------- okuma
def entries(text, tag, proj_dir):
    """{mutlak_normalize_yol: filtre_adi_veya_None}"""
    out = {}
    for el in ET.fromstring(text).iter(NS + tag):
        inc = el.get("Include")
        if inc:
            f = el.find(NS + "Filter")
            out[norm(os.path.join(proj_dir, inc))] = f.text.strip() if f is not None and f.text else None
    return out


def filter_names(text):
    return {el.get("Include") for el in ET.fromstring(text).iter(NS + "Filter") if el.get("Include")}


# ----------------------------------------------------------------------------- yazma
def insert_entries(text, tag, lines):
    """lines'i, son <tag Include=...> girdisinin oldugu ItemGroup'un sonuna ekler;
    hic yoksa yeni bir <ItemGroup> acar."""
    if not lines:
        return text
    last = None
    for m in re.finditer(r"^([ \t]*)<" + tag + r"\s+Include=", text, re.M):
        last = m
    if last:
        indent = last.group(1)
        close = text.find("</ItemGroup>", last.end())
        pos = text.rfind("\n", 0, close) + 1
        return text[:pos] + "".join(indent + ln + "\n" for ln in lines) + text[pos:]
    m = re.search(r"^([ \t]*)<Import\s+Project=\"[^\"]*Microsoft\.Cpp\.targets\"", text, re.M) \
        or re.search(r"^[ \t]*</Project>", text, re.M)
    indent = "  "
    pos = m.start()
    block = indent + "<ItemGroup>\n" + "".join(indent * 2 + ln + "\n" for ln in lines) + indent + "</ItemGroup>\n"
    return text[:pos] + block + text[pos:]


def set_filters(text, tag, proj_dir, targets):
    """Var olan <tag Include="X"> girdilerinin filtresini targets[X] yapar."""
    rx = re.compile(r"^([ \t]*)<" + tag + r'\s+Include="([^"]*)"\s*(?:/>|>.*?</' + tag + r">)",
                    re.M | re.S)

    def repl(m):
        indent, inc = m.group(1), m.group(2)
        key = norm(os.path.join(proj_dir, inc.replace("&amp;", "&")))
        if key not in targets:
            return m.group(0)
        return (f'{indent}<{tag} Include="{inc}">\n'
                f"{indent}  <Filter>{q(targets[key])}</Filter>\n"
                f"{indent}</{tag}>")
    return rx.sub(repl, text)


def filter_def(name):
    guid, ext = STD_FILTERS.get(name, (None, None))
    if guid is None:
        import uuid
        guid = "{" + str(uuid.uuid4()).upper() + "}"
    lines = [f'<Filter Include="{q(name)}">', f"  <UniqueIdentifier>{guid}</UniqueIdentifier>"]
    if ext:
        lines.append(f"  <Extensions>{ext}</Extensions>")
    return lines + ["</Filter>"]


# ----------------------------------------------------------------------------- dosya toplama
def collect(inputs, recursive):
    out = []
    for a in inputs:
        if os.path.isdir(a):
            walker = os.walk(a) if recursive else [(a, [], os.listdir(a))]
            files = [os.path.join(d, fn) for d, _, fs in walker for fn in sorted(fs)
                     if fn.lower().endswith(".cpp")]
        else:
            files = sorted(glob.glob(a, recursive=True))
            if not files:
                print(f"[HATA] bulunamadi: {a}", file=sys.stderr)
        for p in files:
            p = os.path.abspath(p)
            if os.path.isfile(p) and p not in out:
                out.append(p)
    return out


def find_project(given):
    if given:
        return given
    found = glob.glob("*.vcxproj")
    if len(found) == 1:
        return found[0]
    sys.exit("[HATA] --proj ile .vcxproj dosyasini belirtin"
             + (f" (bulunanlar: {', '.join(found)})" if found else " (bu klasorde .vcxproj yok)"))


def header_for(cpp):
    stem = os.path.splitext(cpp)[0]
    for e in HEADER_EXTS:
        if os.path.isfile(stem + e):
            return stem + e
    return None


# ----------------------------------------------------------------------------- ana is
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", metavar="CPP_VEYA_KLASOR")
    ap.add_argument("--proj", help=".vcxproj dosyasi (vars.: bu klasordeki tek .vcxproj)")
    ap.add_argument("-r", "--recursive", action="store_true", help="alt klasorleri de tara")
    ap.add_argument("--source-filter", default="Source Files", help='cpp filtresi (vars.: "Source Files")')
    ap.add_argument("--header-filter", default="Header Files", help='header filtresi (vars.: "Header Files")')
    ap.add_argument("--no-headers", action="store_true", help="header'lara hic dokunma, sadece cpp ekle")
    ap.add_argument("--only-with-bak", action="store_true",
                    help="sadece yaninda Foo.h.bak olan Foo.cpp'leri al (split_header.py ciktilari)")
    ap.add_argument("--dry-run", action="store_true", help="dosyalara yazmadan neler yapilacagini goster")
    ap.add_argument("--backup", action="store_true", help=".vcxproj ve .filters'in .bak kopyasini al")
    opt = ap.parse_args()

    proj = os.path.abspath(find_project(opt.proj))
    proj_dir = os.path.dirname(proj)
    fpath = proj + ".filters"
    has_f = os.path.exists(fpath)

    ptext, peol, pbom = read_text(proj)
    p_cpp = entries(ptext, "ClCompile", proj_dir)
    p_hdr = entries(ptext, "ClInclude", proj_dir)
    if has_f:
        ftext, feol, fbom = read_text(fpath)
        f_cpp = entries(ftext, "ClCompile", proj_dir)
        f_hdr = entries(ftext, "ClInclude", proj_dir)

    def rel(p):
        return os.path.relpath(p, proj_dir).replace("/", "\\")

    add_cpp, add_hdr = [], []                 # projeye eklenecek (mutlak yol)
    add_f_cpp, add_f_hdr = [], []             # .filters'a eklenecek
    move = {"ClCompile": {}, "ClInclude": {}}  # filtresi degisecek
    n_ok = 0

    def plan(path, tag, proj_map, filt_map, want, add_list, add_f_list):
        nonlocal n_ok
        key = norm(path)
        changed = False
        if key not in proj_map:
            add_list.append(path)
            print(f"[EKLE]   {rel(path)}  -> {want}")
            changed = True
        if has_f:
            if key not in filt_map:
                add_f_list.append(path)
            elif filt_map[key] != want:
                move[tag][key] = want
                print(f"[TASI]   {rel(path)}  {filt_map[key] or '(filtresiz)'} -> {want}")
                changed = True
        if not changed:
            n_ok += 1

    for cpp in collect(opt.inputs, opt.recursive):
        hdr = header_for(cpp)
        if opt.only_with_bak and not (hdr and os.path.exists(hdr + ".bak")):
            continue
        plan(cpp, "ClCompile", p_cpp, f_cpp if has_f else {}, opt.source_filter, add_cpp, add_f_cpp)
        if hdr and not opt.no_headers:
            plan(hdr, "ClInclude", p_hdr, f_hdr if has_f else {}, opt.header_filter, add_hdr, add_f_hdr)

    if not (add_cpp or add_hdr or add_f_cpp or add_f_hdr or move["ClCompile"] or move["ClInclude"]):
        print(f"Yapilacak bir sey yok ({n_ok} dosya zaten dogru yerde).")
        return

    # --- .vcxproj
    new_p = insert_entries(ptext, "ClCompile", [f'<ClCompile Include="{q(rel(p))}" />' for p in add_cpp])
    new_p = insert_entries(new_p, "ClInclude", [f'<ClInclude Include="{q(rel(p))}" />' for p in add_hdr])
    ET.fromstring(new_p)

    # --- .vcxproj.filters
    if has_f:
        new_f = ftext
        known = filter_names(ftext)
        need = [f for f in (opt.header_filter, opt.source_filter)
                if f not in known and ((f == opt.source_filter and (add_f_cpp or move["ClCompile"]))
                                       or (f == opt.header_filter and (add_f_hdr or move["ClInclude"])))]
        for name in need:
            print(f"[FILTRE] '{name}' olusturuldu")
        new_f = insert_entries(new_f, "Filter", sum((filter_def(n) for n in need), []))
        new_f = set_filters(new_f, "ClCompile", proj_dir, move["ClCompile"])
        new_f = set_filters(new_f, "ClInclude", proj_dir, move["ClInclude"])
        new_f = insert_entries(new_f, "ClCompile", sum(
            ([f'<ClCompile Include="{q(rel(p))}">', f"  <Filter>{q(opt.source_filter)}</Filter>",
              "</ClCompile>"] for p in add_f_cpp), []))
        new_f = insert_entries(new_f, "ClInclude", sum(
            ([f'<ClInclude Include="{q(rel(p))}">', f"  <Filter>{q(opt.header_filter)}</Filter>",
              "</ClInclude>"] for p in add_f_hdr), []))
        ET.fromstring(new_f)

    print(f"\nOzet: projeye {len(add_cpp)} cpp + {len(add_hdr)} header eklendi, "
          f"{len(move['ClCompile']) + len(move['ClInclude'])} dosyanin filtresi degisti, "
          f"{n_ok} dosya zaten dogru yerdeydi."
          + ("" if has_f else f"\n[UYARI] {os.path.basename(fpath)} yok; sadece .vcxproj guncellenir "
                              "(Solution Explorer'da filtresiz gorunur)."))
    if opt.dry_run:
        print("[DRY-RUN: hicbir sey yazilmadi]")
        return
    if opt.backup:
        shutil.copy2(proj, proj + ".bak")
        if has_f:
            shutil.copy2(fpath, fpath + ".bak")
    write_text(proj, new_p, peol, pbom)
    if has_f:
        write_text(fpath, new_f, feol, fbom)
    print(f"Guncellendi: {proj}" + (f"\n             {fpath}" if has_f else ""))


if __name__ == "__main__":
    main()
