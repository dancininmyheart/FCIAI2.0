from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Callable

from flask import Flask

from app import create_app, db
from app.runtime import parse_runtime_role, start_runtime, stop_runtime

RUN_ROLE = "all"


@dataclass(frozen=True, slots=True)
class LauncherDeps:
    app_factory: Callable[[str], Flask]
    create_schema: Callable[[Flask], None]
    start_runtime: Callable[[Flask, str], None]
    stop_runtime: Callable[[Flask], None]
    run_server: Callable[[Flask], None]
    check_startup: Callable[[str], None]


def _create_schema(flask_app: Flask) -> None:
    with flask_app.app_context():
        db.create_all()


def _run_flask_server(flask_app: Flask) -> None:
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT", "5000"))
    flask_app.run(host=host, port=port)


def _check_startup(config_name: str) -> None:
    from app.config import config as flask_configs

    flask_configs[config_name]
    parse_runtime_role(RUN_ROLE)


DEFAULT_DEPS = LauncherDeps(
    app_factory=create_app,
    create_schema=_create_schema,
    start_runtime=start_runtime,
    stop_runtime=stop_runtime,
    run_server=_run_flask_server,
    check_startup=_check_startup,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FCIAI Flask development server.")
    parser.add_argument("--check", action="store_true", help="Validate startup wiring without running services.")
    parser.add_argument("--config", default=os.environ.get("FLASK_CONFIG", "development"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, deps: LauncherDeps = DEFAULT_DEPS) -> int:
    args = _parse_args(argv)
    if args.check:
        deps.check_startup(args.config)
        return 0
    flask_app = deps.app_factory(args.config)
    deps.create_schema(flask_app)
    deps.start_runtime(flask_app, RUN_ROLE)
    try:
        deps.run_server(flask_app)
    finally:
        deps.stop_runtime(flask_app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
