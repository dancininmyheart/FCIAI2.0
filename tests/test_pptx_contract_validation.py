from __future__ import annotations

import json
import logging

import pytest
from flask import Flask

from app.translation.pptx_contract import (
    PptxContractError,
    parse_pptx_response,
    validate_pptx_translations,
)
from app.translation.pptx_contract_types import (
    PptxGlossaryEntry,
    PptxRequestUnit,
    PptxSegmentTranslation,
    PptxTextStreamItem,
    PptxUnitTranslation,
)
from app.translation.metrics import TranslationMetrics


def _parse_translation(
    source: str,
    target: str,
    *,
    source_language: str = "English",
    target_language: str = "Chinese",
    protected_terms: tuple[str, ...] = (),
    glossary: tuple[tuple[str, str], ...] = (),
) -> None:
    unit_id = "pptx:slide1:shapeId7:tbOrdinal0:p0"
    segment_id = f"{unit_id}:segment0"
    unit = PptxRequestUnit(
        unit_id=unit_id,
        source_text=source,
        source_stream=(PptxTextStreamItem("stream0", segment_id, source),),
        source_language=source_language,
        target_language=target_language,
        protected_terms=protected_terms,
        glossary=tuple(PptxGlossaryEntry(source_term, target_term) for source_term, target_term in glossary),
    )
    response = json.dumps(
        {
            "provider_contract_schema_version": 2,
            "document_kind": "pptx_xml",
            "translations": [
                {
                    "unit_id": unit_id,
                    "target_text": target,
                    "segments": [{"segment_id": segment_id, "target_text": target}],
                },
            ],
        },
        ensure_ascii=False,
    )
    parse_pptx_response(response, (unit,))


def test_rejects_high_confidence_source_language_residue() -> None:
    with pytest.raises(PptxContractError) as raised:
        _parse_translation(
            "Can impact gut health – Proposed Mechanisms",
            "可能影响肠道健康 – Proposed Mechanisms",
        )

    assert raised.value.code == "source_language_residue"


@pytest.mark.parametrize("phrase", ("Economic Outlook", "Market Growth"))
def test_rejects_a_retained_descriptive_title_case_phrase(phrase: str) -> None:
    with pytest.raises(PptxContractError) as raised:
        _parse_translation(
            f"Quarterly briefing – {phrase}",
            f"季度简报 – {phrase}",
        )

    assert raised.value.code == "source_language_residue"


def test_allows_an_honorific_backed_person_name_to_remain_unchanged() -> None:
    _parse_translation(
        "Economic review by Dr Ayo Teriba",
        "由 Dr Ayo Teriba 撰写的经济评论",
    )


def test_allows_a_person_name_without_an_honorific_to_remain_unchanged() -> None:
    _parse_translation(
        "Economic review by Ayo Teriba",
        "由 Ayo Teriba 撰写的经济回顾",
    )


def test_allows_a_multiword_brand_name_to_remain_unchanged() -> None:
    _parse_translation(
        "Nestle Health Science growth outlook",
        "Nestle Health Science 增长展望",
    )


def test_probable_proper_name_acceptance_emits_a_redacted_warning_and_metric(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    app = Flask(__name__)
    metrics = TranslationMetrics()
    app.extensions["translation_metrics"] = metrics

    with app.app_context():
        _parse_translation(
            "Research by Lina Moreno",
            "由 Lina Moreno 开展研究",
        )

    assert metrics.snapshot().quality_findings == {"possible_proper_name_retained_warning": 1}
    assert "reason_code=possible_proper_name_retained_warning" in caplog.text
    assert "candidate_count=1" in caplog.text
    assert "Lina Moreno" not in caplog.text
    assert "Research by" not in caplog.text


def test_probable_proper_name_requires_the_exact_source_literal() -> None:
    with pytest.raises(PptxContractError) as raised:
        _parse_translation(
            "Research by Lina Moreno",
            "由 lina moreno 开展研究",
        )

    assert raised.value.code == "source_language_residue"


@pytest.mark.parametrize(
    "organization",
    (
        "Meridian Health Labs",
        "World Health Organization",
        "European Nutrition Organisation",
        "Global Research Association",
        "National Standards Agency",
        "Continental Development Bank",
        "Meridian Health Partners",
    ),
)
def test_allows_an_organization_name_with_an_explicit_suffix(organization: str) -> None:
    _parse_translation(
        f"Published by {organization}",
        f"由 {organization} 发布",
    )


@pytest.mark.parametrize(
    ("source", "target", "protected_terms", "glossary"),
    (
        ("Read https://example.com/clinical-trials today", "请阅读 https://example.com/clinical-trials", (), ()),
        ("Email jane.doe@example.com today", "请发送邮件至 jane.doe@example.com", (), ()),
        ("See DOI 10.1000/xyz123 for details", "详见 DOI 10.1000/xyz123", (), ()),
        ("Published in 2024", "发布于 2024 年", (), ()),
        ("Dose 5 mg/kg daily", "每日剂量 5 mg/kg", (), ()),
        ("Contains H2O and NaCl", "含 H2O 和 NaCl", (), ()),
        ("HMO DHA support growth", "HMO DHA 支持生长", (), ()),
        ("Keep Alpha Beta stable", "保持 Alpha Beta 稳定", ("Alpha Beta",), ()),
        ("Use HMO Complex daily", "每日使用 HMO Complex", (), (("HMO Complex", "HMO Complex"),)),
    ),
)
def test_allows_explicitly_permitted_latin_content(
    source: str,
    target: str,
    protected_terms: tuple[str, ...],
    glossary: tuple[tuple[str, str], ...],
) -> None:
    _parse_translation(
        source,
        target,
        protected_terms=protected_terms,
        glossary=glossary,
    )


def test_requires_an_exact_glossary_target_when_source_term_is_present() -> None:
    with pytest.raises(PptxContractError) as raised:
        _parse_translation(
            "Supports gut health",
            "支持肠道 健康",
            glossary=(("gut health", "肠道健康"),),
        )

    assert raised.value.code == "glossary_mismatch"


def test_single_latin_token_is_a_redacted_warning_not_a_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    _parse_translation(
        "Can impact gut health",
        "可能 impact 肠道健康",
    )

    assert "reason_code=source_language_residue_warning" in caplog.text
    assert "unit_id=pptx:slide1:shapeId7:tbOrdinal0:p0" in caplog.text
    assert "Can impact gut health" not in caplog.text
    assert "可能 impact 肠道健康" not in caplog.text


def test_empty_glossary_target_requires_source_term_deletion() -> None:
    _parse_translation(
        "Remove allergen from formula",
        "从配方中去除",
        glossary=(("allergen", ""),),
    )


def test_allows_an_obvious_english_citation_to_remain_unchanged() -> None:
    citation = (
        "Smith J, Brown AB. Gut health mechanisms. Journal of Nutrition. "
        "2024;12(3):45-52. doi:10.1000/xyz123"
    )

    _parse_translation(citation, f"参考文献：{citation}")


def test_allows_short_et_al_citations_to_remain_unchanged() -> None:
    citations = (
        "Chen et al., 2025; Nie et al., 2024; Valdes et al., 2018; "
        "Lovegrove et al., 2025"
    )

    _parse_translation(f"Evidence ({citations})", f"证据（{citations}）")


def test_package_validation_does_not_reenforce_semantic_quality() -> None:
    unit_id = "pptx:slide1:shapeId7:tbOrdinal0:p0"
    segment_id = f"{unit_id}:segment0"
    source = "Can impact gut health – Proposed Mechanisms"
    target = "可能影响肠道健康 – Proposed Mechanisms"
    unit = PptxRequestUnit(
        unit_id=unit_id,
        source_text=source,
        source_stream=(PptxTextStreamItem("stream0", segment_id, source),),
        source_language="English",
        target_language="Chinese",
    )
    translation = PptxUnitTranslation(
        unit_id=unit_id,
        target_text=target,
        segments=(PptxSegmentTranslation(segment_id, target),),
    )

    validate_pptx_translations((unit,), (translation,))
