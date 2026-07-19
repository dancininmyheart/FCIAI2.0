from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.translation.providers import DeepSeekProvider, ProviderRegistry, QwenProvider
from app.translation.types import ProviderError, ProviderRequest


@dataclass(slots=True)
class RecordingQwenTransport:
    response: str = '[{"box_index":1}]'
    calls: list[tuple[str, str, str, float]] = field(default_factory=list)

    def complete(self, model: str, system: str, user: str, timeout_seconds: float) -> str:
        self.calls.append((model, system, user, timeout_seconds))
        return self.response


@dataclass(slots=True)
class RecordingRemoteTransport:
    response: str = '[{"box_index":1}]'
    calls: list[tuple[str, dict[str, str | bool], float]] = field(default_factory=list)

    def post(self, url: str, payload: dict[str, str | bool], timeout_seconds: float) -> str:
        self.calls.append((url, payload, timeout_seconds))
        return self.response


class TimeoutQwenTransport:
    def complete(self, model: str, system: str, user: str, timeout_seconds: float) -> str:
        raise TimeoutError("deadline")


@dataclass(slots=True)
class FailingQwenTransport:
    error: Exception
    calls: int = 0

    def complete(self, model: str, system: str, user: str, timeout_seconds: float) -> str:
        self.calls += 1
        raise self.error


def _request() -> ProviderRequest:
    return ProviderRequest.create(
        text="[block] Milk",
        field="nutrition",
        stop_words=("HMO",),
        custom_translations={"milk": "乳汁"},
        source_language="English",
        target_language="Chinese",
        timeout_seconds=9,
    )


def test_qwen_provider_preserves_semantic_prompt_contract() -> None:
    transport = RecordingQwenTransport()
    result = QwenProvider(transport).translate(_request())

    model, system, user, timeout = transport.calls[0]
    assert result.provider == "qwen"
    assert model == "qwen3-235b-a22b-instruct-2507"
    assert user == "[block] Milk"
    assert timeout == 9
    assert "[block]" in system
    assert "box_index" in system and "paragraph_index" in system
    assert '"HMO"' in system and '"milk": "乳汁"' in system


def test_deepseek_provider_preserves_wire_payload_contract() -> None:
    transport = RecordingRemoteTransport()
    result = DeepSeekProvider(transport).translate(_request())

    url, payload, timeout = transport.calls[0]
    assert result.provider == "deepseek"
    assert url.endswith("d145ae592efa4240867c3b1f99c7a5d7")
    assert timeout == 9
    assert payload == {
        "_streaming": False,
        "is_app_uid": False,
        "field": "nutrition",
        "text": "[block] Milk",
        "stop_words_str": '"HMO"',
        "custom_translations_str": '"milk": "乳汁"',
        "source_language": "English",
        "target_language": "Chinese",
    }


def test_registry_unknown_provider_has_no_fallback_call() -> None:
    qwen = RecordingQwenTransport()
    deepseek = RecordingRemoteTransport()
    registry = ProviderRegistry((QwenProvider(qwen), DeepSeekProvider(deepseek)))

    with pytest.raises(ProviderError) as raised:
        registry.translate("gpt4o", _request())

    assert raised.value.code == "unknown_provider"
    assert qwen.calls == []
    assert deepseek.calls == []


def test_provider_timeout_is_typed_and_never_falls_back() -> None:
    deepseek = RecordingRemoteTransport()
    registry = ProviderRegistry((QwenProvider(TimeoutQwenTransport()), DeepSeekProvider(deepseek)))

    with pytest.raises(ProviderError) as raised:
        registry.translate("qwen", _request())

    assert raised.value.code == "provider_timeout"
    assert raised.value.retryable is True
    assert deepseek.calls == []


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    (
        (TimeoutError("secret-token"), "provider_timeout", True),
        (RuntimeError("secret-response-body"), "provider_unavailable", True),
        (ValueError("secret-malformed-json"), "invalid_response", False),
    ),
)
def test_provider_failures_are_typed_redacted_and_never_cross_fallback(
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    qwen = FailingQwenTransport(error)
    deepseek = RecordingRemoteTransport()
    registry = ProviderRegistry((QwenProvider(qwen), DeepSeekProvider(deepseek)))

    with pytest.raises(ProviderError) as raised:
        registry.translate("qwen", _request())

    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "secret" not in str(raised.value)
    assert qwen.calls == 1
    assert deepseek.calls == []
