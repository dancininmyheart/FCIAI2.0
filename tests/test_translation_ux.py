from __future__ import annotations

from pathlib import Path

from flask import Flask, render_template


ROOT = Path(__file__).resolve().parents[1]
AUTH_BASE_TEMPLATE = ROOT / "app" / "templates" / "base.html"
BASE_TEMPLATE = ROOT / "app" / "templates" / "main" / "base_layout.html"
PPT_TEMPLATE = ROOT / "app" / "templates" / "main" / "index.html"
BRAND_CSS = ROOT / "app" / "static" / "css" / "brand.css"
AUTH_CSS = ROOT / "app" / "static" / "css" / "style.css"
BASE_STYLES_CSS = ROOT / "app" / "static" / "css" / "styles.css"
EXPERIENCE_CSS = ROOT / "app" / "static" / "css" / "experience.css"
WORKBENCH_CSS = ROOT / "app" / "static" / "css" / "workbench-demo.css"
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
    assert "url_for('main.index')" in template
    assert "url_for('main.user_management')" not in template


def test_frontend_theme_uses_the_anonymous_studio_palette() -> None:
    brand = _read(BRAND_CSS)
    auth = _read(AUTH_CSS)
    base = _read(BASE_STYLES_CSS)
    experience = _read(EXPERIENCE_CSS)

    assert "--brand-sky-blue: #0094d9;" in brand
    assert "--brand-cool-gray: #6e6f72;" in brand
    assert "--brand-milk-white: #ffffff;" in brand
    assert "--brand-readable-gray: #3f4043;" in brand
    assert "--studio-ink-900: #0b1020;" in brand
    assert "--studio-indigo: #635bff;" in brand
    assert "--studio-cyan: #22d3ee;" in brand

    assert "--primary-color: var(--studio-indigo);" in auth
    assert "--background-color: var(--studio-canvas);" in auth
    assert "--text-color: var(--studio-ink-900);" in auth
    assert "--muted-text-color: var(--studio-slate-500);" in auth

    assert "--primary-color: var(--brand-sky-blue);" in base
    assert "--brand-color: var(--brand-sky-blue);" in base
    assert "--text-color: var(--brand-readable-gray);" in base
    assert "--bg-color: var(--brand-milk-white);" in base

    assert "body.studio-app-shell {" in experience
    assert "--ux-page: var(--studio-canvas);" in experience
    assert "--ux-panel: var(--studio-surface);" in experience
    assert "--ux-text: var(--studio-ink-900);" in experience
    assert "--ux-muted: var(--studio-slate-500);" in experience
    assert "--ux-primary: var(--studio-indigo);" in experience
    assert "--ux-brand: var(--studio-cyan-deep);" in experience


def test_brand_stylesheets_have_a_deterministic_cascade_order() -> None:
    auth_template = _read(AUTH_BASE_TEMPLATE)
    main_template = _read(BASE_TEMPLATE)

    assert auth_template.index("css/brand.css") < auth_template.index("css/style.css")

    brand = main_template.index("css/brand.css")
    base = main_template.index("css/styles.css")
    navigation = main_template.index("css/nav.css")
    toast = main_template.index("css/toast.css")
    user_info = main_template.index("css/user-info.css")
    page_styles = main_template.index("{% block styles %}")
    experience = main_template.index("css/experience.css")

    assert brand < base < navigation < toast < user_info < page_styles < experience


def test_ppt_vocabulary_dialog_does_not_use_legacy_bootstrap_blue() -> None:
    assert "#007bff" not in _read(PPT_TEMPLATE).lower()


def test_ppt_workbench_styles_are_externalized() -> None:
    template = _read(PPT_TEMPLATE)
    workbench = _read(WORKBENCH_CSS)

    assert "<style>" not in template
    assert "css/workbench-demo.css" in template
    assert "function openVocabularyConfig()" not in template
    assert ".demo-shell {" in workbench
    assert ".demo-shell > .queue-status {\n    display: none;" in workbench
    assert ".demo-shell .page-selector {\n    position: fixed;\n    z-index: 1500;\n    display: none;" in workbench


def test_ppt_upload_and_history_expose_accessible_states() -> None:
    ppt = _read(PPT_TEMPLATE)

    assert 'id="dropZone" role="button" tabindex="0"' in ppt
    assert 'id="pptUploadProgressbar" role="progressbar"' in ppt
    assert 'class="history-table-wrap" tabindex="0" role="region"' in ppt
    assert 'class="history-loading-state"' in ppt
    assert 'id="pptResultContainer"' in ppt


def test_translation_feedback_does_not_use_blocking_alerts() -> None:
    assert "alert(" not in _read(PPT_TEMPLATE)

    main_js = _read(MAIN_JS)
    assert "aria-atomic" in main_js
    assert "toast-close" in main_js


def test_ppt_translation_switches_from_page_selection_to_upload_feedback_immediately() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    end = template.index("function checkTaskStatus", start)
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
    end = template.index("function checkTaskStatus", start)
    launch_flow = template[start:end]

    assert "const bilingualTranslation = document.getElementById('bilingual_translation').value;" in launch_flow
    assert "formData.append('bilingual_translation', bilingualTranslation);" in launch_flow


def test_ppt_translation_defaults_to_translation_only_display() -> None:
    template = _read(PPT_TEMPLATE)
    select_start = template.index('<select id="bilingual_translation"')
    select_end = template.index("</select>", select_start)
    language_display = template[select_start:select_end]

    assert 'name="bilingual_translation"' in language_display
    assert '<option value="translation_only" selected>' in language_display
    assert '<option value="paragraph_up" selected>' not in language_display


def test_clearing_page_selection_keeps_unselected_page_numbers_readable() -> None:
    workbench = _read(WORKBENCH_CSS)
    page_item_start = workbench.index(".demo-shell .page-item {")
    page_item_end = workbench.index("}", page_item_start)
    unselected_page_style = workbench[page_item_start:page_item_end]

    assert "color: var(--brand-readable-gray);" in unselected_page_style


def test_hovering_a_selected_page_keeps_its_selected_contrast() -> None:
    workbench = _read(WORKBENCH_CSS)

    assert ".demo-shell .page-item:hover:not(.selected)" in workbench


def test_ppt_translation_rejects_a_server_display_mode_mismatch() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    end = template.index("function checkTaskStatus", start)
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
    status_start = template.index("function checkTaskStatus", start)
    launch_flow = template[start:status_start]
    status_flow = template[status_start:]

    assert "let currentTaskId = null;" in template[:start]
    assert "currentTaskId = typeof result.task_id === 'string' && result.task_id.trim()" in launch_flow
    assert (
        "const statusUrl = taskIdAtRequest\n"
        "            ? `/task_status/${encodeURIComponent(taskIdAtRequest)}`\n"
        "            : '/task_status';"
    ) in status_flow
    assert "fetch(statusUrl)" in status_flow


def test_ppt_completion_download_is_bound_to_the_uploaded_task_not_history() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    helper = template.index("function bindCurrentPptDownload()")
    status_start = template.index("function checkTaskStatus", start)
    launch_flow = template[start:status_start]
    status_flow = template[status_start:]

    assert 'id="pptCurrentDownload"' in template
    assert helper < start
    assert 'id="pptCurrentDownload"' in template and "hidden" in template[
        template.index('id="pptCurrentDownload"') : template.index('id="pptCurrentDownload"') + 240
    ]
    assert "let currentRecordId = null;" in template[:start]
    assert "const parsedRecordId = Number(result.record_id);" in launch_flow
    assert "Number.isInteger(parsedRecordId)" in launch_flow
    assert "currentRecordId = parsedRecordId;" in launch_flow
    assert "resetCurrentPptDownload();" in launch_flow
    assert "const taskDownloadUrl = currentTaskId" in template
    assert "`/download/${encodeURIComponent(currentTaskId)}`" in template
    assert "`/download/${encodeURIComponent(currentRecordId)}`" in template

    completed = status_flow.index("else if (data.status === 'completed')")
    failed = status_flow.index("else if (data.status === 'failed')", completed)
    completed_flow = status_flow[completed:failed]
    assert "bindCurrentPptDownload();" in completed_flow
    assert "if (!bindCurrentPptDownload())" not in completed_flow
    assert completed_flow.index("bindCurrentPptDownload();") < completed_flow.index("showCompletionPopup(")
    assert "currentTaskKey = incomingKey" not in completed_flow


def test_ppt_status_ignores_a_stale_task_response_before_showing_completion() -> None:
    template = _read(PPT_TEMPLATE)
    start = template.index("async function startTranslation()")
    status_start = template.index("function checkTaskStatus")
    launch_flow = template[start:status_start]
    status_flow = template[status_start:]
    dom_start = template.index("document.addEventListener('DOMContentLoaded'")
    dom_initialization = template[dom_start : template.index("window.debugSettings", dom_start)]

    assert "let currentTaskEpoch = 0;" in template[:start]
    assert "const launchEpoch = ++currentTaskEpoch;" in launch_flow
    assert "clearInterval(window.statusCheckInterval);" in launch_flow[
        : launch_flow.index("const formData = new FormData();")
    ]
    assert "setInterval(() => checkTaskStatus(launchEpoch), 2000)" in launch_flow
    assert "checkTaskStatus(launchEpoch);" in launch_flow
    assert "function checkTaskStatus(taskEpoch = currentTaskEpoch)" in status_flow
    assert "const taskIdAtRequest = currentTaskId;" in status_flow
    assert "const recordIdAtRequest = currentRecordId;" in status_flow
    assert "if (!recordIdAtRequest) return;" in status_flow
    guard = status_flow.index("if (taskEpoch !== currentTaskEpoch")
    completed = status_flow.index("else if (data.status === 'completed')")

    assert guard < completed
    assert "return;" in status_flow[guard:completed]
    assert "checkTaskStatus();" not in dom_initialization


def test_experience_styles_define_responsive_drawer_and_readable_type() -> None:
    css = _read(EXPERIENCE_CSS)
    studio_mobile = css[css.rindex("@media (max-width: 900px)") :]

    assert "--ux-sidebar-width: 240px" in css
    assert "@media (max-width: 900px)" in css
    assert ".nav-menu.is-open" in css
    assert "margin-left: 0 !important" in css
    assert "font-size: 15px !important" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".studio-app-shell .app-header {\n        z-index: 1400;" in studio_mobile
    assert ".studio-app-shell .nav-overlay {" in studio_mobile
    assert "z-index: 1300;" in studio_mobile
    assert "body.studio-app-shell.nav-open .mobile-menu-btn" in studio_mobile


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
    assert "const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');" in template


def test_ppt_template_renders_with_the_application_routes(isolated_app: Flask) -> None:
    with isolated_app.test_request_context("/"):
        ppt = render_template("main/index.html")

    assert 'aria-current="page"' in ppt
    assert 'id="dropZone"' in ppt


def test_login_template_exposes_only_sso(isolated_app: Flask) -> None:
    # Given
    with isolated_app.test_request_context("/auth/login"):
        # When
        login = render_template("auth/login.html", sso_enabled=True, sso_provider="oauth2")

    # Then
    assert 'href="/auth/sso/login"' in login
    assert '<form class="login-form"' not in login
    assert 'name="username"' not in login
    assert 'name="password"' not in login
    assert "账号密码登录" not in login
    assert "logo.svg" not in login


def test_login_template_explains_when_sso_is_unavailable(isolated_app: Flask) -> None:
    with isolated_app.test_request_context("/auth/login"):
        login = render_template("auth/login.html", sso_enabled=False, sso_provider="oauth2")

    assert 'href="/auth/sso/login"' not in login
    assert '<form class="login-form"' not in login
    assert 'name="username"' not in login
    assert 'name="password"' not in login
    assert "SSO 登录暂不可用" in login
    assert "请联系系统管理员检查单点登录配置" in login
