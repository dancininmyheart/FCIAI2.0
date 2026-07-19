from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.jobs.pdf_translation import PdfCompletedStatus, PdfFailedStatus


@dataclass(frozen=True, slots=True)
class RecordingStatusUpdater:  # noqa: MUTABLE_OK
    completed_statuses: list[PdfCompletedStatus] = field(default_factory=list)
    failed_statuses: list[PdfFailedStatus] = field(default_factory=list)

    def completed(self, task_id: str, status: PdfCompletedStatus) -> None:
        self.completed_statuses.append(status)

    def failed(self, task_id: str, status: PdfFailedStatus) -> None:
        self.failed_statuses.append(status)


def install_pdf_success_modules(monkeypatch: pytest.MonkeyPatch, events: list[tuple], zip_path: Path) -> None:
    class FakeOssProcessor:
        def process_pdf_with_mineru(self, pdf_path, mineru_api, bucket, region, enable_ocr):
            events.append(("oss", pdf_path, bucket, region, enable_ocr))
            return None

    class FakeLocalProcessor:
        def process_pdf(self, pdf_path):
            events.append(("local", pdf_path))
            return {"code": 0, "data": {"task_id": "task-1", "full_zip_url": f"file://{zip_path}"}}

    def fake_ocr(markdown_content, markdown_dir, target_language, source_language, provider_model="qwen"):
        events.append(
            ("ocr", markdown_content, Path(markdown_dir).name, target_language, source_language, provider_model),
        )
        return [{"success": True, "image_path": "image.png"}]

    def fake_doc(markdown_content, output_path, **kwargs) -> bool:
        events.append(("doc", markdown_content, Path(output_path).name, kwargs))
        Path(output_path).write_bytes(b"docx")
        return True

    oss_module = types.ModuleType("app.function.image_ocr.oss_pdf_processor")
    oss_module.OSSPDFProcessor = FakeOssProcessor
    mineru_module = types.ModuleType("app.function.image_ocr.ocr_api")
    mineru_module.MinerUAPI = lambda: None
    local_module = types.ModuleType("app.function.local_pdf_processor")
    local_module.LocalPDFProcessor = FakeLocalProcessor
    ocr_module = types.ModuleType("app.function.image_ocr.ocr_controller")
    ocr_module.process_markdown_images_ocr_and_translate = fake_ocr
    document_module = types.ModuleType("app.utils.document_generator")
    document_module.translate_markdown_to_bilingual_doc = fake_doc
    monkeypatch.setitem(sys.modules, "app.function.image_ocr.oss_pdf_processor", oss_module)
    monkeypatch.setitem(sys.modules, "app.function.image_ocr.ocr_api", mineru_module)
    monkeypatch.setitem(sys.modules, "app.function.local_pdf_processor", local_module)
    monkeypatch.setitem(sys.modules, "app.function.image_ocr.ocr_controller", ocr_module)
    monkeypatch.setitem(sys.modules, "app.utils.document_generator", document_module)


def install_pdf_failure_modules(monkeypatch: pytest.MonkeyPatch, events: list[tuple]) -> None:
    class FakeOssProcessor:
        def process_pdf_with_mineru(self, pdf_path, mineru_api, bucket, region, enable_ocr):
            events.append(("oss", pdf_path, enable_ocr))
            return None

    class FakeLocalProcessor:
        def process_pdf(self, pdf_path):
            events.append(("local", pdf_path))
            return {"code": 7, "msg": "bad pdf"}

    oss_module = types.ModuleType("app.function.image_ocr.oss_pdf_processor")
    oss_module.OSSPDFProcessor = FakeOssProcessor
    mineru_module = types.ModuleType("app.function.image_ocr.ocr_api")
    mineru_module.MinerUAPI = lambda: None
    local_module = types.ModuleType("app.function.local_pdf_processor")
    local_module.LocalPDFProcessor = FakeLocalProcessor
    monkeypatch.setitem(sys.modules, "app.function.image_ocr.oss_pdf_processor", oss_module)
    monkeypatch.setitem(sys.modules, "app.function.image_ocr.ocr_api", mineru_module)
    monkeypatch.setitem(sys.modules, "app.function.local_pdf_processor", local_module)
