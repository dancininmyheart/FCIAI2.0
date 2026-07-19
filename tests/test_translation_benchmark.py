from __future__ import annotations

from tools.qa.benchmark_translation_architecture import _percentile, run_benchmark


def test_percentile_uses_nearest_rank() -> None:
    assert _percentile([1, 2, 3, 4, 5], 0.95) == 5
    assert _percentile([1, 2, 3, 4, 5], 0.5) == 3


def test_benchmark_gates_latency_and_exact_duplicate_reduction() -> None:
    payload = run_benchmark()
    duplicate = payload["duplicate_fixture"]

    assert all(item["p95_ratio"] <= 1.2 for item in payload["latency"])
    assert duplicate["memory_off_calls"] == 100
    assert duplicate["memory_on_calls"] == 1
    assert duplicate["equal_output_hash_and_order"] is True
