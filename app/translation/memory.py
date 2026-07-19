from __future__ import annotations

import hashlib
import json
import threading
import unicodedata
from dataclasses import asdict, dataclass
from typing import Protocol

from app.translation.types import TranslationUnit, TranslationUnitResult


@dataclass(frozen=True, slots=True)
class MemoryKey:
    normalized_source: str
    context_hash: str
    source_language: str
    target_language: str
    provider: str
    model: str
    prompt_version: str
    glossary_version: str
    stop_words_version: str
    quality_policy_version: str

    @property
    def sha256(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryValue:
    translated_text: str
    provider: str
    model: str

    @classmethod
    def from_result(cls, result: TranslationUnitResult) -> MemoryValue:
        return cls(result.translated_text, result.provider, result.model)

    def for_unit(self, unit: TranslationUnit) -> TranslationUnitResult:
        return TranslationUnitResult(unit.stable_id, self.translated_text, self.provider, self.model)


class TranslationMemory(Protocol):
    def get(self, key: str) -> MemoryValue | None: ...
    def put(self, key: str, value: MemoryValue, *, quality_valid: bool) -> None: ...


class InMemoryTranslationMemory:
    def __init__(self) -> None:
        self._values: dict[str, MemoryValue] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> MemoryValue | None:
        with self._lock:
            return self._values.get(key)

    def put(self, key: str, value: MemoryValue, *, quality_valid: bool) -> None:
        if not quality_valid:
            return
        with self._lock:
            self._values[key] = value


class RedisClient(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def set(self, key: str, value: str) -> bool | None: ...


class RedisTranslationMemory:
    def __init__(self, client: RedisClient, namespace: str = "translation-memory:v1") -> None:
        self._client = client
        self._namespace = namespace

    def get(self, key: str) -> MemoryValue | None:
        try:
            raw = self._client.get(self._namespaced(key))
        except (OSError, RuntimeError, TimeoutError):
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return MemoryValue(
                translated_text=str(payload["translated_text"]),
                provider=str(payload["provider"]),
                model=str(payload["model"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def put(self, key: str, value: MemoryValue, *, quality_valid: bool) -> None:
        if not quality_valid:
            return
        payload = json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self._client.set(self._namespaced(key), payload)
        except (OSError, RuntimeError, TimeoutError):
            return

    def _namespaced(self, key: str) -> str:
        return f"{self._namespace}:{key}"


def build_memory_key(
    unit: TranslationUnit,
    provider: str,
    model: str,
    *,
    prompt_version: str,
    glossary_version: str,
    stop_words_version: str,
    quality_policy_version: str,
) -> MemoryKey:
    context_payload = {
        "before": _normalize(unit.context_before),
        "after": _normalize(unit.context_after),
        "title": _normalize(unit.title_context),
        "layout": asdict(unit.layout_hint) if unit.layout_hint is not None else None,
        "glossary": unit.glossary,
        "stop_words": unit.stop_words,
    }
    serialized_context = json.dumps(context_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return MemoryKey(
        normalized_source=_normalize(unit.source_text),
        context_hash=hashlib.sha256(serialized_context.encode("utf-8")).hexdigest(),
        source_language=unit.source_language.strip().lower(),
        target_language=unit.target_language.strip().lower(),
        provider=provider.strip().lower(),
        model=model.strip().lower(),
        prompt_version=prompt_version,
        glossary_version=glossary_version,
        stop_words_version=stop_words_version,
        quality_policy_version=quality_policy_version,
    )


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())
