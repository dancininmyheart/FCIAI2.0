from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.artifacts import PromotedArtifact
from app.jobs.types import JobKind, JobSnapshot
from app.models.upload_record import UploadRecord


def register_completion_history_once(
    session: Session,
    snapshot: JobSnapshot,
    artifact: PromotedArtifact,
) -> bool:
    if snapshot.kind is not JobKind.PDF_TRANSLATION or snapshot.user_id is None:
        return False
    path = artifact.path.resolve()
    existing = session.execute(
        select(UploadRecord.id).where(
            UploadRecord.user_id == snapshot.user_id,
            UploadRecord.stored_filename == path.name,
            UploadRecord.file_path == str(path.parent),
            UploadRecord.status == "completed",
        ),
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(
        UploadRecord(
            filename=path.name,
            stored_filename=path.name,
            file_path=str(path.parent),
            user_id=snapshot.user_id,
            file_size=path.stat().st_size,
            status="completed",
        ),
    )
    session.commit()
    return True
