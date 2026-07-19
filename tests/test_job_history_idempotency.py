from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.jobs.artifacts import PromotedArtifact
from app.jobs.history import register_completion_history_once
from app.jobs.types import JobKind, JobSnapshot, JobStage, JobStatus, TaskId


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
