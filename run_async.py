from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

from flask import Flask

from app import create_app
from app.runtime import parse_runtime_role, start_runtime, stop_runtime

if TYPE_CHECKING:
    from uvicorn._types import ASGIApplication

ASYNC_ROLE = "web"
DEFAULT_SERVER = "uvicorn"
SUPPORTED_SERVERS = ("uvicorn", "hypercorn")


@dataclass(frozen=True, slots=True)
class OptionalDependencyMissing(Exception):
    package: str

    def __str__(self) -> str:
        return f"optional dependency {self.package} is required"


@dataclass(frozen=True, slots=True)
class UnsupportedServerType(Exception):
    server_type: str

    def __str__(self) -> str:
        supported = ", ".join(SUPPORTED_SERVERS)
        return f"configuration error SERVER_TYPE unsupported: {self.server_type} (expected {supported})"


@dataclass(frozen=True, slots=True)
class AsyncLauncherDeps:
    app_factory: Callable[[str], Flask]
    start_runtime: Callable[[Flask, str], None]
    stop_runtime: Callable[[Flask], None]
    run_server: Callable[[Flask, str], None]
    check_startup: Callable[[str], None]
    check_server: Callable[[str], None]


class UvicornModule(Protocol):
    def run(self, app: "ASGIApplication", *, host: str, port: int, log_level: str) -> None: ...


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PPT Agent Studio async web entrypoint.")
    parser.add_argument("--check", action="store_true", help="Validate startup wiring without running services.")
    parser.add_argument("--config", default=os.environ.get("FLASK_CONFIG", "development"))
    parser.add_argument("--server", default=os.environ.get("SERVER_TYPE", DEFAULT_SERVER))
    return parser.parse_args(argv)


def _check_startup(config_name: str) -> None:
    from app.config import config as flask_configs

    flask_configs[config_name]
    parse_runtime_role(ASYNC_ROLE)


def _check_server(server_type: str) -> None:
    normalized = _normalize_server_type(server_type)
    if normalized == "hypercorn":
        _load_hypercorn()
        return
    _load_wsgi_to_asgi_adapter()
    _load_uvicorn()


def _run_server(flask_app: Flask, server_type: str) -> None:
    normalized = _normalize_server_type(server_type)
    if normalized == "hypercorn":
        _run_hypercorn(flask_app)
        return
    _run_uvicorn(flask_app)


def _normalize_server_type(server_type: str) -> str:
    normalized = server_type.lower()
    if normalized in SUPPORTED_SERVERS:
        return normalized
    raise UnsupportedServerType(server_type=server_type)


def _run_uvicorn(flask_app: Flask) -> None:
    wsgi_to_asgi = _load_wsgi_to_asgi_adapter()
    uvicorn = _load_uvicorn()

    uvicorn.run(
        wsgi_to_asgi(flask_app),
        host=os.environ.get("SERVER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "5000")),
        log_level="info",
    )


def _load_uvicorn() -> UvicornModule:
    try:
        import uvicorn
    except ImportError as exc:
        raise OptionalDependencyMissing(package="uvicorn") from exc
    return uvicorn


def _load_wsgi_to_asgi_adapter() -> Callable[[Flask], "ASGIApplication"]:
    try:
        from a2wsgi import WSGIMiddleware
    except ImportError as exc:
        raise OptionalDependencyMissing(package="a2wsgi") from exc
    return WSGIMiddleware


def _run_hypercorn(flask_app: Flask) -> None:
    hypercorn_config, serve = _load_hypercorn()
    config = hypercorn_config()
    host = os.environ.get("SERVER_HOST", "0.0.0.0")
    port = os.environ.get("SERVER_PORT", "5000")
    config.bind = [f"{host}:{port}"]
    config.worker_class = "asyncio"
    config.workers = int(os.environ.get("SERVER_WORKERS", "2"))
    config.accesslog = "-"
    __import__("asyncio").run(serve(flask_app, config))


def _load_hypercorn():
    try:
        from hypercorn.asyncio import serve
        from hypercorn.config import Config
    except ImportError as exc:
        raise OptionalDependencyMissing(package="hypercorn") from exc
    return Config, serve


DEFAULT_DEPS = AsyncLauncherDeps(
    app_factory=create_app,
    start_runtime=start_runtime,
    stop_runtime=stop_runtime,
    run_server=_run_server,
    check_startup=_check_startup,
    check_server=_check_server,
)


def main(argv: list[str] | None = None, deps: AsyncLauncherDeps = DEFAULT_DEPS) -> int:
    args = _parse_args(argv)
    try:
        deps.check_server(args.server)
    except (OptionalDependencyMissing, UnsupportedServerType) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.check:
        deps.check_startup(args.config)
        return 0
    flask_app = deps.app_factory(args.config)
    deps.start_runtime(flask_app, ASYNC_ROLE)
    try:
        deps.run_server(flask_app, args.server)
    finally:
        deps.stop_runtime(flask_app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
