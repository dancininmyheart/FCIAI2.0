from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field

import pytest

from app.jobs.executor import (
    AdapterExecutionError,
    ExecutionAdapters,
    PdfAnnotationExecution,
    PdfTranslationExecution,
    PptTranslationExecution,
    execute_job,
    execute_legacy_task,
)
from app.jobs.pdf_translation import PdfCompletedStatus, PdfFailedStatus, PdfTranslationRequest
from todo5_legacy_boundaries import LegacyQueueBoundary


@dataclass(frozen=True, slots=True)
class FakeLegacyTask:  # noqa: MUTABLE_OK
    task_type: str = "ppt_translate"
    file_path: str = "deck.pptx"
    annotation_json: dict[str, list[str]] | None = None
    annotation_filename: str | None = None
    annotations: list[dict[str, str]] = field(default_factory=list)
    output_path: str = ""
    select_page: list[int] = field(default_factory=lambda: [1])
    source_language: str = "English"
    target_language: str = "Chinese"
    bilingual_translation: str = "paragraph_up"
    model: str = "qwen"
    enable_text_splitting: str = "False"
    enable_uno_conversion: bool = True
    custom_translations: dict[str, str] | None = field(default_factory=dict)
    user_id: int = 7
    task_id: str = "legacy-task"
    enable_image_ocr: bool = False
    original_filename: str = "doc.pdf"
    unique_filename: str = "unique_doc.pdf"


@dataclass(frozen=True, slots=True)
class RecordingStatusUpdater:  # noqa: MUTABLE_OK
    completed_statuses: list[PdfCompletedStatus] = field(default_factory=list)
    failed_statuses: list[PdfFailedStatus] = field(default_factory=list)

    def completed(self, task_id: str, status: PdfCompletedStatus) -> None:
        self.completed_statuses.append(status)

    def failed(self, task_id: str, status: PdfFailedStatus) -> None:
        self.failed_statuses.append(status)


@dataclass(frozen=True, slots=True)
class RecordingAdapter:  # noqa: MUTABLE_OK
    name: str
    calls: list[str]
    fail: bool = False

    def execute(self, request) -> bool:
        self.calls.append(self.name)
        if self.fail:
            raise AdapterExecutionError(adapter=self.name, message="declared failure")
        progress_callback = getattr(request, "progress_callback", None)
        if progress_callback:
            progress_callback(1, 2)
            progress_callback(2, 2)
        status_updater = getattr(request, "status_updater", None)
        if status_updater:
            status_updater.completed(
                request.request.task_id,
                PdfCompletedStatus(
                    status="completed",
                    filename="translated_en_zh_doc.docx",
                    stored_filename="translated_en_zh_doc.docx",
                    original_filename="doc.pdf",
                    download_name="translated_en_zh_doc.docx",
                    message="翻译完成",
                ),
            )
        return True


@dataclass(frozen=True, slots=True)
class UnexpectedAdapterError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _pdf_request() -> PdfTranslationRequest:
    return PdfTranslationRequest(
        pdf_path="doc.pdf",
        original_filename="doc.pdf",
        unique_filename="unique_doc.pdf",
        source_lang="EN",
        target_lang="ZH",
        model="qwen",
        enable_image_ocr=False,
        custom_translations={},
        user_id=7,
        task_id="pdf-task",
    )


def test_dispatch_invokes_one_correct_adapter_for_each_job_kind() -> None:
    calls: list[str] = []
    adapters = ExecutionAdapters(
        ppt_translation=RecordingAdapter("ppt", calls),
        pdf_translation=RecordingAdapter("pdf", calls),
        pdf_annotation=RecordingAdapter("annotation", calls),
    )

    assert execute_job(PptTranslationExecution(FakeLegacyTask(), None), adapters)
    assert calls == ["ppt"]
    calls.clear()
    assert execute_job(PdfTranslationExecution(_pdf_request(), RecordingStatusUpdater()), adapters)
    assert calls == ["pdf"]
    calls.clear()
    assert execute_job(PdfAnnotationExecution(FakeLegacyTask(task_type="pdf_annotate"), None), adapters)
    assert calls == ["annotation"]


@pytest.mark.parametrize(
    ("execution", "failing_adapter", "expected_calls"),
    (
        (PptTranslationExecution(FakeLegacyTask(), None), "ppt", ["ppt"]),
        (PdfTranslationExecution(_pdf_request(), RecordingStatusUpdater()), "pdf", ["pdf"]),
        (PdfAnnotationExecution(FakeLegacyTask(task_type="pdf_annotate"), None), "annotation", ["annotation"]),
    ),
)
def test_declared_errors_do_not_fallback(execution, failing_adapter: str, expected_calls: list[str]) -> None:
    calls: list[str] = []
    adapters = ExecutionAdapters(
        ppt_translation=RecordingAdapter("ppt", calls, fail=failing_adapter == "ppt"),
        pdf_translation=RecordingAdapter("pdf", calls, fail=failing_adapter == "pdf"),
        pdf_annotation=RecordingAdapter("annotation", calls, fail=failing_adapter == "annotation"),
    )

    with pytest.raises(AdapterExecutionError, match=failing_adapter):
        execute_job(execution, adapters)

    assert calls == expected_calls


def test_unexpected_adapter_errors_preserve_failure_surface() -> None:
    class BrokenAdapter:
        def execute(self, request) -> bool:
            raise UnexpectedAdapterError("unexpected adapter failure")

    adapters = ExecutionAdapters(
        ppt_translation=BrokenAdapter(),
        pdf_translation=RecordingAdapter("pdf", []),
        pdf_annotation=RecordingAdapter("annotation", []),
    )

    with pytest.raises(UnexpectedAdapterError, match="unexpected adapter failure"):
        execute_job(PptTranslationExecution(FakeLegacyTask(), None), adapters)


def test_legacy_task_types_delegate_to_typed_jobs() -> None:
    calls: list[str] = []
    adapters = ExecutionAdapters(
        ppt_translation=RecordingAdapter("ppt", calls),
        pdf_translation=RecordingAdapter("pdf", calls),
        pdf_annotation=RecordingAdapter("annotation", calls),
    )

    assert execute_legacy_task(FakeLegacyTask(task_type="pdf_annotate"), None, adapters)

    assert calls == ["annotation"]


def test_queue_extraction_matches_legacy_production_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.jobs.executor import DefaultPdfAnnotationAdapter, DefaultPptTranslationAdapter

    calls = {"ppt": [], "annotation": []}

    def fake_process_presentation(**kwargs) -> bool:
        calls["ppt"].append({"function": "plain", **kwargs})
        kwargs["progress_callback"](1, 3)
        kwargs["progress_callback"](3, 3)
        return True

    def fake_process_presentation_add_annotations(**kwargs) -> bool:
        calls["ppt"].append({"function": "annotated", **kwargs})
        kwargs["progress_callback"](1, 3)
        kwargs["progress_callback"](3, 3)
        return True

    async def fake_process_pdf_annotations_async(**kwargs) -> bool:
        calls["annotation"].append(kwargs)
        kwargs["progress_callback"](1, 2)
        kwargs["progress_callback"](2, 2)
        return True

    ppt_module = types.ModuleType("app.function.ppt_translate_async")
    ppt_module.process_presentation = fake_process_presentation
    ppt_module.process_presentation_add_annotations = fake_process_presentation_add_annotations
    annotation_module = types.ModuleType("app.function.pdf_annotate_async")
    annotation_module.process_pdf_annotations_async = fake_process_pdf_annotations_async
    monkeypatch.setitem(sys.modules, "app.function.ppt_translate_async", ppt_module)
    monkeypatch.setitem(sys.modules, "app.function.pdf_annotate_async", annotation_module)
    legacy_queue = LegacyQueueBoundary()

    parity = {}
    for label, task in (
        ("ppt_plain", FakeLegacyTask()),
        ("ppt_annotated", FakeLegacyTask(annotation_json={"slide": ["note"]}, annotation_filename="notes.json")),
    ):
        old_progress: list[tuple[int, int]] = []
        new_progress: list[tuple[int, int]] = []
        calls["ppt"].clear()
        old_return = legacy_queue.execute_ppt_translation_task(
            task,
            lambda current, total: old_progress.append((current, total)),
        )
        old_call = dict(calls["ppt"][0])
        calls["ppt"].clear()
        new_return = DefaultPptTranslationAdapter().execute(
            PptTranslationExecution(task, lambda current, total: new_progress.append((current, total))),
        )
        new_call = dict(calls["ppt"][0])
        old_call.pop("progress_callback")
        new_call.pop("progress_callback")
        parity[label] = {
            "return_shape_equal": old_return is new_return,
            "arguments_equal": old_call == new_call,
            "progress_equal": old_progress == new_progress,
            "progress_percentages": [int(current / total * 100) for current, total in new_progress],
            "model": new_call["model"],
            "custom_translations": new_call["custom_translations"],
        }

    task = FakeLegacyTask(task_type="pdf_annotate", output_path="annotated.pdf", annotations=[{"id": "a1"}])
    old_progress = []
    new_progress = []
    calls["annotation"].clear()
    old_return = legacy_queue.execute_pdf_annotation_task(
        task,
        lambda current, total: old_progress.append((current, total)),
    )
    old_call = dict(calls["annotation"][0])
    calls["annotation"].clear()
    new_return = DefaultPdfAnnotationAdapter().execute(
        PdfAnnotationExecution(task, lambda current, total: new_progress.append((current, total))),
    )
    new_call = dict(calls["annotation"][0])
    old_call.pop("progress_callback")
    new_call.pop("progress_callback")
    parity["pdf_annotation"] = {
        "return_shape_equal": old_return is new_return,
        "arguments_equal": old_call == new_call,
        "progress_equal": old_progress == new_progress,
        "progress_percentages": [int(current / total * 100) for current, total in new_progress],
        "output_path": new_call["output_path"],
    }

    assert all(item["return_shape_equal"] and item["arguments_equal"] and item["progress_equal"] for item in parity.values())
    assert parity["ppt_plain"]["progress_percentages"] == [33, 100]
    assert parity["ppt_annotated"]["model"] == "qwen"
    assert parity["pdf_annotation"]["progress_percentages"] == [50, 100]


def test_enhanced_queue_compatibility_methods_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.jobs import executor
    from app.utils.enhanced_task_queue import EnhancedTranslationQueue

    calls: list[str] = []

    def fake_execute(task: FakeLegacyTask, progress_callback) -> bool:
        calls.append(task.task_type)
        return True

    monkeypatch.setattr(executor, "execute_legacy_task", fake_execute)
    queue = EnhancedTranslationQueue()

    assert queue._execute_ppt_translation_task(FakeLegacyTask(task_type="ppt_translate"), None)
    assert queue._execute_pdf_annotation_task(FakeLegacyTask(task_type="pdf_annotate"), None)
    assert calls == ["ppt_translate", "pdf_annotate"]
