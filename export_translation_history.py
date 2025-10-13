from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
start = text.find("@main.route('/api/translation_history')")
end = text.find("@main.route('/api/pdf_translation_history'", start)
Path('translation_history_original.txt').write_text(text[start:end], encoding='utf-8')
