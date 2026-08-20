"""PPT-only route surface.

The original :mod:`app.views.main` module still owns the view implementations so
the translation workflow has a single source of truth.  This blueprint exposes
only the PPT page and the endpoints that page (or the supported public PPT API)
needs.  Keeping the blueprint name and endpoint names unchanged preserves
``url_for("main.<endpoint>")`` compatibility without registering the unrelated
product routes declared by the legacy blueprint.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from flask import Blueprint, current_app

from ..demo_access import demo_access_session_is_verified
from . import main as main_views


bp = Blueprint("main", __name__)


@bp.before_request
def require_verified_demo_access():
    """Keep every PPT surface behind the current process's Demo gate."""
    if (
        current_app.config.get("DEMO_MODE", False)
        and not demo_access_session_is_verified()
    ):
        return current_app.login_manager.unauthorized()
    return None


def _register(
    rule: str,
    endpoint: str,
    view_func: Callable[..., Any],
    methods: Iterable[str] = ("GET",),
) -> None:
    bp.add_url_rule(rule, endpoint=endpoint, view_func=view_func, methods=methods)


# PPT page and backwards-compatible aliases for that same page.
_register("/", "index", main_views.index)
_register("/index", "index_page", main_views.index_page)
_register("/dashboard", "dashboard", main_views.dashboard)

# Authenticated PPT workflow used by the main page.
_register("/upload", "upload_file", main_views.upload_file, ("POST",))
_register("/task_status", "get_task_status", main_views.get_task_status)
_register(
    "/task_status/<task_id>",
    "get_simple_task_status",
    main_views.get_simple_task_status,
)
_register("/download/<int:record_id>", "download_file", main_views.download_file)
_register(
    "/download/<task_id>",
    "download_simple_translated_file",
    main_views.download_simple_translated_file,
)
_register("/delete/<int:record_id>", "delete_file", main_views.delete_file, ("DELETE",))
_register(
    "/api/ppt_translation_history",
    "ppt_translation_history",
    main_views.ppt_translation_history,
)

# The PPT vocabulary picker intentionally remains read-only.
_register(
    "/api/translations",
    "get_translations",
    main_views.get_translations,
)

# Page preference and the supported public PPT compatibility API.
_register("/switch_language", "switch_language", main_views.switch_language, ("POST",))
_register(
    "/start_translation",
    "start_translation",
    main_views.start_translation,
    ("POST",),
)
_register(
    "/ppt_translate",
    "ppt_translate_simple",
    main_views.ppt_translate_simple,
    ("POST",),
)


__all__ = ["bp"]
