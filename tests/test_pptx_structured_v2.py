"""End-to-end PPTX V2 acceptance tests.

# noqa: SIZE_OK - contract, writeback, and fallback acceptance stays self-contained.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

import pytest

from app.function.pynuo_fuc.pptx_xml_ops import (
    extract_structured_units_from_pptx,
    extract_text_boxes_data_from_pptx,
    write_structured_translated_pptx,
    write_translated_pptx_xml,
)
from app.function.pynuo_fuc.pptx_xml_translate import translate_pptx_with_xml
from app.function.pynuo_fuc.pptx_xml_types import (
    PptxXmlDuplicateShapeIdError,
    PptxXmlPackageError,
    XmlTranslationRequest,
)
from app.translation.pptx_contract import (
    PPTX_DOCUMENT_KIND,
    PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION,
    PptxContractError,
    PptxSegmentTranslation,
    PptxUnitTranslation,
    parse_pptx_response,
    serialize_pptx_request,
)
from app.translation.pptx_contract_types import JsonValue
from app.translation.providers import ProviderRegistry, QwenProvider
from app.translation.types import ProviderName, ProviderRequest, ProviderResult


A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
NS = {"a": A_NS, "p": P_NS, "mc": MC_NS}


@dataclass(frozen=True, slots=True)
class ContractProvider:
    responses: list[str] = field(default_factory=list)
    requests: list[ProviderRequest] = field(default_factory=list)

    @property
    def name(self) -> ProviderName:
        return "qwen"

    def translate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        if self.responses:
            response = self.responses.pop(0)
        else:
            payload = json.loads(request.text)
            translations = []
            for unit in payload["units"]:
                segments = [
                    {"segment_id": item["segment_id"], "target_text": f"T:{item['source_text']}"}
                    for item in unit["source_stream"]
                    if item["kind"] == "text"
                ]
                target = _reconstruct_target(unit["source_stream"], segments)
                translations.append(
                    {"unit_id": unit["unit_id"], "target_text": target, "segments": segments},
                )
            response = json.dumps(
                {
                    "provider_contract_schema_version": PPTX_PROVIDER_CONTRACT_SCHEMA_VERSION,
                    "document_kind": PPTX_DOCUMENT_KIND,
                    "translations": translations,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        return ProviderResult(response, "qwen", "fake-qwen")


@dataclass(frozen=True, slots=True)
class PromptTransport:
    calls: list[tuple[str, str, str, float]] = field(default_factory=list)

    def complete(self, model: str, system: str, user: str, timeout_seconds: float) -> str:
        self.calls.append((model, system, user, timeout_seconds))
        return "{}"


def test_structured_manifest_uses_stable_ids_and_explicit_control_stream(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    _write_minimal_pptx(source, _structured_slide_xml())

    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
        stop_words=("HMO",),
        custom_translations={"milk": "乳汁"},
    )

    assert len(units) == 1
    unit = units[0]
    assert unit.unit_id == "pptx:slide1:shapeId7:tbOrdinal0:p0"
    assert unit.source_text == "Hello\n1world"
    assert [item.kind for item in unit.source_stream] == [
        "text",
        "line_break",
        "protected_field",
        "text",
    ]
    assert [item.segment_id for item in unit.text_items] == [
        f"{unit.unit_id}:segment0",
        f"{unit.unit_id}:segment3",
    ]
    assert unit.protected_terms == ("HMO",)
    assert unit.glossary[0].source == "milk"


def test_table_cells_under_one_graphic_frame_get_distinct_text_body_ids(tmp_path: Path) -> None:
    source = tmp_path / "table.pptx"
    _write_minimal_pptx(source, _table_slide_xml())

    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )

    assert [unit.unit_id for unit in units] == [
        "pptx:slide1:shapeId9:tbOrdinal0:p0",
        "pptx:slide1:shapeId9:tbOrdinal1:p0",
    ]


def test_duplicate_shape_identity_is_a_typed_runtime_failure(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.pptx"
    duplicate_shapes = _simple_shape_xml(7, "First") + _simple_shape_xml(7, "Second")
    slide = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{A_NS}' xmlns:p='{P_NS}'><p:cSld><p:spTree>"
        f"{duplicate_shapes}</p:spTree></p:cSld></p:sld>"
    )
    _write_minimal_pptx(source, slide)

    with pytest.raises(PptxXmlDuplicateShapeIdError):
        extract_structured_units_from_pptx(
            source,
            source_language="English",
            target_language="Chinese",
        )


def test_provider_contract_is_exact_json_and_contains_no_internal_sentinel(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    _write_minimal_pptx(source, _structured_slide_xml())
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )

    raw = serialize_pptx_request(units)
    payload = json.loads(raw)

    assert list(payload) == [
        "provider_contract_schema_version",
        "document_kind",
        "units",
    ]
    assert payload["provider_contract_schema_version"] == 2
    assert payload["document_kind"] == "pptx_xml"
    assert "[block]" not in raw.casefold()
    assert "[块]" not in raw
    assert set(payload["units"][0]) == {
        "unit_id",
        "source_text",
        "source_stream",
        "source_language",
        "target_language",
        "context",
        "layout_hint",
        "glossary",
        "protected_terms",
    }


def test_qwen_v2_prompt_uses_ids_and_never_teaches_the_legacy_sentinel() -> None:
    transport = PromptTransport()
    request = ProviderRequest.create(
        text='{"provider_contract_schema_version":2}',
        source_language="English",
        target_language="Chinese",
        field="pptx_structured_v2",
    )

    QwenProvider(transport).translate(request)

    system = transport.calls[0][1]
    assert "unit_id" in system and "segment_id" in system
    assert "source_stream" in system and "protected_field" in system
    assert "[block]" not in system.casefold()
    assert "[块]" not in system


@pytest.mark.parametrize("leaked_marker", ("[块]", "［块］", "[ B L O C K ]"))
def test_response_parser_rejects_added_reserved_marker_even_when_quality_is_off(
    tmp_path: Path,
    leaked_marker: str,
) -> None:
    source = tmp_path / "source.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Milk"))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    translated = f"母乳{leaked_marker}"
    raw = _response_json(
        unit.unit_id,
        translated,
        [(unit.text_items[0].segment_id, translated)],
    )

    with pytest.raises(PptxContractError) as raised:
        parse_pptx_response(raw, units)

    assert raised.value.code == "reserved_marker_added"


def test_legacy_writer_also_rejects_translated_marker_leak(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "translated.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Milk"))
    text_boxes = extract_text_boxes_data_from_pptx(source)

    with pytest.raises(PptxContractError) as raised:
        write_translated_pptx_xml(
            source,
            output,
            text_boxes,
            {0: {"translated_fragments": {"1_1": ["母乳[块]"]}}},
            "translation_only",
        )

    assert raised.value.code == "reserved_marker_added"
    assert not output.exists()


def test_source_authored_reserved_literal_is_allowed_only_when_preserved(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Use [block] literally"))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    target = "按字面使用 [block]"
    response = _response_json(
        unit.unit_id,
        target,
        [(unit.text_items[0].segment_id, target)],
    )

    parsed = parse_pptx_response(response, units)

    assert parsed[0].target_text == target


def test_response_parser_rejects_unknown_fields_and_segment_order(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Hello", "world"))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    payload = json.loads(
        _response_json(
            unit.unit_id,
            "世界你好",
            [
                (unit.text_items[1].segment_id, "世界"),
                (unit.text_items[0].segment_id, "你好"),
            ],
        ),
    )
    payload["unexpected"] = True

    with pytest.raises(PptxContractError) as raised:
        parse_pptx_response(json.dumps(payload, ensure_ascii=False), units)

    assert raised.value.code == "schema_mismatch"


def test_structured_writer_preserves_runs_fields_breaks_and_required_prefix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "translated.pptx"
    _write_minimal_pptx(source, _structured_slide_xml(required_prefix_only=True))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    translations = (
        PptxUnitTranslation(
            unit_id=unit.unit_id,
            target_text="你好\n1世界",
            segments=(
                PptxSegmentTranslation(unit.text_items[0].segment_id, "你好"),
                PptxSegmentTranslation(unit.text_items[1].segment_id, "世界"),
            ),
        ),
    )

    write_structured_translated_pptx(source, output, translations, "translation_only")

    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        slide_data = archive.read("ppt/slides/slide1.xml")
    root = ElementTree.fromstring(slide_data)
    assert [node.text or "" for node in root.findall(".//a:r/a:t", NS)] == ["你好", "世界"]
    assert root.find(".//a:fld/a:t", NS).text == "1"
    assert len(root.findall(".//a:br", NS)) == 1
    assert root.find(".//a:rPr[@sz='2400']", NS) is not None
    assert root.find(".//a:bodyPr/a:normAutofit", NS) is not None
    assert "p14" in _declared_prefixes(slide_data)


def test_default_xml_engine_retries_invalid_contract_once_and_never_publishes_marker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "translated.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Milk"))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    provider = ContractProvider(
        responses=[
            _response_json(
                unit.unit_id,
                "母乳[块]",
                [(unit.text_items[0].segment_id, "母乳[块]")],
            ),
            _response_json(
                unit.unit_id,
                "母乳",
                [(unit.text_items[0].segment_id, "母乳")],
            ),
        ],
    )
    request = XmlTranslationRequest(
        input_path=source,
        output_path=output,
        selected_page_indices=None,
        source_language="English",
        target_language="Chinese",
        model="qwen",
        stop_words=(),
        custom_translations={},
        bilingual_translation="translation_only",
        progress_callback=None,
    )

    result = translate_pptx_with_xml(
        request,
        provider_registry=ProviderRegistry((provider,)),
    )

    assert result == str(output)
    assert len(provider.requests) == 2
    assert all(item.field == "pptx_structured_v2" for item in provider.requests)
    with zipfile.ZipFile(output) as archive:
        slide_data = archive.read("ppt/slides/slide1.xml")
    assert "[块]" not in slide_data.decode("utf-8")
    assert [node.text for node in ElementTree.fromstring(slide_data).findall(".//a:t", NS)] == ["母乳"]


def test_selected_page_translation_preserves_unselected_slide_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "translated.pptx"
    _write_minimal_pptx(
        source,
        _simple_slide_xml("First"),
        _simple_slide_xml("Second"),
    )
    request = XmlTranslationRequest(
        input_path=source,
        output_path=output,
        selected_page_indices=(0,),
        source_language="English",
        target_language="Chinese",
        model="qwen",
        stop_words=(),
        custom_translations={},
        bilingual_translation="translation_only",
        progress_callback=None,
    )
    provider = ContractProvider()

    translate_pptx_with_xml(request, provider_registry=ProviderRegistry((provider,)))

    with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as translated:
        assert translated.read("ppt/slides/slide2.xml") == original.read("ppt/slides/slide2.xml")
        assert translated.read("ppt/slides/slide1.xml") != original.read("ppt/slides/slide1.xml")
    assert len(provider.requests) == 1


def test_default_xml_engine_fails_closed_after_second_invalid_response(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    output = tmp_path / "translated.pptx"
    _write_minimal_pptx(source, _simple_slide_xml("Milk"))
    units = extract_structured_units_from_pptx(
        source,
        source_language="English",
        target_language="Chinese",
    )
    unit = units[0]
    invalid = _response_json(
        unit.unit_id,
        "母乳[块]",
        [(unit.text_items[0].segment_id, "母乳[块]")],
    )
    provider = ContractProvider(responses=[invalid, invalid])
    request = XmlTranslationRequest(
        input_path=source,
        output_path=output,
        selected_page_indices=None,
        source_language="English",
        target_language="Chinese",
        model="qwen",
        stop_words=(),
        custom_translations={},
        bilingual_translation="translation_only",
        progress_callback=None,
    )

    with pytest.raises(PptxContractError):
        translate_pptx_with_xml(request, provider_registry=ProviderRegistry((provider,)))

    assert len(provider.requests) == 2
    assert not output.exists()


def test_provider_contract_failure_never_enters_uno_runtime_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.function.pynuo_fuc import pyuno_controller as controller
    import pptx_xml_translate as xml_translate_module

    def fail_contract(_request: XmlTranslationRequest) -> str:
        raise PptxContractError("reserved_marker_added", "rejected")

    monkeypatch.setenv("PPTX_XML_RUNTIME_FALLBACK", "1")
    monkeypatch.setattr(xml_translate_module, "translate_pptx_with_xml", fail_contract)

    with pytest.raises(PptxContractError):
        _try_controller_xml_path(controller, tmp_path / "deck.pptx")


def test_typed_package_failure_uses_uno_fallback_only_when_explicitly_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.function.pynuo_fuc import pyuno_controller as controller
    import pptx_xml_translate as xml_translate_module

    def fail_package(_request: XmlTranslationRequest) -> str:
        raise PptxXmlPackageError("invalid package")

    monkeypatch.setattr(xml_translate_module, "translate_pptx_with_xml", fail_package)
    monkeypatch.setenv("PPTX_XML_RUNTIME_FALLBACK", "0")
    with pytest.raises(PptxXmlPackageError):
        _try_controller_xml_path(controller, tmp_path / "deck.pptx")

    monkeypatch.setenv("PPTX_XML_RUNTIME_FALLBACK", "1")
    assert _try_controller_xml_path(controller, tmp_path / "deck.pptx") is None


def _response_json(
    unit_id: str,
    target_text: str,
    segments: list[tuple[str, str]],
) -> str:
    return json.dumps(
        {
            "provider_contract_schema_version": 2,
            "document_kind": "pptx_xml",
            "translations": [
                {
                    "unit_id": unit_id,
                    "target_text": target_text,
                    "segments": [
                        {"segment_id": segment_id, "target_text": text}
                        for segment_id, text in segments
                    ],
                },
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _try_controller_xml_path(controller: ModuleType, path: Path) -> str | None:
    translate = getattr(controller, "_try_translate_pptx_with_xml")
    result: str | None = translate(
        str(path),
        [],
        {},
        [],
        "English",
        "Chinese",
        "translation_only",
        None,
        "qwen",
    )
    return result


def _reconstruct_target(
    source_stream: list[dict[str, JsonValue]],
    segments: list[dict[str, str]],
) -> str:
    translated = {item["segment_id"]: item["target_text"] for item in segments}
    parts: list[str] = []
    for item in source_stream:
        kind = item["kind"]
        if kind == "text":
            parts.append(translated[str(item["segment_id"])])
        elif kind == "line_break":
            parts.append("\n")
        else:
            parts.append(str(item["source_text"]))
    return "".join(parts)


def _write_minimal_pptx(path: Path, *slide_xml: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("ppt/presentation.xml", f"<p:presentation xmlns:p='{P_NS}' />")
        for index, slide in enumerate(slide_xml, 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", slide)


def _simple_slide_xml(*text_runs: str) -> str:
    runs = "".join(f"<a:r><a:rPr sz='2400'/><a:t>{text}</a:t></a:r>" for text in text_runs)
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{A_NS}' xmlns:p='{P_NS}'>"
        "<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id='7' name='Text'/></p:nvSpPr>"
        "<p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p>{runs}</a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )


def _simple_shape_xml(shape_id: int, text: str) -> str:
    return (
        f"<p:sp><p:nvSpPr><p:cNvPr id='{shape_id}' name='Text'/></p:nvSpPr>"
        "<p:txBody><a:bodyPr/><a:lstStyle/><a:p>"
        f"<a:r><a:t>{text}</a:t></a:r>"
        "</a:p></p:txBody></p:sp>"
    )


def _table_slide_xml() -> str:
    cells = "".join(
        (
            "<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p>"
            f"<a:r><a:t>{text}</a:t></a:r>"
            "</a:p></a:txBody></a:tc>"
        )
        for text in ("Cell one", "Cell two")
    )
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{A_NS}' xmlns:p='{P_NS}'><p:cSld><p:spTree>"
        "<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id='9' name='Table'/>"
        "</p:nvGraphicFramePr><a:graphic><a:graphicData><a:tbl><a:tr>"
        f"{cells}</a:tr></a:tbl></a:graphicData></a:graphic>"
        "</p:graphicFrame></p:spTree></p:cSld></p:sld>"
    )


def _structured_slide_xml(*, required_prefix_only: bool = False) -> str:
    compatibility = (
        "<mc:AlternateContent><mc:Choice Requires='p14'><p:transition/></mc:Choice>"
        "<mc:Fallback><p:transition/></mc:Fallback></mc:AlternateContent>"
        if required_prefix_only
        else ""
    )
    declarations = f" xmlns:mc='{MC_NS}' xmlns:p14='{P14_NS}' mc:Ignorable='p14'" if required_prefix_only else ""
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{A_NS}' xmlns:p='{P_NS}'{declarations}>"
        "<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id='7' name='Text'/></p:nvSpPr>"
        "<p:spPr><a:xfrm><a:off x='10' y='20'/><a:ext cx='3000' cy='4000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr><a:lstStyle/><a:p>"
        "<a:r><a:rPr lang='en-US' sz='2400'/><a:t>Hello</a:t></a:r>"
        "<a:br/><a:fld id='{A}' type='slidenum'><a:rPr/><a:t>1</a:t></a:fld>"
        "<a:r><a:rPr lang='en-US' sz='1800'/><a:t>world</a:t></a:r>"
        "</a:p></p:txBody></p:sp></p:spTree></p:cSld>"
        f"{compatibility}</p:sld>"
    )


def _declared_prefixes(xml_data: bytes) -> set[str]:
    return {
        prefix
        for _, (prefix, _) in ElementTree.iterparse(BytesIO(xml_data), events=("start-ns",))
    }
