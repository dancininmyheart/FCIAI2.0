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
        <body>
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
                        <section class="upload-card"><h2>PPT Translation</h2></section>
                        <section class="history-card"><h3>History</h3></section>
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
