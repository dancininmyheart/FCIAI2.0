from __future__ import annotations

from io import BytesIO
from pathlib import Path

from flask import Flask
import pytest

from app.jobs.types import JobQueueCounts, JobStatus
from test_job_worker import _creation, _store


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


def test_v2_cancel_projects_from_ledger(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(
        main_views,
        "current_user",
        type("User", (), {"id": 3, "is_authenticated": True, "is_administrator": lambda self: False})(),
    )
    created = store.create(_creation())
    client = isolated_app.test_client()
    with client.session_transaction() as session:
        session["username"] = "public-user"

    # When
    cancel_response = client.get(f"/cancel_task/{created.public_id}")
    status_response = client.get(f"/task_status/{created.public_id}")

    # Then
    assert cancel_response.status_code == 200
    assert status_response.get_json()["canonical_status"] == JobStatus.CANCELED.value


def test_v2_detailed_queue_status_projects_from_ledger(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    import app.views.main as main_views

    def fail_direct_queue_call():
        raise AssertionError("v2 queue status must not read the direct in-memory queue")

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    monkeypatch.setattr(main_views.translation_queue, "get_queue_status", fail_direct_queue_call, raising=False)
    monkeypatch.setattr(
        main_views,
        "queue_counts",
        lambda session: JobQueueCounts(queued=2, running=1, succeeded=3, failed=1, canceled=0, interrupted=1, total=8),
    )
    client = isolated_app.test_client()
    with client.session_transaction() as session:
        session["username"] = "public-user"

    # When
    response = client.get("/get_queue_status")

    # Then
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["queue_status"]["waiting_tasks"] == 2
    assert payload["queue_status"]["active_tasks"] == 1
    assert payload["queue_status"]["failed_tasks"] == 2
