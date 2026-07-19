from __future__ import annotations

import argparse
import os
import signal
import time
from dataclasses import dataclass
from typing import Callable

from flask import Flask

from app import create_app, db
from app.runtime import parse_runtime_role, start_runtime, stop_runtime

WORKER_ROLE = "worker"


@dataclass(frozen=True, slots=True)
class WorkerLauncherDeps:
    app_factory: Callable[[str], Flask]
    create_schema: Callable[[Flask], None]
    start_runtime: Callable[[Flask, str], None]
    stop_runtime: Callable[[Flask], None]
    wait_forever: Callable[[], None]
    check_startup: Callable[[str], None]


def _create_schema(flask_app: Flask) -> None:
    with flask_app.app_context():
        db.create_all()


def _wait_forever() -> None:
    stop = False

    def request_stop(signum, frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        time.sleep(1.0)


def _check_startup(config_name: str) -> None:
    from app.config import config as flask_configs

    flask_configs[config_name]
    parse_runtime_role(WORKER_ROLE)


DEFAULT_DEPS = WorkerLauncherDeps(
    app_factory=create_app,
    create_schema=_create_schema,
    start_runtime=start_runtime,
    stop_runtime=stop_runtime,
    wait_forever=_wait_forever,
    check_startup=_check_startup,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FCIAI embedded translation worker.")
    parser.add_argument("--check", action="store_true", help="Validate startup wiring without running services.")
    parser.add_argument("--config", default=os.environ.get("FLASK_CONFIG", "development"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, deps: WorkerLauncherDeps = DEFAULT_DEPS) -> int:
    args = _parse_args(argv)
    if args.check:
        deps.check_startup(args.config)
        return 0
    flask_app = deps.app_factory(args.config)
    deps.create_schema(flask_app)
    deps.start_runtime(flask_app, WORKER_ROLE)
    try:
        deps.wait_forever()
    finally:
        deps.stop_runtime(flask_app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
