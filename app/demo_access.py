"""Session binding for the environment-configured interview Demo gate."""

from __future__ import annotations

import secrets

from flask import current_app, session
from flask_login import current_user


DEMO_ACCESS_SESSION_KEY = "demo_access_session_marker"


def demo_access_session_is_verified() -> bool:
    """Return whether this login session passed the current Demo gate."""
    if not current_user.is_authenticated:
        return False

    expected = current_app.config.get("DEMO_ACCESS_SESSION_MARKER")
    submitted = session.get(DEMO_ACCESS_SESSION_KEY)
    if not isinstance(expected, str) or not isinstance(submitted, str):
        return False
    if not expected or not submitted:
        return False
    return secrets.compare_digest(
        submitted.encode("utf-8"),
        expected.encode("utf-8"),
    )


def mark_demo_access_session_verified() -> bool:
    """Bind the authenticated session to this server's Demo gate version."""
    marker = current_app.config.get("DEMO_ACCESS_SESSION_MARKER")
    if not isinstance(marker, str) or not marker:
        return False
    session[DEMO_ACCESS_SESSION_KEY] = marker
    return True


__all__ = [
    "DEMO_ACCESS_SESSION_KEY",
    "demo_access_session_is_verified",
    "mark_demo_access_session_verified",
]
