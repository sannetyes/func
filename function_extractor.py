import os
import re
import csv

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------
OUTPUT_BASENAME = "proje_fonksiyon_listesi"

# True  -> icinde bulundugu namespace/class ismi basa eklenir: ns::Foo::bar
# False -> kaynakta yazildigi gibi birakilir:                  bar
QUALIFY_WITH_SCOPE = True

EXTENSIONS = {'.cpp', '.c', '.cxx', '.cc', '.h', '.hpp'}
IGNORE_DIRS = {'.git', '.vs', 'build', 'bin', 'obj', 'out', 'x64',
               'Debug', 'Release', 'node_modules'}

# ---------------------------------------------------------------------------
# `operator` anahtar kelimesinden sonra gelebilecek her sey.
# SIRA ONEMLI: uzun tokenlar once gelmeli, yoksa <=> ikiye bolunur.
# ---------------------------------------------------------------------------
OPERATOR_TOKEN = r'''
    (?:
        \(\s*\)                                  # operator()
      | \[\s*\]                                  # operator[]
      | new\s*\[\s*\] | delete\s*\[\s*\]
      | new\b | delete\b
      | <=>
      | <<=? | >>=?
      | ->\*? | \+\+ | --
      | && | \|\|
      | [-+*/%^&|~!<>=]=?
      | ,
      | ""\s*\w+                                 # user-defined literal
      | [A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*(?:\s*<[^<>;{}]*>)?[\s*&]*
    )                                            # operator bool, operator ns::T&
'''

# ns::  /  Foo::  /  Foo<int>::   -> tekrarlanabilir
QUALIFIER = r'(?:[A-Za-z_]\w*\s*(?:<[^<>;{}]*>)?\s*::\s*)*'

FUNC_REGEX = re.compile(
    r'''
    (?:template\s*<[^>]*>\s*)?
    # Donus tipi. Lookahead `operator` kelimesini yutmasini engeller,
    # yoksa `Foo::operator bool()` -> `bool()` olarak okunur.
    (?:(?!operator\b)[A-Za-z_]\w*
       (?:\s*::\s*(?!operator\b)[A-Za-z_]\w*)*
       (?:\s*<[^<>;{}]*>)?[\s*&]+)?
    (?P<func_name>
        ''' + QUALIFIER + r'''
        (?:
            operator\s*''' + OPERATOR_TOKEN + r'''
          | ~\s*[A-Za-z_]\w*                     # yikici (destructor)
          | [A-Za-z_]\w*                         # normal fonksiyon / kurucu
        )
    )
    \s*\((?P<params>[^;{}]*?)\)
    (?:\s*(?:const|noexcept(?:\s*\([^()]*\))?|override|final|volatile|&&?|
             throw\s*\([^()]*\)))*
    (?:\s*->\s*[^{;]+)?                          # trailing return type
    (?:\s*:\s*[^{;]+)?                           # kurucu init listesi
    \s*\{
    ''',
    re.VERBOSE | re.MULTILINE
)

# Yalnizca son bir emniyet suzgeci. Asil filtreleme parantez derinligi ile
# yapiliyor, bu liste sadece uc durumlar icin.
KEYWORDS = {
    'if', 'else', 'for', 'while', 'switch', 'case', 'default', 'do', 'try',
    'catch', 'return', 'throw', 'sizeof', 'decltype', 'alignof', 'typeid',
    'static_assert', 'and', 'or', 'not', 'new', 'delete', 'typedef', 'using',
    'namespace', 'class', 'struct', 'union', 'enum', 'template',
}


# ---------------------------------------------------------------------------
# ON TEMIZLIK
# ---------------------------------------------------------------------------
def remove_comments_and_strings(source):
    """// ve /* */ yorumlarini ve tirnak icini siler. Satir sayisi korunur."""
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )

    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            # satir numaralari kaymasin diye \n karakterleri korunuyor
            return ''.join(c if c == '\n' else ' ' for c in s)
        return '""' if s.startswith('"') else "''"

    return re.sub(pattern, replacer, source)


def remove_preprocessor(source):
    """#define / #if gibi satirlari siler (icindeki suslu parantezler sayimi bozar)."""
    lines = source.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith('#'):
            out.append('')
            while line.rstrip().endswith('\\') and i + 1 < len(lines):
                i += 1
                line = lines[i]
                out.append('')
        else:
            out.append(line)
        i += 1
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# BLOK SINIFLANDIRMA
# ---------------------------------------------------------------------------
def scope_name(segment, kind):
    """namespace / class blogunun ismini cikarir."""
    if kind == 'namespace':
        m = re.search(r'\bnamespace\s+([A-Za-z_][\w:]*)', segment)
        return m.group(1) if m else ''
    m = re.search(r'\b(?:class|struct|union)\b([^:{]*)', segment)
    if m:
        names = re.findall(r'[A-Za-z_]\w*', m.group(1))
        names = [n for n in names if n not in ('final', 'alignas')]
        if names:
            return names[-1]
    return ''


def classify(segment):
    """Bir '{' karakterini neyin actigini belirler."""
    m = FUNC_REGEX.search(segment)
    if m and m.end() == len(segment):
        return 'function', m
    if re.search(r'\bnamespace\b', segment) or re.search(r'\bextern\b', segment):
        return 'namespace', None
    if re.search(r'\b(?:class|struct|union|enum)\b', segment):
        return 'record', None
    return 'other', None


def find_functions(text):
    """
    Parantez derinligini takip ederek yalnizca gercek fonksiyon tanimlarini
    dondurur. Fonksiyon govdesinin ICINDE kalan her sey (if/for/switch/case,
    lambda, ic ice blok) otomatik olarak elenir.
    """
    results = []
    stack = []      # [(kind, name), ...]
    anchor = 0

    for i, ch in enumerate(text):
        if ch == '{':
            segment = text[anchor:i + 1]
            kind, m = classify(segment)

            # sadece namespace / class icinde duran tanimlar kabul edilir
            if kind == 'function' and all(k in ('namespace', 'record')
                                          for k, _ in stack):
                scopes = [n for _, n in stack if n]
                results.append((m, anchor + m.start(), scopes))

            name = scope_name(segment, kind) if kind in ('namespace', 'record') else ''
            stack.append((kind, name))
            anchor = i + 1

        elif ch == '}':
            if stack:
                stack.pop()
            anchor = i + 1

        elif ch == ';':
            anchor = i + 1

    return results


def normalize(name):
    """'operator !=' -> 'operator!=', 'ns :: f' -> 'ns::f', '~ Foo' -> '~Foo'."""
    name = ' '.join(name.split())
    name = re.sub(r'\s*::\s*', '::', name)
    name = re.sub(r'~\s+', '~', name)
    name = re.sub(r'operator\s+(?=[^\w\s])', 'operator', name)
    return name


# ---------------------------------------------------------------------------
# ANA ISLEM
# ---------------------------------------------------------------------------
def collect(root_dir):
    rows = []
    files_with_funcs = set()

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in sorted(files):
            if not any(file.endswith(ext) for ext in EXTENSIONS):
                continue

            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, root_dir)

            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    raw = f.read()
            except Exception:
                continue

            clean = remove_preprocessor(remove_comments_and_strings(raw))

            directory_name = os.path.dirname(rel_path) or "."
            file_name = os.path.basename(rel_path)

            for m, abs_start, scopes in find_functions(clean):
                func_name = normalize(m.group('func_name'))

                tail = func_name.split('::')[-1].lstrip('~')
                if tail in KEYWORDS:
                    continue

                if QUALIFY_WITH_SCOPE and '::' not in func_name and scopes:
                    func_name = '::'.join(scopes + [func_name])

                params = " ".join((m.group('params') or "").split())
                combined = f"{func_name}({params})"
                line_num = clean[:abs_start].count('\n') + 1

                rows.append([directory_name, file_name, combined, line_num])
                files_with_funcs.add(rel_path)

    return rows, len(files_with_funcs)


def write_output(rows):
    header = ["Directory Name", "Class/File Name", "Function Name", "Line Number"]
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Fonksiyonlar"
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append(row)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col, width in zip("ABCD", (28, 24, 70, 12)):
            ws.column_dimensions[col].width = width

        path = OUTPUT_BASENAME + ".xlsx"
        wb.save(path)
        return path
    except ImportError:
        path = OUTPUT_BASENAME + ".csv"
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(header)
            writer.writerows(rows)
        return path


def parse_project(root_dir):
    rows, file_count = collect(root_dir)
    path = write_output(rows)
    print(f"Bitti! Toplam {file_count} dosyada {len(rows)} fonksiyon "
          f"'{path}' dosyasina kaydedildi.")


if __name__ == "__main__":
    parse_project(os.getcwd())
