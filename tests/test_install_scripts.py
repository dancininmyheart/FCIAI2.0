from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_builds_one_web_and_one_worker() -> None:
    script = (ROOT / "quick_install.bat").read_text(encoding="utf-8")
    production = script.split(":: 创建生产模式启动脚本：一个 Web 进程和一个 Worker 进程", 1)[1].split(
        ":: 创建停止脚本",
        1,
    )[0]

    assert "for %%e in (run.py app.py run_async.py run_worker.py)" in script
    assert "sys.version_info ^>= (3, 11)" in script
    assert production.count("-ArgumentList 'run_async.py'") == 1
    assert production.count("-ArgumentList 'run_worker.py'") == 1
    assert "System already running" in production
    assert "taskkill /f /im python.exe" not in script.lower()
    assert "gunicorn" not in production.lower()


def test_linux_installer_builds_supervisor_web_worker_group() -> None:
    script = (ROOT / "quick_install.sh").read_text(encoding="utf-8")

    assert "for entrypoint in run.py app.py run_async.py run_worker.py" in script
    assert "sys.version_info >= (3, 11)" in script
    assert "[group:ppt-translation]" in script
    assert "programs=ppt-translation-web,ppt-translation-worker" in script
    assert script.count("[program:ppt-translation-web]") == 1
    assert script.count("[program:ppt-translation-worker]") == 1
    assert "command=$PROJECT_DIR/venv/bin/python run_async.py" in script
    assert "command=$PROJECT_DIR/venv/bin/python run_worker.py" in script
    assert "gunicorn" not in script.lower()
