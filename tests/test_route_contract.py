from __future__ import annotations

from io import BytesIO
import json
import re
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest


CONTRACT_PATH = Path("tests/contracts/routes.json")
JsonScalar = str | int | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def route_snapshot(app: Flask) -> list[dict[str, list[str] | str]]:
    ignored = {"HEAD", "OPTIONS"}
    return sorted(
        (
            {
                "rule": rule.rule,
                "endpoint": rule.endpoint,
                "methods": sorted(method for method in rule.methods if method not in ignored),
            }
            for rule in app.url_map.iter_rules()
            if rule.endpoint != "static"
        ),
        key=lambda item: (str(item["rule"]), str(item["endpoint"])),
    )


def load_contract(path: Path = CONTRACT_PATH) -> list[dict[str, list[str] | str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["routes"]


def behavior_contract() -> dict[str, JsonValue]:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return raw["behavior"]


def test_route_contract_matches_current_app(isolated_app: Flask) -> None:
    # Given
    expected = load_contract()

    # When
    actual = route_snapshot(isolated_app)

    # Then
    assert actual == expected


def test_route_manifest_is_sorted_and_unique() -> None:
    # Given
    routes = load_contract()

    # When
    keys = [(route["rule"], route["endpoint"]) for route in routes]

    # Then
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))


def test_translation_contract_routes_and_methods_are_frozen() -> None:
    # Given
    routes = {(route["rule"], tuple(route["methods"])): route["endpoint"] for route in load_contract()}

    # Then
    assert routes[("/upload", ("POST",))] == "main.upload_file"
    assert routes[("/task_status", ("GET",))] == "main.get_task_status"
    assert routes[("/start_translation", ("POST",))] == "main.start_translation"
    assert routes[("/task_status/<task_id>", ("GET",))] == "main.get_simple_task_status"
    assert routes[("/download/<task_id>", ("GET",))] == "main.download_simple_translated_file"
    assert routes[("/api/ppt_translation_history", ("GET",))] == "main.ppt_translation_history"
    assert routes[("/api/translations", ("GET",))] == "main.get_translations"
    assert routes[("/auth/login", ("GET", "POST"))] == "auth.login"


def test_route_contract_includes_required_behavior_surfaces() -> None:
    # Given
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    # When
    behavior = raw.get("behavior", {})

    # Then
    assert behavior["auth"]["login"]["public"] is True
    assert behavior["ppt"]["start"]["task_identifier"] == "task_id"
    assert behavior["ppt"]["start"]["modes"] == ["translation_only", "paragraph_up", "paragraph_down"]
    assert behavior["ppt"]["start"]["selected_pages_field"] == "select_page"
    assert behavior["ppt"]["download"]["name_prefix"] == "translated_"
    assert set(behavior) == {"auth", "ppt"}


def test_route_contract_excludes_removed_product_surfaces() -> None:
    # Given
    routes = {route["rule"] for route in load_contract()}

    # Then
    assert routes.isdisjoint(
        {
            "/pdf_translate",
            "/api/start_pdf_translation",
            "/translate_pdf",
            "/ingredient",
            "/ingredient/upload",
            "/dictionary",
            "/registration_approval",
            "/user_management",
            "/file_management",
            "/logs",
            "/system_monitoring",
        }
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/pdf_translate"),
        ("GET", "/api/pdf_task_status"),
        ("POST", "/api/start_pdf_translation"),
        ("POST", "/translate_pdf"),
        ("GET", "/download_translated_pdf/missing.docx"),
        ("GET", "/ingredient"),
        ("GET", "/ingredient/api/ingredient/search"),
        ("GET", "/dictionary"),
        ("GET", "/user_management"),
        ("GET", "/logs"),
        ("GET", "/api/translation/health"),
        ("GET", "/cancel_task/task_missing"),
        ("GET", "/get_queue_status"),
    ],
)
def test_removed_business_routes_return_not_found(
    isolated_app: Flask,
    method: str,
    path: str,
) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.open(path, method=method)

    # Then
    assert response.status_code == 404


def test_ppt_vocabulary_route_is_read_only(isolated_app: Flask) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.post("/api/translations")

    # Then
    assert response.status_code == 405


def test_upload_requires_authentication(isolated_app: Flask) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.post("/upload")

    # Then
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_ppt_upload_rejects_invalid_translation_mode_before_creating_task(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    import app.views.main as main_views

    class FakeUploadRecord:
        def __init__(self, **kwargs) -> None:
            self.id = 321

    task_calls: list[dict] = []
    fake_session = SimpleNamespace(
        add=lambda record: None,
        commit=lambda: None,
        rollback=lambda: None,
        remove=lambda: None,
    )
    isolated_app.config.update(LOGIN_DISABLED=True, TRANSLATION_ARCH_MODE="legacy")
    monkeypatch.delenv("TRANSLATION_ARCH_MODE", raising=False)
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(id=42, username="tester", is_authenticated=True))
    monkeypatch.setattr(main_views, "UploadRecord", FakeUploadRecord)
    monkeypatch.setattr(main_views.db, "session", fake_session)
    monkeypatch.setattr(main_views.translation_queue, "add_task", lambda **kwargs: task_calls.append(kwargs))
    client = isolated_app.test_client()

    # When
    response = client.post(
        "/upload",
        data={
            "file": (BytesIO(b"pptx"), "demo.pptx"),
            "bilingual_translation": "keep_both",
        },
    )

    # Then
    assert response.status_code == 400
    assert response.get_json()["code"] == 400
    assert task_calls == []


@pytest.mark.parametrize("selected_pages", ["35,", "last", "0", "-1"])
def test_authenticated_ppt_upload_rejects_invalid_page_selection_instead_of_translating_all(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    selected_pages: str,
) -> None:
    # Given
    import app.views.main as main_views

    task_calls: list[dict] = []
    isolated_app.config.update(LOGIN_DISABLED=True, TRANSLATION_ARCH_MODE="legacy")
    monkeypatch.delenv("TRANSLATION_ARCH_MODE", raising=False)
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(id=42, username="tester", is_authenticated=True))
    monkeypatch.setattr(main_views.translation_queue, "add_task", lambda **kwargs: task_calls.append(kwargs))
    client = isolated_app.test_client()

    # When
    response = client.post(
        "/upload",
        data={
            "file": (BytesIO(b"pptx"), "demo.pptx"),
            "select_page": selected_pages,
        },
    )

    # Then
    assert response.status_code == 400
    assert response.get_json()["code"] == 400
    assert task_calls == []


def test_auth_login_public_status_and_failed_post_match_contract(isolated_app: Flask) -> None:
    # Given
    contract = behavior_contract()["auth"]["login"]
    client = isolated_app.test_client()

    # When
    get_response = client.get("/auth/login")
    post_response = client.post("/auth/login", data={"password": "wrong"})

    # Then
    assert get_response.status_code == contract["get_status"]
    assert post_response.status_code == contract["failed_post_status"]
    assert contract["failed_post_location_contains"] in post_response.headers["Location"]


def test_public_ppt_start_status_and_download_match_contract(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    contract = behavior_contract()["ppt"]
    import app.views.main as main_views

    class FakeThread:
        daemon = False

        def __init__(self, target, args) -> None:
            self.target = target
            self.args = args

        def start(self) -> None:
            return None

    monkeypatch.setattr(main_views.threading, "Thread", FakeThread)
    main_views.simple_task_status.clear()
    main_views.simple_task_files.clear()
    (Path(isolated_app.config["UPLOAD_FOLDER"]) / "temp").mkdir(parents=True)
    client = isolated_app.test_client()

    # When
    missing_start = client.post("/start_translation")
    start_response = client.post("/start_translation", data={"file": (BytesIO(b"pptx"), "deck.pptx")})
    task_id = start_response.get_json()[contract["start"]["task_identifier"]]
    missing_status = client.get("/task_status/missing")
    known_status = client.get(f"/task_status/{task_id}")
    not_complete = client.get(f"/download/{task_id}")
    output = tmp_path / "deck.pptx"
    output.write_bytes(b"translated")
    main_views.simple_task_status[task_id]["status"] = "completed"
    main_views.simple_task_files[task_id] = str(output)
    download = client.get(f"/download/{task_id}")

    # Then
    assert missing_start.status_code == contract["start"]["missing_file_status"]
    assert start_response.status_code == contract["start"]["success_status"]
    assert sorted(start_response.get_json()) == sorted(contract["start"]["success_fields"])
    assert missing_status.status_code == contract["status"]["missing_status"]
    assert sorted(missing_status.get_json()) == sorted(contract["status"]["missing_fields"])
    assert sorted(known_status.get_json()) == sorted(contract["status"]["known_fields"])
    assert not_complete.status_code == contract["download"]["not_complete_status"]
    assert download.status_code == contract["download"]["success_status"]
    assert contract["download"]["mimetype"] in download.headers["Content-Type"]
    assert f'{contract["download"]["name_prefix"]}deck.pptx' in download.headers["Content-Disposition"]


def test_authenticated_ppt_upload_pins_options_response_fields_and_queue_payload(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    contract = behavior_contract()["ppt"]["authenticated_upload"]
    options = contract["task_options"]
    import app.views.main as main_views

    class FakeUploadRecord:
        def __init__(self, **kwargs) -> None:
            self.id = 321
            self.kwargs = kwargs

    captured: dict[str, dict] = {}
    fake_session = SimpleNamespace(add=lambda record: None, commit=lambda: None, rollback=lambda: None, remove=lambda: None)

    def add_task(**kwargs) -> int:
        captured["queue"] = kwargs
        return 7

    isolated_app.config.update(LOGIN_DISABLED=True, TRANSLATION_ARCH_MODE="legacy")
    monkeypatch.delenv("TRANSLATION_ARCH_MODE", raising=False)
    (Path(isolated_app.config["UPLOAD_FOLDER"]) / "user_42").mkdir(parents=True)
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(id=42, username="tester", is_authenticated=True))
    monkeypatch.setattr(main_views, "UploadRecord", FakeUploadRecord)
    monkeypatch.setattr(main_views.db, "session", fake_session)
    monkeypatch.setattr(main_views.translation_queue, "add_task", add_task)
    client = isolated_app.test_client()

    # When
    response = client.post(
        contract["rule"],
        data={
            "file": (BytesIO(b"pptx"), "demo.pptx"),
            "source_language": "English",
            "target_language": "Chinese",
            options["mode_field"]: "paragraph_down",
            options["selected_pages_field"]: options["selected_pages_value"],
            options["model_field"]: "deepseek",
            options["text_splitting_field"]: "True_spliting",
            options["uno_conversion_field"]: "false",
        },
    )

    # Then
    assert response.status_code == contract["success_status"]
    assert sorted(response.get_json()) == sorted(contract["success_fields"])
    assert response.get_json()["bilingual_translation"] == "paragraph_down"
    assert captured["queue"]["bilingual_translation"] == "paragraph_down"
    assert captured["queue"]["select_page"] == options["selected_pages_parsed"]
    assert captured["queue"]["model"] in options["models"]
    assert captured["queue"]["model"] == "deepseek"
    assert captured["queue"]["enable_text_splitting"] == "True_spliting"
    assert captured["queue"]["enable_uno_conversion"] is False


def test_authenticated_ppt_upload_v2_response_echoes_accepted_translation_mode(
    isolated_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    import app.views.main as main_views

    class FakeUploadRecord:
        def __init__(self, **kwargs) -> None:
            self.id = 321

    captured: dict[str, str] = {}
    fake_session = SimpleNamespace(
        add=lambda record: None,
        commit=lambda: None,
        rollback=lambda: None,
        remove=lambda: None,
    )

    def create_ledger_job(
        user_id,
        file_path,
        source_language,
        target_language,
        model,
        selected_pages,
        bilingual_translation,
        enable_text_splitting,
        enable_uno_conversion,
        custom_translations,
        original_filename,
        upload_record_id,
    ):
        captured["bilingual_translation"] = bilingual_translation
        captured["upload_record_id"] = upload_record_id
        return SimpleNamespace(public_id="ppt-task-123")

    isolated_app.config.update(LOGIN_DISABLED=True, TRANSLATION_ARCH_MODE="v2")
    monkeypatch.delenv("TRANSLATION_ARCH_MODE", raising=False)
    (Path(isolated_app.config["UPLOAD_FOLDER"]) / "user_42").mkdir(parents=True)
    monkeypatch.setattr(main_views, "current_user", SimpleNamespace(id=42, username="tester", is_authenticated=True))
    monkeypatch.setattr(main_views, "UploadRecord", FakeUploadRecord)
    monkeypatch.setattr(main_views.db, "session", fake_session)
    monkeypatch.setattr(main_views, "_create_ppt_ledger_job", create_ledger_job)
    monkeypatch.setattr(
        main_views.translation_queue,
        "add_task",
        lambda **kwargs: pytest.fail("v2 upload must not enqueue a legacy task"),
    )
    client = isolated_app.test_client()

    # When
    response = client.post(
        "/upload",
        data={
            "file": (BytesIO(b"pptx"), "demo.pptx"),
            "bilingual_translation": "paragraph_up",
        },
    )

    # Then
    assert response.status_code == 200
    assert response.get_json()["task_id"] == "ppt-task-123"
    assert response.get_json()["bilingual_translation"] == "paragraph_up"
    assert captured["bilingual_translation"] == "paragraph_up"
    assert captured["upload_record_id"] == 321


def test_templates_supplement_behavior_contract_with_current_model_values() -> None:
    # Given
    index_html = Path("app/templates/main/index.html").read_text(encoding="utf-8")
    contract = behavior_contract()

    # When
    ppt_models = set(re.findall(r'<option value="([^"]+)">(?:Qwen 3.7 Plus|DeepSeek-Chat)', index_html))

    # Then
    assert set(contract["ppt"]["authenticated_upload"]["task_options"]["models"]) == ppt_models


def test_ppt_only_templates_remove_brand_logo_and_other_product_navigation() -> None:
    # Given
    layout = Path("app/templates/main/base_layout.html").read_text(encoding="utf-8")
    auth_base = Path("app/templates/base.html").read_text(encoding="utf-8")
    login = Path("app/templates/auth/login.html").read_text(encoding="utf-8")

    # Then
    assert "logo.svg" not in layout
    assert "logo.svg" not in auth_base
    assert "company-logo" not in login.lower()
    for endpoint in (
        "main.pdf_translate",
        "main.dictionary",
        "main.ingredient",
        "main.registration_approval",
        "main.user_management",
        "main.file_management",
        "main.logs",
    ):
        assert endpoint not in layout


def test_route_contract_rejects_temp_manifest_mutation(tmp_path: Path, isolated_app: Flask) -> None:
    # Given
    mutated = tmp_path / "routes.json"
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    raw["routes"][0]["rule"] = "/mutated"
    mutated.write_text(json.dumps(raw), encoding="utf-8")

    # When
    expected = load_contract(mutated)
    actual = route_snapshot(isolated_app)

    # Then
    assert actual != expected
