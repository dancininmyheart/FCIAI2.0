from __future__ import annotations

import os
import logging
import re
from io import BytesIO
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.test import EnvironBuilder


DEMO_ACCESS_PASSWORD = "correct-horse-battery-staple"


def _enter_demo(
    client,
    *,
    username: str = "demo",
    password: str = DEMO_ACCESS_PASSWORD,
):
    client.get("/auth/login")
    with client.session_transaction() as browser_session:
        nonce = browser_session["demo_login_nonce"]
    return client.post(
        "/auth/demo",
        data={
            "demo_login_nonce": nonce,
            "username": username,
            "password": password,
        },
    )


def test_demo_entry_is_hidden_and_route_is_closed_when_switch_is_off(
    isolated_app: Flask,
) -> None:
    isolated_app.config["DEMO_MODE"] = False
    client = isolated_app.test_client()

    page = client.get("/auth/login")
    blocked = client.post("/auth/demo")

    assert page.status_code == 200
    assert "PPT Agent Studio" in page.get_data(as_text=True)
    assert "登录 PPT 翻译工作台" not in page.get_data(as_text=True)
    assert blocked.status_code == 404


@pytest.mark.parametrize(
    ("configured_password", "is_configured"),
    [
        (None, False),
        ("too-short", False),
        ("            ", False),
        ("123456789012", True),
        (DEMO_ACCESS_PASSWORD, True),
    ],
)
def test_demo_access_configuration_is_loaded_at_app_initialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured_password: str | None,
    is_configured: bool,
) -> None:
    from app.config import TestingConfig

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "dynamic-demo.sqlite3"))
    monkeypatch.setenv("DEMO_ACCESS_USERNAME", "interview-guest")
    monkeypatch.setenv("DEMO_LOGIN_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("DEMO_LOGIN_LOCKOUT_SECONDS", "42")
    if configured_password is None:
        monkeypatch.delenv("DEMO_ACCESS_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("DEMO_ACCESS_PASSWORD", configured_password)

    flask_app = Flask(__name__)
    flask_app.config.from_object(TestingConfig)
    TestingConfig.init_app(flask_app)

    assert flask_app.config["DEMO_ACCESS_USERNAME"] == "interview-guest"
    assert flask_app.config["DEMO_ACCESS_PASSWORD"] == configured_password
    assert flask_app.config["DEMO_ACCESS_CONFIGURED"] is is_configured
    assert flask_app.config["DEMO_LOGIN_MAX_ATTEMPTS"] == 7
    assert flask_app.config["DEMO_LOGIN_LOCKOUT_SECONDS"] == 42


def test_demo_login_limits_from_environment_are_capped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.config import TestingConfig

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "capped-demo.sqlite3"))
    monkeypatch.setenv("DEMO_ACCESS_PASSWORD", DEMO_ACCESS_PASSWORD)
    monkeypatch.setenv("DEMO_LOGIN_MAX_ATTEMPTS", "1000")
    monkeypatch.setenv("DEMO_LOGIN_LOCKOUT_SECONDS", "999999")

    flask_app = Flask(__name__)
    flask_app.config.from_object(TestingConfig)
    TestingConfig.init_app(flask_app)

    assert flask_app.config["DEMO_LOGIN_MAX_ATTEMPTS"] == 100
    assert flask_app.config["DEMO_LOGIN_LOCKOUT_SECONDS"] == 86400


@pytest.fixture
def demo_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    database = tmp_path / "demo.sqlite3"
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(database))
    monkeypatch.delenv("DEMO_ACCESS_USERNAME", raising=False)
    monkeypatch.setenv("DEMO_ACCESS_PASSWORD", DEMO_ACCESS_PASSWORD)
    monkeypatch.delenv("DEMO_LOGIN_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("DEMO_LOGIN_LOCKOUT_SECONDS", raising=False)
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
    assert flask_app.config["DEMO_ACCESS_USERNAME"] == "demo"
    assert flask_app.config["DEMO_ACCESS_PASSWORD"] == DEMO_ACCESS_PASSWORD
    assert flask_app.config["DEMO_ACCESS_CONFIGURED"] is True
    assert flask_app.config["DEMO_LOGIN_MAX_ATTEMPTS"] == 5
    assert flask_app.config["DEMO_LOGIN_LOCKOUT_SECONDS"] == 300
    assert flask_app.config["DEMO_ACCESS_SESSION_MARKER"]
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


@pytest.mark.parametrize("configured_password", [None, "too-short"])
def test_demo_access_fails_closed_when_password_is_unavailable(
    demo_app: Flask,
    configured_password: str | None,
) -> None:
    from app.models.user import User

    demo_app.config["DEMO_ACCESS_PASSWORD"] = configured_password
    demo_app.config["DEMO_ACCESS_CONFIGURED"] = False
    client = demo_app.test_client()

    page = client.get("/auth/login")
    response = _enter_demo(client, password="attacker-supplied-password")

    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "no-store"
    assert "demo-config-warning" in page.get_data(as_text=True)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert "attacker-supplied-password" not in response.get_data(as_text=True)
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
        assert browser_session["demo_login_nonce"]
    with demo_app.app_context():
        assert User.query.count() == 0


def test_demo_access_rejects_oversized_login_requests_before_form_parsing(
    demo_app: Flask,
) -> None:
    from app.models.user import User

    client = demo_app.test_client()
    client.get("/auth/login")

    response = client.post(
        "/auth/demo",
        data=b"x" * (8 * 1024 + 1),
        content_type="application/x-www-form-urlencoded",
    )

    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
    with demo_app.app_context():
        assert User.query.count() == 0


def test_demo_access_caps_chunked_requests_without_a_content_length(
    demo_app: Flask,
) -> None:
    client = demo_app.test_client()
    client.get("/auth/login")

    builder = EnvironBuilder(
        path="/auth/demo",
        method="POST",
        input_stream=BytesIO(b"x" * (8 * 1024 + 1)),
        content_type="application/x-www-form-urlencoded",
    )
    environ = builder.get_environ()
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True
    response = client.open(environ)

    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session


def test_demo_access_handles_non_ascii_nonce_and_credentials_as_failures(
    demo_app: Flask,
) -> None:
    client = demo_app.test_client()
    client.get("/auth/login")

    invalid_nonce = client.post(
        "/auth/demo",
        data={
            "demo_login_nonce": "无效令牌",
            "username": "demo",
            "password": DEMO_ACCESS_PASSWORD,
        },
    )
    invalid_credentials = _enter_demo(
        client,
        username="访客",
        password="错误的演示访问密码",
    )

    assert invalid_nonce.status_code == 400
    assert invalid_nonce.headers["Cache-Control"] == "no-store"
    assert invalid_credentials.status_code == 401
    assert invalid_credentials.headers["Cache-Control"] == "no-store"


def test_demo_access_rejects_either_incorrect_credential_with_one_response(
    demo_app: Flask,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.models.user import User

    normalized_bodies: list[str] = []
    for username, password, private_value in [
        ("unknown-demo-user", DEMO_ACCESS_PASSWORD, "unknown-demo-user"),
        ("demo", "incorrect-demo-password", "incorrect-demo-password"),
    ]:
        client = demo_app.test_client()
        client.get("/auth/login")
        with client.session_transaction() as browser_session:
            original_nonce = browser_session["demo_login_nonce"]

        response = client.post(
            "/auth/demo",
            data={
                "demo_login_nonce": original_nonce,
                "username": username,
                "password": password,
            },
        )

        assert response.status_code == 401
        assert response.headers["Cache-Control"] == "no-store"
        body = response.get_data(as_text=True)
        assert private_value not in body
        assert private_value not in caplog.text
        normalized_bodies.append(
            re.sub(
                r'name="demo_login_nonce" value="[^"]+"',
                'name="demo_login_nonce" value="<rotated>"',
                body,
            )
        )
        with client.session_transaction() as browser_session:
            assert "_user_id" not in browser_session
            replacement_nonce = browser_session["demo_login_nonce"]
        assert replacement_nonce != original_nonce
        replay = client.post(
            "/auth/demo",
            data={
                "demo_login_nonce": original_nonce,
                "username": "demo",
                "password": DEMO_ACCESS_PASSWORD,
            },
        )
        assert replay.status_code == 400
        assert replay.headers["Cache-Control"] == "no-store"
        with client.session_transaction() as browser_session:
            assert browser_session["demo_login_nonce"] != replacement_nonce

    assert normalized_bodies[0] == normalized_bodies[1]
    with demo_app.app_context():
        assert User.query.count() == 0


def test_demo_access_uses_the_configured_username(demo_app: Flask) -> None:
    demo_app.config["DEMO_ACCESS_USERNAME"] = "interview-guest"
    client = demo_app.test_client()

    default_username = _enter_demo(client)
    configured_username = _enter_demo(client, username="interview-guest")

    assert default_username.status_code == 401
    assert configured_username.status_code == 302
    with client.session_transaction() as browser_session:
        assert "demo_login_failures" not in browser_session


def test_demo_access_locks_the_session_after_the_configured_failure_limit(
    demo_app: Flask,
) -> None:
    from app.models.user import User

    demo_app.config.update(
        DEMO_LOGIN_MAX_ATTEMPTS=3,
        DEMO_LOGIN_LOCKOUT_SECONDS=120,
    )
    client = demo_app.test_client()

    first = _enter_demo(client, password="incorrect-demo-password")
    second = _enter_demo(client, username="unknown-demo-user")
    locked = _enter_demo(client, password="incorrect-demo-password")

    assert first.status_code == 401
    assert second.status_code == 401
    assert locked.status_code == 429
    assert locked.headers["Cache-Control"] == "no-store"
    assert locked.headers["Retry-After"] in {"119", "120"}
    assert "incorrect-demo-password" not in locked.get_data(as_text=True)

    still_locked = _enter_demo(client)
    assert still_locked.status_code == 429
    assert still_locked.headers["Cache-Control"] == "no-store"
    assert still_locked.headers["Retry-After"] in {"119", "120"}
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
        assert browser_session["demo_login_nonce"]
    with demo_app.app_context():
        assert User.query.count() == 0


def test_demo_lockout_sanitizes_session_state_and_caps_runtime_limits(
    demo_app: Flask,
) -> None:
    demo_app.config.update(
        DEMO_LOGIN_MAX_ATTEMPTS=1,
        DEMO_LOGIN_LOCKOUT_SECONDS=10**400,
    )
    client = demo_app.test_client()
    client.get("/auth/login")
    with client.session_transaction() as browser_session:
        browser_session["demo_login_failures"] = -10
        browser_session["demo_login_locked_until"] = float("inf")

    response = _enter_demo(client, password="incorrect-demo-password")

    assert response.status_code == 429
    assert response.headers["Retry-After"] in {"86399", "86400"}
    with client.session_transaction() as browser_session:
        assert browser_session["demo_login_failures"] == 1
        assert browser_session["demo_login_locked_until"] != float("inf")


def test_demo_entry_creates_and_reuses_an_approved_anonymous_user(demo_app: Flask) -> None:
    from app import db
    from app.models.user import User

    client = demo_app.test_client()
    page = client.get("/auth/login")

    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "no-store"
    html = page.get_data(as_text=True)
    assert "登录 PPT 翻译工作台" in html
    assert 'action="/auth/demo"' in html
    assert 'href="/auth/sso/login"' not in html

    with client.session_transaction() as browser_session:
        nonce = browser_session["demo_login_nonce"]
    failed_entry = client.post(
        "/auth/demo",
        data={
            "demo_login_nonce": nonce,
            "username": "demo",
            "password": "incorrect-demo-password",
        },
    )
    assert failed_entry.status_code == 401
    with client.session_transaction() as browser_session:
        assert browser_session["demo_login_failures"] == 1
        retry_nonce = browser_session["demo_login_nonce"]

    first_entry = client.post(
        "/auth/demo",
        data={
            "demo_login_nonce": retry_nonce,
            "username": "demo",
            "password": DEMO_ACCESS_PASSWORD,
        },
    )
    assert first_entry.status_code == 302
    assert first_entry.headers["Location"].endswith("/")

    with client.session_transaction() as browser_session:
        first_user_id = browser_session["_user_id"]
        assert browser_session["username"] == "ppt_demo_guest"
        assert browser_session.permanent is False
        assert browser_session["demo_access_session_marker"]
        assert (
            browser_session["demo_access_session_marker"]
            != DEMO_ACCESS_PASSWORD
        )
        assert "demo_login_failures" not in browser_session
        assert "demo_login_locked_until" not in browser_session

    with demo_app.app_context():
        users = User.query.filter_by(username="ppt_demo_guest").all()
        assert len(users) == 1
        user = users[0]
        assert str(user.id) == first_user_id
        assert user.status == "approved"
        assert user.email == "ppt-demo@localhost.invalid"
        assert user.display_name == "PPT User"
        assert user.sso_provider is None
        assert user.sso_subject == "ppt-agent-studio-demo-v1"
        assert user.role is not None and user.role.name == "user"
        assert not user.is_administrator()
        assert user.password
        assert not user.check_password(DEMO_ACCESS_PASSWORD)

    second_entry = _enter_demo(demo_app.test_client())
    assert second_entry.status_code == 302
    with demo_app.app_context():
        assert User.query.filter_by(username="ppt_demo_guest").count() == 1
        db.session.remove()


def test_demo_restart_marker_invalidates_a_previously_authenticated_session(
    demo_app: Flask,
) -> None:
    client = demo_app.test_client()
    assert _enter_demo(client).status_code == 302

    demo_app.config["DEMO_ACCESS_SESSION_MARKER"] = "new-process-marker"
    response = client.get("/")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_demo_session_is_not_started_when_last_login_persistence_fails(
    demo_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import db

    assert _enter_demo(demo_app.test_client()).status_code == 302
    client = demo_app.test_client()

    def fail_commit() -> None:
        raise RuntimeError("simulated database failure")

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(db.session, "commit", fail_commit)
        response = _enter_demo(client)

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
        assert "username" not in browser_session


def test_demo_identity_never_reuses_an_unmarked_account(demo_app: Flask) -> None:
    from app import db
    from app.models.user import User

    with demo_app.app_context():
        user = User.query.filter_by(username="ppt_demo_guest").first()
        assert user is None
        conflicting_user = User(
            username="ppt_demo_guest",
            email="ppt-demo@localhost.invalid",
            status="approved",
        )
        conflicting_user.set_password("private-account-password")
        db.session.add(conflicting_user)
        db.session.commit()

    client = demo_app.test_client()
    response = _enter_demo(client)

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session


def test_demo_identity_rejects_reserved_email_owned_by_another_user(
    demo_app: Flask,
) -> None:
    from app import db
    from app.models.user import User

    with demo_app.app_context():
        conflicting_user = User(
            username="someone-else",
            email="ppt-demo@localhost.invalid",
            status="approved",
        )
        conflicting_user.set_password("private-account-password")
        db.session.add(conflicting_user)
        db.session.commit()

    client = demo_app.test_client()
    response = _enter_demo(client)

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
    with demo_app.app_context():
        assert User.query.filter_by(username="ppt_demo_guest").first() is None


@pytest.mark.parametrize(
    ("status", "role_name"),
    [
        ("disabled", "user"),
        ("rejected", "user"),
        ("approved", "admin"),
    ],
)
def test_demo_identity_rejects_unsafe_status_or_role_without_mutating_it(
    demo_app: Flask,
    status: str,
    role_name: str,
) -> None:
    from app import db
    from app.models.user import Role, User

    with demo_app.app_context():
        role = Role.query.filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db.session.add(role)
            db.session.flush()
        user = User(
            username="ppt_demo_guest",
            email="ppt-demo@localhost.invalid",
            display_name="PPT User",
            sso_subject="ppt-agent-studio-demo-v1",
            status=status,
            role=role,
        )
        user.set_password("unpublished-internal-password")
        db.session.add(user)
        db.session.commit()

    client = demo_app.test_client()
    response = _enter_demo(client)

    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    with client.session_transaction() as browser_session:
        assert "_user_id" not in browser_session
    with demo_app.app_context():
        unchanged = User.query.filter_by(username="ppt_demo_guest").one()
        assert unchanged.status == status
        assert unchanged.role is not None and unchanged.role.name == role_name


def test_demo_entry_safely_creates_the_least_privilege_role_when_missing(
    demo_app: Flask,
) -> None:
    from app import db
    from app.models.user import Role, User

    with demo_app.app_context():
        Role.query.filter_by(name="user").delete()
        db.session.commit()
        assert Role.query.filter_by(name="user").first() is None

    response = _enter_demo(demo_app.test_client())

    assert response.status_code == 302
    with demo_app.app_context():
        assert Role.query.filter_by(name="user").count() == 1
        user = User.query.filter_by(username="ppt_demo_guest").one()
        assert user.role is not None and user.role.name == "user"


def test_demo_mode_closes_regular_registration_and_password_login(
    demo_app: Flask,
) -> None:
    from app.models.user import User

    client = demo_app.test_client()

    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/register").status_code == 404
    assert client.post(
        "/auth/register",
        data={"username": "attacker", "password": "attacker-password"},
    ).status_code == 404
    assert client.post(
        "/auth/login",
        data={"username": "attacker", "password": "attacker-password"},
    ).status_code == 404
    with demo_app.app_context():
        assert User.query.count() == 0


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
