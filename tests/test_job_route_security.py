from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.jobs.types import JobCreation, JobKind, JobLease, WorkerId
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request
from test_job_worker import _store


def _creation(user_id: int | None, output_path: Path) -> JobCreation:
    request = build_translation_job_request(
        TranslationJobSpec(
            file_type="pptx",
            source_language="en",
            target_language="zh",
            model="qwen",
            access="public" if user_id is None else "private",
            output_path=str(output_path),
            original_filename=output_path.name,
            unique_filename=output_path.name,
        ),
    )
    return JobCreation(
        user_id=user_id,
        kind=JobKind.PPT_TRANSLATION,
        request=request,
        source_path=str(output_path),
    )


def _succeed(store, creation: JobCreation):
    from app.jobs.types import JobSuccess

    created = store.create(creation)
    running = store.claim(
        created.public_id,
        JobLease(
            worker_id=WorkerId("worker-a"),
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            expected_version=created.version,
        ),
    )
    return store.succeed(
        running.public_id,
        JobSuccess(
            output_path=creation.source_path or "",
            artifact_sha256="0" * 64,
            expected_version=running.version,
        ),
    )


def test_v2_download_requires_owner_or_admin_for_private_jobs(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    public_file = upload_root / "public.pptx"
    private_file = upload_root / "private.pptx"
    public_file.write_bytes(b"public")
    private_file.write_bytes(b"private")
    public_job = _succeed(store, _creation(None, public_file))
    private_job = _succeed(store, _creation(10, private_file))
    client = isolated_app.test_client()

    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(is_authenticated=False))
    assert client.get(f"/download/{public_job.public_id}").status_code == 200
    assert client.get(f"/download/{private_job.public_id}").status_code == 401
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=11, is_authenticated=True, is_administrator=lambda: False),
    )
    assert client.get(f"/download/{private_job.public_id}").status_code == 403
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=10, is_authenticated=True, is_administrator=lambda: False),
    )
    assert client.get(f"/download/{private_job.public_id}").status_code == 200
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=99, is_authenticated=True, is_administrator=lambda: True),
    )
    assert client.get(f"/download/{private_job.public_id}").status_code == 200


def test_legacy_upload_download_requires_owner_or_admin(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    import app.views.main as main_views

    isolated_app.config["LOGIN_DISABLED"] = True
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    stored_file = upload_root / "user_10" / "translated.pptx"
    stored_file.parent.mkdir(parents=True, exist_ok=True)
    stored_file.write_bytes(b"translated")
    record = SimpleNamespace(
        id=401,
        user_id=10,
        file_path=str(stored_file.parent),
        stored_filename=stored_file.name,
        filename="presentation.pptx",
    )

    class FakeUploadRecord:
        query = SimpleNamespace(get_or_404=lambda record_id: record)

    monkeypatch.setattr(main_views, "UploadRecord", FakeUploadRecord)
    client = isolated_app.test_client()

    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=11, is_authenticated=True, is_administrator=lambda: False),
    )
    assert client.get("/download/401").status_code == 403

    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=10, is_authenticated=True, is_administrator=lambda: False),
    )
    owner_response = client.get("/download/401")
    assert owner_response.status_code == 200
    assert owner_response.data == b"translated"

    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=99, is_authenticated=True, is_administrator=lambda: True),
    )
    admin_response = client.get("/download/401")
    assert admin_response.status_code == 200
    assert admin_response.data == b"translated"


@pytest.mark.parametrize("escape_kind", ["outside", "symlink"])
def test_v2_public_ppt_download_rejects_containment_escape_before_public_access(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
    escape_kind: str,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    outside_file = tmp_path / "outside-secret.pptx"
    outside_file.write_bytes(b"outside-secret")
    if escape_kind == "outside":
        output_path = outside_file
    else:
        link_path = upload_root / "temp" / "linked-secret.pptx"
        link_path.parent.mkdir(parents=True, exist_ok=True)
        link_path.symlink_to(outside_file)
        output_path = link_path
    public_job = _succeed(store, _creation(None, output_path))
    client = isolated_app.test_client()

    # When
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(is_authenticated=False))
    response = client.get(f"/download/{public_job.public_id}")

    # Then
    assert response.status_code == 404
    assert response.data != b"outside-secret"


def test_v2_public_ppt_download_serves_contained_public_file(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    contained_file = upload_root / "temp" / "translated-public.pptx"
    contained_file.parent.mkdir(parents=True, exist_ok=True)
    contained_file.write_bytes(b"contained-public")
    public_job = _succeed(store, _creation(None, contained_file))
    client = isolated_app.test_client()

    # When
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(is_authenticated=False))
    response = client.get(f"/download/{public_job.public_id}")

    # Then
    assert response.status_code == 200
    assert response.data == b"contained-public"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/download_translated_pdf/task_missing"),
        ("GET", "/api/pdf_task_status"),
        ("GET", "/pdf_annotate"),
        ("POST", "/api/start_pdf_annotation"),
        ("POST", "/api/start_pdf_translation"),
    ],
)
def test_removed_pdf_routes_are_not_exposed(
    isolated_app: Flask,
    method: str,
    path: str,
) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.open(path, method=method)

    # Then
    assert response.status_code == 404
