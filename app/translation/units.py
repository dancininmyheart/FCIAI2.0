from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from app.translation.types import LayoutHint, TranslationUnit, TranslationUnitResult


@dataclass(frozen=True, slots=True)
class PptTextRecord:
    page_index: int
    shape_index: int
    paragraph_index: int
    text: str
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True, slots=True)
class PdfTextBlock:
    block_index: int
    text: str
    title_context: str = ""


def ppt_unit_id(page_index: int, shape_index: int, paragraph_index: int) -> str:
    return f"ppt:p{page_index}:s{shape_index}:r{paragraph_index}"


def pdf_unit_id(block_index: int) -> str:
    return f"pdf:b{block_index}"


def build_ppt_units(
    records: Sequence[PptTextRecord],
    source_language: str,
    target_language: str,
    stop_words: tuple[str, ...] = (),
    glossary: Mapping[str, str] | None = None,
) -> tuple[TranslationUnit, ...]:
    terms = tuple(sorted((glossary or {}).items()))
    units: list[TranslationUnit] = []
    for index, record in enumerate(records):
        units.append(
            TranslationUnit.create(
                stable_id=ppt_unit_id(record.page_index, record.shape_index, record.paragraph_index),
                kind="ppt",
                source_text=record.text,
                source_language=source_language,
                target_language=target_language,
                context_before=records[index - 1].text if index else "",
                context_after=records[index + 1].text if index + 1 < len(records) else "",
                stop_words=stop_words,
                glossary=terms,
                layout_hint=LayoutHint(width=record.width, height=record.height),
            ),
        )
    return tuple(units)


def build_pdf_units(
    blocks: Sequence[PdfTextBlock],
    source_language: str,
    target_language: str,
    stop_words: tuple[str, ...] = (),
    glossary: Mapping[str, str] | None = None,
) -> tuple[TranslationUnit, ...]:
    terms = tuple(sorted((glossary or {}).items()))
    units: list[TranslationUnit] = []
    for index, block in enumerate(blocks):
        units.append(
            TranslationUnit.create(
                stable_id=pdf_unit_id(block.block_index),
                kind="pdf",
                source_text=block.text,
                source_language=source_language,
                target_language=target_language,
                context_before=blocks[index - 1].text if index else "",
                context_after=blocks[index + 1].text if index + 1 < len(blocks) else "",
                title_context=block.title_context,
                stop_words=stop_words,
                glossary=terms,
            ),
        )
    return tuple(units)


def restore_unit_order(
    units: Iterable[TranslationUnit],
    results: Iterable[TranslationUnitResult],
) -> tuple[str, ...]:
    by_id = {result.stable_id: result.translated_text for result in results}
    return tuple(by_id[unit.stable_id] for unit in units)
