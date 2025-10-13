from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
s = "            # 检查文件是否仍然存在\n            file_path = os.path.join(record.file_path, record.stored_filename)\n            file_exists = os.path.exists(file_path)\n"
print('found' if s in text else 'not found')
