from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, assert_never

from flask import current_app, has_app_context

from app.jobs.pdf_translation import PdfTaskStatusUpdater, PdfTranslationRequest
from app.jobs.types import JobKind
from app.translation.metrics import TranslationCorrelation, bind_translation_correlation


class ProgressCallback(Protocol):
    def __call__(self, current: int, total: int) -> None: ...


class LegacyTranslationTask(Protocol):
    task_type: str
    file_path: str
    annotation_json: dict | None
    annotation_filename: str | None
    annotations: list
    output_path: str
    select_page: list[int]
    source_language: str
    target_language: str
    bilingual_translation: str
    model: str
    enable_text_splitting: str
    enable_uno_conversion: bool
    custom_translations: dict[str, str] | None
    user_id: int
    task_id: str
    enable_image_ocr: bool
    original_filename: str
    unique_filename: str
    retry_count: int


@dataclass(frozen=True, slots=True)
class AdapterExecutionError(Exception):
    adapter: str
    message: str

    def __str__(self) -> str:
        return f"{self.adapter}: {self.message}"


@dataclass(frozen=True, slots=True)
class UnsupportedLegacyTaskType(Exception):
    task_type: str

    def __str__(self) -> str:
        return f"unsupported legacy task type: {self.task_type}"


@dataclass(frozen=True, slots=True)
class PptTranslationExecution:
    task: LegacyTranslationTask
    progress_callback: ProgressCallback | None
    kind: Literal[JobKind.PPT_TRANSLATION] = JobKind.PPT_TRANSLATION


@dataclass(frozen=True, slots=True)
class PdfTranslationExecution:
    request: PdfTranslationRequest
    status_updater: PdfTaskStatusUpdater
    kind: Literal[JobKind.PDF_TRANSLATION] = JobKind.PDF_TRANSLATION


@dataclass(frozen=True, slots=True)
class PdfAnnotationExecution:
    task: LegacyTranslationTask
    progress_callback: ProgressCallback | None
    kind: Literal[JobKind.PDF_ANNOTATION] = JobKind.PDF_ANNOTATION


JobExecution: TypeAlias = PptTranslationExecution | PdfTranslationExecution | PdfAnnotationExecution


class PptTranslationAdapter(Protocol):
    def execute(self, request: PptTranslationExecution) -> bool: ...


class PdfTranslationAdapter(Protocol):
    def execute(self, request: PdfTranslationExecution) -> bool: ...


class PdfAnnotationAdapter(Protocol):
    def execute(self, request: PdfAnnotationExecution) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExecutionAdapters:
    ppt_translation: PptTranslationAdapter = field(default_factory=lambda: DefaultPptTranslationAdapter())
    pdf_translation: PdfTranslationAdapter = field(default_factory=lambda: DefaultPdfTranslationAdapter())
    pdf_annotation: PdfAnnotationAdapter = field(default_factory=lambda: DefaultPdfAnnotationAdapter())


class DefaultPptTranslationAdapter:
    def execute(self, request: PptTranslationExecution) -> bool:
        from app.function.ppt_translate_async import process_presentation, process_presentation_add_annotations

        task = request.task
        stop_words: list[str] = []
        custom_translations = task.custom_translations or {}
        if task.annotation_json:
            return process_presentation_add_annotations(
                presentation_path=task.file_path,
                annotations=task.annotation_json,
                stop_words=stop_words,
                custom_translations=custom_translations,
                source_language=task.source_language,
                target_language=task.target_language,
                bilingual_translation=task.bilingual_translation,
                progress_callback=request.progress_callback,
                model=task.model,
            )
        return process_presentation(
            presentation_path=task.file_path,
            stop_words=stop_words,
            custom_translations=custom_translations,
            select_page=task.select_page,
            source_language=task.source_language,
            target_language=task.target_language,
            bilingual_translation=task.bilingual_translation,
            progress_callback=request.progress_callback,
            model=task.model,
            enable_text_splitting=task.enable_text_splitting,
            enable_uno_conversion=task.enable_uno_conversion,
        )


class DefaultPdfTranslationAdapter:
    def execute(self, request: PdfTranslationExecution) -> bool:
        from app.jobs.pdf_translation import process_pdf_translation

        return process_pdf_translation(request.request, request.status_updater)


class DefaultPdfAnnotationAdapter:
    def execute(self, request: PdfAnnotationExecution) -> bool:
        from asyncio import new_event_loop, set_event_loop  # noqa: ANYIO_OK

        from app.function.pdf_annotate_async import process_pdf_annotations_async
        from app.jobs.path_security import resolve_pdf_output_target, resolve_uploaded_source

        task = request.task
        if not task.output_path:
            raise AdapterExecutionError(adapter="pdf_annotation", message="missing service output path")
        if has_app_context():
            source_path = resolve_uploaded_source(task.file_path)
            output_path = resolve_pdf_output_target(task.output_path)
            task.file_path = str(source_path)
            task.output_path = str(output_path)

        loop = new_event_loop()
        set_event_loop(loop)
        try:
            return loop.run_until_complete(
                process_pdf_annotations_async(
                    pdf_path=task.file_path,
                    annotations=task.annotations,
                    output_path=task.output_path,
                    progress_callback=request.progress_callback,
                ),
            )
        finally:
            loop.close()


def execute_job(request: JobExecution, adapters: ExecutionAdapters | None = None) -> bool:
    selected_adapters = adapters or ExecutionAdapters()
    match request.kind:
        case JobKind.PPT_TRANSLATION:
            return selected_adapters.ppt_translation.execute(request)
        case JobKind.PDF_TRANSLATION:
            return selected_adapters.pdf_translation.execute(request)
        case JobKind.PDF_ANNOTATION:
            return selected_adapters.pdf_annotation.execute(request)
        case unreachable:
            assert_never(unreachable)


def execute_legacy_task(
    task: LegacyTranslationTask,
    progress_callback: ProgressCallback | None,
    adapters: ExecutionAdapters | None = None,
) -> bool:
    correlation = TranslationCorrelation(
        public_job_id=task.task_id,
        attempt=int(getattr(task, "ledger_attempt", getattr(task, "retry_count", 0) + 1)),
        stage="translate",
        provider=task.model,
    )
    with bind_translation_correlation(correlation):
        if task.task_type == "ppt_translate":
            return execute_job(PptTranslationExecution(task, progress_callback), adapters)
        if task.task_type == "pdf_translation":
            filename = task.original_filename or task.file_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            unique_filename = task.unique_filename or filename
            request = PdfTranslationRequest(
                pdf_path=task.file_path,
                original_filename=filename,
                unique_filename=unique_filename,
                source_lang=task.source_language,
                target_lang=task.target_language,
                model=task.model,
                enable_image_ocr=task.enable_image_ocr,
                custom_translations=task.custom_translations or {},
                user_id=task.user_id,
                task_id=task.task_id,
                output_path=task.output_path,
                register_history=getattr(task, "ledger_completion_callback", None) is None,
            )
            return execute_job(PdfTranslationExecution(request, _TaskPdfStatusUpdater(task)), adapters)
        if task.task_type == "pdf_annotate":
            return execute_job(PdfAnnotationExecution(task, progress_callback), adapters)
        raise UnsupportedLegacyTaskType(task_type=task.task_type)


class _TaskPdfStatusUpdater:
    def __init__(self, task: LegacyTranslationTask) -> None:
        self._task = task

    def completed(self, task_id, status) -> None:
        if self._task.output_path and Path(self._task.output_path).is_file():
            return
        upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
        if not upload_folder.is_absolute():
            upload_folder = Path(current_app.root_path) / upload_folder
        self._task.output_path = str(upload_folder / "pdf_outputs" / status["stored_filename"])

    def failed(self, task_id, status) -> None:
        return None


__all__ = [
    "AdapterExecutionError",
    "ExecutionAdapters",
    "PdfAnnotationExecution",
    "PdfTranslationExecution",
    "PptTranslationExecution",
    "execute_job",
    "execute_legacy_task",
]
