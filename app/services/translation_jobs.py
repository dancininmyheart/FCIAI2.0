from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Iterable, Literal, Mapping, Protocol, TypeAlias, assert_never, cast

from app.jobs.types import JsonValue, TranslationJobRequest


DEFAULT_UPLOAD_SIZE_LIMIT: Final = 200 * 1024 * 1024

LanguageField: TypeAlias = Literal["english", "chinese", "dutch"]
BilingualTranslationMode: TypeAlias = Literal[
    "translation_only",
    "paragraph_up",
    "paragraph_down",
]

_LANGUAGE_FIELD_ALIASES: Final[Mapping[str, LanguageField]] = {
    "english": "english",
    "en": "english",
    "chinese": "chinese",
    "zh": "chinese",
    "zh-cn": "chinese",
    "dutch": "dutch",
    "nl": "dutch",
}

_SUPPORTED_DURABLE_MODELS: Final = frozenset({"qwen", "deepseek"})
SUPPORTED_BILINGUAL_TRANSLATION_MODES: Final = frozenset(
    {"translation_only", "paragraph_up", "paragraph_down"}
)


@dataclass(frozen=True, slots=True)
class InvalidTranslationJobSpec(Exception):
    field: str
    value: str

    def __str__(self) -> str:
        return f"invalid translation job {self.field}: {self.value}"


class TranslationRecord(Protocol):
    english: str | None
    chinese: str | None
    dutch: str | None


@dataclass(frozen=True, slots=True)
class TranslationJobSpec:
    file_type: str
    source_language: str
    target_language: str
    model: str
    access: Literal["private", "public"] = "private"
    selected_pages: tuple[int, ...] = ()
    bilingual_translation: BilingualTranslationMode = "paragraph_up"
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
    upload_record_id: int | None = None


def build_translation_job_request(spec: TranslationJobSpec) -> TranslationJobRequest:
    model = spec.model.strip()
    if model not in _SUPPORTED_DURABLE_MODELS:
        raise InvalidTranslationJobSpec(field="model", value=spec.model)
    bilingual_translation = validate_bilingual_translation_mode(spec.bilingual_translation)
    return TranslationJobRequest(
        file_type=spec.file_type,
        source_language=spec.source_language,
        target_language=spec.target_language,
        model=model,
        access=spec.access,
        selected_pages=spec.selected_pages,
        bilingual_translation=bilingual_translation,
        enable_image_ocr=spec.enable_image_ocr,
        enable_text_splitting=spec.enable_text_splitting,
        enable_uno_conversion=spec.enable_uno_conversion,
        vocabulary_ids=spec.vocabulary_ids,
        custom_translations=spec.custom_translations,
        original_filename=spec.original_filename,
        unique_filename=spec.unique_filename,
        annotation_filename=spec.annotation_filename,
        annotations=spec.annotations,
        output_path=spec.output_path,
        upload_record_id=spec.upload_record_id,
    )


def validate_bilingual_translation_mode(value: str) -> BilingualTranslationMode:
    if value not in SUPPORTED_BILINGUAL_TRANSLATION_MODES:
        raise InvalidTranslationJobSpec(field="bilingual_translation", value=value)
    return cast(BilingualTranslationMode, value)


def parse_vocabulary_ids(raw_ids: str | None) -> list[int]:
    if not raw_ids:
        return []
    tokens = [token.strip() for token in raw_ids.split(",") if token.strip()]
    try:
        return [int(token) for token in tokens]
    except ValueError:
        return []


def parse_selected_pages(raw_values: Iterable[str]) -> list[int]:
    values = list(raw_values)
    if not values or all(not value.strip() for value in values):
        return []
    parsed: list[int] = []
    for value in values:
        tokens = value.split(",")
        if any(not token.strip() for token in tokens):
            raise InvalidTranslationJobSpec(field="select_page", value=value)
        for token in tokens:
            try:
                page = int(token.strip())
            except ValueError as exc:
                raise InvalidTranslationJobSpec(field="select_page", value=value) from exc
            if page <= 0:
                raise InvalidTranslationJobSpec(field="select_page", value=value)
            if page not in parsed:
                parsed.append(page)
    return parsed


def build_custom_translation_map(
    records: Iterable[TranslationRecord],
    source_language: str,
    target_language: str,
) -> Mapping[str, str]:
    source_field = _resolve_language_field(source_language, fallback="english")
    target_field = _resolve_language_field(target_language, fallback="chinese")
    translations: dict[str, str] = {}

    for record in records:
        source_text = _record_field(record, source_field)
        target_text = _record_field(record, target_field)
        if source_text and target_text and source_text.strip() and target_text.strip():
            translations[source_text.strip()] = target_text.strip()

    return translations


def get_upload_size_limit(config: Mapping[str, int | str | None]) -> int:
    for key in ("MAX_CONTENT_LENGTH", "UPLOAD_MAX_FILE_SIZE", "MAX_FILE_SIZE"):
        limit = _coerce_positive_int(config.get(key))
        if limit is not None:
            return limit
    return DEFAULT_UPLOAD_SIZE_LIMIT


def _resolve_language_field(language: str, fallback: LanguageField) -> LanguageField:
    normalized = language.strip().lower().replace("_", "-")
    return _LANGUAGE_FIELD_ALIASES.get(normalized, fallback)


def _record_field(record: TranslationRecord, field: LanguageField) -> str | None:
    match field:
        case "english":
            return record.english
        case "chinese":
            return record.chinese
        case "dutch":
            return record.dutch
        case unreachable:
            assert_never(unreachable)


def _coerce_positive_int(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed > 0 else None
