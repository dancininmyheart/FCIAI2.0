from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
start = text.find("@main.route('/api/pdf_translation_history')")
end = text.find("@main.route('/api/pdf_translation/delete'", start)
Path('pdf_history_original.txt').write_text(text[start:end], encoding='utf-8')
