from __future__ import annotations

from dataclasses import replace

from app.jobs.types import JobKind, JobSnapshot, JobStage, JobStatus, TaskId, legacy_status


def _snapshot(status: JobStatus) -> JobSnapshot:
    return JobSnapshot(
        public_id=TaskId("task_abc"),
        user_id=1,
        kind=JobKind.PDF_TRANSLATION,
        status=status,
        stage=JobStage.TRANSLATE,
        progress=30,
        request={
            "file_type": "pdf",
            "source_language": "en",
            "target_language": "zh",
            "model": "qwen",
            "selected_pages": [],
            "bilingual_translation": "paragraph_up",
            "enable_image_ocr": False,
            "enable_text_splitting": "False",
            "enable_uno_conversion": True,
            "vocabulary_ids": [],
        },
        version=2,
        attempt=1,
        source_path="source.pdf",
        output_path=None,
        source_sha256=None,
        artifact_sha256=None,
        error_code=None,
        error_message=None,
        lease_owner=None,
        lease_expires_at=None,
    )


def test_legacy_status_projector_maps_active_statuses_without_side_effects():
    # Given
    queued = _snapshot(JobStatus.QUEUED)
    running = _snapshot(JobStatus.RUNNING)

    # When
    queued_projection = legacy_status(queued)
    running_projection = legacy_status(running)

    # Then
    assert queued_projection["status"] == "waiting"
    assert running_projection["status"] == "processing"
    assert running_projection["canonical_status"] == "running"
    assert running.status is JobStatus.RUNNING


def test_legacy_status_projector_maps_terminal_statuses_to_legacy_fields():
    # Given
    succeeded = replace(
        _snapshot(JobStatus.SUCCEEDED),
        progress=100,
        stage=JobStage.FINALIZE,
        output_path="done.docx",
    )
    failed = replace(
        _snapshot(JobStatus.FAILED),
        error_code="provider_error",
        error_message="provider failed",
    )
    interrupted = replace(_snapshot(JobStatus.INTERRUPTED), error_message="lease expired")

    # When
    success_projection = legacy_status(succeeded)
    failed_projection = legacy_status(failed)
    interrupted_projection = legacy_status(interrupted)

    # Then
    assert success_projection["status"] == "completed"
    assert success_projection["stored_filename"] == "done.docx"
    assert failed_projection["status"] == "failed"
    assert failed_projection["error"] == "provider failed"
    assert interrupted_projection["status"] == "failed"
    assert interrupted_projection["error_code"] == "interrupted"
