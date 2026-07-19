from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.jobs.store import TranslationJobStore
from app.jobs.types import JobCreation, JobKind, JobStatus
from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request
from migrations.add_translation_jobs import compile_dry_run, rollback, upgrade


def test_mysql_dry_run_emits_only_create_table_and_indexes():
    # Given
    ddl = compile_dry_run("mysql")

    # When
    lowered = ddl.lower()

    # Then
    assert "create table translation_jobs" in lowered
    assert "create index" in lowered or "create unique index" in lowered
    assert "alter table" not in lowered
    assert "drop table" not in lowered


def test_upgrade_metadata_delta_is_exactly_translation_jobs(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    before = inspect(engine).get_table_names()

    # When
    upgrade(engine)
    after = inspect(engine).get_table_names()

    # Then
    assert before == []
    assert after == ["translation_jobs"]


def test_reapply_and_rollback_are_non_destructive(tmp_path: Path):
    # Given
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.sqlite'}")
    upgrade(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO translation_jobs "
                "(id, public_id, kind, status, stage, progress, request_json, attempt, version, created_at, updated_at) "
                "VALUES ('1', 'task_keep', 'pdf_translation', 'queued', 'validate', 0, '{}', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    # When
    upgrade(engine)
    rollback(engine)
    rows = engine.connect().execute(text("SELECT public_id FROM translation_jobs")).fetchall()

    # Then
    assert inspect(engine).get_table_names() == ["translation_jobs"]
    assert [row[0] for row in rows] == ["task_keep"]


def test_upgraded_schema_supports_file_backed_store_reopen_contract(tmp_path: Path):
    # Given
    database = tmp_path / "jobs.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    upgrade(engine)
    spec = TranslationJobSpec(
        file_type="pdf",
        source_language="en",
        target_language="zh",
        model="qwen",
        enable_image_ocr=True,
    )

    # When
    created = TranslationJobStore(Session(engine)).create(
        JobCreation(
            user_id=9,
            kind=JobKind.PDF_TRANSLATION,
            request=build_translation_job_request(spec),
            source_path="source.pdf",
            source_sha256="c" * 64,
        )
    )
    reopened_engine = create_engine(f"sqlite:///{database}")
    reopened = TranslationJobStore(Session(reopened_engine)).get(created.public_id)

    # Then
    assert reopened.public_id == created.public_id
    assert reopened.status is JobStatus.QUEUED
    assert reopened.request["model"] == "qwen"
    assert reopened.request["enable_image_ocr"] is True
    assert reopened.source_sha256 == "c" * 64
