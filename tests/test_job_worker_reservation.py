from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import pytest
from sqlalchemy import update

from app.jobs.types import JobStatus, WorkerId
from app.models.translation_job import TranslationJob
from test_job_worker import _creation, _store

VALID_ANNOTATION = {
    "page": 1,
    "coords": {"left": 1, "top": 2, "width": 3, "height": 4},
    "text": "note",
    "ocrResult": "ocr",
    "translation": "translated",
}


@dataclass(frozen=True, slots=True)
class QueueRejected(RuntimeError):
    reason: str

    def __str__(self) -> str:
        return self.reason


class RejectOnceQueue:  # noqa: MUTABLE_OK
    def __init__(self, reject_next: bool = True) -> None:
        self.accepted: list[str] = []
        self.reject_next = reject_next

    def has_available_slot(self) -> bool:
        return True

    def add_claimed_task(self, task) -> int:
        if self.reject_next:
            self.reject_next = False
            raise QueueRejected(reason="queue full after reservation")
        self.accepted.append(task.task_id)
        return len(self.accepted)


class CancelAfterAcceptQueue:
    def __init__(self, store) -> None:
        self.store = store
        self.accepted = []

    def has_available_slot(self) -> bool:
        return True

    def add_claimed_task(self, task) -> int:
        self.accepted.append(task)
        snapshot = self.store.get(task.task_id)
        self.store.cancel(snapshot.public_id, snapshot.version)
        return len(self.accepted)


def test_worker_releases_reservation_when_enqueue_raises_then_retries(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    queue = RejectOnceQueue()
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    rejected_count = worker.drain_once()
    after_reject = store.get(created.public_id)
    accepted_count = worker.drain_once()
    after_accept = store.get(created.public_id)

    # Then
    assert rejected_count == 0
    assert after_reject.status is JobStatus.QUEUED
    assert after_reject.attempt == 0
    assert after_reject.lease_owner is None
    assert accepted_count == 1
    assert queue.accepted == [created.public_id]
    assert after_accept.status is JobStatus.RUNNING
    assert after_accept.attempt == 1


def test_worker_fails_malformed_payload_without_enqueue_or_leased_phantom(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    store._session.execute(
        update(TranslationJob)
        .where(TranslationJob.public_id == created.public_id)
        .values(request_json={"schema_version": 999}),
    )
    store._session.commit()
    queue = RejectOnceQueue(reject_next=False)
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    claimed_count = worker.drain_once()
    snapshot = store.get(created.public_id)

    # Then
    assert claimed_count == 0
    assert queue.accepted == []
    assert snapshot.status is JobStatus.FAILED
    assert snapshot.error_code == "invalid_payload"
    assert snapshot.lease_owner is None


def test_worker_accepted_task_noops_when_canceled_before_execution(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    queue = CancelAfterAcceptQueue(store)
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    claimed_count = worker.drain_once()
    snapshot = store.get(created.public_id)
    can_execute = queue.accepted[0].ledger_execution_preflight()

    # Then
    assert claimed_count == 1
    assert snapshot.status is JobStatus.CANCELED
    assert can_execute is False


def test_worker_fails_unknown_and_nested_malformed_payload_before_enqueue(tmp_path: Path) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    unknown = store.create(_creation())
    malformed = store.create(_creation())
    store._session.execute(
        update(TranslationJob)
        .where(TranslationJob.public_id == unknown.public_id)
        .values(request_json={**unknown.request, "unexpected": "x"}),
    )
    store._session.execute(
        update(TranslationJob)
        .where(TranslationJob.public_id == malformed.public_id)
        .values(request_json={**malformed.request, "selected_pages": ["1"]}),
    )
    store._session.commit()
    queue = RejectOnceQueue(reject_next=False)
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    first_count = worker.drain_once()
    second_count = worker.drain_once()
    first = store.get(unknown.public_id)
    second = store.get(malformed.public_id)

    # Then
    assert (first_count, second_count) == (0, 0)
    assert queue.accepted == []
    assert first.status is JobStatus.FAILED
    assert second.status is JobStatus.FAILED
    assert first.error_code == "invalid_payload"
    assert second.error_code == "invalid_payload"


def test_payload_parser_rejects_malformed_nested_keys() -> None:
    # Given
    from app.jobs.request_payload import MalformedTranslationRequest, parse_translation_request

    request = _creation().request.to_json()
    malformed = {**request, "annotations": [{1: "note"}]}

    # When / Then
    try:
        parse_translation_request(malformed)
    except MalformedTranslationRequest as exc:
        assert exc.field == "annotations"
    else:
        raise AssertionError("expected malformed annotations to be rejected")


@pytest.mark.parametrize(
    "payload_patch",
    [
        {"annotations": [{"unexpected": "x"}]},
        {"annotations": [{"page": 1, "coords": {"1": "bad"}}]},
        {"annotations": [{"page": 1, "coords": {"left": "bad", "top": 0, "width": 1, "height": 1}}]},
        {"annotations": [{"page": True, "coords": {"left": 0, "top": 0, "width": 1, "height": 1}}]},
        {"annotations": [{"page": 0, "coords": {"left": 0, "top": 0, "width": 1, "height": 1}}]},
        {"annotations": [{"page": 1, "coords": {"left": 0, "top": 0, "width": 0, "height": 1}}]},
        {"annotations": [{"page": 1, "coords": {"left": 0, "top": 0, "width": 1, "height": 1, "extra": 2}}]},
        {"model": "gpt4o", "annotations": [VALID_ANNOTATION]},
    ],
)
def test_worker_fails_strict_schema_payloads_before_enqueue(
    tmp_path: Path,
    payload_patch: dict,
) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker

    store = _store(tmp_path)
    created = store.create(_creation())
    store._session.execute(
        update(TranslationJob)
        .where(TranslationJob.public_id == created.public_id)
        .values(request_json={**created.request, **payload_patch}),
    )
    store._session.commit()
    queue = RejectOnceQueue(reject_next=False)
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    claimed_count = worker.drain_once()
    snapshot = store.get(created.public_id)

    # Then
    assert claimed_count == 0
    assert queue.accepted == []
    assert snapshot.status is JobStatus.FAILED
    assert snapshot.error_code == "invalid_payload"
