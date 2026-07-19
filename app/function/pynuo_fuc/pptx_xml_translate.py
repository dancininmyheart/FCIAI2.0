from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence

try:
    from .pptx_xml_ops import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )
    from .pptx_xml_types import (
        PageTranslator,
        ProgressCallback,
        TextBoxData,
        TranslationPageResult,
        XmlTranslationRequest,
    )
except ImportError:
    from pptx_xml_ops import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )
    from pptx_xml_types import (
        PageTranslator,
        ProgressCallback,
        TextBoxData,
        TranslationPageResult,
        XmlTranslationRequest,
    )


def translate_pptx_with_xml(
    request: XmlTranslationRequest,
    translator: PageTranslator | None = None,
) -> str:
    text_boxes = extract_text_boxes_data_from_pptx(
        request.input_path,
        request.selected_page_indices,
    )
    if not text_boxes:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(request.input_path, request.output_path)
        return str(request.output_path)

    page_translator = translator or _translate_pages_by_page
    translation_results = page_translator(
        text_boxes,
        request.progress_callback,
        request.source_language,
        request.target_language,
        request.model,
        request.stop_words,
        request.custom_translations,
    )
    return write_translated_pptx_xml(
        request.input_path,
        request.output_path,
        text_boxes,
        translation_results,
        request.bilingual_translation,
    )


def _translate_pages_by_page(
    text_boxes_data: list[TextBoxData],
    progress_callback: ProgressCallback | None,
    source_language: str,
    target_language: str,
    model: str,
    stop_words_list: Sequence[str],
    custom_translations: Mapping[str, str],
) -> Mapping[int, TranslationPageResult]:
    try:
        from .api_translate_uno import translate_pages_by_page
    except ImportError:
        from api_translate_uno import translate_pages_by_page

    return translate_pages_by_page(
        text_boxes_data,
        progress_callback,
        source_language,
        target_language,
        model,
        list(stop_words_list),
        dict(custom_translations),
    )
