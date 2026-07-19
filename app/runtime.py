from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Callable, Final, Protocol

from flask import Flask

RUNTIME_EXTENSION_KEY: Final = "runtime_lifecycle"


@unique
class RuntimeRole(StrEnum):
    WEB = "web"
    WORKER = "worker"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class UnknownRuntimeRole(Exception):
    role: str

    def __str__(self) -> str:
        return f"unknown runtime role: {self.role}"


@dataclass(frozen=True, slots=True)
class RuntimeStartError(Exception):
    resource: str
    detail: str

    def __str__(self) -> str:
        return f"failed to start {self.resource}: {self.detail}"


@dataclass(frozen=True, slots=True)
class RuntimeStopError(Exception):
    resource: str
    detail: str

    def __str__(self) -> str:
        return f"failed to stop {self.resource}: {self.detail}"


class CleanupScheduler(Protocol):
    def shutdown(self, wait: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeResource:
    name: str
    roles: frozenset[RuntimeRole]
    configure: Callable[[], None]
    start: Callable[[], None]
    stop: Callable[[], None]

    def belongs_to(self, role: RuntimeRole) -> bool:
        return role in self.roles


class RuntimeLifecycle:  # noqa: MUTABLE_OK
    def __init__(self, resources: tuple[RuntimeResource, ...]) -> None:
        self._resources = resources
        self._started: list[RuntimeResource] = []
        self._role: RuntimeRole | None = None
        self._lock = threading.RLock()

    @property
    def started_resource_names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(resource.name for resource in self._started)

    @property
    def started(self) -> bool:
        with self._lock:
            return bool(self._started)

    def start(self, role: RuntimeRole) -> None:
        with self._lock:
            if self._started:
                return
            selected = tuple(resource for resource in self._resources if resource.belongs_to(role))
            started: list[RuntimeResource] = []
            for resource in selected:
                try:
                    resource.configure()
                    resource.start()
                except Exception as exc:  # noqa: BROAD_EXCEPT_OK
                    self._rollback(started)
                    raise RuntimeStartError(resource=resource.name, detail=str(exc)) from exc
                started.append(resource)
            self._started = started
            self._role = role

    def stop(self) -> None:
        with self._lock:
            started = tuple(self._started)
            self._started = []
            self._role = None
        for resource in reversed(started):
            resource.stop()

    def _rollback(self, started: list[RuntimeResource]) -> None:
        self._started = []
        self._role = None
        for resource in reversed(started):
            resource.stop()


def parse_runtime_role(role: str) -> RuntimeRole:
    try:
        return RuntimeRole(role)
    except ValueError as exc:
        raise UnknownRuntimeRole(role=role) from exc


def init_runtime_lifecycle(app: Flask) -> RuntimeLifecycle:
    lifecycle = RuntimeLifecycle(default_runtime_resources(app))
    app.extensions[RUNTIME_EXTENSION_KEY] = lifecycle
    return lifecycle


def get_runtime_lifecycle(app: Flask) -> RuntimeLifecycle:
    lifecycle = app.extensions.get(RUNTIME_EXTENSION_KEY)
    if isinstance(lifecycle, RuntimeLifecycle):
        return lifecycle
    return init_runtime_lifecycle(app)


def start_runtime(app: Flask, role: str) -> None:
    parsed = parse_runtime_role(role)
    get_runtime_lifecycle(app).start(parsed)


def stop_runtime(app: Flask) -> None:
    get_runtime_lifecycle(app).stop()


def default_runtime_resources(app: Flask) -> tuple[RuntimeResource, ...]:
    from app.utils.enhanced_task_queue import translation_queue
    from app.utils.lazy_http_client import http_client
    from app.utils.thread_pool_executor import thread_pool

    all_roles = frozenset((RuntimeRole.WEB, RuntimeRole.WORKER, RuntimeRole.ALL))
    worker_roles = frozenset((RuntimeRole.WORKER, RuntimeRole.ALL))
    web_roles = frozenset((RuntimeRole.WEB,))

    return (
        RuntimeResource("http_client", all_roles, _configure_http_client, _noop, http_client.close),
        RuntimeResource("translation_queue_config", web_roles, _configure_translation_queue, _noop, _noop),
        RuntimeResource("thread_pool", worker_roles, _configure_thread_pool, _noop, _stop_thread_pool),
        RuntimeResource(
            "translation_queue",
            worker_roles,
            _configure_translation_queue,
            translation_queue.start_processor,
            translation_queue.stop_processor,
        ),
        _embedded_worker_resource(app, worker_roles),
        _db_monitor_resource(app, worker_roles),
        _cleanup_resource(worker_roles),
    )


def _noop() -> None:
    return None


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _configure_thread_pool() -> None:
    from app.utils.thread_pool_executor import thread_pool

    thread_pool.configure(
        max_workers=_env_int("THREAD_POOL_MAX_WORKERS", 32),
        io_bound_workers=_env_int("THREAD_POOL_IO_WORKERS", 24),
        cpu_bound_workers=_env_int("THREAD_POOL_CPU_WORKERS", 8),
        thread_name_prefix=os.getenv("THREAD_POOL_NAME_PREFIX", "app"),
    )


def _stop_thread_pool() -> None:
    from app.utils.thread_pool_executor import thread_pool

    thread_pool.safe_shutdown(wait=True, timeout=5.0)


def _configure_translation_queue() -> None:
    from app.utils.enhanced_task_queue import translation_queue

    translation_queue.configure(
        max_concurrent_tasks=_env_int("TASK_QUEUE_MAX_CONCURRENT", 10),
        task_timeout=_env_int("TASK_QUEUE_TIMEOUT", 3600),
        retry_times=_env_int("TASK_QUEUE_RETRY_TIMES", 3),
    )


def _configure_http_client() -> None:
    from app.utils.lazy_http_client import http_client

    http_client.configure(
        max_connections=_env_int("HTTP_CLIENT_MAX_CONNECTIONS", 100),
        default_timeout=_env_int("HTTP_CLIENT_TIMEOUT", 60),
        retry_times=_env_int("HTTP_CLIENT_RETRY_TIMES", 3),
        retry_delay=_env_int("HTTP_CLIENT_RETRY_DELAY", 1),
    )


def _db_monitor_resource(app: Flask, roles: frozenset[RuntimeRole]) -> RuntimeResource:
    stop_event = threading.Event()
    monitor_thread: threading.Thread | None = None

    def start_monitor() -> None:
        nonlocal monitor_thread, stop_event
        if monitor_thread is not None and monitor_thread.is_alive():
            return
        stop_event = threading.Event()
        interval = _env_int("DB_MONITOR_INTERVAL", 3600)

        def monitor_loop() -> None:
            from app.utils.db_session_manager import get_db_stats, optimize_db_pool, recycle_idle_connections

            while not stop_event.wait(interval):
                with app.app_context():
                    stats = get_db_stats()
                    checkedout = stats.get("checkedout", 0)
                    pool_size = stats.get("pool_size", 10)
                    if isinstance(checkedout, int) and isinstance(pool_size, int) and checkedout > 0.8 * pool_size:
                        recycle_idle_connections()
                        optimize_db_pool()

        monitor_thread = threading.Thread(target=monitor_loop, name="db_monitor", daemon=True)
        monitor_thread.start()

    def stop_monitor() -> None:
        stop_event.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=5.0)
            if monitor_thread.is_alive():
                raise RuntimeStopError(resource="db_monitor", detail="thread did not stop")

    return RuntimeResource("db_monitor", roles, _noop, start_monitor, stop_monitor)


def _cleanup_resource(roles: frozenset[RuntimeRole]) -> RuntimeResource:
    scheduler: CleanupScheduler | None = None

    def start_cleanup() -> None:
        nonlocal scheduler
        from app.tasks.cleanup import schedule_cleanup_task

        scheduler = schedule_cleanup_task()

    def stop_cleanup() -> None:
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    return RuntimeResource("cleanup_scheduler", roles, _noop, start_cleanup, stop_cleanup)


def _embedded_worker_resource(app: Flask, roles: frozenset[RuntimeRole]) -> RuntimeResource:
    worker = None

    def configure_worker() -> None:
        nonlocal worker
        from app.jobs.worker import create_embedded_worker
        from app.utils.enhanced_task_queue import translation_queue

        worker = create_embedded_worker(app, translation_queue)
        app.extensions["embedded_db_worker"] = worker

    def start_worker() -> None:
        if worker is not None:
            worker.start()

    def stop_worker() -> None:
        if worker is not None:
            worker.stop()

    return RuntimeResource("embedded_db_worker", roles, configure_worker, start_worker, stop_worker)
