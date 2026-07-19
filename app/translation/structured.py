from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from app.translation.metrics import current_metrics
from app.translation.pipeline import MalformedTranslationOutput, translate_with_quality
from app.translation.providers import ProviderRegistry
from app.translation.quality import QualityMode, assess_quality
from app.translation.types import ProviderRequest, TranslationUnit, TranslationUnitResult


_SOURCE_PATTERN = re.compile(
    r"【文本框(?P<box>\d+)-段落(?P<paragraph>\d+)】\s*\r?\n(?P<text>.*?)(?=\r?\n\s*【文本框\d+-段落\d+】|\Z)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class StructuredTranslationResult:
    text: str
    provider_calls: int
    quality_findings: int


def translate_ppt_page(
    registry: ProviderRegistry,
    model: str,
    request: ProviderRequest,
    quality_mode: QualityMode | str,
) -> StructuredTranslationResult:
    mode = QualityMode.parse(quality_mode) if isinstance(quality_mode, str) else quality_mode
    units = parse_ppt_source(request)
    if mode is QualityMode.OFF or not units:
        text = registry.translate(model, request).text
        return StructuredTranslationResult(text, 1, 0)

    raw_responses: list[str] = []

    def translate_batch(batch: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]:
        provider_request = request if not raw_responses else replace(request, text=_serialize_source(batch))
        raw = registry.translate(model, provider_request).text
        raw_responses.append(raw)
        return parse_ppt_result(raw, model)

    if mode is QualityMode.OBSERVE:
        raw = registry.translate(model, request).text
        raw_responses.append(raw)
        try:
            results = parse_ppt_result(raw, model)
            outcome = assess_quality(units, results, mode)
        except MalformedTranslationOutput:
            outcome = assess_quality(units, (), mode, malformed=True)
        _record_findings(outcome.findings)
        return StructuredTranslationResult(raw, 1, len(outcome.findings))

    outcome = translate_with_quality(units, translate_batch, mode, fallback=_source_fallback)
    _record_findings(outcome.findings)
    if not outcome.retried_unit_ids and raw_responses:
        return StructuredTranslationResult(raw_responses[0], 1, len(outcome.findings))
    return StructuredTranslationResult(
        _serialize_results(units, outcome.results),
        len(raw_responses),
        len(outcome.findings),
    )


def parse_ppt_source(request: ProviderRequest) -> tuple[TranslationUnit, ...]:
    units: list[TranslationUnit] = []
    for match in _SOURCE_PATTERN.finditer(request.text):
        unit_id = _unit_id(int(match.group("box")), int(match.group("paragraph")))
        units.append(
            TranslationUnit.create(
                unit_id,
                "ppt",
                match.group("text").strip(),
                request.source_language,
                request.target_language,
                stop_words=request.stop_words,
                glossary=request.custom_translations,
            ),
        )
    return tuple(units)


def parse_ppt_result(raw: str, model: str) -> tuple[TranslationUnitResult, ...]:
    try:
        payload = json.loads(_strip_code_fence(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MalformedTranslationOutput() from exc
    if not isinstance(payload, list):
        raise MalformedTranslationOutput()
    results: list[TranslationUnitResult] = []
    for item in payload:
        if not isinstance(item, dict):
            raise MalformedTranslationOutput()
        try:
            box = int(item["box_index"])
            paragraph = int(item["paragraph_index"])
            translated = item["target_language"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MalformedTranslationOutput() from exc
        if not isinstance(translated, str):
            raise MalformedTranslationOutput()
        results.append(TranslationUnitResult(_unit_id(box, paragraph), translated, model, model))
    return tuple(results)


def _serialize_source(units: tuple[TranslationUnit, ...]) -> str:
    chunks: list[str] = []
    for unit in units:
        box, paragraph = _indices(unit.stable_id)
        chunks.append(f"【文本框{box}-段落{paragraph}】\n{unit.source_text}")
    return "\n\n".join(chunks)


def _serialize_results(
    units: tuple[TranslationUnit, ...],
    results: tuple[TranslationUnitResult, ...],
) -> str:
    by_id = {result.stable_id: result for result in results}
    payload = []
    for unit in units:
        result = by_id.get(unit.stable_id) or _source_fallback(unit)
        box, paragraph = _indices(unit.stable_id)
        payload.append(
            {
                "box_index": box,
                "paragraph_index": paragraph,
                "source_language": unit.source_text,
                "target_language": result.translated_text,
            },
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _source_fallback(unit: TranslationUnit) -> TranslationUnitResult:
    return TranslationUnitResult(unit.stable_id, unit.source_text, "legacy", "legacy")


def _record_findings(findings) -> None:
    metrics = current_metrics()
    if metrics is None:
        return
    for finding in findings:
        metrics.record_quality_finding(finding.code.value)


def _strip_code_fence(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
    return stripped


def _unit_id(box: int, paragraph: int) -> str:
    return f"ppt:b{box}:p{paragraph}"


def _indices(unit_id: str) -> tuple[int, int]:
    match = re.fullmatch(r"ppt:b(\d+):p(\d+)", unit_id)
    if match is None:
        raise MalformedTranslationOutput()
    return int(match.group(1)), int(match.group(2))
