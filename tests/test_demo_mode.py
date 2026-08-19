from __future__ import annotations

import os
import logging
from pathlib import Path

import pytest
from flask import Flask


def _enter_demo(client):
    client.get("/auth/login")
    with client.session_transaction() as browser_session:
        nonce = browser_session["demo_login_nonce"]
    return client.post("/auth/demo", data={"demo_login_nonce": nonce})


def test_demo_entry_is_hidden_and_route_is_closed_when_switch_is_off(
    isolated_app: Flask,
) -> None:
    isolated_app.config["DEMO_MODE"] = False
    client = isolated_app.test_client()

    page = client.get("/auth/login")
    blocked = client.post("/auth/demo")

    assert page.status_code == 200
    assert "PPT Agent Studio" in page.get_data(as_text=True)
    assert "进入演示工作台" not in page.get_data(as_text=True)
    assert blocked.status_code == 404


@pytest.fixture
def demo_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database = tmp_path / "demo.sqlite3"
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(database))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    import app as app_pkg
    from app import create_app, db
    from app.models.user import Role

    # Keep the demo fixture isolated from the process-wide logging tree so it
    # does not change caplog behavior for tests that run later in the suite.
    monkeypatch.setattr(app_pkg.log_manager, "configure", lambda **kwargs: None)
    monkeypatch.setattr(
        app_pkg.log_manager,
        "get_logger",
        lambda: logging.getLogger("tests.demo"),
    )

    flask_app = create_app("testing")
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    assert flask_app.config["DEMO_MODE"] is True
    assert flask_app.config["SECRET_KEY"] != "hard to guess string"
    assert flask_app.config["DEBUG"] is False
    assert flask_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    with flask_app.app_context():
        db.create_all()
        db.session.add(Role(name="user"))
        db.session.commit()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


def test_demo_entry_creates_and_reuses_an_approved_anonymous_user(demo_app: Flask) -> None:
    from app import db
    from app.models.user import User

    client = demo_app.test_client()
    page = client.get("/auth/login")

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "进入演示工作台" in html
    assert 'action="/auth/demo"' in html
    assert 'href="/auth/sso/login"' not in html

    with client.session_transaction() as browser_session:
        nonce = browser_session["demo_login_nonce"]
    first_entry = client.post("/auth/demo", data={"demo_login_nonce": nonce})
    assert first_entry.status_code == 302
    assert first_entry.headers["Location"].endswith("/")

    with client.session_transaction() as browser_session:
        first_user_id = browser_session["_user_id"]
        assert browser_session["username"] == "ppt_demo_guest"

    with demo_app.app_context():
        users = User.query.filter_by(username="ppt_demo_guest").all()
        assert len(users) == 1
        user = users[0]
        assert str(user.id) == first_user_id
        assert user.status == "approved"
        assert user.email == "ppt-demo@localhost.invalid"
        assert user.display_name == "Demo Visitor"
        assert user.role is not None and user.role.name == "user"
        assert user.password
        assert not user.check_password("demo")

    second_entry = _enter_demo(demo_app.test_client())
    assert second_entry.status_code == 302
    with demo_app.app_context():
        assert User.query.filter_by(username="ppt_demo_guest").count() == 1
        db.session.remove()


def test_demo_identity_never_reuses_an_unmarked_account(demo_app: Flask) -> None:
    from app import db
    from app.models.user import User

    with demo_app.app_context():
        user = User.query.filter_by(username="ppt_demo_guest").first()
        assert user is None
        conflicting_user = User(
            username="ppt_demo_guest",
            email="someone@example.test",
            status="approved",
        )
        conflicting_user.set_password("private-account-password")
        db.session.add(conflicting_user)
        db.session.commit()

    client = demo_app.test_client()
    response = _enter_demo(client)

    assert response.status_code == 409
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session


def test_run_demo_sets_cli_environment_only_for_the_server_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run

    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("SSO_ENABLED", raising=False)
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("SERVER_HOST", raising=False)
    for key in run.DEMO_WORKFLOW_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    events: list[tuple[str, str | None]] = []
    observed_workflow: dict[str, str | None] = {}
    flask_app = Flask(__name__)

    def create_demo_app(config_name: str) -> Flask:
        events.append(("factory", os.environ.get("DEMO_MODE")))
        observed_workflow.update(
            {key: os.environ.get(key) for key in run.DEMO_WORKFLOW_DEFAULTS}
        )
        return flask_app

    deps = run.LauncherDeps(
        app_factory=create_demo_app,
        create_schema=lambda app: events.append(("schema", os.environ.get("DEMO_MODE"))),
        start_runtime=lambda app, role: events.append(("runtime", role)),
        stop_runtime=lambda app: events.append(("stop", os.environ.get("DEMO_MODE"))),
        run_server=lambda app: events.append(
            ("serve", f"{os.environ.get('APP_NAME')}@{os.environ.get('SERVER_HOST')}")
        ),
        check_startup=lambda config_name: None,
    )

    exit_code = run.main(["--demo"], deps)

    assert exit_code == 0
    assert events == [
        ("factory", "true"),
        ("schema", "true"),
        ("runtime", "all"),
        ("serve", "PPT Agent Studio@127.0.0.1"),
        ("stop", "true"),
    ]
    assert "DEMO_MODE" not in os.environ
    assert "SSO_ENABLED" not in os.environ
    assert "APP_NAME" not in os.environ
    assert "SERVER_HOST" not in os.environ
    assert observed_workflow == run.DEMO_WORKFLOW_DEFAULTS
    assert not set(run.DEMO_WORKFLOW_DEFAULTS).intersection(os.environ)
