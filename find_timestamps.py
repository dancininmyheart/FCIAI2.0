from pathlib import Path
import re
text = Path('original_main.py').read_text(encoding='utf-16')
indices = [m.start() for m in re.finditer(r"datetime.now\(\).strftime\('%Y%m%d_%H%M%S'\)", text)]
print(len(indices))
