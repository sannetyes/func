import os
import re
import csv

# ---------------------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------------------
OUTPUT_BASENAME = "proje_fonksiyon_listesi"

# "xlsx" -> gercek Excel dosyasi (harici kutuphane gerekmez, sadece zipfile)
# "csv"  -> noktali virgullu, BOM'lu CSV
OUTPUT_FORMAT = "xlsx"

# True  -> icinde bulundugu namespace/class ismi basa eklenir: ns::Foo::bar
# False -> kaynakta yazildigi gibi birakilir:                  bar
QUALIFY_WITH_SCOPE = True

EXTENSIONS = {'.cpp'}
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


def _xml_escape(value):
    """XML'de gecersiz olan kontrol karakterlerini atar, ozel karakterleri kacirir."""
    text = str(value)
    text = ''.join(c for c in text if c in '\t\n\r' or ord(c) >= 0x20)
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))


def _col_letter(index):
    """0 -> A, 1 -> B, ... 26 -> AA"""
    letters = ''
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def write_xlsx(path, header, rows, sheet_name="Fonksiyonlar", widths=None):
    """
    Harici kutuphane KULLANMADAN .xlsx yazar.
    Bir xlsx dosyasi aslinda icinde XML bulunan bir ZIP arsividir; standart
    kutuphanedeki zipfile modulu yeterli.
    """
    import zipfile

    all_rows = [header] + [list(r) for r in rows]
    n_rows = len(all_rows)
    n_cols = len(header)
    last_ref = f"{_col_letter(n_cols - 1)}{n_rows}"

    # --- sayfa (worksheet) ---
    cols_xml = ''
    if widths:
        parts = ''.join(
            f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)
        )
        cols_xml = f'<cols>{parts}</cols>'

    body = []
    for r_i, row in enumerate(all_rows, start=1):
        cells = []
        for c_i, value in enumerate(row):
            ref = f"{_col_letter(c_i)}{r_i}"
            style = ' s="1"' if r_i == 1 else ''
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{ref}"{style} t="inlineStr">'
                    f'<is><t xml:space="preserve">{_xml_escape(value)}</t></is></c>'
                )
        body.append(f'<row r="{r_i}">{"".join(cells)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last_ref}"/>'
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'{cols_xml}'
        f'<sheetData>{"".join(body)}</sheetData>'
        f'<autoFilter ref="A1:{last_ref}"/>'
        '</worksheet>'
    )

    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '</cellXfs>'
        '<cellStyles count="1">'
        '<cellStyle name="Normal" xfId="0" builtinId="0"/>'
        '</cellStyles>'
        '</styleSheet>'
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        z.writestr('xl/styles.xml', styles)
        z.writestr('xl/worksheets/sheet1.xml', sheet)


def write_output(rows):
    header = ["Directory Name", "Class/File Name", "Function Name", "Line Number"]

    if OUTPUT_FORMAT == "csv":
        path = OUTPUT_BASENAME + ".csv"
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(header)
            writer.writerows(rows)
        return path

    path = OUTPUT_BASENAME + ".xlsx"
    write_xlsx(path, header, rows, widths=(28, 24, 70, 12))
    return path


def parse_project(root_dir):
    rows, file_count = collect(root_dir)
    path = write_output(rows)
    print(f"Bitti! Toplam {file_count} dosyada {len(rows)} fonksiyon "
          f"'{path}' dosyasina kaydedildi.")


if __name__ == "__main__":
    parse_project(os.getcwd())
