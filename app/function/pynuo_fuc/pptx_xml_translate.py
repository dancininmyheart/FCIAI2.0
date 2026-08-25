from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from xml.etree import ElementTree

from app.translation.pptx_contract import (
    PPTX_DOCUMENT_KIND,
    PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION,
    PPTX_PROVIDER_FIELD,
    PPTX_PROVIDER_REPAIR_FIELD,
    PptxContractError,
    parse_pptx_response,
    parse_pptx_response_structure,
    recover_single_unit_segment_count_response,
    serialize_pptx_request,
    validate_unit_translation_quality,
)
from app.translation.pptx_contract_types import PptxRequestUnit, PptxUnitTranslation
from app.translation.domain import build_presentation_domain_sample, detect_presentation_domain
from app.translation.providers import ProviderRegistry, default_provider_registry
from app.translation.metrics import current_correlation
from app.translation.types import ProviderError, ProviderRequest, ProviderResult


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
    semantic_qa_mode = _pptx_semantic_qa_mode()
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
    domain_sample = build_presentation_domain_sample(
        "\n".join(unit.source_text for unit in batch)
        for batch in batches
    )
    domain = detect_presentation_domain(registry, domain_sample, request.source_language)
    translations: list[PptxUnitTranslation] = []
    for current, batch in enumerate(batches, 1):
        translations.extend(
            _translate_structured_batch(
                request,
                registry,
                batch,
                domain,
                semantic_qa_mode,
            ),
        )
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
    domain: str,
    semantic_qa_mode: str,
) -> tuple[PptxUnitTranslation, ...]:
    provider_request = ProviderRequest.create(
        text=serialize_pptx_request(units, domain=domain),
        source_language=request.source_language,
        target_language=request.target_language,
        field=PPTX_PROVIDER_FIELD,
        domain=domain,
        stop_words=tuple(request.stop_words),
        custom_translations=dict(request.custom_translations),
        timeout_seconds=request.provider_timeout_seconds,
        output_format="structured",
    )
    last_contract_error: PptxContractError | None = None
    for contract_attempt in range(2):
        try:
            response = _translate_provider_request(
                request,
                registry,
                provider_request,
                units,
            )
        except ProviderError as error:
            if error.code == "provider_timeout" and error.retryable and len(units) > 1:
                midpoint = len(units) // 2
                logger.warning(
                    "pptx_provider_timeout_split job_id=%s units=%d left=%d right=%d "
                    "request_chars=%d timeout_seconds=%.3f",
                    current_correlation(request.model).public_job_id,
                    len(units),
                    midpoint,
                    len(units) - midpoint,
                    len(provider_request.text),
                    provider_request.timeout_seconds,
                )
                return (
                    _translate_structured_batch(
                        request,
                        registry,
                        units[:midpoint],
                        domain,
                        semantic_qa_mode,
                    )
                    + _translate_structured_batch(
                        request,
                        registry,
                        units[midpoint:],
                        domain,
                        semantic_qa_mode,
                    )
                )
            raise
        try:
            translations = parse_pptx_response_structure(response.text, units)
        except PptxContractError as error:
            last_contract_error = error
            _log_contract_rejection(request, error, contract_attempt + 1, len(response.text))
            if len(units) > 1:
                midpoint = len(units) // 2
                logger.info(
                    "pptx_contract_split job_id=%s units=%d left=%d right=%d error_code=%s",
                    current_correlation(request.model).public_job_id,
                    len(units),
                    midpoint,
                    len(units) - midpoint,
                    error.code,
                )
                return (
                    _translate_structured_batch(
                        request,
                        registry,
                        units[:midpoint],
                        domain,
                        semantic_qa_mode,
                    )
                    + _translate_structured_batch(
                        request,
                        registry,
                        units[midpoint:],
                        domain,
                        semantic_qa_mode,
                    )
                )
            if contract_attempt == 0:
                provider_request = _repair_provider_request(
                    request,
                    provider_request.text,
                    response.text,
                    error,
                    domain,
                )
                continue
            recovery = (
                recover_single_unit_segment_count_response(response.text, units[0])
                if error.code == "segment_count"
                else None
            )
            if recovery is None:
                raise
            recovered, actual_segments = recovery
            translations = (recovered,)
            _log_segment_count_recovery(
                request,
                recovered.unit_id,
                len(units[0].text_items),
                actual_segments,
            )
        if semantic_qa_mode == "off":
            return translations
        quality_errors = _quality_errors(units, translations)
        if not quality_errors:
            return translations
        if semantic_qa_mode == "observe":
            for error in quality_errors:
                _log_quality_observation(request, error)
            return translations
        for error in quality_errors:
            _log_contract_rejection(request, error, contract_attempt + 1, len(response.text))
        return _repair_quality_failures(
            request,
            registry,
            units,
            translations,
            quality_errors,
            domain,
        )
    if last_contract_error is not None:
        raise last_contract_error
    raise PptxContractError("provider_failure", "provider did not return a response")


def _translate_provider_request(
    request: XmlTranslationRequest,
    registry: ProviderRegistry,
    provider_request: ProviderRequest,
    units: tuple[PptxRequestUnit, ...],
) -> ProviderResult:
    for provider_attempt in range(2):
        try:
            return registry.translate(request.model, provider_request)
        except ProviderError as error:
            should_retry = provider_attempt == 0 and error.retryable
            if error.code == "provider_timeout" and len(units) > 1:
                should_retry = False
            if not should_retry:
                raise
            logger.warning(
                "pptx_provider_retry job_id=%s provider=%s attempt=%d unit_id=%s "
                "error_code=%s request_chars=%d timeout_seconds=%.3f",
                current_correlation(request.model).public_job_id,
                error.provider,
                provider_attempt + 1,
                units[0].unit_id if len(units) == 1 else "multiple",
                error.code,
                len(provider_request.text),
                provider_request.timeout_seconds,
            )
    raise AssertionError("provider retry loop exhausted without a result")


def _pptx_semantic_qa_mode() -> str:
    configured: object | None = None
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            configured = current_app.config.get("PPTX_SEMANTIC_QA_MODE")
    except (ImportError, RuntimeError):
        configured = None
    if configured is None:
        configured = os.getenv("PPTX_SEMANTIC_QA_MODE", "enforce")
    normalized = str(configured).strip().lower()
    return normalized if normalized in ("off", "observe") else "enforce"


def _quality_errors(
    units: tuple[PptxRequestUnit, ...],
    translations: tuple[PptxUnitTranslation, ...],
) -> tuple[PptxContractError, ...]:
    errors: list[PptxContractError] = []
    for unit, translation in zip(units, translations, strict=True):
        try:
            validate_unit_translation_quality(unit, translation)
        except PptxContractError as error:
            errors.append(error)
    return tuple(errors)


def _repair_quality_failures(
    request: XmlTranslationRequest,
    registry: ProviderRegistry,
    units: tuple[PptxRequestUnit, ...],
    translations: tuple[PptxUnitTranslation, ...],
    quality_errors: tuple[PptxContractError, ...],
    domain: str,
) -> tuple[PptxUnitTranslation, ...]:
    errors_by_unit = {error.unit_id: error for error in quality_errors}
    repaired: list[PptxUnitTranslation] = []
    for unit, translation in zip(units, translations, strict=True):
        error = errors_by_unit.get(unit.unit_id)
        if error is None:
            repaired.append(translation)
            continue
        source_contract = serialize_pptx_request((unit,), domain=domain)
        repair_request = _repair_provider_request(
            request,
            source_contract,
            _serialize_candidate_response(translation),
            error,
            domain,
        )
        response = _translate_provider_request(
            request,
            registry,
            repair_request,
            (unit,),
        )
        try:
            repaired.append(parse_pptx_response(response.text, (unit,))[0])
        except PptxContractError as repair_error:
            _log_contract_rejection(request, repair_error, 2, len(response.text))
            raise
    return tuple(repaired)


def _serialize_candidate_response(translation: PptxUnitTranslation) -> str:
    return json.dumps(
        {
            "provider_contract_schema_version": PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION,
            "document_kind": PPTX_DOCUMENT_KIND,
            "translations": [
                {
                    "unit_id": translation.unit_id,
                    "target_text": translation.target_text,
                    "segments": [
                        {
                            "segment_id": segment.segment_id,
                            "target_text": segment.target_text,
                        }
                        for segment in translation.segments
                    ],
                },
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _log_contract_rejection(
    request: XmlTranslationRequest,
    error: PptxContractError,
    attempt: int,
    response_characters: int,
) -> None:
    correlation = current_correlation(request.model)
    logger.warning(
        "pptx_contract_rejected job_id=%s contract_attempt=%d unit_id=%s error_code=%s response_chars=%d",
        correlation.public_job_id,
        attempt,
        error.unit_id,
        error.code,
        response_characters,
    )


def _log_quality_observation(
    request: XmlTranslationRequest,
    error: PptxContractError,
) -> None:
    correlation = current_correlation(request.model)
    logger.warning(
        "pptx_quality_observed job_id=%s unit_id=%s error_code=%s",
        correlation.public_job_id,
        error.unit_id,
        error.code,
    )


def _log_segment_count_recovery(
    request: XmlTranslationRequest,
    unit_id: str,
    expected_segments: int,
    actual_segments: int,
) -> None:
    correlation = current_correlation(request.model)
    logger.warning(
        "pptx_segment_count_recovered job_id=%s unit_id=%s expected_segments=%d actual_segments=%d strategy=longest_source_run",
        correlation.public_job_id,
        unit_id,
        expected_segments,
        actual_segments,
    )


def _repair_provider_request(
    request: XmlTranslationRequest,
    source_contract: str,
    candidate_response: str,
    error: PptxContractError,
    domain: str,
) -> ProviderRequest:
    source_payload = json.loads(source_contract)
    try:
        candidate: object = json.loads(candidate_response)
    except (json.JSONDecodeError, UnicodeDecodeError):
        candidate = candidate_response
    payload = {
        "validation_error": {
            "code": error.code,
            "unit_id": error.unit_id,
            "detail": error.detail,
        },
        "source_contract": source_payload,
        "candidate_response": candidate,
    }
    response_requirements = _segment_response_requirements(source_payload, error)
    if response_requirements is not None:
        payload["response_requirements"] = response_requirements
    return ProviderRequest.create(
        text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        source_language=request.source_language,
        target_language=request.target_language,
        field=PPTX_PROVIDER_REPAIR_FIELD,
        domain=domain,
        stop_words=tuple(request.stop_words),
        custom_translations=dict(request.custom_translations),
        timeout_seconds=request.provider_timeout_seconds,
        output_format="structured",
    )


def _segment_response_requirements(
    source_payload: object,
    error: PptxContractError,
) -> dict[str, object] | None:
    if (
        error.code not in {
            "segment_count",
            "target_mismatch",
            "duplicate_target_span",
            "missing_target_boundary_space",
        }
        or not isinstance(source_payload, dict)
    ):
        return None
    units = source_payload.get("units")
    if not isinstance(units, list):
        return None
    for unit in units:
        if not isinstance(unit, dict) or unit.get("unit_id") != error.unit_id:
            continue
        stream = unit.get("source_stream")
        if not isinstance(stream, list):
            return None
        segment_ids = [
            item.get("segment_id")
            for item in stream
            if isinstance(item, dict) and item.get("kind") == "text"
        ]
        if not segment_ids or any(not isinstance(segment_id, str) for segment_id in segment_ids):
            return None
        return {
            "expected_segment_count": len(segment_ids),
            "segments": [
                {"segment_id": segment_id, "target_text": ""}
                for segment_id in segment_ids
            ],
        }
    return None


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
