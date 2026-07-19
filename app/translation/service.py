from __future__ import annotations

import threading
from dataclasses import dataclass

from flask import current_app, has_app_context

from app.config import TranslationSettings
from app.translation.batching import BatchSettings, TranslationBatchProcessor
from app.translation.memory import InMemoryTranslationMemory, TranslationMemory
from app.translation.metrics import current_metrics
from app.translation.pipeline import QualityPipelineResult, translate_with_quality
from app.translation.quality import QualityFinding, QualityMode, assess_quality
from app.translation.types import (
    ProviderError,
    ProviderRequest,
    TranslationProvider,
    TranslationUnit,
    TranslationUnitResult,
)


@dataclass(frozen=True, slots=True)
class DocumentTranslationResult:
    results: tuple[TranslationUnitResult, ...]
    findings: tuple[QualityFinding, ...]
    provider_unit_calls: int
    cache_hits: int


class DocumentTranslationService:
    def __init__(
        self,
        provider: TranslationProvider,
        model: str,
        settings: TranslationSettings,
        memory: TranslationMemory | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._settings = settings
        self._memory = memory
        self._findings: list[QualityFinding] = []
        self._findings_lock = threading.Lock()

    def translate(self, units: tuple[TranslationUnit, ...]) -> DocumentTranslationResult:
        batch_settings = BatchSettings(
            max_concurrency=self._settings.max_concurrency,
            provider_max_concurrency=self._settings.provider_max_concurrency,
            memory_enabled=self._settings.memory_enabled,
            quality_policy_version=self._settings.quality_mode,
        )
        processor = TranslationBatchProcessor(
            self._translate_unit,
            self._provider.name,
            self._model,
            batch_settings,
            self._memory,
            self._quality_valid_for_cache,
        )
        batch = processor.process(units)
        metrics = current_metrics()
        if metrics is not None:
            for _ in range(batch.cache_hits):
                metrics.record_cache(True)
            for _ in range(batch.provider_unit_calls):
                metrics.record_cache(False)
        return DocumentTranslationResult(
            results=batch.results,
            findings=tuple(self._findings),
            provider_unit_calls=batch.provider_unit_calls,
            cache_hits=batch.cache_hits,
        )

    def _translate_unit(self, unit: TranslationUnit) -> TranslationUnitResult:
        outcome = translate_with_quality(
            (unit,),
            self._translate_batch,
            QualityMode.parse(self._settings.quality_mode),
            fallback=self._legacy_fallback,
        )
        self._record_findings(outcome)
        if outcome.results:
            return outcome.results[0]
        return self._legacy_fallback(unit)

    def _translate_batch(self, units: tuple[TranslationUnit, ...]) -> tuple[TranslationUnitResult, ...]:
        results: list[TranslationUnitResult] = []
        for unit in units:
            try:
                response = self._provider.translate(
                    ProviderRequest.create(
                        text=unit.source_text,
                        field=unit.title_context or "document",
                        stop_words=unit.stop_words,
                        custom_translations=dict(unit.glossary),
                        source_language=unit.source_language,
                        target_language=unit.target_language,
                        output_format="plain",
                    ),
                )
                translated = response.text.strip()
            except ProviderError:
                translated = ""
            results.append(TranslationUnitResult(unit.stable_id, translated, self._provider.name, self._model))
        return tuple(results)

    def _record_findings(self, outcome: QualityPipelineResult) -> None:
        if not outcome.findings:
            return
        with self._findings_lock:
            self._findings.extend(outcome.findings)
        metrics = current_metrics()
        if metrics is not None:
            for finding in outcome.findings:
                metrics.record_quality_finding(finding.code.value)

    @staticmethod
    def _legacy_fallback(unit: TranslationUnit) -> TranslationUnitResult:
        return TranslationUnitResult(unit.stable_id, "", "legacy", "legacy")

    @staticmethod
    def _quality_valid_for_cache(unit: TranslationUnit, result: TranslationUnitResult) -> bool:
        return not assess_quality((unit,), (result,), QualityMode.OBSERVE).findings


def current_translation_settings() -> TranslationSettings:
    if not has_app_context():
        return TranslationSettings()
    settings = current_app.extensions.get("translation_settings")
    return settings if isinstance(settings, TranslationSettings) else TranslationSettings()


def current_translation_memory() -> TranslationMemory | None:
    if not has_app_context():
        return None
    memory = current_app.extensions.get("translation_memory")
    return memory if isinstance(memory, InMemoryTranslationMemory) else None
