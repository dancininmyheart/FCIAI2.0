from __future__ import annotations

from dataclasses import dataclass, field

from app.translation.pipeline import MalformedTranslationOutput, translate_with_quality
from app.translation.types import TranslationUnit, TranslationUnitResult


def _unit(unit_id: str) -> TranslationUnit:
    return TranslationUnit.create(unit_id, "pdf", f"source {unit_id}", "en", "zh")


@dataclass(slots=True)
class RepairingTranslator:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, units: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]:
        self.calls.append(tuple(unit.stable_id for unit in units))
        if len(self.calls) == 1:
            return (
                TranslationUnitResult("a", "有效", "qwen", "qwen"),
                TranslationUnitResult("b", "", "qwen", "qwen"),
            )
        return (TranslationUnitResult("b", "已修复", "qwen", "qwen"),)


def test_enforce_retries_only_invalid_units_once() -> None:
    translator = RepairingTranslator()

    outcome = translate_with_quality((_unit("a"), _unit("b")), translator, "enforce")

    assert translator.calls == [("a", "b"), ("b",)]
    assert [result.translated_text for result in outcome.results] == ["有效", "已修复"]
    assert outcome.retried_unit_ids == ("b",)
    assert outcome.failures == ()


def test_second_invalid_result_uses_legacy_fallback_without_third_call() -> None:
    calls: list[tuple[str, ...]] = []

    def invalid(units: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]:
        calls.append(tuple(unit.stable_id for unit in units))
        return tuple(TranslationUnitResult(unit.stable_id, "", "deepseek", "deepseek") for unit in units)

    def legacy(unit: TranslationUnit) -> TranslationUnitResult:
        return TranslationUnitResult(unit.stable_id, unit.source_text, "legacy", "legacy")

    outcome = translate_with_quality((_unit("a"),), invalid, "enforce", fallback=legacy)

    assert calls == [("a",), ("a",)]
    assert outcome.results[0].translated_text == "source a"
    assert outcome.failures[0].code == "quality_validation_failed"


def test_malformed_output_is_retried_once() -> None:
    calls = 0

    def translator(units: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MalformedTranslationOutput()
        return (TranslationUnitResult("a", "有效", "qwen", "qwen"),)

    outcome = translate_with_quality((_unit("a"),), translator, "enforce")

    assert calls == 2
    assert outcome.results[0].translated_text == "有效"
