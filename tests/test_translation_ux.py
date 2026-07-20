from __future__ import annotations

from pathlib import Path

from flask import Flask, render_template


ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "app" / "templates" / "main" / "base_layout.html"
PPT_TEMPLATE = ROOT / "app" / "templates" / "main" / "index.html"
PDF_TEMPLATE = ROOT / "app" / "templates" / "main" / "pdf_translate.html"
EXPERIENCE_CSS = ROOT / "app" / "static" / "css" / "experience.css"
MAIN_JS = ROOT / "app" / "static" / "js" / "main.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_application_shell_is_zoomable_and_keyboard_navigable() -> None:
    template = _read(BASE_TEMPLATE)

    assert 'content="width=device-width, initial-scale=1.0"' in template
    assert "user-scalable=no" not in template
    assert "maximum-scale" not in template
    assert 'class="skip-link"' in template
    assert 'id="mobileMenuBtn"' in template
    assert 'id="primaryNavigation"' in template
    assert 'id="main-content"' in template
    assert 'aria-live="polite"' in template
    assert "css/experience.css" in template
    assert "url_for('main.user_management')" in template


def test_translation_uploads_and_history_expose_accessible_states() -> None:
    ppt = _read(PPT_TEMPLATE)
    pdf = _read(PDF_TEMPLATE)

    assert 'id="dropZone" role="button" tabindex="0"' in ppt
    assert 'id="pptUploadProgressbar" role="progressbar"' in ppt
    assert 'class="history-table-wrap" tabindex="0" role="region"' in ppt
    assert 'class="history-loading-state"' in ppt
    assert 'id="pptResultContainer"' in ppt

    assert 'id="pdfUploadZone" role="button" tabindex="0"' in pdf
    assert 'id="pdfUploadStatus" role="status" aria-live="polite"' in pdf
    assert 'class="table-responsive" tabindex="0" role="region"' in pdf
    assert 'class="history-loading-state"' in pdf
    assert 'id="pdfResultContainer"' in pdf


def test_translation_feedback_does_not_use_blocking_alerts() -> None:
    assert "alert(" not in _read(PPT_TEMPLATE)
    assert "alert(" not in _read(PDF_TEMPLATE)

    main_js = _read(MAIN_JS)
    assert "aria-atomic" in main_js
    assert "toast-close" in main_js


def test_ppt_translation_switches_from_page_selection_to_upload_feedback_immediately() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    end = template.index("function checkTaskStatus()", start)
    launch_flow = template[start:end]

    hide_selector = launch_flow.index("pageSelector.style.display = 'none';")
    send_upload = launch_flow.index("xhr.send(formData);")
    error_handler = launch_flow.index("} catch (error) {")

    assert "let isTranslationLaunching = false;" in template
    assert "if (isTranslationLaunching) return;" in launch_flow
    assert hide_selector < send_upload
    assert "startButton.disabled = true;" in launch_flow[:send_upload]
    assert "if (resultContainer) resultContainer.hidden = true;" in launch_flow[:send_upload]
    assert "pageSelector.style.display = 'block';" in launch_flow[error_handler:]
    assert "updateStartButton();" in launch_flow[error_handler:]


def test_ppt_translation_submits_current_language_display_selection() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    end = template.index("function checkTaskStatus()", start)
    launch_flow = template[start:end]

    assert "const bilingualTranslation = document.getElementById('bilingual_translation').value;" in launch_flow
    assert "formData.append('bilingual_translation', bilingualTranslation);" in launch_flow


def test_ppt_translation_defaults_to_source_first_bilingual_display() -> None:
    template = _read(PPT_TEMPLATE)
    select_start = template.index('<select id="bilingual_translation"')
    select_end = template.index("</select>", select_start)
    language_display = template[select_start:select_end]

    assert 'name="bilingual_translation"' in language_display
    assert '<option value="paragraph_up" selected>' in language_display
    assert '<option value="translation_only" selected>' not in language_display


def test_ppt_translation_rejects_a_server_display_mode_mismatch() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    end = template.index("function checkTaskStatus()", start)
    launch_flow = template[start:end]

    upload_response = launch_flow.index("const result = await new Promise")
    validate_mode = launch_flow.index(
        "if (result.bilingual_translation !== bilingualTranslation)"
    )
    mark_complete = launch_flow.index("markUploadCompleted();")

    assert upload_response < validate_mode < mark_complete
    assert "throw new Error(getText('translationModeMismatch'));" in launch_flow
    assert "translationModeMismatch:" in template


def test_ppt_translation_polls_the_uploaded_task_without_losing_legacy_status() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    status_start = template.index("function checkTaskStatus()", start)
    launch_flow = template[start:status_start]
    status_flow = template[status_start:]

    assert "let currentTaskId = null;" in template[:start]
    assert "currentTaskId = result.task_id || null;" in launch_flow
    assert (
        "const statusUrl = currentTaskId\n"
        "            ? `/task_status/${encodeURIComponent(currentTaskId)}`\n"
        "            : '/task_status';"
    ) in status_flow
    assert "fetch(statusUrl)" in status_flow


def test_experience_styles_define_responsive_drawer_and_readable_type() -> None:
    css = _read(EXPERIENCE_CSS)

    assert "--ux-sidebar-width: 240px" in css
    assert "@media (max-width: 900px)" in css
    assert ".nav-menu.is-open" in css
    assert "margin-left: 0 !important" in css
    assert "font-size: 15px !important" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_ppt_history_keeps_download_actions_visible() -> None:
    template = _read(PPT_TEMPLATE)
    css = _read(EXPERIENCE_CSS)

    assert 'class="history-actions"' in template
    assert 'class="history-mobile-meta"' in template
    assert ".history-table th:last-child" in css
    assert ".history-table td:last-child" in css
    assert "min-width: 620px" in css
    assert "table-layout: fixed !important" in css
    assert "position: sticky" in css
    assert "right: 0" in css
    assert ".history-mobile-meta" in css


def test_translation_templates_render_with_the_application_routes(isolated_app: Flask) -> None:
    with isolated_app.test_request_context("/"):
        ppt = render_template("main/index.html")
        pdf = render_template("main/pdf_translate.html")

    assert 'aria-current="page"' in ppt
    assert 'id="dropZone"' in ppt
    assert 'id="pdfUploadZone"' in pdf


def test_login_template_exposes_local_credentials_and_keeps_sso(isolated_app: Flask) -> None:
    # Given
    with isolated_app.test_request_context("/auth/login"):
        # When
        login = render_template("auth/login.html", sso_enabled=True, sso_provider="oauth2")

    # Then
    assert '<form class="login-form" method="post" action="/auth/login">' in login
    assert 'name="username"' in login
    assert 'autocomplete="username"' in login
    assert 'name="password"' in login
    assert 'autocomplete="current-password"' in login
    assert "账号密码登录" in login
    assert 'href="/auth/sso/login"' in login
    assert 'rel="icon" href="/static/images/logo.svg"' in login


def test_login_template_uses_local_credentials_when_sso_is_unavailable(isolated_app: Flask) -> None:
    with isolated_app.test_request_context("/auth/login"):
        login = render_template("auth/login.html", sso_enabled=False, sso_provider="oauth2")

    assert 'href="/auth/sso/login"' not in login
    assert '<form class="login-form" method="post" action="/auth/login">' in login
    assert 'name="username"' in login
    assert 'name="password"' in login
    assert "账号密码登录" in login
