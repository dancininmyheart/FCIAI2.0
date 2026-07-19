from __future__ import annotations

from pathlib import Path

from flask import Flask

from app.jobs.artifacts import JobArtifactStore, sha256_file
from app.jobs.types import JobKind, JobSnapshot, JobStage, JobStatus, TaskId
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request


def _snapshot(source: Path, output: Path) -> JobSnapshot:
    request = build_translation_job_request(
        TranslationJobSpec(
            file_type="pptx",
            source_language="en",
            target_language="zh",
            model="qwen",
            output_path=str(output),
        ),
    )
    return JobSnapshot(
        public_id=TaskId("task_recovery"),
        user_id=9,
        kind=JobKind.PPT_TRANSLATION,
        status=JobStatus.RUNNING,
        stage=JobStage.FINALIZE,
        progress=90,
        request=request.to_json(),
        version=5,
        attempt=2,
        source_path=str(source),
        output_path=None,
        source_sha256=None,
        artifact_sha256=None,
        error_code=None,
        error_message=None,
        lease_owner="worker",
        lease_expires_at=None,
    )


def test_crash_before_promotion_leaves_no_downloadable_partial(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    final = tmp_path / "final.pptx"
    source.write_bytes(b"source")
    snapshot = _snapshot(source, final)

    with isolated_app.app_context():
        prepared = JobArtifactStore().prepare_attempt(snapshot)
        prepared.work_path.write_bytes(b"partial")

    assert not final.exists()
    assert prepared.work_path.read_bytes() == b"partial"


def test_crash_after_promotion_reuses_existing_artifact(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    final = tmp_path / "final.pptx"
    source.write_bytes(b"source")
    snapshot = _snapshot(source, final)

    with isolated_app.app_context():
        store = JobArtifactStore()
        prepared = store.prepare_attempt(snapshot)
        prepared.work_path.write_bytes(b"valid")
        first = store.promote(snapshot, prepared, prepared.work_path)
        recovered = store.promoted(snapshot)

    assert recovered == first
    assert sha256_file(final) == first.sha256


def test_corrupt_attempt_never_promotes_or_replaces_valid_artifact(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    final = tmp_path / "final.pptx"
    source.write_bytes(b"source")
    snapshot = _snapshot(source, final)

    with isolated_app.app_context():
        store = JobArtifactStore()
        prepared = store.prepare_attempt(snapshot)
        prepared.work_path.write_bytes(b"valid")
        valid = store.promote(snapshot, prepared, prepared.work_path)
        prepared.work_path.write_bytes(b"corrupt")
        recovered = store.promote(snapshot, prepared, prepared.work_path)

    assert recovered == valid
    assert final.read_bytes() == b"valid"
    assert sha256_file(final) == valid.sha256
