from __future__ import annotations

import threading
import time

from app.translation.batching import BatchSettings, TranslationBatchProcessor
from app.translation.types import TranslationUnit, TranslationUnitResult


def test_total_and_provider_concurrency_limits_are_both_honored() -> None:
    lock = threading.Lock()
    active = 0
    maximum = 0

    def translate(unit: TranslationUnit) -> TranslationUnitResult:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return TranslationUnitResult(unit.stable_id, "ok", "qwen", "qwen")

    units = tuple(TranslationUnit.create(str(index), "pdf", str(index), "en", "zh") for index in range(12))
    processor = TranslationBatchProcessor(
        translate,
        "qwen",
        "qwen",
        BatchSettings(max_concurrency=4, provider_max_concurrency=2),
    )

    result = processor.process(units)

    assert len(result.results) == 12
    assert maximum == 2
