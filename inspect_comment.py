from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
index = text.find('# 检查文件是否仍然存在')
print(index)
print(repr(text[index:index+80]))
