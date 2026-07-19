from __future__ import annotations

import logging
import threading
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, TypedDict

from flask import current_app, has_app_context


class MetricsSnapshotJson(TypedDict):
    stage_latency_ms: dict[str, dict[str, float | int]]
    provider_failures: dict[str, int]
    quality_findings: dict[str, int]
    cache: dict[str, int]


@dataclass(frozen=True, slots=True)
class TranslationCorrelation:
    public_job_id: str
    attempt: int
    stage: str
    provider: str


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    stage_latency_ms: dict[str, dict[str, float | int]]
    provider_failures: dict[str, int]
    quality_findings: dict[str, int]
    cache: dict[str, int]

    def to_dict(self) -> MetricsSnapshotJson:
        return {
            "stage_latency_ms": self.stage_latency_ms,
            "provider_failures": self.provider_failures,
            "quality_findings": self.quality_findings,
            "cache": self.cache,
        }


_CORRELATION: ContextVar[TranslationCorrelation | None] = ContextVar("translation_correlation", default=None)


class TranslationMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage_total_ms: Counter[str] = Counter()
        self._stage_count: Counter[str] = Counter()
        self._provider_failures: Counter[str] = Counter()
        self._quality_findings: Counter[str] = Counter()
        self._cache: Counter[str] = Counter()

    def record_stage(self, stage: str, duration_seconds: float) -> None:
        with self._lock:
            self._stage_total_ms[stage] += max(0.0, duration_seconds * 1000)
            self._stage_count[stage] += 1

    def record_provider_failure(self, provider: str, error_code: str) -> None:
        with self._lock:
            self._provider_failures[f"{provider}:{error_code}"] += 1

    def record_quality_finding(self, code: str) -> None:
        with self._lock:
            self._quality_findings[code] += 1

    def record_cache(self, hit: bool) -> None:
        with self._lock:
            self._cache["hit" if hit else "miss"] += 1

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            latency = {
                stage: {
                    "count": self._stage_count[stage],
                    "total_ms": round(total, 3),
                    "average_ms": round(total / self._stage_count[stage], 3),
                }
                for stage, total in sorted(self._stage_total_ms.items())
            }
            return MetricsSnapshot(
                stage_latency_ms=latency,
                provider_failures=dict(sorted(self._provider_failures.items())),
                quality_findings=dict(sorted(self._quality_findings.items())),
                cache={"hit": self._cache["hit"], "miss": self._cache["miss"]},
            )


@contextmanager
def bind_translation_correlation(correlation: TranslationCorrelation) -> Iterator[None]:
    token = _CORRELATION.set(correlation)
    try:
        yield
    finally:
        _CORRELATION.reset(token)


def current_correlation(provider: str = "") -> TranslationCorrelation:
    existing = _CORRELATION.get()
    if existing is not None:
        return TranslationCorrelation(existing.public_job_id, existing.attempt, existing.stage, provider or existing.provider)
    return TranslationCorrelation("unbound", 0, "translate", provider)


def current_metrics() -> TranslationMetrics | None:
    if not has_app_context():
        return None
    metrics = current_app.extensions.get("translation_metrics")
    return metrics if isinstance(metrics, TranslationMetrics) else None


def log_translation_event(
    logger: logging.Logger,
    event: str,
    correlation: TranslationCorrelation,
    *,
    duration_seconds: float,
    retry_count: int = 0,
    cache_result: str = "none",
    error_code: str = "none",
) -> None:
    logger.info(
        "translation_event=%s job_id=%s attempt=%d stage=%s provider=%s duration_ms=%.3f retry_count=%d cache=%s error_code=%s",
        event,
        correlation.public_job_id,
        correlation.attempt,
        correlation.stage,
        correlation.provider,
        max(0.0, duration_seconds * 1000),
        retry_count,
        cache_result,
        error_code,
    )
