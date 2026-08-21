import os
import re
import csv

# Çok satırlı (multiline) fonksiyon gövdelerini yakalayan gelişmiş regex
FUNC_REGEX = re.compile(
    r'''
    (?:template\s*<[^>]*>\s*)?                 
    (?:[a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)*\s+)?    
    (?P<func_name>[a-zA-Z_]\w*(?:::[~a-zA-Z_]\w*)+|[a-zA-Z_]\w*) 
    \s*\((?P<params>[^;]*?)\)                  
    (?:\s*const|\s*noexcept|\s*override|\s*final)* 
    (?:\s*->\s*[^{;]+)?                        
    (?:\s*:\s*[^{;]+)?                         
    \s*\{                                      
    ''',
    re.VERBOSE | re.MULTILINE
)

EXTENSIONS = {'.cpp'}
IGNORE_DIRS = {'.git', '.vs', 'build', 'bin', 'obj', 'out', 'x64', 'Debug', 'Release', 'node_modules'}

def remove_comments_and_strings(source):
    """Yorum satırlarını (// ve /* */) ve tırnak içindeki stringleri temizler."""
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " " 
        else:
            return s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, source)

def parse_project(root_dir):
    csv_filename = "proje_fonksiyon_listesi.csv"
    total_funcs = 0
    total_files = 0
    keywords = {'if', 'for', 'while', 'switch', 'catch', 'sizeof', 'decltype'}

    # CSV dosyasını yazma modunda aç
    with open(csv_filename, mode='w', newline='', encoding='utf-8-sig') as csv_file:
        writer = csv.writer(csv_file, delimiter=';') # Excel'de sütunların düzgün ayrılması için noktalı virgül (;) kullanıyoruz
        
        # CSV Başlık (Header) satırını yaz
        writer.writerow(["Directory Name", "Class/File Name", "Function Name", "Line Number"])

        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in sorted(files):
                if any(file.endswith(ext) for ext in EXTENSIONS):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, root_dir)
                    
                    try:
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                            raw_content = f.read()
                    except Exception:
                        continue

                    clean_content = remove_comments_and_strings(raw_content)
                    
                    # Dizin adını ve Dosya adını ayır
                    directory_name = os.path.dirname(rel_path)
                    if not directory_name:
                        directory_name = "." # Dosya ana dizindeyse
                        
                    file_name = os.path.basename(rel_path)
                    file_has_functions = False

                    for match in FUNC_REGEX.finditer(clean_content):
                        func_name = match.group('func_name').strip()
                        
                        if func_name in keywords:
                            continue

                        line_num = raw_content[:match.start()].count('\n') + 1
                        
                        # CSV'ye yeni bir satır ekle
                        writer.writerow([directory_name, file_name, func_name, line_num])
                        
                        total_funcs += 1
                        file_has_functions = True
                        
                    if file_has_functions:
                        total_files += 1
                        
    print(f"Bitti! Toplam {total_files} dosyada {total_funcs} fonksiyon '{csv_filename}' dosyasına CSV formatında kaydedildi.")

if __name__ == "__main__":
    parse_project(os.getcwd())
