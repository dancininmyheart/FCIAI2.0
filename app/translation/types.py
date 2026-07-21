from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

ProviderName: TypeAlias = Literal["qwen", "deepseek"]
OutputFormat: TypeAlias = Literal["structured", "plain"]
UnitKind: TypeAlias = Literal["ppt", "pdf"]


@dataclass(frozen=True, slots=True)
class LayoutHint:
    width: float | None = None
    height: float | None = None
    max_characters: int | None = None


@dataclass(frozen=True, slots=True)
class TranslationUnit:
    stable_id: str
    kind: UnitKind
    source_text: str
    source_language: str
    target_language: str
    context_before: str = ""
    context_after: str = ""
    title_context: str = ""
    placeholders: tuple[str, ...] = ()
    stop_words: tuple[str, ...] = ()
    glossary: tuple[tuple[str, str], ...] = ()
    layout_hint: LayoutHint | None = None

    @classmethod
    def create(
        cls,
        stable_id: str,
        kind: UnitKind,
        source_text: str,
        source_language: str,
        target_language: str,
        context_before: str = "",
        context_after: str = "",
        title_context: str = "",
        placeholders: tuple[str, ...] | None = None,
        stop_words: tuple[str, ...] = (),
        glossary: tuple[tuple[str, str], ...] = (),
        layout_hint: LayoutHint | None = None,
    ) -> TranslationUnit:
        resolved_placeholders = placeholders if placeholders is not None else tuple(re.findall(r"\[block\]", source_text))
        return cls(
            stable_id=stable_id,
            kind=kind,
            source_text=source_text,
            source_language=source_language,
            target_language=target_language,
            context_before=context_before,
            context_after=context_after,
            title_context=title_context,
            placeholders=resolved_placeholders,
            stop_words=stop_words,
            glossary=glossary,
            layout_hint=layout_hint,
        )


@dataclass(frozen=True, slots=True)
class TranslationUnitResult:
    stable_id: str
    translated_text: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    text: str
    source_language: str
    target_language: str
    field: str = ""
    domain: str = ""
    stop_words: tuple[str, ...] = ()
    custom_translations: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 120.0
    output_format: OutputFormat = "structured"

    @classmethod
    def create(
        cls,
        text: str,
        source_language: str,
        target_language: str,
        field: str = "",
        domain: str = "",
        stop_words: tuple[str, ...] = (),
        custom_translations: dict[str, str] | None = None,
        timeout_seconds: float = 120.0,
        output_format: OutputFormat = "structured",
    ) -> ProviderRequest:
        return cls(
            text=text,
            source_language=source_language,
            target_language=target_language,
            field=field,
            domain=domain,
            stop_words=stop_words,
            custom_translations=tuple(sorted((custom_translations or {}).items())),
            timeout_seconds=timeout_seconds,
            output_format=output_format,
        )


@dataclass(frozen=True, slots=True)
class ProviderResult:
    text: str
    provider: ProviderName
    model: str
    retry_count: int = 0


@dataclass(frozen=True, slots=True)
class ProviderError(Exception):
    provider: str
    code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.provider} {self.code}: {self.detail}"


class TranslationProvider(Protocol):
    @property
    def name(self) -> ProviderName: ...

    def translate(self, request: ProviderRequest) -> ProviderResult: ...
