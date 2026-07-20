from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping

from app.jobs.types import JsonValue, TranslationRequestJson


@dataclass(frozen=True, slots=True)
class MalformedTranslationRequest(Exception):
    field: str
    value: str

    def __str__(self) -> str:
        return f"malformed translation request {self.field}: {self.value}"


_REQUIRED_KEYS: Final = frozenset(
    {
        "schema_version",
        "access",
        "file_type",
        "source_language",
        "target_language",
        "model",
        "selected_pages",
        "bilingual_translation",
        "enable_image_ocr",
        "enable_text_splitting",
        "enable_uno_conversion",
        "vocabulary_ids",
        "custom_translations",
        "original_filename",
        "unique_filename",
        "annotation_filename",
        "annotations",
        "output_path",
    },
)
_OPTIONAL_KEYS: Final = frozenset({"upload_record_id"})
_ALLOWED_KEYS: Final = _REQUIRED_KEYS | _OPTIONAL_KEYS
_SUPPORTED_FILE_TYPES: Final = frozenset({"pptx", "pdf", "pdf_annotation"})
_SUPPORTED_MODELS: Final = frozenset({"qwen", "deepseek"})
_ANNOTATION_KEYS: Final = frozenset({"page", "coords", "text", "ocrResult", "translation"})
_REQUIRED_ANNOTATION_KEYS: Final = frozenset({"page", "coords"})
_COORD_KEYS: Final = frozenset({"left", "top", "width", "height"})


def parse_translation_request(raw: Mapping[str, JsonValue]) -> TranslationRequestJson:
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise MalformedTranslationRequest(field="unknown", value=",".join(sorted(unknown)))
    missing = _REQUIRED_KEYS - set(raw)
    if missing:
        raise MalformedTranslationRequest(field="missing", value=",".join(sorted(missing)))
    schema_version = _required_int(raw, "schema_version")
    if schema_version != 1:
        raise MalformedTranslationRequest(field="schema_version", value=str(schema_version))
    access = _required_str(raw, "access")
    if access not in ("private", "public"):
        raise MalformedTranslationRequest(field="access", value=access)
    file_type = _required_str(raw, "file_type")
    if file_type not in _SUPPORTED_FILE_TYPES:
        raise MalformedTranslationRequest(field="file_type", value=file_type)
    model = _required_str(raw, "model")
    if model not in _SUPPORTED_MODELS:
        raise MalformedTranslationRequest(field="model", value=model)
    return TranslationRequestJson(
        schema_version=schema_version,
        access=access,
        file_type=file_type,
        source_language=_required_str(raw, "source_language"),
        target_language=_required_str(raw, "target_language"),
        model=model,
        selected_pages=_required_positive_int_list(raw, "selected_pages"),
        bilingual_translation=_required_str(raw, "bilingual_translation"),
        enable_image_ocr=_required_bool(raw, "enable_image_ocr"),
        enable_text_splitting=_required_str(raw, "enable_text_splitting"),
        enable_uno_conversion=_required_bool(raw, "enable_uno_conversion"),
        vocabulary_ids=_required_int_list(raw, "vocabulary_ids"),
        custom_translations=_required_str_map(raw, "custom_translations"),
        original_filename=_required_str(raw, "original_filename"),
        unique_filename=_required_str(raw, "unique_filename"),
        annotation_filename=_required_str(raw, "annotation_filename"),
        annotations=_required_annotation_list(raw, "annotations"),
        output_path=_required_str(raw, "output_path"),
        upload_record_id=_optional_positive_int(raw, "upload_record_id"),
    )


def parse_annotation_payload(value: JsonValue) -> list[dict[str, JsonValue]]:
    return _required_annotation_list({"annotations": value}, "annotations")


def _required_str(raw: Mapping[str, JsonValue], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise MalformedTranslationRequest(field=field, value=str(value))
    return value


def _required_bool(raw: Mapping[str, JsonValue], field: str) -> bool:
    value = raw[field]
    if not isinstance(value, bool):
        raise MalformedTranslationRequest(field=field, value=str(value))
    return value


def _required_int(raw: Mapping[str, JsonValue], field: str) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedTranslationRequest(field=field, value=str(value))
    return value


def _optional_positive_int(raw: Mapping[str, JsonValue], field: str) -> int | None:
    value = raw.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MalformedTranslationRequest(field=field, value=str(value))
    return value


def _required_int_list(raw: Mapping[str, JsonValue], field: str) -> list[int]:
    value = raw[field]
    if not isinstance(value, list):
        raise MalformedTranslationRequest(field=field, value=str(value))
    parsed: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise MalformedTranslationRequest(field=field, value=str(item))
        parsed.append(item)
    return parsed


def _required_positive_int_list(raw: Mapping[str, JsonValue], field: str) -> list[int]:
    parsed = _required_int_list(raw, field)
    for item in parsed:
        if item <= 0:
            raise MalformedTranslationRequest(field=field, value=str(item))
    return parsed


def _required_str_map(raw: Mapping[str, JsonValue], field: str) -> dict[str, str]:
    value = raw[field]
    if not isinstance(value, dict):
        raise MalformedTranslationRequest(field=field, value=str(value))
    parsed: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise MalformedTranslationRequest(field=field, value=str(key))
        if not isinstance(item, str):
            raise MalformedTranslationRequest(field=field, value=f"{key}={item}")
        parsed[key] = item
    return parsed


def _required_annotation_list(raw: Mapping[str, JsonValue], field: str) -> list[dict[str, JsonValue]]:
    value = raw[field]
    if not isinstance(value, list):
        raise MalformedTranslationRequest(field=field, value=str(value))
    parsed: list[dict[str, JsonValue]] = []
    for item in value:
        if not isinstance(item, dict):
            raise MalformedTranslationRequest(field=field, value=str(item))
        parsed.append(_annotation_item(field, item))
    return parsed


def _annotation_item(field: str, item: dict[JsonValue, JsonValue]) -> dict[str, JsonValue]:
    unknown = set(item) - _ANNOTATION_KEYS
    if unknown:
        raise MalformedTranslationRequest(field=field, value=",".join(sorted(str(key) for key in unknown)))
    missing = _REQUIRED_ANNOTATION_KEYS - set(item)
    if missing:
        raise MalformedTranslationRequest(field=field, value=",".join(sorted(missing)))
    page = item["page"]
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise MalformedTranslationRequest(field=field, value=f"page={page}")
    coords = item["coords"]
    if not isinstance(coords, dict):
        raise MalformedTranslationRequest(field=field, value=f"coords={coords}")
    parsed: dict[str, JsonValue] = {
        "page": page,
        "coords": _annotation_coords(field, coords),
    }
    for key in ("text", "ocrResult", "translation"):
        if key in item:
            value = item[key]
            if not isinstance(value, str):
                raise MalformedTranslationRequest(field=field, value=f"{key}={value}")
            parsed[key] = value
    return parsed


def _annotation_coords(field: str, coords: dict[JsonValue, JsonValue]) -> dict[str, JsonValue]:
    unknown = set(coords) - _COORD_KEYS
    if unknown:
        raise MalformedTranslationRequest(field=field, value=f"coords={','.join(sorted(str(key) for key in unknown))}")
    missing = _COORD_KEYS - set(coords)
    if missing:
        raise MalformedTranslationRequest(field=field, value=f"coords={','.join(sorted(missing))}")
    parsed: dict[str, JsonValue] = {}
    for key in ("left", "top", "width", "height"):
        value = coords[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MalformedTranslationRequest(field=field, value=f"coords.{key}={value}")
        if key in ("left", "top") and value < 0:
            raise MalformedTranslationRequest(field=field, value=f"coords.{key}={value}")
        if key in ("width", "height") and value <= 0:
            raise MalformedTranslationRequest(field=field, value=f"coords.{key}={value}")
        parsed[key] = value
    return parsed
