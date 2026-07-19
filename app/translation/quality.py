from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Sequence

from app.translation.types import TranslationUnit, TranslationUnitResult


class QualityMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    ENFORCE = "enforce"

    @classmethod
    def parse(cls, value: str) -> QualityMode:
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise InvalidQualityMode(value) from exc


@dataclass(frozen=True, slots=True)
class InvalidQualityMode(Exception):
    value: str

    def __str__(self) -> str:
        return f"unsupported translation quality mode: {self.value}"


class FindingCode(StrEnum):
    DUPLICATE_ID = "duplicate_id"
    MISSING_ID = "missing_id"
    UNEXPECTED_ID = "unexpected_id"
    BLANK_TARGET = "blank_target"
    MALFORMED_OUTPUT = "malformed_output"
    PLACEHOLDER_MISMATCH = "placeholder_mismatch"
    PROTECTED_TERM_MISSING = "protected_term_missing"
    GLOSSARY_MISS = "glossary_miss"
    TARGET_SCRIPT_RATIO = "target_script_ratio"
    LENGTH_RATIO = "length_ratio"


_ENFORCED_CODES = frozenset(
    {
        FindingCode.DUPLICATE_ID,
        FindingCode.MISSING_ID,
        FindingCode.UNEXPECTED_ID,
        FindingCode.BLANK_TARGET,
        FindingCode.MALFORMED_OUTPUT,
        FindingCode.PLACEHOLDER_MISMATCH,
    },
)


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: FindingCode
    unit_id: str
    detail: str

    @property
    def enforceable(self) -> bool:
        return self.code in _ENFORCED_CODES


@dataclass(frozen=True, slots=True)
class QualityOutcome:
    results: tuple[TranslationUnitResult, ...]
    findings: tuple[QualityFinding, ...]

    @property
    def valid_for_cache(self) -> bool:
        return not any(finding.enforceable for finding in self.findings)

    @property
    def invalid_unit_ids(self) -> frozenset[str]:
        return frozenset(finding.unit_id for finding in self.findings if finding.enforceable)


def assess_quality(
    units: Sequence[TranslationUnit],
    results: Sequence[TranslationUnitResult],
    mode: QualityMode | str,
    *,
    malformed: bool = False,
) -> QualityOutcome:
    selected_mode = QualityMode.parse(mode) if isinstance(mode, str) else mode
    unchanged = tuple(results)
    if selected_mode is QualityMode.OFF:
        return QualityOutcome(unchanged, ())

    findings: list[QualityFinding] = []
    unit_ids = [unit.stable_id for unit in units]
    result_ids = [result.stable_id for result in results]
    if malformed:
        findings.append(QualityFinding(FindingCode.MALFORMED_OUTPUT, "*", "structured output could not be parsed"))
    findings.extend(_duplicate_findings(unit_ids, "source unit"))
    findings.extend(_duplicate_findings(result_ids, "translation result"))
    expected = set(unit_ids)
    actual = set(result_ids)
    for unit_id in unit_ids:
        if unit_id not in actual:
            findings.append(QualityFinding(FindingCode.MISSING_ID, unit_id, "translation result is missing"))
    for unit_id in result_ids:
        if unit_id not in expected:
            findings.append(QualityFinding(FindingCode.UNEXPECTED_ID, unit_id, "translation result was not requested"))

    first_result = {result.stable_id: result for result in results}
    for unit in units:
        result = first_result.get(unit.stable_id)
        if result is None:
            continue
        findings.extend(_unit_findings(unit, result))
    return QualityOutcome(unchanged, tuple(findings))


def _duplicate_findings(ids: Iterable[str], label: str) -> list[QualityFinding]:
    counts = Counter(ids)
    return [
        QualityFinding(FindingCode.DUPLICATE_ID, unit_id, f"duplicate {label}")
        for unit_id, count in counts.items()
        if count > 1
    ]


def _unit_findings(unit: TranslationUnit, result: TranslationUnitResult) -> list[QualityFinding]:
    target = result.translated_text
    findings: list[QualityFinding] = []
    if unit.source_text.strip() and not target.strip():
        findings.append(QualityFinding(FindingCode.BLANK_TARGET, unit.stable_id, "nonblank source has blank target"))
        return findings
    required = Counter(unit.placeholders)
    actual = Counter(token for token in required for _ in range(target.count(token)))
    if required != actual:
        findings.append(QualityFinding(FindingCode.PLACEHOLDER_MISMATCH, unit.stable_id, "placeholder counts differ"))
    source_folded = unit.source_text.casefold()
    target_folded = target.casefold()
    for term in unit.stop_words:
        if term.casefold() in source_folded and term.casefold() not in target_folded:
            findings.append(QualityFinding(FindingCode.PROTECTED_TERM_MISSING, unit.stable_id, f"protected term missing: {term}"))
    for source, translated in unit.glossary:
        if source.casefold() in source_folded and translated.casefold() not in target_folded:
            findings.append(QualityFinding(FindingCode.GLOSSARY_MISS, unit.stable_id, f"glossary translation missing: {source}"))
    if _script_ratio_is_low(target, unit.target_language):
        findings.append(QualityFinding(FindingCode.TARGET_SCRIPT_RATIO, unit.stable_id, "target script ratio is low"))
    source_length = len(unit.source_text.strip())
    ratio = len(target.strip()) / max(source_length, 1)
    if source_length >= 5 and (ratio < 0.15 or ratio > 6.0):
        findings.append(QualityFinding(FindingCode.LENGTH_RATIO, unit.stable_id, f"target/source length ratio is {ratio:.2f}"))
    return findings


def _script_ratio_is_low(text: str, language: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 4:
        return False
    normalized = language.lower()
    if normalized.startswith("zh") or "chinese" in normalized:
        matching = sum("\u4e00" <= char <= "\u9fff" for char in letters)
        return matching / len(letters) < 0.2
    if normalized.startswith("en") or "english" in normalized:
        matching = sum(char.isascii() and char.isalpha() for char in letters)
        return matching / len(letters) < 0.5
    return False
