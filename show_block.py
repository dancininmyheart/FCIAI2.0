from pathlib import Path
import re
text = Path('original_main.py').read_text(encoding='utf-16')
pattern = r"# 检查文件是否仍然存在\s*\n\s*file_path = os.path.join\(record.file_path, record.stored_filename\)\s*\n\s*file_exists = os.path.exists\(file_path\)"
match = re.search(pattern, text)
print('found' if match else 'not found')
if match:
    print(repr(text[match.start():match.end()]))
