from __future__ import annotations

import logging
import os
import re
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from xml.etree import ElementTree

from app.translation.pptx_contract import (
    PPTX_PROVIDER_FIELD,
    PptxContractError,
    parse_pptx_response,
    serialize_pptx_request,
)
from app.translation.pptx_contract_types import PptxRequestUnit, PptxUnitTranslation
from app.translation.providers import ProviderRegistry, default_provider_registry
from app.translation.metrics import current_correlation
from app.translation.types import ProviderError, ProviderRequest


logger = logging.getLogger(__name__)

try:
    from .pptx_xml_ops import (
        extract_structured_units_from_pptx,
        extract_text_boxes_data_from_pptx,
        write_structured_translated_pptx,
        write_translated_pptx_xml,
    )
    from .pptx_xml_types import (
        PageTranslator,
        PptxXmlReadError,
        PptxXmlWriteError,
        ProgressCallback,
        TextBoxData,
        TranslationPageResult,
        XmlTranslationRequest,
    )
except ImportError:
    from app.function.pynuo_fuc.pptx_xml_ops import (
        extract_structured_units_from_pptx,
        extract_text_boxes_data_from_pptx,
        write_structured_translated_pptx,
        write_translated_pptx_xml,
    )
    from app.function.pynuo_fuc.pptx_xml_types import (
        PageTranslator,
        PptxXmlReadError,
        PptxXmlWriteError,
        ProgressCallback,
        TextBoxData,
        TranslationPageResult,
        XmlTranslationRequest,
    )


def translate_pptx_with_xml(
    request: XmlTranslationRequest,
    translator: PageTranslator | None = None,
    *,
    provider_registry: ProviderRegistry | None = None,
) -> str:
    engine = os.getenv("PPTX_XML_ENGINE", "structured_v2").strip().lower()
    if translator is None and engine != "legacy":
        if engine != "structured_v2":
            raise PptxContractError("engine_config", "unsupported PPTX XML engine")
        return _translate_pptx_structured(
            request,
            provider_registry or default_provider_registry(),
        )

    try:
        text_boxes = extract_text_boxes_data_from_pptx(
            request.input_path,
            request.selected_page_indices,
        )
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise PptxXmlReadError("legacy XML extraction failed") from exc
    if not text_boxes:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(request.input_path, request.output_path)
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
    try:
        return write_translated_pptx_xml(
            request.input_path,
            request.output_path,
            text_boxes,
            translation_results,
            request.bilingual_translation,
        )
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise PptxXmlWriteError("legacy XML writeback failed") from exc


def _translate_pptx_structured(
    request: XmlTranslationRequest,
    registry: ProviderRegistry,
) -> str:
    units = extract_structured_units_from_pptx(
        request.input_path,
        request.selected_page_indices,
        source_language=request.source_language,
        target_language=request.target_language,
        stop_words=request.stop_words,
        custom_translations=request.custom_translations,
    )
    if not units:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(request.input_path, request.output_path)
        return str(request.output_path)

    batches = _slide_batches(units)
    translations: list[PptxUnitTranslation] = []
    for current, batch in enumerate(batches, 1):
        translations.extend(_translate_structured_batch(request, registry, batch))
        if request.progress_callback is not None:
            request.progress_callback(current, len(batches))
    return write_structured_translated_pptx(
        request.input_path,
        request.output_path,
        tuple(translations),
        request.bilingual_translation,
    )


def _translate_structured_batch(
    request: XmlTranslationRequest,
    registry: ProviderRegistry,
    units: tuple[PptxRequestUnit, ...],
) -> tuple[PptxUnitTranslation, ...]:
    provider_request = ProviderRequest.create(
        text=serialize_pptx_request(units),
        source_language=request.source_language,
        target_language=request.target_language,
        field=PPTX_PROVIDER_FIELD,
        stop_words=tuple(request.stop_words),
        custom_translations=dict(request.custom_translations),
        output_format="structured",
    )
    last_contract_error: PptxContractError | None = None
    for attempt in range(2):
        try:
            response = registry.translate(request.model, provider_request)
        except ProviderError as error:
            if attempt == 0 and error.retryable:
                continue
            raise
        try:
            return parse_pptx_response(response.text, units)
        except PptxContractError as error:
            last_contract_error = error
            correlation = current_correlation(request.model)
            logger.warning(
                "pptx_contract_rejected job_id=%s contract_attempt=%d first_unit=%s error_code=%s response_chars=%d",
                correlation.public_job_id,
                attempt + 1,
                units[0].unit_id,
                error.code,
                len(response.text),
            )
            if attempt == 0:
                continue
            raise
    if last_contract_error is not None:
        raise last_contract_error
    raise PptxContractError("provider_failure", "provider did not return a response")


def _slide_batches(
    units: tuple[PptxRequestUnit, ...],
) -> tuple[tuple[PptxRequestUnit, ...], ...]:
    batches: list[list[PptxRequestUnit]] = []
    current_slide = ""
    for unit in units:
        match = re.match(r"pptx:slide(\d+):", unit.unit_id)
        slide = match.group(1) if match is not None else unit.unit_id
        if slide != current_slide:
            batches.append([])
            current_slide = slide
        batches[-1].append(unit)
    return tuple(tuple(batch) for batch in batches)


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
        from app.function.pynuo_fuc.api_translate_uno import translate_pages_by_page

    return translate_pages_by_page(
        text_boxes_data,
        progress_callback,
        source_language,
        target_language,
        model,
        list(stop_words_list),
        dict(custom_translations),
    )
