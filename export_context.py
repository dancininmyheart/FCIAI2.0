from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
index = text.find('record.stored_filename')
Path('context.txt').write_text(text[index-200:index+200], encoding='utf-8')
