from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, Sequence, TypeAlias

from app.translation.memory import MemoryValue, TranslationMemory, build_memory_key
from app.translation.types import TranslationUnit, TranslationUnitResult


class UnitTranslator(Protocol):
    def __call__(self, unit: TranslationUnit) -> TranslationUnitResult: ...


QualityValidator: TypeAlias = Callable[[TranslationUnit, TranslationUnitResult], bool]


@dataclass(frozen=True, slots=True)
class BatchSettings:
    max_concurrency: int = 10
    provider_max_concurrency: int | None = None
    batch_size: int = 10
    memory_enabled: bool = False
    prompt_version: str = "v1"
    glossary_version: str = "v1"
    stop_words_version: str = "v1"
    quality_policy_version: str = "v1"

    @property
    def effective_concurrency(self) -> int:
        provider_limit = self.provider_max_concurrency or self.max_concurrency
        return max(1, min(self.max_concurrency, provider_limit))


@dataclass(frozen=True, slots=True)
class BatchResult:
    results: tuple[TranslationUnitResult, ...]
    provider_unit_calls: int
    cache_hits: int


@dataclass(frozen=True, slots=True)
class InvalidBatchSetting(ValueError):
    field: str
    value: int

    def __str__(self) -> str:
        return f"{self.field} must be positive, got {self.value}"


class TranslationBatchProcessor:
    def __init__(
        self,
        translator: UnitTranslator,
        provider: str,
        model: str,
        settings: BatchSettings = BatchSettings(),
        memory: TranslationMemory | None = None,
        quality_validator: QualityValidator | None = None,
    ) -> None:
        if settings.max_concurrency < 1:
            raise InvalidBatchSetting("max_concurrency", settings.max_concurrency)
        if settings.batch_size < 1:
            raise InvalidBatchSetting("batch_size", settings.batch_size)
        self._translator = translator
        self._provider = provider
        self._model = model
        self._settings = settings
        self._memory = memory
        self._quality_validator = quality_validator or _default_quality_validator

    def process(self, units: Sequence[TranslationUnit]) -> BatchResult:
        expected = tuple(units)
        if not expected:
            return BatchResult((), 0, 0)
        if not self._settings.memory_enabled or self._memory is None:
            translated = self._translate_work(tuple(enumerate(expected)))
            return BatchResult(tuple(translated[index] for index in range(len(expected))), len(expected), 0)

        keys = [self._key(unit) for unit in expected]
        restored: dict[int, TranslationUnitResult] = {}
        missing_by_key: dict[str, list[int]] = {}
        cache_hits = 0
        for index, (unit, key) in enumerate(zip(expected, keys, strict=True)):
            cached = self._memory.get(key)
            if cached is not None:
                restored[index] = cached.for_unit(unit)
                cache_hits += 1
            else:
                missing_by_key.setdefault(key, []).append(index)

        representatives = tuple((indices[0], expected[indices[0]]) for indices in missing_by_key.values())
        translated = self._translate_work(representatives)
        for key, indices in missing_by_key.items():
            representative = indices[0]
            result = translated[representative]
            valid = self._quality_validator(expected[representative], result)
            self._memory.put(key, MemoryValue.from_result(result), quality_valid=valid)
            for index in indices:
                restored[index] = TranslationUnitResult(
                    stable_id=expected[index].stable_id,
                    translated_text=result.translated_text,
                    provider=result.provider,
                    model=result.model,
                )
        return BatchResult(
            tuple(restored[index] for index in range(len(expected))),
            len(representatives),
            cache_hits,
        )

    def _translate_work(
        self,
        indexed_units: tuple[tuple[int, TranslationUnit], ...],
    ) -> dict[int, TranslationUnitResult]:
        translated: dict[int, TranslationUnitResult] = {}
        with ThreadPoolExecutor(max_workers=self._settings.effective_concurrency) as executor:
            futures = {
                executor.submit(self._translator, unit): index
                for index, unit in indexed_units
            }
            for future in as_completed(futures):
                translated[futures[future]] = future.result()
        return translated

    def _key(self, unit: TranslationUnit) -> str:
        return build_memory_key(
            unit,
            self._provider,
            self._model,
            prompt_version=self._settings.prompt_version,
            glossary_version=self._settings.glossary_version,
            stop_words_version=self._settings.stop_words_version,
            quality_policy_version=self._settings.quality_policy_version,
        ).sha256


def iter_batches(units: Sequence[TranslationUnit], batch_size: int) -> Iterable[tuple[TranslationUnit, ...]]:
    if batch_size < 1:
        raise InvalidBatchSetting("batch_size", batch_size)
    for start in range(0, len(units), batch_size):
        yield tuple(units[start : start + batch_size])


def _default_quality_validator(unit: TranslationUnit, result: TranslationUnitResult) -> bool:
    return result.stable_id == unit.stable_id and (not unit.source_text.strip() or bool(result.translated_text.strip()))
