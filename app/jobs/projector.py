from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.jobs.store import _snapshot
from app.jobs.types import JobQueueCounts, JobSnapshot, parse_job_status
from app.models.translation_job import TranslationJob


def latest_for_user(session: Session, user_id: int) -> JobSnapshot | None:
    row = session.execute(
        select(TranslationJob).where(TranslationJob.user_id == user_id).order_by(TranslationJob.created_at.desc()).limit(1),
    ).scalar_one_or_none()
    return _snapshot(row) if row is not None else None


def queue_counts(session: Session) -> JobQueueCounts:
    rows = session.execute(select(TranslationJob.status, func.count(TranslationJob.id)).group_by(TranslationJob.status)).all()
    counts = JobQueueCounts(queued=0, running=0, succeeded=0, failed=0, canceled=0, interrupted=0, total=0)
    for status, count in rows:
        parsed = parse_job_status(status)
        counts[parsed.value] = int(count)
        counts["total"] += int(count)
    return counts


def queue_counts_for_user(session: Session, user_id: int) -> JobQueueCounts:
    rows = session.execute(
        select(TranslationJob.status, func.count(TranslationJob.id))
        .where(TranslationJob.user_id == user_id)
        .group_by(TranslationJob.status),
    ).all()
    counts = JobQueueCounts(queued=0, running=0, succeeded=0, failed=0, canceled=0, interrupted=0, total=0)
    for status, count in rows:
        parsed = parse_job_status(status)
        counts[parsed.value] = int(count)
        counts["total"] += int(count)
    return counts
