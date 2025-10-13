from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
start = text.find("@main.route('/download_translated_pdf/<filename>')")
end = text.find("@main.route('/api/pdf_translation/delete'", start)
print(repr(text[start:end]))
