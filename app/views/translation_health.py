from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required

from app import db
from app.config import TranslationSettings
from app.jobs.projector import queue_counts, queue_counts_for_user
from app.translation.metrics import TranslationMetrics

bp = Blueprint("translation_health", __name__)


@bp.get("/api/translation/health")
@login_required
def translation_health():
    is_admin = bool(current_user.is_administrator())
    counts = queue_counts(db.session) if is_admin else queue_counts_for_user(db.session, int(current_user.id))
    settings = current_app.extensions.get("translation_settings")
    if not isinstance(settings, TranslationSettings):
        settings = TranslationSettings.from_environment({})
    metrics = current_app.extensions.get("translation_metrics")
    metric_payload = metrics.snapshot().to_dict() if isinstance(metrics, TranslationMetrics) else {}
    return jsonify(
        {
            "healthy": True,
            "scope": "global" if is_admin else "current_user",
            "jobs": dict(counts),
            "metrics": metric_payload,
            "settings": asdict(settings),
        },
    )
