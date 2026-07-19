from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.translation.quality import FindingCode, QualityFinding, QualityMode, assess_quality
from app.translation.types import TranslationUnit, TranslationUnitResult


class BatchUnitTranslator(Protocol):
    def __call__(self, units: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]: ...


class UnitFallback(Protocol):
    def __call__(self, unit: TranslationUnit) -> TranslationUnitResult: ...


@dataclass(frozen=True, slots=True)
class MalformedTranslationOutput(Exception):
    detail: str = "structured translation output is malformed"

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True, slots=True)
class QualityFailure:
    unit_id: str
    code: str = "quality_validation_failed"


@dataclass(frozen=True, slots=True)
class QualityPipelineResult:
    results: tuple[TranslationUnitResult, ...]
    findings: tuple[QualityFinding, ...]
    retried_unit_ids: tuple[str, ...] = ()
    failures: tuple[QualityFailure, ...] = ()


def translate_with_quality(
    units: Sequence[TranslationUnit],
    translator: BatchUnitTranslator,
    mode: QualityMode | str,
    fallback: UnitFallback | None = None,
) -> QualityPipelineResult:
    selected_mode = QualityMode.parse(mode) if isinstance(mode, str) else mode
    expected = tuple(units)
    first, malformed = _call_translator(translator, expected)
    first_quality = assess_quality(expected, first, selected_mode, malformed=malformed)
    if selected_mode is not QualityMode.ENFORCE:
        return QualityPipelineResult(first_quality.results, first_quality.findings)

    invalid_ids = _invalid_expected_ids(expected, first_quality.findings)
    if not invalid_ids:
        return QualityPipelineResult(first_quality.results, first_quality.findings)
    retry_units = tuple(unit for unit in expected if unit.stable_id in invalid_ids)
    retried, retry_malformed = _call_translator(translator, retry_units)
    merged = _merge_results(expected, first, retried, invalid_ids)
    final_quality = assess_quality(expected, merged, selected_mode, malformed=retry_malformed)
    unresolved = _invalid_expected_ids(expected, final_quality.findings)
    failures = tuple(QualityFailure(unit_id) for unit_id in sorted(unresolved))
    if unresolved and fallback is not None:
        replacements = tuple(fallback(unit) for unit in expected if unit.stable_id in unresolved)
        merged = _merge_results(expected, merged, replacements, unresolved)
    return QualityPipelineResult(
        results=merged,
        findings=final_quality.findings,
        retried_unit_ids=tuple(unit.stable_id for unit in retry_units),
        failures=failures,
    )


def _call_translator(
    translator: BatchUnitTranslator,
    units: tuple[TranslationUnit, ...],
) -> tuple[tuple[TranslationUnitResult, ...], bool]:
    try:
        return tuple(translator(units)), False
    except MalformedTranslationOutput:
        return (), True


def _invalid_expected_ids(
    units: tuple[TranslationUnit, ...],
    findings: tuple[QualityFinding, ...],
) -> frozenset[str]:
    expected = frozenset(unit.stable_id for unit in units)
    invalid = {finding.unit_id for finding in findings if finding.enforceable and finding.unit_id in expected}
    if any(
        finding.enforceable
        and (finding.unit_id == "*" or finding.code is FindingCode.UNEXPECTED_ID)
        for finding in findings
    ):
        invalid.update(expected)
    return frozenset(invalid)


def _merge_results(
    units: tuple[TranslationUnit, ...],
    original: tuple[TranslationUnitResult, ...],
    replacements: tuple[TranslationUnitResult, ...],
    replaced_ids: frozenset[str],
) -> tuple[TranslationUnitResult, ...]:
    original_by_id = {result.stable_id: result for result in original if result.stable_id not in replaced_ids}
    replacement_by_id = {result.stable_id: result for result in replacements}
    merged: list[TranslationUnitResult] = []
    for unit in units:
        result = replacement_by_id.get(unit.stable_id) or original_by_id.get(unit.stable_id)
        if result is not None:
            merged.append(result)
    return tuple(merged)
