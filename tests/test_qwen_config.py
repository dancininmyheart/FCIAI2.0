from __future__ import annotations

import pytest

from app.translation.qwen_config import DEFAULT_QWEN_MODEL, qwen_model_name


def test_qwen_model_defaults_to_qwen_3_7_plus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QWEN_MODEL", raising=False)

    assert DEFAULT_QWEN_MODEL == "qwen3.7-plus"
    assert qwen_model_name() == "qwen3.7-plus"


def test_qwen_model_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MODEL", "qwen-test-model")

    assert qwen_model_name() == "qwen-test-model"
