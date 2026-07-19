from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from flask import Flask

from app.jobs.pdf_translation import PdfCompletedStatus, PdfFailedStatus, PdfTranslationError, PdfTranslationRequest
from todo5_legacy_boundaries import LegacyBoundaryError, legacy_pdf_translation_status
from todo5_pdf_fakes import RecordingStatusUpdater, install_pdf_failure_modules, install_pdf_success_modules


def _request(tmp_path: Path) -> PdfTranslationRequest:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF")
    return PdfTranslationRequest(
        pdf_path=str(pdf_path),
        original_filename="Source Paper.pdf",
        unique_filename="unique_source.pdf",
        source_lang="EN",
        target_lang="ZH",
        model="deepseek",
        enable_image_ocr=True,
        custom_translations={"HMO": "human milk oligosaccharide"},
        user_id=42,
        task_id="pdf-job",
    )


def test_pdf_translation_matches_legacy_production_boundary(
    isolated_app: Flask,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app as app_pkg
    import app.models as app_models
    from app.jobs import pdf_translation

    zip_path = tmp_path / "mineru.zip"
    with pdf_translation.zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr("task-1.md", "# Title")
    events: list[tuple] = []

    class FakeUploadRecord:
        def __init__(self, **kwargs) -> None:
            self.id = 1
            events.append(("history", kwargs))

    class FakeSession:
        def add(self, record) -> None:
            events.append(("history_add", type(record).__name__))

        def commit(self) -> None:
            events.append(("history_commit",))

        def remove(self) -> None:
            events.append(("history_remove",))

    def run_legacy():
        events.clear()
        install_pdf_success_modules(monkeypatch, events, zip_path)
        result, status = legacy_pdf_translation_status(
            str(tmp_path / "source.pdf"),
            "Source Paper.pdf",
            "unique_source.pdf",
            "EN",
            "ZH",
            True,
            {"HMO": "human milk oligosaccharide"},
            42,
            "legacy-pdf",
        )
        return result, list(events), status

    def run_current():
        events.clear()
        install_pdf_success_modules(monkeypatch, events, zip_path)
        updater = RecordingStatusUpdater()
        result = pdf_translation.process_pdf_translation(_request(tmp_path), updater)
        return result, list(events), dict(updater.completed_statuses[0])

    monkeypatch.setattr(app_pkg, "create_app", lambda: isolated_app)
    monkeypatch.setattr(app_pkg.db, "session", FakeSession())
    monkeypatch.setattr(app_models, "UploadRecord", FakeUploadRecord)
    real_copy2 = shutil.copy2

    def copy2_with_parent(src, dst, *args, **kwargs):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2_with_parent)

    legacy_result, legacy_events, legacy_status = run_legacy()
    current_result, current_events, current_status = run_current()
    legacy_history = [event for event in legacy_events if event[0] == "history"][0][1]
    current_history = [event for event in current_events if event[0] == "history"][0][1]
    assert legacy_result is current_result
    assert [event[0] for event in legacy_events[:2]] == [event[0] for event in current_events[:2]]
    legacy_ocr = [event for event in legacy_events if event[0] == "ocr"][0]
    current_ocr = [event for event in current_events if event[0] == "ocr"][0]
    assert legacy_ocr[:-1] == current_ocr[:-1]
    assert legacy_ocr[-1] == "qwen"
    assert current_ocr[-1] == "deepseek"
    legacy_doc = [event for event in legacy_events if event[0] == "doc"][0]
    current_doc = [event for event in current_events if event[0] == "doc"][0]
    assert legacy_doc[:3] == current_doc[:3]
    assert current_doc[3]["provider_model"] == "deepseek"
    assert {key: value for key, value in legacy_status.items() if key != "message"} == {
        key: value for key, value in current_status.items() if key != "message"
    }
    assert legacy_status["message"]
    assert current_status["message"]
    assert current_status["filename"] == "translated_en_zh_Source Paper.docx"
    assert current_history == legacy_history
    assert _request(tmp_path).model == "deepseek"


def test_pdf_translation_failure_preserves_failed_surface(
    isolated_app: Flask,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.jobs import pdf_translation

    import app as app_pkg
    import app.models as app_models

    events: list[tuple] = []

    class FakeUploadRecord:
        def __init__(self, **kwargs) -> None:
            events.append(("history", kwargs))

    class FakeSession:
        def add(self, record) -> None:
            events.append(("history_add", type(record).__name__))

        def commit(self) -> None:
            events.append(("history_commit",))

        def remove(self) -> None:
            events.append(("history_remove",))

    install_pdf_failure_modules(monkeypatch, events)
    monkeypatch.setattr(app_pkg, "create_app", lambda: isolated_app)
    monkeypatch.setattr(app_pkg.db, "session", FakeSession())
    monkeypatch.setattr(app_models, "UploadRecord", FakeUploadRecord)

    with pytest.raises(LegacyBoundaryError, match="bad pdf") as legacy_error:
        legacy_pdf_translation_status(
            str(tmp_path / "source.pdf"),
            "Source Paper.pdf",
            "unique_source.pdf",
            "EN",
            "ZH",
            True,
            {"HMO": "human milk oligosaccharide"},
            42,
            "legacy-pdf",
        )

    updater = RecordingStatusUpdater()

    with pytest.raises(PdfTranslationError, match="bad pdf") as current_error:
        pdf_translation.process_pdf_translation(_request(tmp_path), updater)

    assert updater.completed_statuses == []
    assert updater.failed_statuses[0]["status"] == "failed"
    assert str(legacy_error.value).endswith(": bad pdf")
    assert str(current_error.value).endswith(": bad pdf")
    assert updater.failed_statuses[0]["error"] == str(current_error.value)


def test_pdf_extraction_uses_mineru_before_local_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.jobs import pdf_translation

    order: list[str] = []
    zip_path = tmp_path / "mineru.zip"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    with pdf_translation.zipfile.ZipFile(zip_path, "w") as zip_file:
        zip_file.writestr("task-1.md", "# Extracted")

    def mineru_failure(request: PdfTranslationRequest) -> None:
        order.append("mineru")
        return None

    def local_success(request: PdfTranslationRequest) -> pdf_translation.MinerUResult:
        order.append("local")
        return {"code": 0, "data": {"task_id": "task-1", "full_zip_url": f"file://{zip_path}"}}

    monkeypatch.setattr(pdf_translation, "_extract_with_mineru", mineru_failure)
    monkeypatch.setattr(pdf_translation, "_extract_with_local_processor", local_success)

    md_file = pdf_translation._extract_markdown(_request(tmp_path), work_dir)

    assert order == ["mineru", "local"]
    assert md_file is not None
    assert md_file.read_text(encoding="utf-8") == "# Extracted"


def test_main_pdf_translation_wrapper_preserves_success_and_failure_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.views import main

    seen_models: list[str] = []

    def succeed(request: PdfTranslationRequest, status_updater: RecordingStatusUpdater) -> bool:
        seen_models.append(request.model)
        status_updater.completed(
            request.task_id,
            PdfCompletedStatus(
                status="completed",
                filename="translated_en_zh_doc.docx",
                stored_filename="translated_en_zh_doc.docx",
                original_filename=request.original_filename,
                download_name="translated_en_zh_doc.docx",
                message="缈昏瘧瀹屾垚",
            ),
        )
        return True

    monkeypatch.setattr("app.jobs.pdf_translation.process_pdf_translation", succeed)
    assert main.process_pdf_translation_async(
        "doc.pdf",
        "doc.pdf",
        "unique_doc.pdf",
        "EN",
        "ZH",
        "deepseek",
        False,
        {},
        1,
        "wrapper-ok",
    )
    assert seen_models == ["deepseek"]
    assert main.pdf_task_status_cache["wrapper-ok"]["status"] == "completed"

    def fail(request: PdfTranslationRequest, status_updater: RecordingStatusUpdater) -> bool:
        status_updater.failed(
            request.task_id,
            PdfFailedStatus(status="failed", error="adapter failed", message="缈昏瘧澶辫触"),
        )
        raise PdfTranslationError("adapter failed")

    monkeypatch.setattr("app.jobs.pdf_translation.process_pdf_translation", fail)
    with pytest.raises(PdfTranslationError, match="adapter failed"):
        main.process_pdf_translation_async(
            "doc.pdf",
            "doc.pdf",
            "unique_doc.pdf",
            "EN",
            "ZH",
            "qwen",
            False,
            {},
            1,
            "wrapper-fail",
        )
    assert main.pdf_task_status_cache["wrapper-fail"]["status"] == "failed"
    assert main.pdf_task_status_cache["wrapper-fail"]["error"] == "adapter failed"
