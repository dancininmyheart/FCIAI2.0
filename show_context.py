from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
index = text.find('record.stored_filename')
print(index)
print(repr(text[index-120:index+80]))
