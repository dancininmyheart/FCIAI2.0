from __future__ import annotations

from flask import Flask


def test_removed_translation_health_route_is_not_exposed(isolated_app: Flask) -> None:
    # Given
    client = isolated_app.test_client()

    # When
    response = client.get("/api/translation/health")

    # Then
    assert response.status_code == 404
