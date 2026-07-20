from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest
from flask import Flask

from app.jobs.types import JobCreation, JobKind, JobLease, JobStatus, WorkerId
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request
from test_job_worker import _store

VALID_ANNOTATION = {
    "page": 1,
    "coords": {"left": 1, "top": 2, "width": 3, "height": 4},
    "text": "note",
    "ocrResult": "ocr",
    "translation": "translated",
}


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
    return JobCreation(user_id=user_id, kind=JobKind.PPT_TRANSLATION, request=request, source_path=str(output_path))


def _pdf_creation(user_id: int | None, output_path: Path) -> JobCreation:
    request = build_translation_job_request(
        TranslationJobSpec(
            file_type="pdf",
            source_language="en",
            target_language="zh",
            model="qwen",
            access="public" if user_id is None else "private",
            output_path=str(output_path),
            original_filename="source.pdf",
            unique_filename="source.pdf",
        ),
    )
    return JobCreation(user_id=user_id, kind=JobKind.PDF_TRANSLATION, request=request, source_path=str(output_path))


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
        JobSuccess(output_path=creation.source_path or "", artifact_sha256="0" * 64, expected_version=running.version),
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

    # When / Then: unrelated users remain forbidden.
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=11, is_authenticated=True, is_administrator=lambda: False),
    )
    assert client.get("/download/401").status_code == 403

    # When / Then: the owner can download.
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=10, is_authenticated=True, is_administrator=lambda: False),
    )
    owner_response = client.get("/download/401")
    assert owner_response.status_code == 200
    assert owner_response.data == b"translated"

    # When / Then: an administrator can download another user's file.
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


def test_v2_download_translated_pdf_uses_task_id_authorization_and_rejects_traversal(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    isolated_app.config["LOGIN_DISABLED"] = True
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    output_root = Path(isolated_app.config["UPLOAD_FOLDER"]) / "pdf_outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    owned_file = output_root / "owned.docx"
    public_file = output_root / "public.docx"
    owned_file.write_bytes(b"owned")
    public_file.write_bytes(b"public")
    private_job = _succeed(store, _pdf_creation(10, owned_file))
    public_job = _succeed(store, _pdf_creation(None, public_file))
    client = isolated_app.test_client()

    # When / Then
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=11, is_authenticated=True, is_administrator=lambda: False),
    )
    assert client.get(f"/download_translated_pdf/{private_job.public_id}").status_code == 403
    traversal = client.get("/download_translated_pdf/..%5Csecret.docx")
    assert traversal.status_code == 400
    assert traversal.data != b"secret"
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=10, is_authenticated=True, username="owner", is_administrator=lambda: False),
    )
    owner = client.get(f"/download_translated_pdf/{private_job.public_id}")
    assert owner.status_code == 200
    assert owner.data == b"owned"
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(is_authenticated=False))
    public = client.get(f"/download_translated_pdf/{public_job.public_id}")
    assert public.status_code == 200
    assert public.data == b"public"


def test_v2_pdf_annotation_submit_status_cancel_and_download_use_ledger(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views
    from app.jobs.types import JobSuccess

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    isolated_app.config["LOGIN_DISABLED"] = True
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(main_views, "_signal_worker", lambda: None)
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=12, username="annotator", is_authenticated=True, is_administrator=lambda: False),
    )
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    pdf_path = upload_root / "pdf_uploads" / "source.pdf"
    output_path = upload_root / "pdf_outputs" / "source_annotated.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF")
    output_path.write_bytes(b"annotated")
    client = isolated_app.test_client()
    with client.session_transaction() as session:
        session["username"] = "annotator"

    # When
    start = client.post(
        "/api/start_pdf_annotation",
        json={"file_path": str(pdf_path), "output_path": str(output_path), "annotations": [VALID_ANNOTATION]},
    )
    task_id = start.get_json()["task_id"]
    status = client.get("/api/pdf_task_status")
    cancel = client.get(f"/cancel_task/{task_id}")
    canceled = store.get(task_id)
    second = main_views._create_pdf_annotation_ledger_job(
        12,
        str(pdf_path),
        [VALID_ANNOTATION],
        str(output_path),
        "source.pdf",
    )
    running = store.claim(
        second.public_id,
        JobLease(
            worker_id=WorkerId("worker-a"),
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            expected_version=second.version,
        ),
    )
    store.succeed(
        running.public_id,
        JobSuccess(output_path=str(output_path), artifact_sha256="0" * 64, expected_version=running.version),
    )
    download = client.get(f"/download/{second.public_id}")

    # Then
    assert start.status_code == 200
    assert status.get_json()["canonical_status"] == JobStatus.QUEUED.value
    assert cancel.status_code == 200
    assert canceled.status is JobStatus.CANCELED
    assert download.status_code == 200
    assert b"annotated" in download.data


def test_v2_pdf_annotation_rejects_arbitrary_source_and_ignores_client_output(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    isolated_app.config["LOGIN_DISABLED"] = True
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(main_views, "_signal_worker", lambda: None)
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=12, username="annotator", is_authenticated=True, is_administrator=lambda: False),
    )
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    uploaded_pdf = upload_root / "pdf_uploads" / "source.pdf"
    uploaded_pdf.parent.mkdir(parents=True, exist_ok=True)
    uploaded_pdf.write_bytes(b"%PDF")
    outside_pdf = tmp_path / "outside.pdf"
    outside_output = tmp_path / "outside_annotated.pdf"
    outside_pdf.write_bytes(b"%PDF")
    client = isolated_app.test_client()
    with client.session_transaction() as session:
        session["username"] = "annotator"

    # When
    rejected = client.post("/api/start_pdf_annotation", json={"file_path": str(outside_pdf), "annotations": []})
    accepted = client.post(
        "/api/start_pdf_annotation",
        json={"file_path": str(uploaded_pdf), "output_path": str(outside_output), "annotations": [VALID_ANNOTATION]},
    )
    task_id = accepted.get_json()["task_id"]
    snapshot = store.get(task_id)

    # Then
    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert snapshot.source_path == str(uploaded_pdf.resolve())
    assert snapshot.request["output_path"].startswith(str((upload_root / "pdf_outputs").resolve()))
    assert snapshot.request["output_path"] != str(outside_output)


@pytest.mark.parametrize(
    "annotations",
    [
        [3],
        [{"unexpected": "x"}],
        [{"page": 1, "coords": {"1": "bad"}}],
        [{"page": 1, "coords": {"left": "bad", "top": 0, "width": 1, "height": 1}}],
        [{"page": True, "coords": {"left": 0, "top": 0, "width": 1, "height": 1}}],
        [{"page": 0, "coords": {"left": 0, "top": 0, "width": 1, "height": 1}}],
        [{"page": 1, "coords": {"left": 0, "top": 0, "width": 0, "height": 1}}],
        [{"page": 1, "coords": {"left": 0, "top": 0, "width": 1, "height": 1, "extra": 2}}],
    ],
)
def test_v2_pdf_annotation_rejects_malformed_annotations_before_ledger_create(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
    annotations: list,
) -> None:
    # Given
    import app.views.main as main_views
    from app.models.translation_job import TranslationJob

    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    isolated_app.config["LOGIN_DISABLED"] = True
    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(main_views, "_signal_worker", lambda: None)
    monkeypatch.setattr(
        main_views,
        "current_user",
        SimpleNamespace(id=12, username="annotator", is_authenticated=True, is_administrator=lambda: False),
    )
    upload_root = Path(isolated_app.config["UPLOAD_FOLDER"])
    uploaded_pdf = upload_root / "pdf_uploads" / "source.pdf"
    uploaded_pdf.parent.mkdir(parents=True, exist_ok=True)
    uploaded_pdf.write_bytes(b"%PDF")
    client = isolated_app.test_client()

    # When
    response = client.post(
        "/api/start_pdf_annotation",
        json={"file_path": str(uploaded_pdf), "annotations": annotations},
    )

    # Then
    assert response.status_code == 400
    assert store._session.query(TranslationJob).count() == 0
