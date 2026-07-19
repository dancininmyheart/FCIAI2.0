from __future__ import annotations  # noqa: SIZE_OK - aggregated Todo 3 entrypoint contracts share import fixtures.

import importlib
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from wsgiref.types import WSGIApplication, WSGIEnvironment
from wsgiref.util import setup_testing_defaults

import pytest
from flask import Flask


@dataclass(frozen=True, slots=True)
class EntrypointImport:
    name: str
    module_name: str
    file_path: Path | None = None


class ServerBoom(RuntimeError):
    pass


class ResourceBomb(RuntimeError):
    pass


class RuntimeBoom(RuntimeError):
    pass


def _explode_app_factory(config_name: str) -> Flask:
    raise ResourceBomb(f"create_app called for {config_name}")


def _explode_flask_resource(flask_app: Flask) -> None:
    raise ResourceBomb("Flask resource touched")


def _fresh_import(entrypoint: EntrypointImport):
    sys.modules.pop(entrypoint.module_name, None)
    if entrypoint.file_path is None:
        return importlib.import_module(entrypoint.module_name)
    spec = importlib.util.spec_from_file_location(entrypoint.module_name, entrypoint.file_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[entrypoint.module_name] = module
    spec.loader.exec_module(module)
    return module


def _flask_response(name: str, body: str = "ok") -> Flask:
    flask_app = Flask(name)

    @flask_app.get("/")
    def index() -> str:
        return body

    return flask_app


def _call_wsgi(wsgi_app: WSGIApplication) -> tuple[str, bytes]:
    environ: WSGIEnvironment = {}
    setup_testing_defaults(environ)
    status_values: list[str] = []

    def start_response(status, headers, exc_info=None):
        status_values.append(status)

    response = wsgi_app(environ, start_response)
    try:
        body = b"".join(response)
    finally:
        response.close()
    return status_values[0], body


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    process.terminate()
    try:
        return process.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            process.kill()
        return process.communicate(timeout=5.0)


@pytest.mark.parametrize(
    "entrypoint",
    (
        EntrypointImport("run", "run"),
        EntrypointImport("run_async", "run_async"),
        EntrypointImport("run_worker", "run_worker"),
        EntrypointImport("legacy_app", "legacy_app_entrypoint", Path("app.py")),
    ),
)
def test_importing_entrypoints_starts_no_worker(
    entrypoint: EntrypointImport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    calls: list[str] = []
    import app.runtime as runtime
    import app as app_pkg

    monkeypatch.setattr(app_pkg, "create_app", _explode_app_factory)
    monkeypatch.setattr(runtime, "start_runtime", lambda flask_app, role: calls.append(f"start:{role}"))
    monkeypatch.setattr(runtime, "stop_runtime", lambda flask_app: calls.append("stop"))

    # When
    _fresh_import(entrypoint)

    # Then
    assert calls == []


def test_run_launcher_creates_schema_and_all_runtime_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    import run

    events: list[str] = []
    flask_app = Flask(__name__)
    deps = run.LauncherDeps(
        app_factory=lambda config_name: flask_app,
        create_schema=lambda app: events.append("schema"),
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        run_server=lambda app: events.append("serve"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = run.main([], deps)

    # Then
    assert exit_code == 0
    assert events == ["schema", "start:all", "serve", "stop"]


def test_run_check_does_not_create_schema_start_runtime_or_serve() -> None:
    # Given
    import run

    events: list[str] = []
    deps = run.LauncherDeps(
        app_factory=_explode_app_factory,
        create_schema=_explode_flask_resource,
        start_runtime=lambda app, role: _explode_flask_resource(app),
        stop_runtime=_explode_flask_resource,
        run_server=_explode_flask_resource,
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = run.main(["--check"], deps)

    # Then
    assert exit_code == 0
    assert events == ["check:development"]


def test_worker_launcher_creates_schema_and_worker_runtime_once() -> None:
    # Given
    import run_worker

    events: list[str] = []
    flask_app = Flask(__name__)
    deps = run_worker.WorkerLauncherDeps(
        app_factory=lambda config_name: flask_app,
        create_schema=lambda app: events.append("schema"),
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        wait_forever=lambda: events.append("wait"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = run_worker.main([], deps)

    # Then
    assert exit_code == 0
    assert events == ["schema", "start:worker", "wait", "stop"]


def test_worker_check_does_not_create_app_schema_runtime_or_wait() -> None:
    # Given
    import run_worker

    events: list[str] = []
    deps = run_worker.WorkerLauncherDeps(
        app_factory=_explode_app_factory,
        create_schema=_explode_flask_resource,
        start_runtime=lambda app, role: _explode_flask_resource(app),
        stop_runtime=_explode_flask_resource,
        wait_forever=lambda: events.append("wait"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = run_worker.main(["--check"], deps)

    # Then
    assert exit_code == 0
    assert events == ["check:development"]


def test_async_launcher_defaults_to_uvicorn_and_web_runtime() -> None:
    # Given
    import run_async

    events: list[str] = []
    flask_app = Flask(__name__)
    deps = run_async.AsyncLauncherDeps(
        app_factory=lambda config_name: flask_app,
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        run_server=lambda app, server_type: events.append(f"serve:{server_type}"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
        check_server=lambda server_type: events.append(f"server:{server_type}"),
    )

    # When
    exit_code = run_async.main([], deps)

    # Then
    assert exit_code == 0
    assert events == ["server:uvicorn", "start:web", "serve:uvicorn", "stop"]


def test_async_check_uses_one_app_and_no_runtime_start() -> None:
    # Given
    import run_async

    events: list[str] = []
    deps = run_async.AsyncLauncherDeps(
        app_factory=_explode_app_factory,
        start_runtime=lambda app, role: _explode_flask_resource(app),
        stop_runtime=_explode_flask_resource,
        run_server=lambda app, server_type: _explode_flask_resource(app),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
        check_server=lambda server_type: events.append(f"server:{server_type}"),
    )

    # When
    exit_code = run_async.main(["--check"], deps)

    # Then
    assert exit_code == 0
    assert events == ["server:uvicorn", "check:development"]


def test_async_run_rejects_unsupported_server_before_app_or_runtime() -> None:
    # Given
    import run_async

    events: list[str] = []
    flask_app = Flask(__name__)
    deps = run_async.AsyncLauncherDeps(
        app_factory=lambda config_name: events.append(f"app:{config_name}") or flask_app,
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        run_server=lambda app, server_type: events.append(f"serve:{server_type}"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
        check_server=run_async._check_server,
    )

    # When
    exit_code = run_async.main(["--server", "bogus"], deps)

    # Then
    assert exit_code == 1
    assert events == []


def test_async_check_reports_missing_default_uvicorn_dependency_before_app_construction() -> None:
    # Given
    import run_async

    deps = run_async.AsyncLauncherDeps(
        app_factory=_explode_app_factory,
        start_runtime=lambda app, role: _explode_flask_resource(app),
        stop_runtime=_explode_flask_resource,
        run_server=lambda app, server_type: _explode_flask_resource(app),
        check_startup=lambda config_name: None,
        check_server=lambda server_type: (_ for _ in ()).throw(run_async.OptionalDependencyMissing("uvicorn")),
    )

    # When
    exit_code = run_async.main(["--check"], deps)

    # Then
    assert exit_code == 1


def test_async_check_reports_missing_default_uvicorn_dependency_from_subprocess() -> None:
    # Given
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{Path('tests/helpers').resolve()}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["BLOCK_IMPORT"] = "uvicorn"

    # When
    result = subprocess.run(
        [sys.executable, "run_async.py", "--check"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert result.returncode == 1
    assert "optional dependency uvicorn" in result.stderr
    assert result.stdout == ""


def test_uvicorn_wsgi_adapter_uses_supported_a2wsgi_adapter() -> None:
    # Given
    import run_async

    # When
    adapter = run_async._load_wsgi_to_asgi_adapter()

    # Then
    assert adapter.__module__.split(".", maxsplit=1)[0] == "a2wsgi"
    assert adapter.__module__ != "uvicorn.middleware.wsgi"
    assert adapter.__name__ == "WSGIMiddleware"


def test_async_check_reports_missing_a2wsgi_dependency_before_app_construction() -> None:
    # Given
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{Path('tests/helpers').resolve()}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["BLOCK_IMPORT"] = "a2wsgi"

    # When
    result = subprocess.run(
        [sys.executable, "run_async.py", "--check"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert result.returncode == 1
    assert "optional dependency a2wsgi" in result.stderr
    assert result.stdout == ""


def test_default_uvicorn_server_serves_wsgi_flask_app_over_http_and_cleans_up() -> None:
    # Given
    port = _free_tcp_port()
    env = os.environ.copy()
    env["SERVER_HOST"] = "127.0.0.1"
    env["SERVER_PORT"] = str(port)
    command = [
        sys.executable,
        "-c",
        "\n".join(
            (
                "from __future__ import annotations",
                "from flask import Flask",
                "import run_async",
                "flask_app = Flask('default-uvicorn-smoke')",
                "@flask_app.get('/')",
                "def index() -> str:",
                "    return 'default-uvicorn-ok'",
                "deps = run_async.AsyncLauncherDeps(",
                "    app_factory=lambda config_name: flask_app,",
                "    start_runtime=lambda app, role: None,",
                "    stop_runtime=lambda app: None,",
                "    run_server=run_async._run_server,",
                "    check_startup=lambda config_name: None,",
                "    check_server=run_async._check_server,",
                ")",
                "raise SystemExit(run_async.main([], deps))",
            )
        ),
    ]
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    status = 0
    body = ""

    # When
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.0) as response:
                    status = response.status
                    body = response.read().decode("utf-8")
                    break
            except urllib.error.HTTPError as exc:
                status = exc.code
                body = exc.read().decode("utf-8", errors="replace")
                break
            except OSError:
                time.sleep(0.1)
    finally:
        stdout, stderr = _terminate_process(process)

    # Then
    assert status == 200, stderr
    assert body == "default-uvicorn-ok"
    assert process.poll() is not None
    assert "TypeError: Flask.__call__()" not in stderr
    assert stdout is not None


def test_server_failure_stops_runtime() -> None:
    # Given
    import run

    events: list[str] = []
    flask_app = Flask(__name__)

    def fail_server(app: Flask) -> None:
        events.append("serve")
        raise ServerBoom

    deps = run.LauncherDeps(
        app_factory=lambda config_name: flask_app,
        create_schema=lambda app: events.append("schema"),
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        run_server=fail_server,
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    with pytest.raises(ServerBoom):
        run.main([], deps)

    # Then
    assert events == ["schema", "start:all", "serve", "stop"]


def test_legacy_app_launcher_uses_web_runtime() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_for_role", Path("app.py")))
    events: list[str] = []
    flask_app = Flask(__name__)
    deps = legacy_app.LegacyLauncherDeps(
        app_factory=lambda config_name: flask_app,
        create_schema=lambda app: events.append("schema"),
        start_runtime=lambda app, role: events.append(f"start:{role}"),
        stop_runtime=lambda app: events.append("stop"),
        run_server=lambda app: events.append("serve"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = legacy_app.main([], deps)

    # Then
    assert exit_code == 0
    assert events == ["schema", "start:web", "serve", "stop"]


def test_legacy_check_does_not_create_app_schema_runtime_or_serve() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_for_check", Path("app.py")))
    events: list[str] = []
    deps = legacy_app.LegacyLauncherDeps(
        app_factory=_explode_app_factory,
        create_schema=_explode_flask_resource,
        start_runtime=lambda app, role: _explode_flask_resource(app),
        stop_runtime=_explode_flask_resource,
        run_server=_explode_flask_resource,
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    exit_code = legacy_app.main(["--check"], deps)

    # Then
    assert exit_code == 0
    assert events == ["check:development"]


def test_legacy_app_exposes_callable_wsgi_application() -> None:
    # Given / When
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_surface", Path("app.py")))

    # Then
    assert hasattr(legacy_app, "application")
    assert callable(legacy_app.application)


def test_wsgi_import_starts_no_app_or_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    events: list[str] = []
    import app.runtime as runtime
    import app as app_pkg

    monkeypatch.setattr(app_pkg, "create_app", _explode_app_factory)
    monkeypatch.setattr(app_pkg.db, "create_all", lambda: events.append("schema"))
    monkeypatch.setattr(runtime, "start_runtime", lambda flask_app, role: events.append(f"start:{role}"))
    monkeypatch.setattr(runtime, "stop_runtime", lambda flask_app: events.append("stop"))

    # When
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_import", Path("app.py")))

    # Then
    assert callable(legacy_app.application)
    assert events == []


def test_wsgi_first_request_creates_app_and_web_runtime_once() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_once", Path("app.py")))
    events: list[str] = []
    flask_app = _flask_response("wsgi-once", "first")
    wsgi_app = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=lambda config_name: events.append(f"app:{config_name}") or flask_app,
            start_runtime=lambda app, role: events.append(f"start:{role}"),
            stop_runtime=lambda app: events.append("stop"),
        )
    )

    # When
    status, body = _call_wsgi(wsgi_app)

    # Then
    assert status == "200 OK"
    assert body == b"first"
    assert events == ["app:development", "start:web"]


def test_wsgi_repeated_requests_reuse_app_and_runtime() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_reuse", Path("app.py")))
    events: list[str] = []
    flask_app = _flask_response("wsgi-reuse", "reuse")
    wsgi_app = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=lambda config_name: events.append(f"app:{config_name}") or flask_app,
            start_runtime=lambda app, role: events.append(f"start:{role}"),
            stop_runtime=lambda app: events.append("stop"),
        )
    )

    # When
    first = _call_wsgi(wsgi_app)
    second = _call_wsgi(wsgi_app)

    # Then
    assert first == ("200 OK", b"reuse")
    assert second == ("200 OK", b"reuse")
    assert events == ["app:development", "start:web"]


def test_wsgi_concurrent_first_requests_create_and_start_once() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_concurrent", Path("app.py")))
    events: list[str] = []
    factory_entered = threading.Event()
    release_factory = threading.Event()
    flask_app = _flask_response("wsgi-concurrent", "shared")

    def app_factory(config_name: str) -> Flask:
        events.append(f"app:{config_name}")
        factory_entered.set()
        assert release_factory.wait(timeout=2.0)
        return flask_app

    wsgi_app = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=app_factory,
            start_runtime=lambda app, role: events.append(f"start:{role}"),
            stop_runtime=lambda app: events.append("stop"),
        )
    )
    results: list[tuple[str, bytes]] = []
    failures: list[AssertionError | RuntimeError] = []

    def call_app() -> None:
        try:
            results.append(_call_wsgi(wsgi_app))
        except (AssertionError, RuntimeError) as exc:
            failures.append(exc)

    threads = [threading.Thread(target=call_app) for _ in range(5)]

    # When
    for thread in threads:
        thread.start()
    assert factory_entered.wait(timeout=2.0)
    release_factory.set()
    for thread in threads:
        thread.join(timeout=2.0)

    # Then
    assert failures == []
    assert all(not thread.is_alive() for thread in threads)
    assert results == [("200 OK", b"shared")] * 5
    assert events == ["app:development", "start:web"]


def test_wsgi_startup_failure_stops_partial_app_and_next_request_retries() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_retry", Path("app.py")))
    events: list[str] = []
    apps = [_flask_response("wsgi-fail-first", "failed"), _flask_response("wsgi-retry", "retried")]

    def app_factory(config_name: str) -> Flask:
        flask_app = apps.pop(0)
        events.append(f"app:{flask_app.name}:{config_name}")
        return flask_app

    def start_runtime_probe(flask_app: Flask, role: str) -> None:
        events.append(f"start:{flask_app.name}:{role}")
        if flask_app.name == "wsgi-fail-first":
            raise RuntimeBoom

    wsgi_app = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=app_factory,
            start_runtime=start_runtime_probe,
            stop_runtime=lambda app: events.append(f"stop:{app.name}"),
        )
    )

    # When
    with pytest.raises(RuntimeBoom):
        _call_wsgi(wsgi_app)
    retry_status, retry_body = _call_wsgi(wsgi_app)

    # Then
    assert (retry_status, retry_body) == ("200 OK", b"retried")
    assert events == [
        "app:wsgi-fail-first:development",
        "start:wsgi-fail-first:web",
        "stop:wsgi-fail-first",
        "app:wsgi-retry:development",
        "start:wsgi-retry:web",
    ]


def test_wsgi_shutdown_is_idempotent_and_test_invokable() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_wsgi_shutdown", Path("app.py")))
    events: list[str] = []
    flask_app = _flask_response("wsgi-shutdown", "bye")
    wsgi_app = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=lambda config_name: flask_app,
            start_runtime=lambda app, role: events.append(f"start:{role}"),
            stop_runtime=lambda app: events.append(f"stop:{app.name}"),
        )
    )
    _call_wsgi(wsgi_app)

    # When
    wsgi_app.shutdown()
    wsgi_app.shutdown()

    # Then
    assert events == ["start:web", "stop:wsgi-shutdown"]


def test_legacy_cli_main_does_not_share_wsgi_singleton() -> None:
    # Given
    legacy_app = _fresh_import(EntrypointImport("legacy_app", "legacy_app_entrypoint_cli_separate", Path("app.py")))
    events: list[str] = []
    wsgi_flask_app = _flask_response("wsgi-singleton", "wsgi")
    cli_flask_app = Flask("cli-main")
    legacy_app.application = legacy_app.LazyWsgiApplication(
        legacy_app.WsgiDeps(
            app_factory=lambda config_name: events.append(f"wsgi-app:{config_name}") or wsgi_flask_app,
            start_runtime=lambda app, role: events.append(f"wsgi-start:{role}"),
            stop_runtime=lambda app: events.append("wsgi-stop"),
        )
    )
    deps = legacy_app.LegacyLauncherDeps(
        app_factory=lambda config_name: events.append(f"cli-app:{config_name}") or cli_flask_app,
        create_schema=lambda app: events.append(f"schema:{app.name}"),
        start_runtime=lambda app, role: events.append(f"cli-start:{app.name}:{role}"),
        stop_runtime=lambda app: events.append(f"cli-stop:{app.name}"),
        run_server=lambda app: events.append(f"serve:{app.name}"),
        check_startup=lambda config_name: events.append(f"check:{config_name}"),
    )

    # When
    _call_wsgi(legacy_app.application)
    exit_code = legacy_app.main([], deps)

    # Then
    assert exit_code == 0
    assert events == [
        "wsgi-app:development",
        "wsgi-start:web",
        "cli-app:development",
        "schema:cli-main",
        "cli-start:cli-main:web",
        "serve:cli-main",
        "cli-stop:cli-main",
    ]
