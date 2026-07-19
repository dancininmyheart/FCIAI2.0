from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.jobs.store import IllegalJobTransition, StaleJobState, TranslationJobStore
from app.jobs.types import JobFailure, JobLease, JobSnapshot, JobStatus, TaskId
from app.models.translation_job import TranslationJob


class JobReservationStore:
    def __init__(self, store: TranslationJobStore) -> None:
        self._store = store

    def reserve_next(self, lease: JobLease) -> JobSnapshot | None:
        now = datetime.now(UTC)
        rows = self._store._session.execute(
            select(TranslationJob)
            .where(TranslationJob.status == JobStatus.QUEUED.value)
            .where(or_(TranslationJob.lease_owner.is_(None), TranslationJob.lease_expires_at < now))
            .order_by(TranslationJob.created_at.asc())
            .limit(10),
        ).scalars()
        for row in rows:
            try:
                self._store._transition_from_statuses(
                    TaskId(row.public_id),
                    row.version,
                    (JobStatus.QUEUED,),
                    "reserve",
                    {"lease_owner": lease.worker_id, "lease_expires_at": lease.expires_at},
                )
                return self._store.get(TaskId(row.public_id))
            except (IllegalJobTransition, StaleJobState):
                continue
        return None

    def claim_reserved(self, public_id: TaskId, lease: JobLease) -> JobSnapshot:
        self._store._transition_from_statuses(
            public_id,
            lease.expected_version,
            (JobStatus.QUEUED,),
            "claim_reserved",
            {
                "status": JobStatus.RUNNING.value,
                "lease_owner": lease.worker_id,
                "lease_expires_at": lease.expires_at,
                "attempt": TranslationJob.attempt + 1,
                "started_at": datetime.now(UTC),
            },
        )
        return self._store.get(public_id)

    def release_reservation(self, public_id: TaskId, expected_version: int) -> JobSnapshot:
        self._store._transition_from_statuses(
            public_id,
            expected_version,
            (JobStatus.QUEUED,),
            "release_reservation",
            {"lease_owner": None, "lease_expires_at": None},
        )
        return self._store.get(public_id)

    def requeue_claim(self, public_id: TaskId, expected_version: int) -> JobSnapshot:
        self._store._transition_from_statuses(
            public_id,
            expected_version,
            (JobStatus.RUNNING,),
            "requeue_claim",
            {
                "status": JobStatus.QUEUED.value,
                "lease_owner": None,
                "lease_expires_at": None,
                "attempt": TranslationJob.attempt - 1,
                "started_at": None,
            },
        )
        return self._store.get(public_id)

    def fail_reserved(self, public_id: TaskId, failure: JobFailure) -> JobSnapshot:
        self._store._transition_from_statuses(
            public_id,
            failure.expected_version,
            (JobStatus.QUEUED,),
            "fail_reserved",
            {
                "status": JobStatus.FAILED.value,
                "error_code": failure.error_code,
                "error_message": failure.error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "finished_at": datetime.now(UTC),
            },
        )
        return self._store.get(public_id)
