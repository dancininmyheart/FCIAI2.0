from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path
from typing import Iterator

import pytest
from flask import Flask

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[1]
TASK_EVIDENCE = ROOT / ".omo" / "evidence" / "task-1-translation-architecture-optimization"
PYTEST_BASETEMP_ROOT = ROOT / ".omo" / "evidence" / "pytest-basetemp"


def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp is not None:
        return
    PYTEST_BASETEMP_ROOT.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(PYTEST_BASETEMP_ROOT / f"run-{os.getpid()}")


@pytest.fixture
def isolated_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Flask]:
    # Given
    runtime = tmp_path / "runtime"
    uploads = runtime / "uploads"
    logs = runtime / "logs"
    database = runtime / "testing.sqlite"
    for path in (uploads, logs):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.setenv("LOG_DIR", str(logs))

    import app as app_pkg

    cleanup = types.ModuleType("app.tasks.cleanup")
    cleanup.schedule_cleanup_task = lambda: None
    monkeypatch.setitem(sys.modules, "app.tasks.cleanup", cleanup)
    monkeypatch.setattr(app_pkg.os, "makedirs", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_pkg.db, "create_all", lambda: None)
    monkeypatch.setattr(app_pkg.thread_pool, "configure", lambda **kwargs: None)
    monkeypatch.setattr(app_pkg.translation_queue, "configure", lambda **kwargs: None)
    monkeypatch.setattr(app_pkg.translation_queue, "start_processor", lambda: None)
    monkeypatch.setattr(app_pkg.http_client, "configure", lambda **kwargs: None)
    monkeypatch.setattr(app_pkg, "setup_db_monitoring", lambda flask_app, interval=3600: None)
    monkeypatch.setattr(app_pkg.log_manager, "configure", lambda **kwargs: None)
    monkeypatch.setattr(app_pkg.log_manager, "get_logger", lambda: logging.getLogger("tests.app"))

    # When
    flask_app = app_pkg.create_app("testing")
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database}",
        UPLOAD_FOLDER=str(uploads),
        WTF_CSRF_ENABLED=False,
    )

    # Then
    yield flask_app
