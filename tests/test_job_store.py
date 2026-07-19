from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.jobs.store import IllegalJobTransition, StaleJobState, TranslationJobStore
from app.jobs.types import (
    JobCreation,
    JobFailure,
    JobKind,
    JobLease,
    JobProgress,
    JobStage,
    JobStatus,
    JobSnapshot,
    JobSuccess,
    WorkerId,
)
from app.models.translation_job import TranslationJob
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request
from migrations.add_translation_jobs import upgrade


@pytest.fixture
def store(tmp_path: Path) -> TranslationJobStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    assert inspect(engine).get_table_names() == ["translation_jobs"]
    return TranslationJobStore(Session(engine))


def _creation() -> JobCreation:
    spec = TranslationJobSpec(
        file_type="pptx",
        source_language="en",
        target_language="zh",
        model="deepseek",
        selected_pages=(1, 3),
        vocabulary_ids=(7,),
    )
    return JobCreation(
        user_id=42,
        kind=JobKind.PPT_TRANSLATION,
        request=build_translation_job_request(spec),
        source_path="source.pptx",
        source_sha256="a" * 64,
    )


def _claim_running_job(engine: Engine) -> JobSnapshot:
    store = TranslationJobStore(Session(engine))
    created = store.create(_creation())
    claimed = store.claim(
        created.public_id,
        JobLease(
            worker_id=WorkerId("worker-a"),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            expected_version=created.version,
        ),
    )
    return claimed


def test_store_creates_task_prefixed_row_with_immutable_request(store: TranslationJobStore):
    # Given
    creation = _creation()

    # When
    snapshot = store.create(creation)

    # Then
    assert snapshot.public_id.startswith("task_")
    assert snapshot.status is JobStatus.QUEUED
    assert snapshot.stage is JobStage.VALIDATE
    assert snapshot.version == 1
    assert snapshot.request["model"] == "deepseek"
    assert snapshot.request["selected_pages"] == [1, 3]


def test_claim_progress_and_succeed_update_sqlite_row_state(store: TranslationJobStore):
    # Given
    created = store.create(_creation())
    lease = JobLease(
        worker_id=WorkerId("worker-a"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        expected_version=created.version,
    )

    # When
    claimed = store.claim(created.public_id, lease)
    progressed = store.progress(
        created.public_id,
        JobProgress(stage=JobStage.TRANSLATE, progress=55, expected_version=claimed.version),
    )
    succeeded = store.succeed(
        created.public_id,
        JobSuccess(output_path="out.pptx", artifact_sha256="b" * 64, expected_version=progressed.version),
    )

    # Then
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempt == 1
    assert progressed.stage is JobStage.TRANSLATE
    assert progressed.progress == 55
    assert succeeded.status is JobStatus.SUCCEEDED
    assert succeeded.progress == 100
    assert succeeded.output_path == "out.pptx"
    assert succeeded.lease_owner is None


def test_illegal_and_stale_transitions_are_rejected(store: TranslationJobStore):
    # Given
    created = store.create(_creation())
    claimed = store.claim(
        created.public_id,
        JobLease(
            worker_id=WorkerId("worker-a"),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            expected_version=created.version,
        ),
    )

    # When / Then
    with pytest.raises(StaleJobState):
        store.progress(
            created.public_id,
            JobProgress(stage=JobStage.RENDER, progress=80, expected_version=created.version),
        )
    succeeded = store.succeed(
        created.public_id,
        JobSuccess(output_path="out.pptx", artifact_sha256="b" * 64, expected_version=claimed.version),
    )
    with pytest.raises(IllegalJobTransition):
        store.claim(
            created.public_id,
            JobLease(
                worker_id=WorkerId("worker-b"),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                expected_version=succeeded.version,
            ),
        )


def test_cancel_and_interrupt_are_terminal(store: TranslationJobStore):
    # Given
    queued = store.create(_creation())
    canceled = store.cancel(queued.public_id, queued.version)
    running = store.claim(
        store.create(_creation()).public_id,
        JobLease(worker_id=WorkerId("worker-a"), expires_at=datetime.now(UTC), expected_version=1),
    )

    # When
    interrupted = store.interrupt(running.public_id, running.version)

    # Then
    with pytest.raises(IllegalJobTransition):
        store.claim(
            canceled.public_id,
            JobLease(worker_id=WorkerId("worker-b"), expires_at=datetime.now(UTC), expected_version=canceled.version),
        )
    with pytest.raises(IllegalJobTransition):
        store.progress(
            interrupted.public_id,
            JobProgress(stage=JobStage.FINALIZE, progress=99, expected_version=interrupted.version),
        )


def test_repeated_claim_changes_only_version_and_lease_once(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    session = Session(engine)
    store = TranslationJobStore(session)
    created = store.create(_creation())

    # When
    first = store.claim(
        created.public_id,
        JobLease(worker_id=WorkerId("worker-a"), expires_at=datetime.now(UTC), expected_version=created.version),
    )

    # Then
    with pytest.raises(IllegalJobTransition):
        store.claim(
            created.public_id,
            JobLease(worker_id=WorkerId("worker-b"), expires_at=datetime.now(UTC), expected_version=first.version),
        )
    row = session.execute(select(TranslationJob).where(TranslationJob.public_id == created.public_id)).scalar_one()
    assert row.attempt == 1
    assert row.lease_owner == "worker-a"


def test_cancel_racing_with_success_raises_stale_and_preserves_success(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    claimed = _claim_running_job(engine)

    def succeed_before_cancel_update() -> None:
        TranslationJobStore(Session(engine)).succeed(
            claimed.public_id,
            JobSuccess(output_path="out.pptx", artifact_sha256="b" * 64, expected_version=claimed.version),
        )

    _install_update_interleaving(engine, succeed_before_cancel_update)

    # When / Then
    with pytest.raises(StaleJobState):
        TranslationJobStore(Session(engine, expire_on_commit=False)).cancel(claimed.public_id, claimed.version)
    fresh = TranslationJobStore(Session(engine)).get(claimed.public_id)
    assert fresh.status is JobStatus.SUCCEEDED
    assert fresh.output_path == "out.pptx"
    assert fresh.version == claimed.version + 1


def test_cancel_racing_with_failure_raises_stale_and_preserves_failure(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    claimed = _claim_running_job(engine)

    def fail_before_cancel_update() -> None:
        TranslationJobStore(Session(engine)).fail(
            claimed.public_id,
            JobFailure(error_code="provider_error", error_message="provider failed", expected_version=claimed.version),
        )

    _install_update_interleaving(engine, fail_before_cancel_update)

    # When / Then
    with pytest.raises(StaleJobState):
        TranslationJobStore(Session(engine, expire_on_commit=False)).cancel(claimed.public_id, claimed.version)
    fresh = TranslationJobStore(Session(engine)).get(claimed.public_id)
    assert fresh.status is JobStatus.FAILED
    assert fresh.error_code == "provider_error"
    assert fresh.error_message == "provider failed"
    assert fresh.version == claimed.version + 1


def test_cancel_racing_with_interruption_raises_stale_and_preserves_interruption(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    claimed = _claim_running_job(engine)

    def interrupt_before_cancel_update() -> None:
        TranslationJobStore(Session(engine)).interrupt(claimed.public_id, claimed.version)

    _install_update_interleaving(engine, interrupt_before_cancel_update)

    # When / Then
    with pytest.raises(StaleJobState):
        TranslationJobStore(Session(engine, expire_on_commit=False)).cancel(claimed.public_id, claimed.version)
    fresh = TranslationJobStore(Session(engine)).get(claimed.public_id)
    assert fresh.status is JobStatus.INTERRUPTED
    assert fresh.error_code == "interrupted"
    assert fresh.version == claimed.version + 1


def test_repeated_cancel_delivery_is_stale_then_illegal(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    store = TranslationJobStore(Session(engine))
    queued = store.create(_creation())

    # When
    canceled = store.cancel(queued.public_id, queued.version)

    # Then
    with pytest.raises(StaleJobState):
        store.cancel(queued.public_id, queued.version)
    with pytest.raises(IllegalJobTransition):
        store.cancel(canceled.public_id, canceled.version)


def _install_update_interleaving(engine: Engine, interleaving: Callable[[], None]) -> None:
    fired = False

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        nonlocal fired
        if fired or not statement.lstrip().upper().startswith("UPDATE translation_jobs".upper()):
            return
        fired = True
        interleaving()

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
