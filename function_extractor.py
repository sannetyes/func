import os
import re

# Fonksiyon gövdesi tanımlarını yakalayan regex
FUNC_PATTERN = re.compile(
    r'^\s*(?:[\w:<>&*~]+\s+)+(\w+(?:::~\w+|::\w+)?)\s*\([^;]*\)(?:\s*const)?\s*(?:noexcept)?\s*\{'
)

EXTENSIONS = {'.cpp', '.c', '.cxx', '.cc'} # İsteğe göre .h, .hpp ekleyebilirsiniz

def parse_project(root_dir):
    output_lines = []
    
    for root, _, files in os.walk(root_dir):
        for file in sorted(files):
            if any(file.endswith(ext) for ext in EXTENSIONS):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                
                file_functions = []
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, start=1):
                            if FUNC_PATTERN.match(line):
                                clean_line = line.strip().rstrip('{').strip()
                                file_functions.append((line_num, clean_line))
                except Exception as e:
                    continue

                if file_functions:
                    output_lines.append(f"📁 {rel_path}")
                    for line_num, func_sig in file_functions:
                        output_lines.append(f"   ├── L{line_num}: {func_sig}")
                    output_lines.append("")

    with open("proje_fonksiyon_agaci.txt", "w", encoding="utf-8") as out:
        out.write("\n".join(output_lines))
    print("Hiyerarşik fonksiyon ağacı 'proje_fonksiyon_agaci.txt' dosyasına kaydedildi.")

if __name__ == "__main__":
    parse_project(os.getcwd())
