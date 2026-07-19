from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from typing import Literal, NewType, TypeAlias, TypedDict, assert_never

TaskId = NewType("TaskId", str)
WorkerId = NewType("WorkerId", str)
JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class TranslationRequestJson(TypedDict):
    schema_version: int
    access: Literal["private", "public"]
    file_type: str
    source_language: str
    target_language: str
    model: str
    selected_pages: list[int]
    bilingual_translation: str
    enable_image_ocr: bool
    enable_text_splitting: str
    enable_uno_conversion: bool
    vocabulary_ids: list[int]
    custom_translations: dict[str, str]
    original_filename: str
    unique_filename: str
    annotation_filename: str
    annotations: list[dict[str, JsonValue]]
    output_path: str


class LegacyStatusJson(TypedDict, total=False):
    task_id: str
    status: str
    canonical_status: str
    stage: str
    progress: int
    current_slide: int
    total_slides: int
    message: str
    error: str
    error_code: str
    filename: str
    stored_filename: str
    output_path: str


class JobQueueCounts(TypedDict):
    queued: int
    running: int
    succeeded: int
    failed: int
    canceled: int
    interrupted: int
    total: int


@unique
class JobKind(StrEnum):
    PPT_TRANSLATION = "ppt_translation"
    PDF_TRANSLATION = "pdf_translation"
    PDF_ANNOTATION = "pdf_annotation"


@unique
class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


@unique
class JobStage(StrEnum):
    VALIDATE = "validate"
    EXTRACT = "extract"
    TRANSLATE = "translate"
    RENDER = "render"
    VERIFY = "verify"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class InvalidJobField(Exception):
    field: str
    value: str

    def __str__(self) -> str:
        return f"invalid job {self.field}: {self.value}"


@dataclass(frozen=True, slots=True)
class TranslationJobRequest:
    file_type: str
    source_language: str
    target_language: str
    model: str
    schema_version: int = 1
    access: Literal["private", "public"] = "private"
    selected_pages: tuple[int, ...] = ()
    bilingual_translation: str = "paragraph_up"
    enable_image_ocr: bool = False
    enable_text_splitting: str = "False"
    enable_uno_conversion: bool = True
    vocabulary_ids: tuple[int, ...] = ()
    custom_translations: dict[str, str] = field(default_factory=dict)
    original_filename: str = ""
    unique_filename: str = ""
    annotation_filename: str = ""
    annotations: tuple[dict[str, JsonValue], ...] = ()
    output_path: str = ""

    def to_json(self) -> TranslationRequestJson:
        return {
            "schema_version": self.schema_version,
            "access": self.access,
            "file_type": self.file_type,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "model": self.model,
            "selected_pages": list(self.selected_pages),
            "bilingual_translation": self.bilingual_translation,
            "enable_image_ocr": self.enable_image_ocr,
            "enable_text_splitting": self.enable_text_splitting,
            "enable_uno_conversion": self.enable_uno_conversion,
            "vocabulary_ids": list(self.vocabulary_ids),
            "custom_translations": dict(self.custom_translations),
            "original_filename": self.original_filename,
            "unique_filename": self.unique_filename,
            "annotation_filename": self.annotation_filename,
            "annotations": [dict(annotation) for annotation in self.annotations],
            "output_path": self.output_path,
        }


@dataclass(frozen=True, slots=True)
class JobCreation:
    user_id: int | None
    kind: JobKind
    request: TranslationJobRequest
    source_path: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class JobLease:
    worker_id: WorkerId
    expires_at: datetime
    expected_version: int


@dataclass(frozen=True, slots=True)
class JobProgress:
    stage: JobStage
    progress: int
    expected_version: int


@dataclass(frozen=True, slots=True)
class JobSuccess:
    output_path: str
    artifact_sha256: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class JobFailure:
    error_code: str
    error_message: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    public_id: TaskId
    user_id: int | None
    kind: JobKind
    status: JobStatus
    stage: JobStage
    progress: int
    request: TranslationRequestJson
    version: int
    attempt: int
    source_path: str | None
    output_path: str | None
    source_sha256: str | None
    artifact_sha256: str | None
    error_code: str | None
    error_message: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None


def parse_job_kind(raw: str) -> JobKind:
    try:
        return JobKind(raw)
    except ValueError as exc:
        raise InvalidJobField(field="kind", value=raw) from exc


def parse_job_status(raw: str) -> JobStatus:
    try:
        return JobStatus(raw)
    except ValueError as exc:
        raise InvalidJobField(field="status", value=raw) from exc


def parse_job_stage(raw: str) -> JobStage:
    try:
        return JobStage(raw)
    except ValueError as exc:
        raise InvalidJobField(field="stage", value=raw) from exc


def legacy_task_type(kind: JobKind) -> str:
    match kind:
        case JobKind.PPT_TRANSLATION:
            return "ppt_translate"
        case JobKind.PDF_TRANSLATION:
            return "pdf_translation"
        case JobKind.PDF_ANNOTATION:
            return "pdf_annotate"
        case unreachable:
            assert_never(unreachable)


def legacy_status(snapshot: JobSnapshot) -> LegacyStatusJson:
    base = LegacyStatusJson(
        task_id=snapshot.public_id,
        canonical_status=snapshot.status.value,
        stage=snapshot.stage.value,
        progress=snapshot.progress,
        current_slide=0,
        total_slides=0,
    )
    match snapshot.status:
        case JobStatus.QUEUED:
            base.update(status="waiting", message="任务正在排队...")
        case JobStatus.RUNNING:
            base.update(status="processing", message="正在翻译中...")
        case JobStatus.SUCCEEDED:
            base.update(status="completed", message="翻译完成")
            if snapshot.output_path:
                base.update(
                    output_path=snapshot.output_path,
                    filename=snapshot.output_path,
                    stored_filename=snapshot.output_path,
                )
        case JobStatus.FAILED:
            base.update(status="failed", message="翻译失败")
            if snapshot.error_message:
                base["error"] = snapshot.error_message
            if snapshot.error_code:
                base["error_code"] = snapshot.error_code
        case JobStatus.CANCELED:
            base.update(status="canceled", message="任务已取消")
        case JobStatus.INTERRUPTED:
            base.update(status="failed", message="任务已中断", error_code="interrupted")
            if snapshot.error_message:
                base["error"] = snapshot.error_message
        case unreachable:
            assert_never(unreachable)
    return base
