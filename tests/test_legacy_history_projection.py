from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest
from flask import Flask, current_app, has_app_context
from flask.globals import _cv_app

from app import db
from app.models import UploadRecord
from app.runtime import default_runtime_resources
from app.utils import enhanced_task_queue as queue_module
from app.utils.enhanced_task_queue import EnhancedTranslationQueue, TranslationTask
from app.utils.thread_pool_executor import TaskStatus


@pytest.fixture
def legacy_queue_app(tmp_path) -> Flask:
    flask_app = Flask("legacy-queue-history-test")
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'legacy-queue.sqlite'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(flask_app)

    with flask_app.app_context():
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def test_completed_legacy_translation_is_persisted_without_leaking_app_context(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    translated_file = tmp_path / "translated.pptx"
    translated_file.touch()

    with legacy_queue_app.app_context():
        record = UploadRecord(
            user_id=7,
            filename="source.pptx",
            stored_filename=translated_file.name,
            file_path=str(translated_file.parent),
            file_size=translated_file.stat().st_size,
            status="pending",
        )
        db.session.add(record)
        db.session.commit()
        record_id = record.id

    task = SimpleNamespace(
        task_id="task-completed",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(translated_file),
        status="completed",
        error=None,
    )
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    queue._schedule_database_update(task)

    leaked_context = has_app_context()
    if leaked_context:
        _cv_app.get().pop()

    with legacy_queue_app.app_context():
        persisted_status = db.session.get(UploadRecord, record_id).status

    assert persisted_status == "completed"
    assert leaked_context is False


def test_legacy_execution_releases_its_application_context(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    task = TranslationTask(
        task_id="task-unsupported",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "source.pptx"),
        model="qwen",
        task_type="unsupported",
    )
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    result = queue._execute_task(task)

    leaked_context = has_app_context()
    if leaked_context:
        _cv_app.get().pop()

    assert result is False
    assert leaked_context is False


def test_completion_callback_uses_configured_app_context(
    legacy_queue_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class CapturedThreadTask:
        status = TaskStatus.COMPLETED
        result = True
        error = None
        thread_id = None
        callback = None

        def add_callback(self, callback) -> None:
            self.callback = callback

    class NoopCleanupExecutor:
        _shutdown = False

        def submit(self, *args, **kwargs):
            return None

    callback_observations = []
    task = TranslationTask(
        task_id="task-callback",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
        ledger_completion_callback=lambda completed_task: callback_observations.append(
            (
                has_app_context(),
                current_app._get_current_object() if has_app_context() else None,
            )
        ),
    )
    thread_task = CapturedThreadTask()
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)
    queue.cleanup_executor = NoopCleanupExecutor()
    monkeypatch.setattr(queue, "_check_thread_pool_health", lambda: True)
    monkeypatch.setattr(queue_module.thread_pool, "submit", lambda **kwargs: thread_task)

    queue.add_claimed_task(task)
    queue._process_task(task)
    thread_task.callback(thread_task)

    assert callback_observations == [(True, legacy_queue_app)]
    assert has_app_context() is False


def test_legacy_completion_is_published_only_after_history_is_persisted(
    legacy_queue_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class CapturedThreadTask:
        status = TaskStatus.COMPLETED
        result = True
        error = None
        thread_id = None
        callback = None

        def add_callback(self, callback) -> None:
            self.callback = callback

    class NoopCleanupExecutor:
        _shutdown = False

        def submit(self, *args, **kwargs):
            return None

    update_started = threading.Event()
    release_update = threading.Event()

    def persist_history(completed_task, status=None) -> bool:
        update_started.set()
        release_update.wait(timeout=5)
        return True

    task = TranslationTask(
        task_id="task-publication-order",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
    )
    thread_task = CapturedThreadTask()
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)
    queue.cleanup_executor = NoopCleanupExecutor()
    monkeypatch.setattr(queue, "_check_thread_pool_health", lambda: True)
    monkeypatch.setattr(queue, "_schedule_database_update", persist_history)
    monkeypatch.setattr(queue_module.thread_pool, "submit", lambda **kwargs: thread_task)

    queue.add_claimed_task(task)
    queue._process_task(task)
    callback_thread = threading.Thread(
        target=thread_task.callback,
        args=(thread_task,),
        daemon=True,
    )
    callback_thread.start()
    started = update_started.wait(timeout=5)
    status_during_update = queue.get_task_status(task.task_id)
    event_during_update = task.event.is_set()
    release_update.set()
    callback_thread.join(timeout=5)

    assert started is True
    assert status_during_update["status"] == "processing"
    assert event_during_update is False
    assert task.status == "completed"
    assert task.event.is_set() is True


def test_legacy_ppt_completion_is_not_reported_when_history_persistence_fails(
    legacy_queue_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class CapturedThreadTask:
        status = TaskStatus.COMPLETED
        result = True
        error = None
        thread_id = None
        callback = None

        def add_callback(self, callback) -> None:
            self.callback = callback

    class NoopCleanupExecutor:
        _shutdown = False

        def submit(self, *args, **kwargs):
            return None

    task = TranslationTask(
        task_id="task-history-failure",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
        task_type="ppt_translate",
    )
    thread_task = CapturedThreadTask()
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)
    queue.cleanup_executor = NoopCleanupExecutor()
    monkeypatch.setattr(queue, "_check_thread_pool_health", lambda: True)
    monkeypatch.setattr(queue, "_schedule_database_update", lambda task, status=None: False)
    monkeypatch.setattr(queue_module.thread_pool, "submit", lambda **kwargs: thread_task)

    queue.add_claimed_task(task)
    queue._process_task(task)
    thread_task.callback(thread_task)

    assert task.status == "failed"
    assert "历史记录" in task.error
    assert task.event.is_set() is True


def test_ledger_completion_failure_fails_task_and_releases_resources(
    legacy_queue_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class CapturedThreadTask:
        status = TaskStatus.COMPLETED
        result = True
        error = None
        thread_id = None
        callback = None

        def add_callback(self, callback) -> None:
            self.callback = callback

    class NoopCleanupExecutor:
        _shutdown = False

        def submit(self, *args, **kwargs):
            return None

    def fail_ledger_completion(completed_task) -> None:
        raise RuntimeError("ledger completion failed")

    task = TranslationTask(
        task_id="task-ledger-failure",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
        task_type="ppt_translate",
        ledger_completion_callback=fail_ledger_completion,
    )
    task.result = object()
    thread_task = CapturedThreadTask()
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)
    queue.cleanup_executor = NoopCleanupExecutor()
    monkeypatch.setattr(queue, "_check_thread_pool_health", lambda: True)
    monkeypatch.setattr(queue, "_schedule_database_update", lambda task, status=None: False)
    monkeypatch.setattr(queue_module.thread_pool, "submit", lambda **kwargs: thread_task)

    queue.add_claimed_task(task)
    queue._process_task(task)
    thread_task.callback(thread_task)

    assert task.status == "failed"
    assert "ledger completion failed" in task.error
    assert task.event.is_set() is True
    assert task.result is None
    assert task.task_id not in queue.active_tasks


def test_cleanup_worker_releases_its_application_context(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    task = TranslationTask(
        task_id="task-cleanup",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
    )
    task.result = object()
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    queue._cleanup_task_resources(task)

    leaked_context = has_app_context()
    if leaked_context:
        _cv_app.get().pop()

    assert task.result is None
    assert leaked_context is False


def test_runtime_configures_translation_queue_with_owning_app(
    legacy_queue_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_apps = []
    monkeypatch.setattr(
        queue_module.translation_queue,
        "configure",
        lambda **kwargs: configured_apps.append(kwargs.get("app")),
    )
    queue_resource = next(
        resource
        for resource in default_runtime_resources(legacy_queue_app)
        if resource.name == "translation_queue_config"
    )

    queue_resource.configure()

    assert configured_apps == [legacy_queue_app]


def test_legacy_error_handler_releases_its_application_context(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    task = TranslationTask(
        task_id="task-error",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        model="qwen",
    )
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    queue._handle_task_error(task, "translation failed")

    leaked_context = has_app_context()
    if leaked_context:
        _cv_app.get().pop()

    assert task.status == "waiting"
    assert leaked_context is False


def test_connection_recycling_succeeds_and_releases_its_application_context(
    legacy_queue_app: Flask,
) -> None:
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    result = queue.recycle_idle_connections()

    leaked_context = has_app_context()
    if leaked_context:
        _cv_app.get().pop()

    assert result["success"] is True
    assert result["message"] == "成功回收空闲连接"
    assert leaked_context is False


def test_missing_upload_record_does_not_retain_database_session(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    task = SimpleNamespace(
        task_id="task-missing-record",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "missing.pptx"),
        status="completed",
        error=None,
    )
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    with legacy_queue_app.app_context():
        queue._schedule_database_update(task)

        assert db.session.registry.has() is False


def test_database_update_error_does_not_retain_database_session(
    legacy_queue_app: Flask,
    tmp_path,
) -> None:
    task = SimpleNamespace(
        task_id="task-database-error",
        user_id=7,
        user_name="translator",
        file_path=os.fspath(tmp_path / "translated.pptx"),
        status="completed",
        error=None,
    )
    queue = EnhancedTranslationQueue()
    queue.configure(app=legacy_queue_app)

    with legacy_queue_app.app_context():
        UploadRecord.__table__.drop(db.engine)
        queue._schedule_database_update(task)

        assert db.session.registry.has() is False
