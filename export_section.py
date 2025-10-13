from pathlib import Path
text = Path('original_main.py').read_text(encoding='utf-16')
start = text.find("@main.route('/download_translated_pdf/<filename>')")
end = text.find("@main.route('/api/pdf_translation/delete'", start)
Path('download_original_section.txt').write_text(text[start:end], encoding='utf-8')
