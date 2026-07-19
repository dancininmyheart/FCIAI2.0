from __future__ import annotations

from app import db
from app.utils.timezone_helper import now_with_timezone


class TranslationJob(db.Model):  # noqa: MUTABLE_OK
    __tablename__ = "translation_jobs"
    __table_args__ = (
        db.Index("ix_translation_jobs_public_id", "public_id", unique=True),
        db.Index("ix_translation_jobs_user_status", "user_id", "status"),
        db.Index("ix_translation_jobs_kind_status", "kind", "status"),
        db.Index("ix_translation_jobs_lease", "lease_owner", "lease_expires_at"),
    )

    id = db.Column(db.String(36), primary_key=True)
    public_id = db.Column(db.String(64), nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    kind = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False)
    stage = db.Column(db.String(32), nullable=False)
    progress = db.Column(db.Integer, nullable=False, default=0)
    request_json = db.Column(db.JSON, nullable=False)
    source_path = db.Column(db.String(1024), nullable=True)
    output_path = db.Column(db.String(1024), nullable=True)
    source_sha256 = db.Column(db.String(64), nullable=True)
    artifact_sha256 = db.Column(db.String(64), nullable=True)
    attempt = db.Column(db.Integer, nullable=False, default=0)
    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.String(2048), nullable=True)
    lease_owner = db.Column(db.String(128), nullable=True)
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_with_timezone)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=now_with_timezone,
        onupdate=now_with_timezone,
    )
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
