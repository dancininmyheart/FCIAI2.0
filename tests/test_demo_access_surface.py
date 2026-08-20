from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flask import Flask
from flask_login import UserMixin
import pytest


class _AuthenticatedUser(UserMixin):
    id = 42
    username = "demo-test-user"

    def is_administrator(self) -> bool:
        return False


class _FakeColumn:
    def __eq__(self, other: object) -> tuple[str, object]:
        return ("eq", other)

    def desc(self) -> "_FakeColumn":
        return self


class _EmptyTranslationQuery:
    def filter(self, *criteria: object) -> "_EmptyTranslationQuery":
        return self

    def filter_by(self, **criteria: object) -> "_EmptyTranslationQuery":
        return self

    def order_by(self, *columns: object) -> "_EmptyTranslationQuery":
        return self

    def paginate(self, **options: object) -> SimpleNamespace:
        return SimpleNamespace(items=[], pages=0, page=1, total=0)


class _EmptyTranslation:
    id = _FakeColumn()
    user_id = _FakeColumn()
    is_public = _FakeColumn()
    query = _EmptyTranslationQuery()


def _request_ppt_surface(client: Any, method: str, path: str):
    data = None
    if method == "POST":
        data = {"file": (BytesIO(b"pptx"), "demo.pptx")}
    return client.open(path, method=method, data=data)


def _authenticate_test_client(
    app: Flask,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    verified_demo_access: bool = True,
) -> None:
    from app.demo_access import DEMO_ACCESS_SESSION_KEY

    login_manager = app.login_manager
    user = _AuthenticatedUser()
    marker = "demo-access-surface-test-marker"
    app.config["DEMO_ACCESS_SESSION_MARKER"] = marker
    monkeypatch.setattr(login_manager, "_user_callback", lambda user_id: user)
    with client.session_transaction() as browser_session:
        browser_session["_user_id"] = user.get_id()
        browser_session["_fresh"] = True
        if verified_demo_access:
            browser_session[DEMO_ACCESS_SESSION_KEY] = marker


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/start_translation"),
        ("POST", "/ppt_translate"),
        ("GET", "/task_status/missing-task"),
        ("GET", "/download/missing-task"),
        ("GET", "/api/translations"),
    ],
)
def test_demo_ppt_surface_requires_real_auth_before_work_even_if_login_is_disabled(
    isolated_app: Flask,
    tmp_path: Path,
    method: str,
    path: str,
) -> None:
    upload_dir = tmp_path / "isolated-uploads"
    isolated_app.config.update(
        DEMO_MODE=True,
        LOGIN_DISABLED=True,
        UPLOAD_FOLDER=str(upload_dir),
    )
    temp_upload_dir = upload_dir / "temp"
    assert not temp_upload_dir.exists()

    response = _request_ppt_surface(isolated_app.test_client(), method, path)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    assert not temp_upload_dir.exists()


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("POST", "/start_translation", 400),
        ("POST", "/ppt_translate", 400),
        ("GET", "/task_status/missing-task", 404),
        ("GET", "/download/missing-task", 404),
        ("GET", "/api/translations", 200),
    ],
)
def test_authenticated_demo_user_reaches_underlying_ppt_validation(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    expected_status: int,
) -> None:
    import app.views.main as main_views

    isolated_app.config["DEMO_MODE"] = True
    client = isolated_app.test_client()
    _authenticate_test_client(isolated_app, client, monkeypatch)
    if path == "/api/translations":
        monkeypatch.setattr(main_views, "Translation", _EmptyTranslation)

    response = client.open(path, method=method)

    assert response.status_code == expected_status
    if path == "/api/translations":
        assert response.get_json() == {
            "translations": [],
            "total_pages": 0,
            "current_page": 1,
            "total_items": 0,
        }


@pytest.mark.parametrize("stale_marker", [None, "previous-process-marker"])
def test_demo_surface_rejects_authenticated_sessions_that_did_not_pass_current_gate(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    stale_marker: str | None,
) -> None:
    from app.demo_access import DEMO_ACCESS_SESSION_KEY

    isolated_app.config["DEMO_MODE"] = True
    client = isolated_app.test_client()
    _authenticate_test_client(
        isolated_app,
        client,
        monkeypatch,
        verified_demo_access=False,
    )
    if stale_marker is not None:
        with client.session_transaction() as browser_session:
            browser_session[DEMO_ACCESS_SESSION_KEY] = stale_marker

    response = client.get("/")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("POST", "/start_translation", 400),
        ("POST", "/ppt_translate", 400),
        ("GET", "/task_status/missing-task", 404),
        ("GET", "/download/missing-task", 404),
        ("GET", "/api/translations", 302),
    ],
)
def test_non_demo_ppt_compatibility_behavior_is_unchanged(
    isolated_app: Flask,
    method: str,
    path: str,
    expected_status: int,
) -> None:
    isolated_app.config["DEMO_MODE"] = False

    response = isolated_app.test_client().open(path, method=method)

    assert response.status_code == expected_status


def test_demo_mode_hard_closes_every_sso_route_before_sso_side_effects(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.views.sso_auth as sso_auth

    isolated_app.config.update(DEMO_MODE=True, ENV="development")
    calls: list[str] = []

    def unexpected_sso_call(*args: object, **kwargs: object) -> None:
        calls.append("sso")
        pytest.fail("demo request reached an SSO dependency")

    monkeypatch.setattr(sso_auth, "get_sso_service", unexpected_sso_call)
    monkeypatch.setattr(
        sso_auth.sso_user_manager,
        "authenticate_sso_user",
        unexpected_sso_call,
    )
    sso_routes = sorted(
        (method, rule.rule)
        for rule in isolated_app.url_map.iter_rules()
        if rule.endpoint.startswith("sso.")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    )
    assert ("GET", "/auth/sso/dev-callback") in sso_routes

    responses = [
        (method, path, isolated_app.test_client().open(path, method=method))
        for method, path in sso_routes
    ]

    assert responses
    assert all(response.status_code == 404 for _, _, response in responses)
    assert calls == []


def test_non_demo_sso_status_behavior_is_unchanged(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.views.sso_auth as sso_auth

    class FakeSsoService:
        providers = {"oauth2": object()}

        def is_enabled(self) -> bool:
            return True

    isolated_app.config.update(
        DEMO_MODE=False,
        SSO_PROVIDER="oauth2",
        SSO_AUTO_CREATE_USER=True,
    )
    monkeypatch.setattr(sso_auth, "get_sso_service", FakeSsoService)

    response = isolated_app.test_client().get("/auth/sso/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "enabled": True,
        "provider": "oauth2",
        "auto_create_user": True,
        "providers": ["oauth2"],
    }
