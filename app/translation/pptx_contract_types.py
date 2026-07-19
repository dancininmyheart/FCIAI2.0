from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class PptxContractError(Exception):
    code: str
    detail: str
    unit_id: str = "*"

    def __str__(self) -> str:
        return f"PPTX translation contract {self.code} for {self.unit_id}: {self.detail}"


@dataclass(frozen=True, slots=True)
class PptxContext:
    previous_text: str = ""
    next_text: str = ""
    title_text: str = ""


@dataclass(frozen=True, slots=True)
class PptxLayoutHint:
    x_emu: int | None = None
    y_emu: int | None = None
    width_emu: int | None = None
    height_emu: int | None = None


@dataclass(frozen=True, slots=True)
class PptxGlossaryEntry:
    source: str
    target: str


@dataclass(frozen=True, slots=True)
class PptxTextStreamItem:
    stream_id: str
    segment_id: str
    source_text: str
    kind: Literal["text"] = field(init=False, default="text")


@dataclass(frozen=True, slots=True)
class PptxLineBreakStreamItem:
    stream_id: str
    kind: Literal["line_break"] = field(init=False, default="line_break")


@dataclass(frozen=True, slots=True)
class PptxProtectedFieldStreamItem:
    stream_id: str
    source_text: str
    kind: Literal["protected_field"] = field(init=False, default="protected_field")


PptxSourceStreamItem: TypeAlias = (
    PptxTextStreamItem | PptxLineBreakStreamItem | PptxProtectedFieldStreamItem
)


@dataclass(frozen=True, slots=True)
class PptxRequestUnit:
    unit_id: str
    source_text: str
    source_stream: tuple[PptxSourceStreamItem, ...]
    source_language: str
    target_language: str
    context: PptxContext = PptxContext()
    layout_hint: PptxLayoutHint = PptxLayoutHint()
    glossary: tuple[PptxGlossaryEntry, ...] = ()
    protected_terms: tuple[str, ...] = ()

    @property
    def text_items(self) -> tuple[PptxTextStreamItem, ...]:
        return tuple(item for item in self.source_stream if isinstance(item, PptxTextStreamItem))


@dataclass(frozen=True, slots=True)
class PptxSegmentTranslation:
    segment_id: str
    target_text: str


@dataclass(frozen=True, slots=True)
class PptxUnitTranslation:
    unit_id: str
    target_text: str
    segments: tuple[PptxSegmentTranslation, ...]
