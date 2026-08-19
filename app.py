from __future__ import annotations

import argparse
import atexit
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable
from wsgiref.types import StartResponse, WSGIEnvironment

from flask import Flask

from app import create_app, db
from app.runtime import parse_runtime_role, start_runtime, stop_runtime

LEGACY_ROLE = "web"


@dataclass(frozen=True, slots=True)
class LegacyLauncherDeps:
    app_factory: Callable[[str], Flask]
    create_schema: Callable[[Flask], None]
    start_runtime: Callable[[Flask, str], None]
    stop_runtime: Callable[[Flask], None]
    run_server: Callable[[Flask], None]
    check_startup: Callable[[str], None]


@dataclass(frozen=True, slots=True)
class WsgiDeps:
    app_factory: Callable[[str], Flask]
    start_runtime: Callable[[Flask, str], None]
    stop_runtime: Callable[[Flask], None]


class LazyWsgiApplication:  # noqa: MUTABLE_OK
    def __init__(self, deps: WsgiDeps, role: str = LEGACY_ROLE) -> None:
        self._deps = deps
        self._role = role
        self._lock = threading.RLock()
        self._flask_app: Flask | None = None

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        return self._load_app()(environ, start_response)

    def shutdown(self) -> None:
        with self._lock:
            flask_app = self._flask_app
            self._flask_app = None
        if flask_app is not None:
            self._deps.stop_runtime(flask_app)

    def _load_app(self) -> Flask:
        with self._lock:
            if self._flask_app is not None:
                return self._flask_app
            config_name = os.environ.get("FLASK_CONFIG", "development")
            flask_app = self._deps.app_factory(config_name)
            try:
                self._deps.start_runtime(flask_app, self._role)
            except Exception:  # noqa: BROAD_EXCEPT_OK
                self._deps.stop_runtime(flask_app)
                raise
            self._flask_app = flask_app
            return flask_app


def _create_schema(flask_app: Flask) -> None:
    with flask_app.app_context():
        db.create_all()


def _run_flask_server(flask_app: Flask) -> None:
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    flask_app.run(host=host, port=port, debug=debug)


def _check_startup(config_name: str) -> None:
    from app.config import config as flask_configs

    flask_configs[config_name]
    parse_runtime_role(LEGACY_ROLE)


DEFAULT_DEPS = LegacyLauncherDeps(
    app_factory=create_app,
    create_schema=_create_schema,
    start_runtime=start_runtime,
    stop_runtime=stop_runtime,
    run_server=_run_flask_server,
    check_startup=_check_startup,
)

DEFAULT_WSGI_DEPS = WsgiDeps(
    app_factory=create_app,
    start_runtime=start_runtime,
    stop_runtime=stop_runtime,
)

application = LazyWsgiApplication(DEFAULT_WSGI_DEPS)
atexit.register(application.shutdown)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PPT Agent Studio Flask entrypoint.")
    parser.add_argument("--check", action="store_true", help="Validate startup wiring without running services.")
    parser.add_argument("--config", default=os.environ.get("FLASK_CONFIG", "development"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, deps: LegacyLauncherDeps = DEFAULT_DEPS) -> int:
    args = _parse_args(argv)
    if args.check:
        deps.check_startup(args.config)
        return 0
    flask_app = deps.app_factory(args.config)
    deps.create_schema(flask_app)
    deps.start_runtime(flask_app, LEGACY_ROLE)
    try:
        deps.run_server(flask_app)
    finally:
        deps.stop_runtime(flask_app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
