from __future__ import annotations

from dataclasses import replace

from app.translation.batching import BatchSettings, TranslationBatchProcessor
from app.translation.memory import InMemoryTranslationMemory, MemoryValue, RedisTranslationMemory, build_memory_key
from app.translation.types import TranslationUnit, TranslationUnitResult


def _unit(unit_id: str = "a") -> TranslationUnit:
    return TranslationUnit.create(
        unit_id,
        "pdf",
        "same source",
        "en",
        "zh",
        context_before="before",
        glossary=(("source", "来源"),),
        stop_words=("HMO",),
    )


def _key(unit: TranslationUnit, **versions: str) -> str:
    defaults = {
        "prompt_version": "p1",
        "glossary_version": "g1",
        "stop_words_version": "s1",
        "quality_policy_version": "q1",
    }
    defaults.update(versions)
    return build_memory_key(unit, "qwen", "qwen-model", **defaults).sha256


def test_complete_memory_key_changes_for_every_semantic_dimension() -> None:
    unit = _unit()
    baseline = _key(unit)
    changed = {
        _key(replace(unit, source_text="different")),
        _key(replace(unit, context_before="different")),
        _key(replace(unit, target_language="ja")),
        _key(replace(unit, glossary=(("source", "源"),))),
        _key(unit, prompt_version="p2"),
        _key(unit, glossary_version="g2"),
        _key(unit, stop_words_version="s2"),
        _key(unit, quality_policy_version="q2"),
    }

    assert baseline not in changed
    assert len(changed) == 8


def test_invalid_result_is_never_cached() -> None:
    calls = 0

    def invalid(unit: TranslationUnit) -> TranslationUnitResult:
        nonlocal calls
        calls += 1
        return TranslationUnitResult(unit.stable_id, "", "qwen", "qwen")

    processor = TranslationBatchProcessor(
        invalid,
        "qwen",
        "qwen",
        BatchSettings(memory_enabled=True),
        InMemoryTranslationMemory(),
    )

    processor.process((_unit(),))
    processor.process((_unit(),))

    assert calls == 2


class FailingRedis:
    def get(self, key: str):
        raise RuntimeError("redis unavailable")

    def set(self, key: str, value: str):
        raise RuntimeError("redis unavailable")


def test_invalid_changed_key_and_redis_failure_never_reuse_stale_result() -> None:
    memory = InMemoryTranslationMemory()
    unit = _unit()
    memory.put(_key(unit), MemoryValue("cached", "qwen", "qwen"), quality_valid=False)

    assert memory.get(_key(unit)) is None
    assert memory.get(_key(replace(unit, glossary=(("source", "new"),)))) is None
    redis = RedisTranslationMemory(FailingRedis())
    assert redis.get("missing") is None
    redis.put("missing", MemoryValue("value", "qwen", "qwen"), quality_valid=True)
