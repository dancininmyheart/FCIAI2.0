from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from flask import Flask

from app.jobs.artifacts import ArtifactIntegrityError, JobArtifactStore, sha256_file
from app.jobs.types import JobKind, JobSnapshot, JobStage, JobStatus, TaskId
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request


def _snapshot(source: Path, output: Path, *, public_id: str = "task_artifact") -> JobSnapshot:
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
        public_id=TaskId(public_id),
        user_id=7,
        kind=JobKind.PPT_TRANSLATION,
        status=JobStatus.RUNNING,
        stage=JobStage.TRANSLATE,
        progress=20,
        request=request.to_json(),
        version=4,
        attempt=1,
        source_path=str(source),
        output_path=None,
        source_sha256=None,
        artifact_sha256=None,
        error_code=None,
        error_message=None,
        lease_owner="worker",
        lease_expires_at=None,
    )


def test_source_is_immutable_and_attempt_uses_a_copy(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    source.write_bytes(b"original")
    snapshot = _snapshot(source, tmp_path / "final.pptx")

    with isolated_app.app_context():
        prepared = JobArtifactStore().prepare_attempt(snapshot)

    assert prepared.source_path.read_bytes() == b"original"
    assert prepared.work_path.read_bytes() == b"original"
    assert prepared.source_path != source
    assert prepared.source_sha256 == sha256_file(source)
    assert "attempts" in prepared.work_path.parts


def test_changed_immutable_source_is_rejected(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    source.write_bytes(b"original")
    snapshot = _snapshot(source, tmp_path / "final.pptx")

    with isolated_app.app_context():
        store = JobArtifactStore()
        immutable, digest = store.ensure_source(snapshot)
        immutable.write_bytes(b"changed")
        guarded = replace(snapshot, source_path=str(immutable), source_sha256=digest)
        with pytest.raises(ArtifactIntegrityError, match="source SHA-256 changed"):
            store.ensure_source(guarded)


def test_atomic_promotion_is_idempotent_for_ten_deliveries(isolated_app: Flask, tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    final = tmp_path / "final.pptx"
    source.write_bytes(b"source")
    snapshot = _snapshot(source, final)

    with isolated_app.app_context():
        store = JobArtifactStore()
        prepared = store.prepare_attempt(snapshot)
        prepared.work_path.write_bytes(b"translated")
        promoted = [store.promote(snapshot, prepared, prepared.work_path) for _ in range(10)]

    assert final.read_bytes() == b"translated"
    assert len({item.sha256 for item in promoted}) == 1
    assert len({item.path for item in promoted}) == 1
    assert promoted[0].sha256 == sha256_file(final)
