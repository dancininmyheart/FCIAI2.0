from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Final, assert_never

from app.translation.pptx_contract_types import (
    PptxContractError,
    PptxLineBreakStreamItem,
    PptxProtectedFieldStreamItem,
    PptxRequestUnit,
    PptxSegmentTranslation,
    PptxTextStreamItem,
    PptxUnitTranslation,
)


_RESERVED_MARKER_RE: Final = re.compile(
    r"\[\s*(?P<marker>b\s*l\s*o\s*c\s*k|块)\s*\]",
    re.IGNORECASE,
)


def validate_request_units(units: tuple[PptxRequestUnit, ...]) -> None:
    unit_ids = [unit.unit_id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise PptxContractError("duplicate_unit_id", "request contains duplicate unit IDs")
    for unit in units:
        stream_ids = [item.stream_id for item in unit.source_stream]
        segment_ids = [item.segment_id for item in unit.text_items]
        if len(stream_ids) != len(set(stream_ids)) or len(segment_ids) != len(set(segment_ids)):
            raise PptxContractError("duplicate_stream_id", "request contains duplicate stream IDs", unit.unit_id)
        if not segment_ids:
            raise PptxContractError("missing_segment", "request unit has no text segment", unit.unit_id)
        if unit.layout_hint.width_emu is not None and unit.layout_hint.width_emu <= 0:
            raise PptxContractError("layout_hint", "width must be positive", unit.unit_id)
        if unit.layout_hint.height_emu is not None and unit.layout_hint.height_emu <= 0:
            raise PptxContractError("layout_hint", "height must be positive", unit.unit_id)


def validate_pptx_translations(
    expected_units: tuple[PptxRequestUnit, ...],
    translations: tuple[PptxUnitTranslation, ...],
) -> None:
    if len(expected_units) != len(translations):
        raise PptxContractError("unit_count", "translation count does not match request")
    for unit, translation in zip(expected_units, translations, strict=True):
        if translation.unit_id != unit.unit_id:
            raise PptxContractError("unit_order", "unit ID or order differs from request", unit.unit_id)
        expected_ids = tuple(item.segment_id for item in unit.text_items)
        actual_ids = tuple(item.segment_id for item in translation.segments)
        if expected_ids != actual_ids:
            raise PptxContractError("segment_order", "segment IDs or order differ from request", unit.unit_id)
        validate_unit_translation(unit, translation)


def validate_unit_translation(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> None:
    if unit.source_text.strip() and not translation.target_text.strip():
        raise PptxContractError("blank_target", "nonblank source has blank target", unit.unit_id)
    reconstructed = reconstruct_target(unit, translation.segments)
    if _consistency_text(reconstructed) != _consistency_text(translation.target_text):
        raise PptxContractError("target_mismatch", "target text differs from translated stream", unit.unit_id)
    if reserved_marker_counts(unit.source_text) != reserved_marker_counts(translation.target_text):
        raise PptxContractError("reserved_marker_added", "reserved marker provenance differs", unit.unit_id)
    for source, target in zip(unit.text_items, translation.segments, strict=True):
        if reserved_marker_counts(source.source_text) != reserved_marker_counts(target.target_text):
            raise PptxContractError("reserved_marker_added", "segment marker provenance differs", unit.unit_id)


def reserved_marker_counts(text: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", text)
    counts: Counter[str] = Counter()
    for match in _RESERVED_MARKER_RE.finditer(normalized):
        marker = "".join(match.group("marker").split()).casefold()
        counts[marker] += 1
    return counts


def reconstruct_target(
    unit: PptxRequestUnit,
    segments: tuple[PptxSegmentTranslation, ...],
) -> str:
    by_id = {segment.segment_id: segment.target_text for segment in segments}
    parts: list[str] = []
    for item in unit.source_stream:
        match item:
            case PptxTextStreamItem():
                parts.append(by_id[item.segment_id])
            case PptxLineBreakStreamItem():
                parts.append("\n")
            case PptxProtectedFieldStreamItem():
                parts.append(item.source_text)
            case _ as unreachable:
                assert_never(unreachable)
    return "".join(parts)


def _consistency_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
