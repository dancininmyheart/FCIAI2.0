from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
pattern = "file_exists = os.path.exists(os.path.join(record.file_path, record.stored_filename))"
print(text.count(pattern))
