from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import db
from app.jobs.artifacts import PromotedArtifact
from app.jobs.history import register_completion_history_once
from app.jobs.types import JobKind, JobSnapshot, JobStage, JobStatus, TaskId
from app.models.upload_record import UploadRecord
from app.models.user import User


@dataclass(slots=True)
class ScalarResult:
    value: int | None

    def scalar_one_or_none(self) -> int | None:
        return self.value


class RecordingSession:
    def __init__(self) -> None:
        self.records = []
        self.commits = 0

    def execute(self, statement) -> ScalarResult:
        return ScalarResult(1 if self.records else None)

    def add(self, record) -> None:
        self.records.append(record)

    def commit(self) -> None:
        self.commits += 1


def _snapshot(path: Path) -> JobSnapshot:
    return JobSnapshot(
        public_id=TaskId("task_history"),
        user_id=12,
        kind=JobKind.PDF_TRANSLATION,
        status=JobStatus.RUNNING,
        stage=JobStage.FINALIZE,
        progress=90,
        request={},
        version=5,
        attempt=1,
        source_path=str(path),
        output_path=None,
        source_sha256=None,
        artifact_sha256=None,
        error_code=None,
        error_message=None,
        lease_owner="worker",
        lease_expires_at=None,
    )


def test_completion_history_registration_is_idempotent_after_promotion(tmp_path: Path) -> None:
    artifact_path = tmp_path / "translated.docx"
    artifact_path.write_bytes(b"docx")
    artifact = PromotedArtifact(artifact_path, "a" * 64)
    session = RecordingSession()
    snapshot = _snapshot(artifact_path)

    registrations = [register_completion_history_once(session, snapshot, artifact) for _ in range(10)]

    assert registrations == [True] + [False] * 9
    assert len(session.records) == 1
    assert session.commits == 1
    assert session.records[0].file_path == str(tmp_path.resolve())


def test_v2_ppt_completion_makes_the_exact_upload_record_downloadable(tmp_path: Path) -> None:
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'history.sqlite'}")
    db.metadata.create_all(engine, tables=[User.__table__, UploadRecord.__table__])
    session = Session(engine)
    session.add(User(id=12, username="ppt-owner", password="unused", status="approved"))
    source = tmp_path / "user_12" / "upload-uuid.pptx"
    source.parent.mkdir()
    source.write_bytes(b"translated-last-page")
    record = UploadRecord(
        user_id=12,
        filename="deck.pptx",
        stored_filename=source.name,
        file_path=str(source.parent),
        file_size=7,
        status="pending",
    )
    unrelated = UploadRecord(
        user_id=12,
        filename="other.pptx",
        stored_filename="other.pptx",
        file_path=str(tmp_path / "unrelated"),
        file_size=5,
        status="pending",
    )
    session.add_all([record, unrelated])
    session.commit()
    snapshot = JobSnapshot(
        public_id=TaskId("task_ppt_history"),
        user_id=12,
        kind=JobKind.PPT_TRANSLATION,
        status=JobStatus.RUNNING,
        stage=JobStage.FINALIZE,
        progress=90,
        request={"upload_record_id": record.id, "output_path": str(source)},
        version=5,
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
    artifact = PromotedArtifact(source.resolve(), "b" * 64)

    # When
    mismatched = replace(
        snapshot,
        request={"upload_record_id": unrelated.id, "output_path": str(source)},
    )
    mismatched_registered = register_completion_history_once(session, mismatched, artifact)
    registered = register_completion_history_once(session, snapshot, artifact)

    # Then
    assert mismatched_registered is False
    assert unrelated.status == "pending"
    assert unrelated.stored_filename == "other.pptx"
    assert registered is True
    assert record in session.dirty
    with Session(engine) as verification:
        assert verification.get(UploadRecord, record.id).status == "pending"

    session.commit()
    session.refresh(record)
    assert record.status == "completed"
    assert record.file_path == str(source.parent.resolve())
    assert record.stored_filename == source.name
    assert record.file_size == len(b"translated-last-page")
    assert register_completion_history_once(session, snapshot, artifact) is False
