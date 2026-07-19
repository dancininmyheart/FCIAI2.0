from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TypedDict
from xml.etree import ElementTree


class TextBoxData(TypedDict):
    page_index: int
    box_index: int
    box_id: str
    paragraph_index: int
    paragraph_id: str
    combined_text: str


class TranslationPageResult(TypedDict, total=False):
    translated_fragments: Mapping[str, Sequence[str]]
    error: str


class ProgressCallback(Protocol):
    def __call__(self, current: int, total: int) -> None: ...


class PageTranslator(Protocol):
    def __call__(
        self,
        text_boxes_data: list[TextBoxData],
        progress_callback: ProgressCallback | None,
        source_language: str,
        target_language: str,
        model: str,
        stop_words_list: Sequence[str],
        custom_translations: Mapping[str, str],
    ) -> Mapping[int, TranslationPageResult]: ...


class WriteMode(StrEnum):
    PARAGRAPH_UP = "paragraph_up"
    PARAGRAPH_DOWN = "paragraph_down"
    TRANSLATION_ONLY = "translation_only"


@dataclass(frozen=True, slots=True)
class XmlTranslationRequest:
    input_path: Path
    output_path: Path
    selected_page_indices: tuple[int, ...] | None
    source_language: str
    target_language: str
    model: str
    stop_words: Sequence[str]
    custom_translations: Mapping[str, str]
    bilingual_translation: str
    progress_callback: ProgressCallback | None


@dataclass(frozen=True, slots=True)
class XmlParagraphTarget:
    page_index: int
    slide_path: str
    box_index: int
    paragraph_index: int
    paragraph: ElementTree.Element
    runs: tuple[ElementTree.Element, ...]
    text_nodes: tuple[ElementTree.Element, ...]
    text: str
