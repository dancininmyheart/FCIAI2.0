from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

from app.jobs.types import JobQueueCounts


def _counts(total: int) -> JobQueueCounts:
    return JobQueueCounts(
        queued=total,
        running=0,
        succeeded=0,
        failed=0,
        canceled=0,
        interrupted=0,
        total=total,
    )


def test_translation_health_requires_authentication(isolated_app: Flask) -> None:
    response = isolated_app.test_client().get("/api/translation/health")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_non_admin_health_uses_only_current_user_job_counts(isolated_app: Flask, monkeypatch) -> None:
    from app.views import translation_health

    seen_user_ids: list[int] = []
    isolated_app.config["LOGIN_DISABLED"] = True
    monkeypatch.setattr(
        translation_health,
        "current_user",
        SimpleNamespace(id=17, is_administrator=lambda: False),
    )
    monkeypatch.setattr(
        translation_health,
        "queue_counts_for_user",
        lambda session, user_id: seen_user_ids.append(user_id) or _counts(2),
    )
    monkeypatch.setattr(
        translation_health,
        "queue_counts",
        lambda session: (_ for _ in ()).throw(AssertionError("global counts must not be queried")),
    )

    response = isolated_app.test_client().get("/api/translation/health")

    assert response.status_code == 200
    assert response.get_json()["scope"] == "current_user"
    assert response.get_json()["jobs"]["total"] == 2
    assert seen_user_ids == [17]


def test_admin_health_exposes_aggregate_counts_without_job_identifiers(isolated_app: Flask, monkeypatch) -> None:
    from app.views import translation_health

    isolated_app.config["LOGIN_DISABLED"] = True
    monkeypatch.setattr(
        translation_health,
        "current_user",
        SimpleNamespace(id=1, is_administrator=lambda: True),
    )
    monkeypatch.setattr(translation_health, "queue_counts", lambda session: _counts(4))

    payload = isolated_app.test_client().get("/api/translation/health").get_json()

    assert payload["scope"] == "global"
    assert payload["jobs"]["total"] == 4
    assert "job_id" not in str(payload)
