from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.jobs.store import TranslationJobStore
from app.jobs.types import JobCreation, JobKind, JobLease, JobStatus, WorkerId
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request
from migrations.add_translation_jobs import upgrade


@dataclass(frozen=True, slots=True)
class RecordingQueue:  # noqa: MUTABLE_OK
    task_ids: list[str] = field(default_factory=list)
    available: bool = True

    def has_available_slot(self) -> bool:
        return self.available

    def add_claimed_task(self, task) -> int:
        self.task_ids.append(task.task_id)
        return len(self.task_ids)


def _store(tmp_path: Path) -> TranslationJobStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    return TranslationJobStore(Session(engine))


def _creation() -> JobCreation:
    request = build_translation_job_request(
        TranslationJobSpec(file_type="pptx", source_language="en", target_language="zh", model="qwen"),
    )
    return JobCreation(user_id=3, kind=JobKind.PPT_TRANSLATION, request=request, source_path="deck.pptx")


def test_worker_claims_one_queued_job_once_when_two_workers_poll(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    queue = RecordingQueue()
    worker_a = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))
    worker_b = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-b"))

    # When
    claimed_a = worker_a.drain_once()
    claimed_b = worker_b.drain_once()

    # Then
    assert (claimed_a, claimed_b) == (1, 0)
    assert queue.task_ids == [created.public_id]
    snapshot = store.get(created.public_id)
    assert snapshot.status is JobStatus.RUNNING
    assert snapshot.attempt == 1
    assert snapshot.lease_owner == "worker-a"


def test_claimed_worker_crash_projects_interrupted_once(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    running = store.claim(
        created.public_id,
        JobLease(
            worker_id=WorkerId("worker-a"),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            expected_version=created.version,
        ),
    )
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=RecordingQueue(), worker_id=WorkerId("worker-b"))

    # When
    interrupted_count = worker.interrupt_expired_leases(datetime.now(UTC))

    # Then
    assert interrupted_count == 1
    snapshot = store.get(running.public_id)
    assert snapshot.status is JobStatus.INTERRUPTED
    assert snapshot.output_path is None


def test_worker_does_not_claim_when_bounded_queue_is_full(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    worker = EmbeddedDbWorker(
        store_factory=lambda: store,
        queue=RecordingQueue(available=False),
        worker_id=WorkerId("worker-a"),
    )

    # When
    claimed_count = worker.drain_once()

    # Then
    assert claimed_count == 0
    snapshot = store.get(created.public_id)
    assert snapshot.status is JobStatus.QUEUED
    assert snapshot.attempt == 0
