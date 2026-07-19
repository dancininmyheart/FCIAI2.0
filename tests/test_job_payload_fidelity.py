from __future__ import annotations

from pathlib import Path

from flask import Flask

from app.jobs.types import JobKind, WorkerId
from test_job_worker import _store

VALID_ANNOTATION = {
    "page": 1,
    "coords": {"left": 1, "top": 2, "width": 3, "height": 4},
    "text": "note",
    "ocrResult": "ocr",
    "translation": "translated",
}


class CapturingQueue:
    def __init__(self) -> None:
        self.tasks: list = []

    def has_available_slot(self) -> bool:
        return True

    def add_claimed_task(self, task) -> int:
        self.tasks.append(task)
        return len(self.tasks)


def test_ppt_ledger_payload_preserves_full_options_and_custom_map(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    import app.views.main as main_views

    store = _store(tmp_path)
    monkeypatch.setenv("TRANSLATION_ARCH_MODE", "v2")
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(main_views, "_signal_worker", lambda: None)

    # When
    snapshot = main_views._create_ppt_ledger_job(
        9,
        str(tmp_path / "deck.pptx"),
        "English",
        "Chinese",
        "deepseek",
        selected_pages=(2, 4),
        bilingual_translation="paragraph_down",
        enable_text_splitting="True_spliting",
        enable_uno_conversion=False,
        custom_translations={"Milk": "Nai"},
        original_filename="deck.pptx",
    )

    # Then
    request = store.get(snapshot.public_id).request
    assert request["schema_version"] == 1
    assert request["access"] == "private"
    assert request["selected_pages"] == [2, 4]
    assert request["bilingual_translation"] == "paragraph_down"
    assert request["enable_text_splitting"] == "True_spliting"
    assert request["enable_uno_conversion"] is False
    assert request["custom_translations"] == {"Milk": "Nai"}


def test_worker_reconstructs_pdf_and_annotation_adapter_arguments(
    isolated_app: Flask,
    monkeypatch,
    tmp_path: Path,
) -> None:
    # Given
    from app.jobs.worker import EmbeddedDbWorker
    import app.views.main as main_views

    store = _store(tmp_path)
    monkeypatch.setattr(main_views, "_job_store", lambda: store)
    monkeypatch.setattr(main_views, "_signal_worker", lambda: None)
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF")
    pdf = main_views._create_pdf_ledger_job(
        8,
        str(pdf_path),
        "EN",
        "ZH",
        "deepseek",
        True,
        [3],
        {"HMO": "human milk oligosaccharide"},
        "Source.pdf",
        "unique_source.pdf",
    )
    annotation = main_views._create_pdf_annotation_ledger_job(
        8,
        str(pdf_path),
        [VALID_ANNOTATION],
        str(tmp_path / "annotated.pdf"),
        "Source.pdf",
    )
    queue = CapturingQueue()
    worker = EmbeddedDbWorker(store_factory=lambda: store, queue=queue, worker_id=WorkerId("worker-a"))

    # When
    worker.drain_once()
    worker.drain_once()

    # Then
    tasks_by_kind = {task.task_type: task for task in queue.tasks}
    pdf_task = tasks_by_kind["pdf_translation"]
    annotation_task = tasks_by_kind["pdf_annotate"]
    assert store.get(pdf.public_id).kind is JobKind.PDF_TRANSLATION
    assert pdf_task.model == "deepseek"
    assert pdf_task.enable_image_ocr is True
    assert pdf_task.custom_translations == {"HMO": "human milk oligosaccharide"}
    assert pdf_task.original_filename == "Source.pdf"
    assert pdf_task.unique_filename == "unique_source.pdf"
    assert store.get(annotation.public_id).kind is JobKind.PDF_ANNOTATION
    assert annotation_task.annotations == [VALID_ANNOTATION]
    assert annotation_task.output_path.endswith("annotated.pdf")


def test_pdf_legacy_execution_records_actual_output_path(
    isolated_app: Flask,
    tmp_path: Path,
) -> None:
    # Given
    from app.jobs.executor import ExecutionAdapters, execute_legacy_task
    from app.utils.enhanced_task_queue import TranslationTask
    from test_job_executor import RecordingAdapter

    task = TranslationTask(
        task_id="pdf-task",
        user_id=7,
        user_name="tester",
        file_path=str(tmp_path / "source.pdf"),
        model="qwen",
        task_type="pdf_translation",
        source_language="EN",
        target_language="ZH",
        custom_translations={"A": "B"},
        enable_image_ocr=True,
        original_filename="source.pdf",
        unique_filename="unique_source.pdf",
    )
    calls: list[str] = []
    adapters = ExecutionAdapters(pdf_translation=RecordingAdapter("pdf", calls))

    # When
    with isolated_app.app_context():
        result = execute_legacy_task(task, None, adapters)

    # Then
    assert result is True
    assert calls == ["pdf"]
    assert task.output_path.endswith("pdf_outputs\\translated_en_zh_doc.docx") or task.output_path.endswith(
        "pdf_outputs/translated_en_zh_doc.docx",
    )
    assert task.output_path != task.file_path
