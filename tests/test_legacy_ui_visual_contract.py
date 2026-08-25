from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Error, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BRAND_CSS = ROOT / "app" / "static" / "css" / "brand.css"
AUTH_CSS = ROOT / "app" / "static" / "css" / "style.css"
BASE_CSS = ROOT / "app" / "static" / "css" / "styles.css"
EXPERIENCE_CSS = ROOT / "app" / "static" / "css" / "experience.css"
BASE_TEMPLATE = ROOT / "app" / "templates" / "main" / "base_layout.html"
PPT_TEMPLATE = ROOT / "app" / "templates" / "main" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _inline_style(path: Path) -> str:
    source = _read(path)
    start = source.index("<style>") + len("<style>")
    end = source.index("</style>", start)
    return source[start:end]


def _translation_surface() -> str:
    css = "\n".join(
        (
            _read(BRAND_CSS),
            _read(BASE_CSS),
            _inline_style(BASE_TEMPLATE),
            _inline_style(PPT_TEMPLATE),
            _read(EXPERIENCE_CSS),
        )
    )
    return f"""
        <!doctype html>
        <html>
        <head><style>{css}</style></head>
        <body class="legacy-layout">
            <header class="mobile-app-bar">
                <button class="mobile-menu-btn" type="button">Menu</button>
                <span class="mobile-app-title">Translation Management System</span>
            </header>
            <button class="nav-overlay" type="button">Close</button>
            <nav class="nav-menu">
                <div class="nav-container">
                    <a class="nav-brand"><span class="brand-logo">FC</span></a>
                    <button class="nav-close-btn" type="button">Close</button>
                    <div class="nav-links"><a class="nav-link active">PPT Translation</a></div>
                </div>
            </nav>
            <main class="container">
                <section class="page-header">
                    <span class="header-icon"></span>
                    <h1 class="header-title">PPT File Translation Tool</h1>
                </section>
                <div class="main-content">
                    <aside class="config-panel"><h3>Translation Settings</h3></aside>
                    <div class="translation-area">
                        <section class="upload-card">
                            <h2>PPT Translation</h2>
                            <div
                                class="upload-zone"
                                id="dropZone"
                                role="button"
                                tabindex="0"
                                aria-controls="fileInput"
                                aria-describedby="pptUploadHint"
                                aria-busy="false"
                            >
                                <div class="upload-zone-content">
                                    <i class="bi bi-cloud-arrow-up upload-zone-icon" aria-hidden="true"></i>
                                    <div class="upload-text">Drag PPT file here or click to upload</div>
                                    <span class="upload-btn">
                                        <i class="bi bi-upload" aria-hidden="true"></i>
                                        Upload PPT File
                                    </span>
                                    <p class="upload-hint" id="pptUploadHint">PPT or PPTX, up to 50 MB</p>
                                </div>
                                <input
                                    type="file"
                                    id="fileInput"
                                    accept=".ppt,.pptx"
                                    style="display: none;"
                                    aria-label="Select a PPT file"
                                >
                            </div>
                        </section>
                        <section class="history-card">
                            <div class="history-header">
                                <h3>History</h3>
                                <button
                                    type="button"
                                    class="refresh-btn-header"
                                    id="refreshHistoryBtn"
                                    title="Refresh history"
                                    aria-label="Refresh history"
                                >Refresh</button>
                            </div>
                            <div class="history-table-wrap" tabindex="0" role="region" aria-label="PPT translation history table">
                                <table class="history-table">
                                    <thead>
                                        <tr>
                                            <th>File Name</th>
                                            <th>Upload Time</th>
                                            <th>File Size</th>
                                            <th>Translation Status</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody id="historyTableBody">
                                        <tr>
                                            <td>
                                                <span class="history-file-name">quarterly-customer-update-with-long-name.pptx</span>
                                                <span class="history-mobile-meta">2026-08-25 | 12 MB | Completed</span>
                                            </td>
                                            <td>2026-08-25 09:30</td>
                                            <td>12 MB</td>
                                            <td><span class="status-badge completed">Completed</span></td>
                                            <td class="history-actions">
                                                <a class="action-btn download" href="#" title="Download" aria-label="Download">
                                                    <i class="bi bi-download" aria-hidden="true"></i>
                                                </a>
                                                <button type="button" class="action-btn danger delete" title="Delete" aria-label="Delete">
                                                    <i class="bi bi-trash" aria-hidden="true"></i>
                                                </button>
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </section>
                    </div>
                </div>
            </main>
        </body>
        </html>
    """


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True)
        except Error as exc:
            pytest.fail(
                "Chromium is required for UI contract checks; "
                "run `python -m playwright install chromium`. "
                f"Launch error: {exc}",
                pytrace=False,
            )
        yield instance
        instance.close()


def test_translation_surface_renders_the_legacy_desktop_hierarchy(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    surface = page.locator(".container").evaluate(
        """element => ({
            background: getComputedStyle(element).backgroundColor,
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth
        })"""
    )
    cards = page.locator(
        ".page-header, .config-panel, .upload-card, .history-card"
    ).evaluate_all(
        """elements => elements.map(element => ({
            background: getComputedStyle(element).backgroundColor,
            radius: getComputedStyle(element).borderRadius,
            shadow: getComputedStyle(element).boxShadow
        }))"""
    )
    heading_colors = page.locator(
        ".header-title, .config-panel h3, .upload-card h2, .history-card h3"
    ).evaluate_all(
        "elements => elements.map(element => getComputedStyle(element).color)"
    )

    assert surface == {
        "background": "rgb(248, 249, 250)",
        "documentWidth": 1440,
        "viewportWidth": 1440,
    }
    assert all(card["background"] == "rgb(255, 255, 255)" for card in cards)
    assert all(8 <= float(card["radius"].removesuffix("px")) <= 14 for card in cards)
    assert all(
        card["shadow"] == "rgba(0, 0, 0, 0.06) 0px 2px 8px 0px"
        for card in cards
    )
    assert heading_colors == ["rgb(0, 148, 217)"] * 4

    page.close()


def test_desktop_upload_zone_keeps_legacy_density_with_accessible_new_markup(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    upload = page.locator("#dropZone").evaluate(
        """element => {
            const bounds = element.getBoundingClientRect();
            const icon = element.querySelector('.upload-zone-icon');
            const hint = element.querySelector('.upload-hint');
            const iconStyle = getComputedStyle(icon);
            const hintStyle = getComputedStyle(hint);
            return {
                role: element.getAttribute('role'),
                tabindex: element.getAttribute('tabindex'),
                controls: element.getAttribute('aria-controls'),
                describedby: element.getAttribute('aria-describedby'),
                busy: element.getAttribute('aria-busy'),
                height: bounds.height,
                iconDisplay: iconStyle.display,
                iconPosition: iconStyle.position,
                iconHeight: icon.getBoundingClientRect().height,
                hintDisplay: hintStyle.display,
                hintPosition: hintStyle.position,
                hintHeight: hint.getBoundingClientRect().height
            };
        }"""
    )

    assert upload["role"] == "button"
    assert upload["tabindex"] == "0"
    assert upload["controls"] == "fileInput"
    assert upload["describedby"] == "pptUploadHint"
    assert upload["busy"] == "false"
    assert upload["height"] <= 235
    assert upload["iconDisplay"] == "none" or upload["iconPosition"] == "absolute"
    assert upload["iconHeight"] <= 1
    assert upload["hintDisplay"] == "none" or upload["hintPosition"] == "absolute"
    assert upload["hintHeight"] <= 1

    page.close()


def test_desktop_history_actions_keep_legacy_compact_button_size(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    buttons = page.locator(".history-actions .action-btn").evaluate_all(
        """elements => elements.map(element => {
            const style = getComputedStyle(element);
            const bounds = element.getBoundingClientRect();
            return {
                width: bounds.width,
                height: bounds.height,
                minWidth: style.minWidth,
                flexBasis: style.flexBasis,
                display: style.display,
                alignItems: style.alignItems,
                justifyContent: style.justifyContent
            };
        })"""
    )

    assert len(buttons) == 2
    assert all(24 <= button["width"] <= 32 for button in buttons)
    assert all(24 <= button["height"] <= 32 for button in buttons)
    assert all(button["minWidth"] in {"0px", "24px"} for button in buttons)
    assert all(button["flexBasis"] in {"auto", "0px"} for button in buttons)
    assert all(button["display"] in {"flex", "inline-flex"} for button in buttons)
    assert all(button["alignItems"] == "center" for button in buttons)
    assert all(button["justifyContent"] == "center" for button in buttons)

    page.close()


def test_desktop_history_action_column_is_not_sticky(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    action_column = page.locator(
        ".history-table th:last-child, .history-table td:last-child"
    ).evaluate_all(
        """elements => elements.map(element => {
            const style = getComputedStyle(element);
            return {
                position: style.position,
                right: style.right,
                boxShadow: style.boxShadow,
                width: element.getBoundingClientRect().width
            };
        })"""
    )
    wrap = page.locator(".history-table-wrap").evaluate(
        """element => ({
            overflowX: getComputedStyle(element).overflowX,
            width: element.getBoundingClientRect().width
        })"""
    )

    assert wrap["overflowX"] == "auto"
    assert wrap["width"] > 700
    assert all(column["position"] == "static" for column in action_column)
    assert all(column["right"] == "auto" for column in action_column)
    assert all(column["boxShadow"] == "none" for column in action_column)

    page.close()


def test_mobile_history_remains_single_row_responsive_after_desktop_rollback(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    mobile = page.evaluate(
        """() => {
            const table = document.querySelector('.history-table');
            const hiddenColumns = [
                ...document.querySelectorAll(
                    '.history-table th:nth-child(2), .history-table th:nth-child(3), .history-table th:nth-child(4), .history-table td:nth-child(2), .history-table td:nth-child(3), .history-table td:nth-child(4)'
                )
            ].map(element => getComputedStyle(element).display);
            const actionHeaderStyle = getComputedStyle(
                document.querySelector('.history-table th:last-child')
            );
            const actionCellStyle = getComputedStyle(
                document.querySelector('.history-table td:last-child')
            );
            return {
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                tableMinWidth: getComputedStyle(table).minWidth,
                hiddenColumns,
                actionHeaderPosition: actionHeaderStyle.position,
                actionCellPosition: actionCellStyle.position,
                mobileMetaDisplay: getComputedStyle(
                    document.querySelector('.history-mobile-meta')
                ).display,
                mobileMetaWhiteSpace: getComputedStyle(
                    document.querySelector('.history-mobile-meta')
                ).whiteSpace
            };
        }"""
    )

    assert mobile["documentWidth"] == mobile["viewportWidth"] == 390
    assert mobile["tableMinWidth"] == "0px"
    assert set(mobile["hiddenColumns"]) == {"none"}
    assert mobile["actionHeaderPosition"] == "static"
    assert mobile["actionCellPosition"] == "static"
    assert mobile["mobileMetaDisplay"] == "block"
    assert mobile["mobileMetaWhiteSpace"] == "normal"

    page.close()


def test_translation_surface_stays_aligned_at_tablet_and_mobile_widths(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1024, "height": 768})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_surface())

    tablet = page.evaluate(
        """() => {
            const nav = document.querySelector('.nav-menu').getBoundingClientRect();
            const canvas = document.querySelector('.container').getBoundingClientRect();
            return {
                navRight: nav.right,
                canvasLeft: canvas.left,
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth
            };
        }"""
    )
    assert tablet == {
        "navRight": 180,
        "canvasLeft": 180,
        "documentWidth": 1024,
        "viewportWidth": 1024,
    }

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function(
        "document.querySelector('.nav-menu').getBoundingClientRect().right < 0"
    )
    mobile_closed = page.evaluate(
        """() => {
            const nav = document.querySelector('.nav-menu').getBoundingClientRect();
            const canvas = document.querySelector('.container').getBoundingClientRect();
            return {
                navRight: nav.right,
                canvasLeft: canvas.left,
                canvasWidth: canvas.width,
                appBarDisplay: getComputedStyle(
                    document.querySelector('.mobile-app-bar')
                ).display,
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth
            };
        }"""
    )
    assert mobile_closed["navRight"] < 0
    assert mobile_closed["canvasLeft"] == 0
    assert mobile_closed["canvasWidth"] == 390
    assert mobile_closed["appBarDisplay"] == "flex"
    assert mobile_closed["documentWidth"] == mobile_closed["viewportWidth"] == 390

    page.locator(".nav-menu").evaluate("element => element.classList.add('is-open')")
    page.wait_for_function(
        "Math.abs(document.querySelector('.nav-menu').getBoundingClientRect().left) < 0.5"
    )
    mobile_open = page.locator(".nav-menu").evaluate(
        """element => {
            const bounds = element.getBoundingClientRect();
            return {left: bounds.left, width: bounds.width};
        }"""
    )
    assert mobile_open["left"] == 0
    assert mobile_open["width"] <= 320

    page.close()


def test_auth_primary_action_renders_legacy_blue_depth(browser: Browser) -> None:
    css = "\n".join((_read(BRAND_CSS), _read(AUTH_CSS)))
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(
        f"""
            <!doctype html>
            <html>
            <head><style>{css}</style></head>
            <body>
                <div class="auth-shell">
                    <div class="auth-card">
                        <a class="btn btn-primary">Use SSO Login</a>
                        <div class="links">Contact the system administrator for help.</div>
                    </div>
                </div>
            </body>
            </html>
        """
    )

    primary = page.locator(".btn-primary")
    initial = primary.evaluate(
        """element => ({
            background: getComputedStyle(element).backgroundImage,
            shadow: getComputedStyle(element).boxShadow,
            color: getComputedStyle(element).color
        })"""
    )
    primary.hover()
    page.wait_for_function(
        """getComputedStyle(document.querySelector('.btn-primary'))
            .backgroundImage.includes('rgb(0, 123, 182)')"""
    )
    hovered_background = primary.evaluate(
        "element => getComputedStyle(element).backgroundImage"
    )

    assert initial == {
        "background": (
            "linear-gradient(135deg, rgb(0, 148, 217), rgb(0, 95, 153))"
        ),
        "shadow": "rgba(0, 148, 217, 0.18) 0px 12px 24px 0px",
        "color": "rgb(255, 255, 255)",
    }
    assert hovered_background == (
        "linear-gradient(135deg, rgb(0, 123, 182), rgb(0, 95, 153))"
    )
    assert page.locator(".links").is_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth === window.innerWidth"
    )

    page.close()
