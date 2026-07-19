from __future__ import annotations

import logging
import sys
import threading
import types
from dataclasses import dataclass

import pytest
from flask import Flask

from app.runtime import (
    RUNTIME_EXTENSION_KEY,
    RuntimeLifecycle,
    RuntimeResource,
    RuntimeRole,
    RuntimeStartError,
    UnknownRuntimeRole,
    start_runtime,
    stop_runtime,
)


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    name: str
    roles: frozenset[RuntimeRole]
    fail_on_start: bool = False
    fail_with_generic_exception: bool = False
    worker_resource: bool = True


@dataclass(frozen=True, slots=True)
class ProbeStartError(RuntimeError):
    resource: str

    def __str__(self) -> str:
        return f"probe failed: {self.resource}"


@dataclass(frozen=True, slots=True)
class ProbeGenericStartError(Exception):
    resource: str

    def __str__(self) -> str:
        return f"generic probe failed: {self.resource}"


class ThreadProbeResource:  # noqa: MUTABLE_OK
    def __init__(self, spec: ProbeSpec, events: list[str]) -> None:
        self.spec = spec
        self.events = events
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.thread: threading.Thread | None = None

    def configure(self) -> None:
        self.events.append(f"{self.spec.name}:configure")

    def start(self) -> None:
        if self.spec.fail_on_start:
            self.events.append(f"{self.spec.name}:start_failed")
            if self.spec.fail_with_generic_exception:
                raise ProbeGenericStartError(resource=self.spec.name)
            raise ProbeStartError(resource=self.spec.name)
        self.events.append(f"{self.spec.name}:start")
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"runtime-probe-{self.spec.name}", daemon=True)
        self.thread.start()
        if not self.ready_event.wait(timeout=1.0):
            raise ProbeStartError(resource=self.spec.name)

    def stop(self) -> None:
        self.events.append(f"{self.spec.name}:stop")
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def as_runtime_resource(self) -> RuntimeResource:
        return RuntimeResource(
            name=self.spec.name,
            roles=self.spec.roles,
            configure=self.configure,
            start=self.start,
            stop=self.stop,
        )

    def _run(self) -> None:
        self.ready_event.set()
        self.stop_event.wait(timeout=10.0)


def build_lifecycle(specs: tuple[ProbeSpec, ...]) -> tuple[RuntimeLifecycle, list[ThreadProbeResource], list[str]]:
    events: list[str] = []
    probes = [ThreadProbeResource(spec, events) for spec in specs]
    resources = tuple(probe.as_runtime_resource() for probe in probes)
    return RuntimeLifecycle(resources), probes, events


def test_create_app_does_not_start_schema_or_background_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    calls: list[str] = []
    import app as app_pkg

    cleanup = types.ModuleType("app.tasks.cleanup")
    cleanup.schedule_cleanup_task = lambda: calls.append("cleanup")
    monkeypatch.setitem(sys.modules, "app.tasks.cleanup", cleanup)
    monkeypatch.setattr(app_pkg.os, "makedirs", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_pkg.db, "create_all", lambda: calls.append("create_all"))
    monkeypatch.setattr(app_pkg.thread_pool, "configure", lambda **kwargs: calls.append("thread_pool.configure"))
    monkeypatch.setattr(app_pkg.translation_queue, "configure", lambda **kwargs: calls.append("queue.configure"))
    monkeypatch.setattr(app_pkg.translation_queue, "start_processor", lambda: calls.append("queue.start"))
    monkeypatch.setattr(app_pkg.http_client, "configure", lambda **kwargs: calls.append("http.configure"))
    monkeypatch.setattr(app_pkg, "setup_db_monitoring", lambda flask_app, interval=3600: calls.append("db_monitor"))
    monkeypatch.setattr(app_pkg.log_manager, "configure", lambda **kwargs: None)
    monkeypatch.setattr(app_pkg.log_manager, "get_logger", lambda: logging.getLogger("tests.runtime"))

    # When
    flask_app = app_pkg.create_app("testing")

    # Then
    assert calls == []
    assert isinstance(flask_app.extensions[RUNTIME_EXTENSION_KEY], RuntimeLifecycle)


def test_queue_configure_is_configuration_only() -> None:
    # Given
    from app.utils.enhanced_task_queue import EnhancedTranslationQueue

    queue = EnhancedTranslationQueue()

    # When
    queue.configure(max_concurrent_tasks=2, task_timeout=3, retry_times=4)

    # Then
    assert queue.initialized is True
    assert queue.running is False
    assert queue.max_concurrent_tasks == 2
    assert queue.task_timeout == 3
    assert queue.retry_times == 4
    assert queue.recycle_thread is None
    assert not hasattr(queue, "processor_thread")


def test_unknown_role_fails_before_any_resource_starts() -> None:
    # Given
    lifecycle, probes, events = build_lifecycle(
        (ProbeSpec("worker", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),)
    )
    flask_app = Flask(__name__)
    flask_app.extensions[RUNTIME_EXTENSION_KEY] = lifecycle

    # When
    with pytest.raises(UnknownRuntimeRole):
        start_runtime(flask_app, "bad-role")

    # Then
    assert events == []
    assert lifecycle.started_resource_names == ()
    assert all(not probe.is_alive() for probe in probes)


def test_web_role_starts_zero_worker_resources() -> None:
    # Given
    lifecycle, probes, events = build_lifecycle(
        (
            ProbeSpec("http_client", frozenset((RuntimeRole.WEB, RuntimeRole.ALL)), worker_resource=False),
            ProbeSpec("queue_worker", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec("cleanup_worker", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
        )
    )

    # When
    lifecycle.start(RuntimeRole.WEB)
    lifecycle.stop()

    # Then
    assert events == ["http_client:configure", "http_client:start", "http_client:stop"]
    assert all(not probe.is_alive() for probe in probes)


@pytest.mark.parametrize("role", (RuntimeRole.WORKER, RuntimeRole.ALL))
def test_worker_and_all_double_start_stop_are_idempotent(role: RuntimeRole) -> None:
    # Given
    lifecycle, probes, events = build_lifecycle(
        (
            ProbeSpec("thread_pool", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec("queue", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
        )
    )

    # When
    lifecycle.start(role)
    lifecycle.start(role)
    lifecycle.stop()
    lifecycle.stop()

    # Then
    assert events == [
        "thread_pool:configure",
        "thread_pool:start",
        "queue:configure",
        "queue:start",
        "queue:stop",
        "thread_pool:stop",
    ]
    assert lifecycle.started_resource_names == ()
    assert all(not probe.is_alive() for probe in probes)


def test_start_failure_rolls_back_in_reverse_order() -> None:
    # Given
    lifecycle, probes, events = build_lifecycle(
        (
            ProbeSpec("thread_pool", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec("queue", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec("db_monitor", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL)), fail_on_start=True),
        )
    )
    flask_app = Flask(__name__)
    flask_app.extensions[RUNTIME_EXTENSION_KEY] = lifecycle

    # When
    with pytest.raises(RuntimeStartError):
        start_runtime(flask_app, "worker")
    stop_runtime(flask_app)
    stop_runtime(flask_app)

    # Then
    assert events == [
        "thread_pool:configure",
        "thread_pool:start",
        "queue:configure",
        "queue:start",
        "db_monitor:configure",
        "db_monitor:start_failed",
        "queue:stop",
        "thread_pool:stop",
    ]
    assert lifecycle.started is False
    assert all(not probe.is_alive() for probe in probes)


def test_generic_start_exception_rolls_back_thread_pool_and_queue() -> None:
    # Given
    lifecycle, probes, events = build_lifecycle(
        (
            ProbeSpec("thread_pool", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec("translation_queue", frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))),
            ProbeSpec(
                "db_monitor_generic",
                frozenset((RuntimeRole.WORKER, RuntimeRole.ALL)),
                fail_on_start=True,
                fail_with_generic_exception=True,
            ),
        )
    )
    flask_app = Flask(__name__)
    flask_app.extensions[RUNTIME_EXTENSION_KEY] = lifecycle

    # When
    with pytest.raises(RuntimeStartError) as raised:
        start_runtime(flask_app, "worker")
    stop_runtime(flask_app)

    # Then
    assert isinstance(raised.value.__cause__, ProbeGenericStartError)
    assert events == [
        "thread_pool:configure",
        "thread_pool:start",
        "translation_queue:configure",
        "translation_queue:start",
        "db_monitor_generic:configure",
        "db_monitor_generic:start_failed",
        "translation_queue:stop",
        "thread_pool:stop",
    ]
    assert lifecycle.started is False
    assert lifecycle.started_resource_names == ()
    assert all(not probe.is_alive() for probe in probes)
