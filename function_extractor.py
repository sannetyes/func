import os
import re

# Çok satırlı (multiline) fonksiyon gövdelerini yakalayan gelişmiş regex
# 1. Yorum satırlarını ve stringleri temizler
# 2. Çok satırlı fonksiyon tanımlarını ve Constructor/Destructor yapılarını yakalar
FUNC_REGEX = re.compile(
    r'''
    (?:template\s*<[^>]*>\s*)?                 # Varsa template tanımı
    (?:[a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)*\s+)?    # Dönüş tipi (Constructor değilse)
    (?P<func_name>[a-zA-Z_]\w*(?:::[~a-zA-Z_]\w*)+|[a-zA-Z_]\w*) # Fonksiyon/Metot adı (ClassName::Method)
    \s*\((?P<params>[^;]*?)\)                  # Parametreler (parantez içi)
    (?:\s*const|\s*noexcept|\s*override|\s*final)* # Niteleyiciler
    (?:\s*->\s*[^{;]+)?                        # Trailing return type (C++11+)
    (?:\s*:\s*[^{;]+)?                         # Constructor Initializer List (: a(1), b(2))
    \s*\{                                      # Fonksiyon gövdesinin açılış parantezi
    ''',
    re.VERBOSE | re.MULTILINE
)

EXTENSIONS = {'.cpp', '.c', '.cxx', '.cc', '.h', '.hpp'}
IGNORE_DIRS = {'.git', '.vs', 'build', 'bin', 'obj', 'out', 'x64', 'Debug', 'Release', 'node_modules'}

def remove_comments_and_strings(source):
    """Yorum satırlarını (// ve /* */) ve tırnak içindeki stringleri temizler."""
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " "  # Yorum yerine boşluk bırak (satır düzeni için)
        else:
            return s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, source)

def parse_project(root_dir):
    output_lines = []
    total_funcs = 0
    total_files = 0
    
    # Sadece fonksiyon olarak kabul edilmeyecek C++ anahtar kelimeleri
    keywords = {'if', 'for', 'while', 'switch', 'catch', 'sizeof', 'decltype'}

    for root, dirs, files in os.walk(root_dir):
        # Gereksiz derleme klasörlerini atla
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
                file_functions = []

                for match in FUNC_REGEX.finditer(clean_content):
                    func_name = match.group('func_name').strip()
                    
                    # if, for, while gibi kontrol bloklarını filtrele
                    if func_name in keywords:
                        continue

                    # Karakter indeksinden satır numarasını hesapla
                    line_num = raw_content[:match.start()].count('\n') + 1
                    
                    # Eşleşen fonksiyon imzasını tek satırda temizle
                    raw_sig = match.group(0).rstrip('{').strip()
                    clean_sig = " ".join(raw_sig.split()) # Çok satırı tek satıra indir
                    
                    file_functions.append((line_num, clean_sig))

                if file_functions:
                    total_files += 1
                    total_funcs += len(file_functions)
                    output_lines.append(f"📁 {rel_path}")
                    for line_num, sig in file_functions:
                        output_lines.append(f"   ├── L{line_num:4d}: {sig}")
                    output_lines.append("")

    summary = f"Toplam {total_files} dosyada {total_funcs} fonksiyon tespit edildi.\n" + "="*50 + "\n\n"
    final_output = summary + "\n".join(output_lines)
    
    with open("proje_fonksiyon_agaci.txt", "w", encoding="utf-8") as out:
        out.write(final_output)
        
    print(f"Bitti! Toplam {total_files} dosyada {total_funcs} fonksiyon 'proje_fonksiyon_agaci.txt' dosyasına kaydedildi.")

if __name__ == "__main__":
    parse_project(os.getcwd())
