from __future__ import annotations

from app.translation.types import TranslationUnitResult
from app.translation.units import (
    PdfTextBlock,
    PptTextRecord,
    build_pdf_units,
    build_ppt_units,
    restore_unit_order,
)


def test_ppt_units_have_stable_identity_and_preserve_selected_order() -> None:
    records = (
        PptTextRecord(2, 4, 0, "HEAD [block] text", width=100, height=30),
        PptTextRecord(2, 4, 1, "TAIL text", width=100, height=30),
    )

    units = build_ppt_units(records, "en", "zh", stop_words=("HEAD",), glossary={"text": "文本"})

    assert [unit.stable_id for unit in units] == ["ppt:p2:s4:r0", "ppt:p2:s4:r1"]
    assert units[0].placeholders == ("[block]",)
    assert units[0].context_after == "TAIL text"
    assert units[1].context_before == "HEAD [block] text"


def test_pdf_units_round_trip_in_block_order() -> None:
    blocks = (PdfTextBlock(8, "First", "Title"), PdfTextBlock(9, "Second", "Title"))
    units = build_pdf_units(blocks, "en", "zh")
    results = (
        TranslationUnitResult("pdf:b9", "第二", "qwen", "qwen"),
        TranslationUnitResult("pdf:b8", "第一", "qwen", "qwen"),
    )

    restored = restore_unit_order(units, results)

    assert [unit.stable_id for unit in units] == ["pdf:b8", "pdf:b9"]
    assert restored == ("第一", "第二")
