from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.jobs.errors import IllegalJobTransition, InvalidProgress, JobNotFound, StaleJobState
from app.jobs.types import (
    JobCreation,
    JobFailure,
    JobLease,
    JobProgress,
    JobSnapshot,
    JobStage,
    JobStatus,
    JobSuccess,
    TaskId,
    parse_job_kind,
    parse_job_stage,
    parse_job_status,
)
from app.models.translation_job import TranslationJob


class TranslationJobStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, creation: JobCreation) -> JobSnapshot:
        row = TranslationJob(
            id=str(uuid.uuid4()),
            public_id=f"task_{uuid.uuid4().hex}",
            user_id=creation.user_id,
            kind=creation.kind.value,
            status=JobStatus.QUEUED.value,
            stage=JobStage.VALIDATE.value,
            progress=0,
            request_json=creation.request.to_json(),
            source_path=creation.source_path,
            source_sha256=creation.source_sha256,
            attempt=0,
            version=1,
        )
        self._session.add(row)
        self._session.commit()
        return _snapshot(row)

    def get(self, public_id: TaskId) -> JobSnapshot:
        return _snapshot(self._row(public_id))

    def record_source(
        self,
        public_id: TaskId,
        expected_version: int,
        source_path: str,
        source_sha256: str,
    ) -> JobSnapshot:
        current = self.get(public_id)
        if current.source_path == source_path and current.source_sha256 == source_sha256:
            return current
        self._transition_from_statuses(
            public_id,
            expected_version,
            (JobStatus.QUEUED,),
            "record_source",
            {"source_path": source_path, "source_sha256": source_sha256},
        )
        return self.get(public_id)

    def claim_next(self, lease: JobLease) -> JobSnapshot | None:
        rows = self._session.execute(
            select(TranslationJob).where(TranslationJob.status == JobStatus.QUEUED.value).order_by(TranslationJob.created_at.asc()).limit(10)
        ).scalars()
        for row in rows:
            try:
                next_lease = JobLease(worker_id=lease.worker_id, expires_at=lease.expires_at, expected_version=row.version)
                return self.claim(TaskId(row.public_id), next_lease)
            except (IllegalJobTransition, StaleJobState):
                continue
        return None

    def claim(self, public_id: TaskId, lease: JobLease) -> JobSnapshot:
        self._transition(
            public_id,
            lease.expected_version,
            JobStatus.QUEUED,
            "claim",
            {
                "status": JobStatus.RUNNING.value,
                "lease_owner": lease.worker_id,
                "lease_expires_at": lease.expires_at,
                "attempt": TranslationJob.attempt + 1,
                "started_at": datetime.now(UTC),
            },
        )
        return self.get(public_id)

    def progress(self, public_id: TaskId, progress: JobProgress) -> JobSnapshot:
        if progress.progress < 0 or progress.progress > 100:
            raise InvalidProgress(progress=progress.progress)
        self._transition(
            public_id,
            progress.expected_version,
            JobStatus.RUNNING,
            "progress",
            {"stage": progress.stage.value, "progress": progress.progress},
        )
        return self.get(public_id)

    def succeed(self, public_id: TaskId, success: JobSuccess) -> JobSnapshot:
        self._transition(
            public_id,
            success.expected_version,
            JobStatus.RUNNING,
            "succeed",
            {
                "status": JobStatus.SUCCEEDED.value,
                "stage": JobStage.FINALIZE.value,
                "progress": 100,
                "output_path": success.output_path,
                "artifact_sha256": success.artifact_sha256,
                "lease_owner": None,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            },
        )
        return self.get(public_id)

    def fail(self, public_id: TaskId, failure: JobFailure) -> JobSnapshot:
        self._transition(
            public_id,
            failure.expected_version,
            JobStatus.RUNNING,
            "fail",
            {
                "status": JobStatus.FAILED.value,
                "error_code": failure.error_code,
                "error_message": failure.error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            },
        )
        return self.get(public_id)

    def cancel(self, public_id: TaskId, expected_version: int) -> JobSnapshot:
        self._transition_from_statuses(
            public_id,
            expected_version,
            (JobStatus.QUEUED, JobStatus.RUNNING),
            "cancel",
            {
                "status": JobStatus.CANCELED.value,
                "lease_owner": None,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            },
        )
        return self.get(public_id)

    def interrupt(self, public_id: TaskId, expected_version: int) -> JobSnapshot:
        self._transition(
            public_id,
            expected_version,
            JobStatus.RUNNING,
            "interrupt",
            {
                "status": JobStatus.INTERRUPTED.value,
                "error_code": "interrupted",
                "lease_owner": None,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            },
        )
        return self.get(public_id)

    def interrupt_expired(self, now: datetime) -> int:
        rows = tuple(
            self._session.execute(
                select(TranslationJob).where(
                    TranslationJob.status == JobStatus.RUNNING.value,
                    TranslationJob.lease_expires_at.is_not(None),
                    TranslationJob.lease_expires_at < now,
                )
            ).scalars(),
        )
        interrupted = 0
        for row in rows:
            try:
                self.interrupt(TaskId(row.public_id), row.version)
            except (IllegalJobTransition, StaleJobState):
                continue
            interrupted += 1
        return interrupted

    def _row(self, public_id: TaskId) -> TranslationJob:
        row = self._session.execute(
            select(TranslationJob).where(TranslationJob.public_id == public_id)
        ).scalar_one_or_none()
        if row is None:
            raise JobNotFound(public_id=public_id)
        return row

    def _transition(
        self,
        public_id: TaskId,
        expected_version: int,
        expected_status: JobStatus,
        action: str,
        values: dict[str, str | int | datetime | None],
    ) -> None:
        self._transition_from_statuses(public_id, expected_version, (expected_status,), action, values)

    def _transition_from_statuses(
        self,
        public_id: TaskId,
        expected_version: int,
        expected_statuses: tuple[JobStatus, ...],
        action: str,
        values: dict[str, str | int | datetime | None],
    ) -> None:
        result = self._session.execute(
            update(TranslationJob)
            .where(TranslationJob.public_id == public_id)
            .where(TranslationJob.version == expected_version)
            .where(TranslationJob.status.in_([status.value for status in expected_statuses]))
            .values(**values, version=TranslationJob.version + 1)
        )
        if result.rowcount == 1:
            self._session.commit()
            return
        self._session.rollback()
        row = self._row(public_id)
        if row.version != expected_version:
            raise StaleJobState(public_id=public_id, expected_version=expected_version, actual_version=row.version)
        raise IllegalJobTransition(public_id=public_id, status=parse_job_status(row.status), action=action)


def _snapshot(row: TranslationJob) -> JobSnapshot:
    return JobSnapshot(
        public_id=TaskId(row.public_id),
        user_id=row.user_id,
        kind=parse_job_kind(row.kind),
        status=parse_job_status(row.status),
        stage=parse_job_stage(row.stage),
        progress=row.progress,
        request=row.request_json,
        version=row.version,
        attempt=row.attempt,
        source_path=row.source_path,
        output_path=row.output_path,
        source_sha256=row.source_sha256,
        artifact_sha256=row.artifact_sha256,
        error_code=row.error_code,
        error_message=row.error_message,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
    )
