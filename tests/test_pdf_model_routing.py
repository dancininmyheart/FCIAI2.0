from __future__ import annotations

from dataclasses import dataclass, field

from app.translation.providers import ProviderRegistry
from app.translation.types import ProviderError, ProviderName, ProviderRequest, ProviderResult
from app.utils import document_generator


@dataclass(slots=True)
class RecordingProvider:
    provider_name: ProviderName
    fail: bool = False
    calls: list[ProviderRequest] = field(default_factory=list)

    @property
    def name(self) -> ProviderName:
        return self.provider_name

    def translate(self, request: ProviderRequest) -> ProviderResult:
        self.calls.append(request)
        if self.fail:
            raise ProviderError(self.provider_name, "provider_unavailable", "offline", retryable=True)
        return ProviderResult(f"{self.provider_name}:{request.text}", self.provider_name, self.provider_name)


def test_pdf_text_invokes_exactly_selected_provider(monkeypatch) -> None:
    qwen = RecordingProvider("qwen")
    deepseek = RecordingProvider("deepseek")
    registry = ProviderRegistry((qwen, deepseek))
    monkeypatch.setattr(document_generator, "default_provider_registry", lambda: registry)

    translated = document_generator._sync_translate_single_text("Milk", provider_model="deepseek")

    assert translated == "deepseek:Milk"
    assert qwen.calls == []
    assert len(deepseek.calls) == 1


def test_selected_deepseek_failure_never_calls_qwen(monkeypatch) -> None:
    qwen = RecordingProvider("qwen")
    deepseek = RecordingProvider("deepseek", fail=True)
    registry = ProviderRegistry((qwen, deepseek))
    monkeypatch.setattr(document_generator, "default_provider_registry", lambda: registry)

    translated = document_generator._sync_translate_single_text("Milk", provider_model="deepseek")

    assert translated == ""
    assert qwen.calls == []
    assert len(deepseek.calls) == 1
