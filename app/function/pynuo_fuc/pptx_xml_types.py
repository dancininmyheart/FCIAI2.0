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
    provider_timeout_seconds: float = 120.0


@dataclass(frozen=True, slots=True)
class XmlParagraphTarget:
    page_index: int
    slide_path: str
    box_index: int
    paragraph_index: int
    text_body: ElementTree.Element
    paragraph: ElementTree.Element
    runs: tuple[ElementTree.Element, ...]
    text_nodes: tuple[ElementTree.Element, ...]
    text: str


class PptxXmlFallbackEligibleError(Exception):
    """Base class for failures that may use the explicit UNO compatibility lane."""


@dataclass(frozen=True, slots=True)
class PptxXmlReadError(PptxXmlFallbackEligibleError):
    detail: str

    def __str__(self) -> str:
        return f"PPTX XML read failed: {self.detail}"


@dataclass(frozen=True, slots=True)
class PptxXmlWriteError(PptxXmlFallbackEligibleError):
    detail: str

    def __str__(self) -> str:
        return f"PPTX XML write failed: {self.detail}"


@dataclass(frozen=True, slots=True)
class PptxXmlPackageError(PptxXmlFallbackEligibleError):
    detail: str

    def __str__(self) -> str:
        return f"PPTX package validation failed: {self.detail}"


@dataclass(frozen=True, slots=True)
class PptxXmlUnsupportedStructureError(PptxXmlFallbackEligibleError):
    slide_path: str
    detail: str

    def __str__(self) -> str:
        return f"unsupported PPTX text structure in {self.slide_path}: {self.detail}"


@dataclass(frozen=True, slots=True)
class PptxXmlDuplicateShapeIdError(PptxXmlFallbackEligibleError):
    slide_path: str
    shape_id: str

    def __str__(self) -> str:
        return f"duplicate shape ID {self.shape_id} in {self.slide_path}"
