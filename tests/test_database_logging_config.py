from __future__ import annotations

import importlib

import pytest
from flask import Flask

from app.config import DevelopmentConfig


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (
        (None, False),
        ("false", False),
        ("0", False),
        ("true", True),
        ("1", True),
    ),
)
def test_sqlalchemy_echo_is_quiet_by_default_and_explicitly_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str | None,
    expected: bool,
) -> None:
    if raw_value is None:
        monkeypatch.delenv("SQLALCHEMY_ECHO", raising=False)
    else:
        monkeypatch.setenv("SQLALCHEMY_ECHO", raw_value)
    config_module = importlib.import_module("app.config")
    monkeypatch.setattr(config_module.os, "makedirs", lambda *args, **kwargs: None)

    flask_app = Flask(__name__)
    flask_app.config.from_object(DevelopmentConfig)
    DevelopmentConfig.init_app(flask_app)

    assert flask_app.config["SQLALCHEMY_ECHO"] is expected
