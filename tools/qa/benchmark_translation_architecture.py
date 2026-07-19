from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypeAlias

sys.dont_write_bytecode = True

BenchmarkJson: TypeAlias = str | int | float | bool | list["BenchmarkJson"] | dict[str, "BenchmarkJson"]


@dataclass(frozen=True, slots=True)
class LatencyResult:
    fixture: str
    warmups: int
    measured: int
    alternating_order: tuple[str, ...]
    legacy_seconds: tuple[float, ...]
    v2_seconds: tuple[float, ...]
    legacy_p50: float
    legacy_p95: float
    v2_p50: float
    v2_p95: float
    p95_ratio: float


def main() -> int:
    arguments = _arguments()
    sys.path.insert(0, str(arguments.root.resolve()))
    payload = run_benchmark()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ratios_ok = all(item["p95_ratio"] <= 1.2 for item in payload["latency"])
    duplicate = payload["duplicate_fixture"]
    duplicate_ok = duplicate["memory_off_calls"] == 100 and duplicate["memory_on_calls"] == 1
    return 0 if ratios_ok and duplicate_ok and duplicate["equal_output_hash_and_order"] else 1


def run_benchmark() -> dict[str, BenchmarkJson]:
    from app.translation.batching import BatchSettings, TranslationBatchProcessor
    from app.translation.memory import InMemoryTranslationMemory
    from app.translation.types import TranslationUnit, TranslationUnitResult

    units = tuple(TranslationUnit.create(str(index), "pdf", f"source {index}", "en", "zh") for index in range(20))

    def translate(unit: TranslationUnit) -> TranslationUnitResult:
        time.sleep(0.001)
        return TranslationUnitResult(unit.stable_id, f"translated {unit.source_text}", "qwen", "qwen")

    def legacy() -> str:
        results = tuple(translate(unit) for unit in units)
        return _result_hash(results)

    def v2() -> str:
        processor = TranslationBatchProcessor(
            translate,
            "qwen",
            "qwen",
            BatchSettings(max_concurrency=4, memory_enabled=False),
        )
        return _result_hash(processor.process(units).results)

    latency = _measure("uncached_translation", legacy, v2)
    duplicate_units = tuple(TranslationUnit.create(str(index), "pdf", "same", "en", "zh") for index in range(100))
    lock = threading.Lock()
    calls = 0

    def counted(unit: TranslationUnit) -> TranslationUnitResult:
        nonlocal calls
        with lock:
            calls += 1
        return TranslationUnitResult(unit.stable_id, "相同", "qwen", "qwen")

    memory_off = TranslationBatchProcessor(counted, "qwen", "qwen", BatchSettings(memory_enabled=False))
    off_results = memory_off.process(duplicate_units).results
    off_calls = calls
    calls = 0
    memory_on = TranslationBatchProcessor(
        counted,
        "qwen",
        "qwen",
        BatchSettings(memory_enabled=True),
        InMemoryTranslationMemory(),
    )
    on_results = memory_on.process(duplicate_units).results
    on_calls = calls
    return {
        "fixture_hash": hashlib.sha256("|".join(unit.source_text for unit in units).encode()).hexdigest(),
        "latency": [asdict(latency)],
        "duplicate_fixture": {
            "unit_count": 100,
            "memory_off_calls": off_calls,
            "memory_on_calls": on_calls,
            "call_reduction_ratio": 1 - (on_calls / max(off_calls, 1)),
            "equal_output_hash_and_order": _normalized_hash(off_results) == _normalized_hash(on_results),
            "output_hash": _normalized_hash(on_results),
        },
        "max_concurrency": 4,
    }


def _measure(fixture: str, legacy, v2, warmups: int = 5, measured: int = 30) -> LatencyResult:
    for _ in range(warmups):
        legacy()
        v2()
    legacy_times: list[float] = []
    v2_times: list[float] = []
    order: list[str] = []
    for index in range(measured):
        pair = (("legacy", legacy, legacy_times), ("v2", v2, v2_times))
        if index % 2:
            pair = tuple(reversed(pair))
        for name, operation, samples in pair:
            started = time.perf_counter()
            operation()
            samples.append(time.perf_counter() - started)
            order.append(name)
    legacy_p95 = _percentile(legacy_times, 0.95)
    v2_p95 = _percentile(v2_times, 0.95)
    return LatencyResult(
        fixture,
        warmups,
        measured,
        tuple(order),
        tuple(legacy_times),
        tuple(v2_times),
        statistics.median(legacy_times),
        legacy_p95,
        statistics.median(v2_times),
        v2_p95,
        v2_p95 / legacy_p95,
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _result_hash(results) -> str:
    return hashlib.sha256("|".join(result.translated_text for result in results).encode()).hexdigest()


def _normalized_hash(results) -> str:
    payload = "|".join(f"{result.stable_id}:{result.translated_text}" for result in results)
    return hashlib.sha256(payload.encode()).hexdigest()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
