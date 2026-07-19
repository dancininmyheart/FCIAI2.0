from __future__ import annotations

from app.translation.quality import FindingCode, QualityMode, assess_quality
from app.translation.types import TranslationUnit, TranslationUnitResult


def _unit(unit_id: str, text: str = "Milk supports infants") -> TranslationUnit:
    return TranslationUnit.create(
        stable_id=unit_id,
        kind="ppt",
        source_text=text,
        source_language="en",
        target_language="zh",
    )


def test_observe_valid_results_have_no_structural_findings() -> None:
    units = (_unit("a", "Milk [block]"), _unit("b", "Growth"))
    results = (
        TranslationUnitResult("a", "母乳 [block]", "qwen", "qwen"),
        TranslationUnitResult("b", "生长", "qwen", "qwen"),
    )

    outcome = assess_quality(units, results, QualityMode.OBSERVE)

    assert outcome.results == results
    assert outcome.findings == ()
    assert outcome.valid_for_cache


def test_observe_reports_all_structural_findings_without_mutation() -> None:
    units = (
        TranslationUnit.create(
            stable_id="a",
            kind="ppt",
            source_text="HMO [block] milk",
            source_language="en",
            target_language="zh",
            stop_words=("HMO",),
            glossary=(("milk", "母乳"),),
        ),
        _unit("b"),
        _unit("c"),
    )
    results = (
        TranslationUnitResult("a", "翻译", "deepseek", "deepseek"),
        TranslationUnitResult("a", "重复", "deepseek", "deepseek"),
        TranslationUnitResult("c", "", "deepseek", "deepseek"),
        TranslationUnitResult("extra", "额外", "deepseek", "deepseek"),
    )
    original_bytes = tuple(result.translated_text.encode("utf-8") for result in results)

    outcome = assess_quality(units, results, "observe")

    codes = {finding.code for finding in outcome.findings}
    assert {
        FindingCode.DUPLICATE_ID,
        FindingCode.MISSING_ID,
        FindingCode.UNEXPECTED_ID,
        FindingCode.BLANK_TARGET,
        FindingCode.PLACEHOLDER_MISMATCH,
        FindingCode.PROTECTED_TERM_MISSING,
        FindingCode.GLOSSARY_MISS,
    } <= codes
    assert outcome.results == results
    assert tuple(result.translated_text.encode("utf-8") for result in outcome.results) == original_bytes


def test_off_mode_skips_quality_work() -> None:
    outcome = assess_quality((_unit("a"),), (), "off", malformed=True)

    assert outcome.findings == ()
    assert outcome.results == ()
