from pathlib import Path
import re
text = Path('original_main.py').read_text(encoding='utf-16')
for m in re.finditer(r"datetime.now\(\).strftime\('%Y%m%d_%H%M%S'\)", text):
    start = max(0, m.start()-100)
    end = m.end()+100
    snippet = text[start:end]
    print('---')
    print(repr(snippet))
