from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol, TypeAlias, assert_never

from flask import Flask, has_app_context

from app import db
from app.jobs.reservations import JobReservationStore
from app.jobs.artifacts import ArtifactIntegrityError, JobArtifactStore, PreparedAttempt
from app.jobs.history import register_completion_history_once
from app.jobs.errors import IllegalJobTransition, StaleJobState
from app.jobs.store import TranslationJobStore
from app.jobs.request_payload import MalformedTranslationRequest, parse_translation_request
from app.jobs.types import (
    JobFailure,
    JobKind,
    JobLease,
    JobProgress,
    JobSnapshot,
    JobStage,
    JobStatus,
    JobSuccess,
    WorkerId,
    legacy_task_type,
)
from app.utils.enhanced_task_queue import TranslationTask

logger = logging.getLogger(__name__)


class ClaimedTaskQueue(Protocol):
    def has_available_slot(self) -> bool: ...

    def add_claimed_task(self, task: TranslationTask) -> int: ...


StoreFactory: TypeAlias = Callable[[], TranslationJobStore]


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    poll_interval_seconds: float = 0.5
    lease_seconds: int = 300


class EmbeddedDbWorker:  # noqa: MUTABLE_OK
    def __init__(
        self,
        store_factory: StoreFactory,
        queue: ClaimedTaskQueue,
        worker_id: WorkerId,
        config: WorkerConfig = WorkerConfig(),
        app: Flask | None = None,
    ) -> None:
        self._store_factory = store_factory
        self._queue = queue
        self._worker_id = worker_id
        self._config = config
        self._app = app
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="embedded_db_worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def wake(self) -> None:
        self._wake.set()

    def drain_once(self) -> int:
        store = self._store_factory()
        reservations = JobReservationStore(store)
        self.interrupt_expired_leases(datetime.now(UTC), store)
        if not self._queue.has_available_slot():
            return 0
        lease = JobLease(
            worker_id=self._worker_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._config.lease_seconds),
            expected_version=0,
        )
        reserved = reservations.reserve_next(lease)
        if reserved is None:
            return 0
        running: JobSnapshot | None = None
        prepared: PreparedAttempt | None = None
        try:
            parse_translation_request(reserved.request)
            if has_app_context():
                artifacts = JobArtifactStore()
                immutable_source, source_sha256 = artifacts.ensure_source(reserved)
                reserved = store.record_source(
                    reserved.public_id,
                    reserved.version,
                    str(immutable_source),
                    source_sha256,
                )
            running = reservations.claim_reserved(
                reserved.public_id,
                JobLease(
                    worker_id=self._worker_id,
                    expires_at=lease.expires_at,
                    expected_version=reserved.version,
                ),
            )
            if has_app_context():
                artifacts = JobArtifactStore()
                promoted = artifacts.promoted(running)
                if promoted is not None:
                    register_completion_history_once(store._session, running, promoted)
                    store.succeed(
                        running.public_id,
                        JobSuccess(
                            output_path=str(promoted.path),
                            artifact_sha256=promoted.sha256,
                            expected_version=running.version,
                        ),
                    )
                    return 1
                prepared = artifacts.prepare_attempt(running)
            task = self._task_from_snapshot(running, prepared)
            self._queue.add_claimed_task(task)
        except (ArtifactIntegrityError, MalformedTranslationRequest) as exc:
            reservations.fail_reserved(
                reserved.public_id,
                JobFailure(error_code="invalid_payload", error_message=str(exc), expected_version=reserved.version),
            )
            return 0
        except (IllegalJobTransition, StaleJobState):
            return 0
        except RuntimeError:
            if running is None:
                reservations.release_reservation(reserved.public_id, reserved.version)
            else:
                reservations.requeue_claim(running.public_id, running.version)
            return 0
        return 1

    def interrupt_expired_leases(self, now: datetime, store: TranslationJobStore | None = None) -> int:
        selected_store = store or self._store_factory()
        return selected_store.interrupt_expired(now)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._app is None:
                    self.drain_once()
                else:
                    with self._app.app_context():
                        self.drain_once()
            except RuntimeError as exc:
                logger.warning("embedded worker tick failed: %s", exc)
            self._wake.wait(self._config.poll_interval_seconds)
            self._wake.clear()

    def _task_from_snapshot(
        self,
        snapshot: JobSnapshot,
        prepared: PreparedAttempt | None = None,
    ) -> TranslationTask:
        request = parse_translation_request(snapshot.request)
        file_path = str(prepared.work_path) if prepared else (snapshot.source_path or "")
        output_path = str(prepared.output_path) if prepared else request["output_path"]
        return TranslationTask(
            task_id=snapshot.public_id,
            user_id=snapshot.user_id or 0,
            user_name=f"user_{snapshot.user_id or 0}",
            file_path=file_path,
            task_type=legacy_task_type(snapshot.kind),
            source_language=request["source_language"],
            target_language=request["target_language"],
            select_page=request["selected_pages"],
            bilingual_translation=request["bilingual_translation"],
            model=request["model"],
            enable_text_splitting=request["enable_text_splitting"],
            enable_uno_conversion=request["enable_uno_conversion"],
            custom_translations=request["custom_translations"],
            annotations=request["annotations"],
            output_path=output_path,
            annotation_filename=request["annotation_filename"],
            enable_image_ocr=request["enable_image_ocr"],
            original_filename=request["original_filename"],
            unique_filename=request["unique_filename"],
            ledger_execution_preflight=lambda: self._execution_preflight(snapshot.public_id, snapshot.version),
            ledger_progress_callback=lambda progress: self._record_progress(snapshot.public_id, progress),
            ledger_completion_callback=lambda task: self._record_completion(task, snapshot, prepared),
            ledger_attempt=snapshot.attempt,
        )

    def _execution_preflight(self, public_id: str, expected_version: int) -> bool:
        snapshot = self._store_factory().get(public_id)
        return (
            snapshot.status is JobStatus.RUNNING
            and snapshot.version == expected_version
            and snapshot.lease_owner == self._worker_id
        )

    def _record_progress(self, public_id: str, progress: int) -> None:
        store = self._store_factory()
        snapshot = store.get(public_id)
        if snapshot.status is JobStatus.RUNNING:
            store.progress(
                snapshot.public_id,
                JobProgress(stage=JobStage.TRANSLATE, progress=progress, expected_version=snapshot.version),
            )

    def _record_completion(
        self,
        task: TranslationTask,
        claimed: JobSnapshot,
        prepared: PreparedAttempt | None,
    ) -> None:
        store = self._store_factory()
        snapshot = store.get(task.task_id)
        if snapshot.status is not JobStatus.RUNNING:
            return
        if task.status == "completed" and getattr(task.thread_task, "result", True):
            output_path = task.output_path or task.file_path
            artifact_sha256 = "0" * 64
            if prepared is not None and has_app_context():
                match claimed.kind:
                    case JobKind.PPT_TRANSLATION:
                        candidate = Path(task.file_path)
                    case JobKind.PDF_TRANSLATION | JobKind.PDF_ANNOTATION:
                        candidate = Path(task.output_path)
                    case unreachable:
                        assert_never(unreachable)
                promoted = JobArtifactStore().promote(claimed, prepared, candidate)
                register_completion_history_once(store._session, claimed, promoted)
                output_path = str(promoted.path)
                artifact_sha256 = promoted.sha256
            store.succeed(
                snapshot.public_id,
                JobSuccess(
                    output_path=output_path,
                    artifact_sha256=artifact_sha256,
                    expected_version=snapshot.version,
                ),
            )
            return
        store.fail(
            snapshot.public_id,
            JobFailure(
                error_code="execution_failed",
                error_message=str(task.error or "execution failed"),
                expected_version=snapshot.version,
            ),
        )


def create_embedded_worker(app: Flask, queue: ClaimedTaskQueue) -> EmbeddedDbWorker:
    return EmbeddedDbWorker(lambda: TranslationJobStore(db.session), queue, WorkerId("embedded-worker-1"), app=app)


def signal_embedded_worker(app: Flask) -> None:
    worker = app.extensions.get("embedded_db_worker")
    if isinstance(worker, EmbeddedDbWorker):
        worker.wake()
