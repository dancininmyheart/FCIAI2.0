from __future__ import annotations

from app.translation.batching import BatchSettings, TranslationBatchProcessor, iter_batches
from app.translation.memory import InMemoryTranslationMemory
from app.translation.types import TranslationUnit, TranslationUnitResult


def _units(count: int) -> tuple[TranslationUnit, ...]:
    return tuple(TranslationUnit.create(f"pdf:b{index}", "pdf", "duplicate", "en", "zh") for index in range(count))


def test_duplicate_collapse_reduces_one_hundred_calls_to_one_and_preserves_order() -> None:
    calls = 0

    def translate(unit: TranslationUnit) -> TranslationUnitResult:
        nonlocal calls
        calls += 1
        return TranslationUnitResult(unit.stable_id, "重复", "qwen", "qwen")

    units = _units(100)
    without_memory = TranslationBatchProcessor(translate, "qwen", "qwen", BatchSettings(memory_enabled=False))
    legacy = without_memory.process(units)
    assert calls == 100

    calls = 0
    with_memory = TranslationBatchProcessor(
        translate,
        "qwen",
        "qwen",
        BatchSettings(memory_enabled=True),
        InMemoryTranslationMemory(),
    )
    optimized = with_memory.process(units)

    assert calls == 1
    assert legacy.provider_unit_calls == 100
    assert optimized.provider_unit_calls == 1
    assert [result.stable_id for result in optimized.results] == [unit.stable_id for unit in units]
    assert [result.translated_text for result in optimized.results] == ["重复"] * 100


def test_batch_boundaries_never_split_or_reorder_units() -> None:
    units = _units(7)

    batches = tuple(iter_batches(units, 3))

    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert tuple(unit for batch in batches for unit in batch) == units
