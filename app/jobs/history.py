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
    if snapshot.user_id is None:
        return False
    path = artifact.path.resolve()
    if snapshot.kind is JobKind.PPT_TRANSLATION:
        record_id = snapshot.request.get("upload_record_id")
        if not isinstance(record_id, int) or isinstance(record_id, bool) or record_id <= 0:
            return False
        record = session.get(UploadRecord, record_id)
        if record is None or record.user_id != snapshot.user_id:
            return False
        requested_output = snapshot.request.get("output_path")
        if not isinstance(requested_output, str) or not requested_output:
            return False
        record_path = (Path(record.file_path) / record.stored_filename).resolve()
        if record_path != Path(requested_output).resolve() or record_path != path:
            return False
        expected_size = path.stat().st_size
        if (
            record.status == "completed"
            and record.file_size == expected_size
        ):
            return False
        record.file_size = expected_size
        record.status = "completed"
        record.error_message = None
        return True
    if snapshot.kind is not JobKind.PDF_TRANSLATION:
        return False
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
