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
WORKBENCH_CSS = ROOT / "app" / "static" / "css" / "workbench-demo.css"
BASE_TEMPLATE = ROOT / "app" / "templates" / "main" / "base_layout.html"
PPT_TEMPLATE = ROOT / "app" / "templates" / "main" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _inline_style(path: Path) -> str:
    source = _read(path)
    if "<style>" not in source:
        return ""
    start = source.index("<style>") + len("<style>")
    end = source.index("</style>", start)
    return source[start:end]


def _translation_surface() -> str:
    css = "\n".join(
        (
            _read(BRAND_CSS),
            _read(BASE_CSS),
            _inline_style(BASE_TEMPLATE),
            _read(WORKBENCH_CSS),
            _read(EXPERIENCE_CSS),
        )
    )
    return f"""
        <!doctype html>
        <html>
        <head><style>{css}</style></head>
        <body class="studio-app-shell">
            <header class="mobile-app-bar">
                <button class="mobile-menu-btn" type="button">Menu</button>
                <span class="mobile-app-title">PPT Translation</span>
            </header>
            <button class="nav-overlay" type="button">Close</button>
            <nav class="nav-menu">
                <div class="nav-container">
                    <a class="nav-brand"><span>PPT Translation</span></a>
                    <button class="nav-close-btn" type="button">Close</button>
                    <div class="nav-links"><a class="nav-link active">PPT Translation</a></div>
                </div>
            </nav>
            <main class="container app-main">
                <div class="demo-shell">
                    <section class="portfolio-hero">
                        <div class="hero-copy">
                            <h1>Turn slide translation into a verifiable Agent workflow</h1>
                        </div>
                        <div class="workflow-card">
                            <ol class="workflow-list"><li><span>Parse PPTX</span></li></ol>
                        </div>
                    </section>
                    <section class="workbench-section">
                        <div class="main-content">
                            <aside class="config-panel">
                                <div class="panel-heading"><h3>Translation strategy</h3></div>
                            </aside>
                            <div class="translation-area">
                                <section class="upload-card">
                                    <div class="panel-heading"><h2>Upload and select pages</h2></div>
                                </section>
                                <section class="history-card"><h3>Task history</h3></section>
                            </div>
                        </div>
                    </section>
                </div>
            </main>
        </body>
        </html>
    """


def _translation_waiting_surface() -> str:
    css = "\n".join(
        (
            _read(BRAND_CSS),
            _read(BASE_CSS),
            _inline_style(BASE_TEMPLATE),
            _read(WORKBENCH_CSS),
            _read(EXPERIENCE_CSS),
        )
    )
    return f"""
        <!doctype html>
        <html>
        <head><style>{css}</style></head>
        <body class="studio-app-shell">
            <main class="container app-main">
                <div class="demo-shell">
                    <div id="queue-status" class="queue-status alert-info" style="display: flex">
                        <div class="loading-spinner" style="width: 20px; height: 20px; border-width: 2px;"></div>
                        <span>Translation task is running...</span>
                    </div>
                    <div class="main-content">
                        <aside class="config-panel"></aside>
                        <div class="translation-area">
                            <section class="upload-card">
                                <div id="progressContainer" class="progress-container" style="display: block">
                                    <div class="progress-info">
                                        <div class="slide-info">Translating page 2 of 8</div>
                                        <div class="progress-percentage">25%</div>
                                    </div>
                                    <div class="progress-bar-container">
                                        <div class="progress-bar-fill" style="width: 25%"></div>
                                    </div>
                                    <div class="detailed-status">
                                        <div class="status-header">
                                            <h4>Translation Details</h4>
                                            <button type="button" class="toggle-detail-btn">
                                                <i class="bi bi-chevron-down"></i>
                                            </button>
                                        </div>
                                        <div class="detail-content"></div>
                                    </div>
                                </div>
                            </section>
                        </div>
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


def test_translation_surface_renders_the_portfolio_demo_hierarchy(
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
    hero = page.locator(".portfolio-hero").evaluate(
        """element => ({
            backgroundImage: getComputedStyle(element).backgroundImage,
            radius: getComputedStyle(element).borderRadius,
            shadow: getComputedStyle(element).boxShadow
        })"""
    )
    cards = page.locator(
        ".demo-shell .config-panel, .demo-shell .upload-card, .demo-shell .history-card"
    ).evaluate_all(
        """elements => elements.map(element => ({
            background: getComputedStyle(element).backgroundColor,
            radius: getComputedStyle(element).borderRadius,
            shadow: getComputedStyle(element).boxShadow
        }))"""
    )
    heading_colors = page.locator(
        ".demo-shell .config-panel h3, .demo-shell .upload-card h2, .demo-shell .history-card h3"
    ).evaluate_all(
        "elements => elements.map(element => getComputedStyle(element).color)"
    )

    assert surface["documentWidth"] == surface["viewportWidth"] == 1440
    assert "linear-gradient" in hero["backgroundImage"]
    assert hero["radius"] == "28px"
    assert hero["shadow"] != "none"
    assert all(card["background"] == "rgba(255, 255, 255, 0.94)" for card in cards)
    assert all(10 <= float(card["radius"].removesuffix("px")) <= 22 for card in cards)
    assert all(card["shadow"] != "none" for card in cards)
    assert "rgb(0, 148, 217)" not in heading_colors

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
        "navRight": 1024,
        "canvasLeft": 0,
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
    assert mobile_open["width"] <= 360

    page.close()


def test_ppt_waiting_surface_uses_the_demo_progress_layout(
    browser: Browser,
) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.emulate_media(reduced_motion="reduce")
    page.set_content(_translation_waiting_surface())

    waiting = page.evaluate(
        """() => {
            const value = selector => getComputedStyle(document.querySelector(selector));
            const queue = value('#queue-status');
            const progress = value('#progressContainer');
            const header = value('.status-header');
            const toggle = value('.toggle-detail-btn');
            return {
                queueBackground: queue.backgroundColor,
                queuePadding: queue.padding,
                progressBackground: progress.backgroundColor,
                progressPadding: progress.padding,
                progressRadius: progress.borderRadius,
                detailHeaderHeight: parseFloat(header.height),
                toggleWidth: parseFloat(toggle.width),
                toggleHeight: parseFloat(toggle.height)
            };
        }"""
    )

    assert {
        key: waiting[key]
        for key in (
            "queueBackground",
            "queuePadding",
            "progressBackground",
            "progressPadding",
            "progressRadius",
        )
    } == {
        "queueBackground": "rgb(238, 242, 255)",
        "queuePadding": "14px 18px",
        "progressBackground": "rgb(248, 249, 255)",
        "progressPadding": "18px",
        "progressRadius": "14px",
    }
    assert 64 <= waiting["detailHeaderHeight"] <= 74
    assert waiting["toggleWidth"] < 56
    assert waiting["toggleHeight"] < 32

    page.close()


def test_auth_primary_action_renders_studio_gradient_depth(browser: Browser) -> None:
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
            .backgroundImage.includes('rgb(81, 72, 229)')"""
    )
    hovered_background = primary.evaluate(
        "element => getComputedStyle(element).backgroundImage"
    )

    assert initial == {
        "background": (
            "linear-gradient(135deg, rgb(99, 91, 255), rgb(8, 145, 178))"
        ),
        "shadow": "rgba(99, 91, 255, 0.22) 0px 12px 36px 0px",
        "color": "rgb(255, 255, 255)",
    }
    assert hovered_background == (
        "linear-gradient(135deg, rgb(81, 72, 229), rgb(8, 145, 178))"
    )
    assert page.locator(".links").is_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth === window.innerWidth"
    )

    page.close()
