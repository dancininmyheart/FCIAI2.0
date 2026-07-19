from __future__ import annotations

import json
from typing import Final, assert_never

from app.translation.pptx_contract_types import (
    JsonValue,
    PptxContractError,
    PptxLineBreakStreamItem,
    PptxProtectedFieldStreamItem,
    PptxRequestUnit,
    PptxSegmentTranslation,
    PptxSourceStreamItem,
    PptxTextStreamItem,
    PptxUnitTranslation,
)
from app.translation.pptx_contract_validation import (
    reconstruct_target,
    reserved_marker_counts,
    validate_pptx_translations,
    validate_request_units,
    validate_unit_translation,
)


PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION: Final = 2
PPTX_DOCUMENT_KIND: Final = "pptx_xml"
PPTX_PROVIDER_FIELD: Final = "pptx_structured_v2"
PPTX_PROVIDER_REPAIR_FIELD: Final = "pptx_structured_v2_repair"

_ROOT_FIELDS: Final = frozenset(
    {"provider_contract_schema_version", "document_kind", "translations"},
)
_TRANSLATION_FIELDS: Final = frozenset({"unit_id", "target_text", "segments"})
_SEGMENT_FIELDS: Final = frozenset({"segment_id", "target_text"})
def serialize_pptx_request(units: tuple[PptxRequestUnit, ...]) -> str:
    validate_request_units(units)
    payload = {
        "provider_contract_schema_version": PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION,
        "document_kind": PPTX_DOCUMENT_KIND,
        "units": [_serialize_unit(unit) for unit in units],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_pptx_response(
    raw: str,
    expected_units: tuple[PptxRequestUnit, ...],
) -> tuple[PptxUnitTranslation, ...]:
    payload = _parse_json_object(_strip_json_fence(raw))
    _require_exact_fields(payload, _ROOT_FIELDS)
    if _integer(payload["provider_contract_schema_version"]) != PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION:
        raise PptxContractError("schema_version", "unsupported provider contract version")
    if _string(payload["document_kind"]) != PPTX_DOCUMENT_KIND:
        raise PptxContractError("document_kind", "unexpected document kind")
    items = _array(payload["translations"])
    if len(items) != len(expected_units):
        raise PptxContractError("unit_count", "translation count does not match request")

    translations: list[PptxUnitTranslation] = []
    for raw_item, unit in zip(items, expected_units, strict=True):
        item = _mapping(raw_item)
        _require_exact_fields(item, _TRANSLATION_FIELDS, unit.unit_id)
        unit_id = _string(item["unit_id"], unit.unit_id)
        if unit_id != unit.unit_id:
            raise PptxContractError("unit_order", "unit ID or order differs from request", unit.unit_id)
        # The aggregate field is retained for provider compatibility, but the
        # segment stream is the source of truth because it is what gets written.
        _string(item["target_text"], unit.unit_id)
        segments = _parse_segments(item["segments"], unit)
        translation = PptxUnitTranslation(
            unit_id,
            reconstruct_target(unit, segments),
            segments,
        )
        validate_unit_translation(unit, translation)
        translations.append(translation)
    return tuple(translations)


def _serialize_unit(unit: PptxRequestUnit) -> dict[str, JsonValue]:
    return {
        "unit_id": unit.unit_id,
        "source_text": unit.source_text,
        "source_stream": [_serialize_stream_item(item) for item in unit.source_stream],
        "source_language": unit.source_language,
        "target_language": unit.target_language,
        "context": {
            "previous_text": unit.context.previous_text,
            "next_text": unit.context.next_text,
            "title_text": unit.context.title_text,
        },
        "layout_hint": {
            "x_emu": unit.layout_hint.x_emu,
            "y_emu": unit.layout_hint.y_emu,
            "width_emu": unit.layout_hint.width_emu,
            "height_emu": unit.layout_hint.height_emu,
        },
        "glossary": [
            {"source": item.source, "target": item.target}
            for item in unit.glossary
        ],
        "protected_terms": list(unit.protected_terms),
    }


def _serialize_stream_item(item: PptxSourceStreamItem) -> dict[str, JsonValue]:
    match item:
        case PptxTextStreamItem():
            return {
                "stream_id": item.stream_id,
                "kind": item.kind,
                "segment_id": item.segment_id,
                "source_text": item.source_text,
            }
        case PptxLineBreakStreamItem():
            return {"stream_id": item.stream_id, "kind": item.kind}
        case PptxProtectedFieldStreamItem():
            return {"stream_id": item.stream_id, "kind": item.kind, "source_text": item.source_text}
        case _ as unreachable:
            assert_never(unreachable)


def _parse_segments(raw: JsonValue, unit: PptxRequestUnit) -> tuple[PptxSegmentTranslation, ...]:
    items = _array(raw, unit.unit_id)
    expected = unit.text_items
    if len(items) != len(expected):
        raise PptxContractError("segment_count", "segment count differs from request", unit.unit_id)
    parsed: list[PptxSegmentTranslation] = []
    for raw_item, source in zip(items, expected, strict=True):
        item = _mapping(raw_item, unit.unit_id)
        _require_exact_fields(item, _SEGMENT_FIELDS, unit.unit_id)
        segment_id = _string(item["segment_id"], unit.unit_id)
        if segment_id != source.segment_id:
            raise PptxContractError("segment_order", "segment ID or order differs from request", unit.unit_id)
        parsed.append(PptxSegmentTranslation(segment_id, _string(item["target_text"], unit.unit_id)))
    return tuple(parsed)


def _parse_json_object(raw: str) -> dict[str, JsonValue]:
    try:
        value: JsonValue = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PptxContractError("malformed_json", "response is not valid JSON") from exc
    return _mapping(value)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise PptxContractError("duplicate_json_key", "response contains a duplicate key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> JsonValue:
    raise PptxContractError("non_finite_number", f"invalid JSON number: {value}")


def _mapping(value: JsonValue, unit_id: str = "*") -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise PptxContractError("schema_mismatch", "expected a JSON object", unit_id)
    return dict(value)


def _array(value: JsonValue, unit_id: str = "*") -> list[JsonValue]:
    if not isinstance(value, list):
        raise PptxContractError("schema_mismatch", "expected a JSON array", unit_id)
    return list(value)


def _string(value: JsonValue, unit_id: str = "*") -> str:
    if not isinstance(value, str):
        raise PptxContractError("schema_mismatch", "expected a string", unit_id)
    return value


def _integer(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PptxContractError("schema_mismatch", "expected an integer")
    return value


def _require_exact_fields(
    value: dict[str, JsonValue],
    expected: frozenset[str],
    unit_id: str = "*",
) -> None:
    if frozenset(value) != expected:
        raise PptxContractError("schema_mismatch", "missing or unknown response field", unit_id)


def _strip_json_fence(raw: str) -> str:
    stripped = raw.strip()
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0] == "```json" and lines[-1] == "```":
        return "\n".join(lines[1:-1])
    return stripped


__all__ = [
    "PPTX_DOCUMENT_KIND",
    "PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION",
    "PPTX_PROVIDER_FIELD",
    "PptxContractError",
    "PptxSegmentTranslation",
    "PptxUnitTranslation",
    "parse_pptx_response",
    "reconstruct_target",
    "reserved_marker_counts",
    "serialize_pptx_request",
    "validate_pptx_translations",
]
