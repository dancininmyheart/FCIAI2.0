from __future__ import annotations

import logging

import pytest
from flask import Flask

from app.translation.metrics import TranslationCorrelation, TranslationMetrics, log_translation_event
from app.translation.providers import ProviderRegistry, QwenProvider
from app.translation.types import ProviderError, ProviderRequest


class SecretFailingTransport:
    def complete(self, model: str, system: str, user: str, timeout_seconds: float) -> str:
        raise RuntimeError("api-key=secret response=private-source")


def test_metrics_aggregate_stage_provider_quality_and_cache() -> None:
    metrics = TranslationMetrics()
    metrics.record_stage("provider", 0.01)
    metrics.record_stage("provider", 0.03)
    metrics.record_provider_failure("qwen", "provider_timeout")
    metrics.record_quality_finding("placeholder_mismatch")
    metrics.record_cache(True)
    metrics.record_cache(False)

    snapshot = metrics.snapshot()

    assert snapshot.stage_latency_ms["provider"] == {"count": 2, "total_ms": 40.0, "average_ms": 20.0}
    assert snapshot.provider_failures == {"qwen:provider_timeout": 1}
    assert snapshot.quality_findings == {"placeholder_mismatch": 1}
    assert snapshot.cache == {"hit": 1, "miss": 1}


def test_provider_failure_logs_correlation_without_secret_or_source_body(
    isolated_app: Flask,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = ProviderRequest.create("private-source", "en", "zh")
    registry = ProviderRegistry((QwenProvider(SecretFailingTransport()),))
    caplog.set_level(logging.INFO)

    with isolated_app.app_context(), pytest.raises(ProviderError):
        registry.translate("qwen", request)

    logs = caplog.text
    assert "provider_failed" in logs
    assert "provider=qwen" in logs
    assert "provider_unavailable" in logs
    assert "secret" not in logs
    assert "private-source" not in logs


def test_structured_event_contains_required_correlation_fields(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("translation-test")
    caplog.set_level(logging.INFO)

    log_translation_event(
        logger,
        "completed",
        TranslationCorrelation("task_public", 2, "finalize", "deepseek"),
        duration_seconds=0.25,
        retry_count=1,
        cache_result="hit",
    )

    assert "job_id=task_public" in caplog.text
    assert "attempt=2" in caplog.text
    assert "stage=finalize" in caplog.text
    assert "provider=deepseek" in caplog.text
    assert "retry_count=1" in caplog.text
    assert "cache=hit" in caplog.text
