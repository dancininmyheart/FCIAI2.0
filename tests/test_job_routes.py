from __future__ import annotations

from io import BytesIO
from pathlib import Path

from flask import Flask
import pytest

from app.jobs.types import JobStatus
from test_job_worker import _store


def test_public_v2_submission_persists_ledger_and_survives_second_app(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    import app as app_pkg
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    main_views.simple_task_status.clear()
    main_views.simple_task_files.clear()
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    (Path(isolated_app.config["UPLOAD_FOLDER"]) / "temp").mkdir(parents=True)
    client = isolated_app.test_client()

    # When
    start_response = client.post("/start_translation", data={"file": (BytesIO(b"pptx"), "deck.pptx")})
    task_id = start_response.get_json()["task_id"]
    first_status = client.get(f"/task_status/{task_id}").get_json()

    second_app = app_pkg.create_app("testing")
    second_app.config.update(isolated_app.config)
    second_status = second_app.test_client().get(f"/task_status/{task_id}").get_json()

    # Then
    assert start_response.status_code == 200
    assert task_id.startswith("task_")
    assert first_status == second_status
    assert first_status["canonical_status"] == JobStatus.QUEUED.value
    assert main_views.simple_task_status == {}


def test_public_legacy_submission_keeps_simple_status_cache(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    import app.views.main as main_views

    class FakeThread:
        daemon = False

        def __init__(self, target, args) -> None:
            self.target = target
            self.args = args

        def start(self) -> None:
            return None

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "legacy")
    monkeypatch.setattr(main_views.threading, "Thread", FakeThread)
    main_views.simple_task_status.clear()
    (Path(isolated_app.config["UPLOAD_FOLDER"]) / "temp").mkdir(parents=True)
    client = isolated_app.test_client()

    # When
    response = client.post("/start_translation", data={"file": (BytesIO(b"pptx"), "deck.pptx")})
    task_id = response.get_json()["task_id"]

    # Then
    assert response.status_code == 200
    assert task_id in main_views.simple_task_status
    assert main_views.simple_task_status[task_id]["status"] == "processing"


@pytest.mark.parametrize("path", ["/cancel_task/task_missing", "/get_queue_status"])
def test_removed_operational_routes_are_not_exposed(isolated_app: Flask, path: str) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.get(path)

    # Then
    assert response.status_code == 404
