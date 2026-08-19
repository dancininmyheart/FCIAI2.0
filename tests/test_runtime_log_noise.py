from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask

from app.utils.logger import LogManager


def test_application_logger_does_not_propagate_to_root(tmp_path: Path) -> None:
    manager = LogManager()
    logger = logging.getLogger("tests.ppt_agent.runtime")
    original_level = logger.level
    original_propagate = logger.propagate
    manager.logger = logger

    try:
        manager.configure(log_dir=str(tmp_path))

        assert logger.propagate is False
    finally:
        manager._remove_handlers()
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def test_embedded_worker_development_server_disables_reloader(monkeypatch) -> None:
    import run

    calls: list[dict[str, object]] = []
    flask_app = Flask(__name__)
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("SERVER_PORT", "5055")
    monkeypatch.setattr(flask_app, "run", lambda **kwargs: calls.append(kwargs))

    run._run_flask_server(flask_app)

    assert calls == [{"host": "127.0.0.1", "port": 5055, "use_reloader": False}]
