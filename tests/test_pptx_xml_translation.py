from __future__ import annotations

import zipfile
import sys
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree


PPTX_XML_MODULE_DIR = Path(__file__).resolve().parents[1] / "app" / "function" / "pynuo_fuc"
sys.path.insert(0, str(PPTX_XML_MODULE_DIR))

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def test_extract_text_boxes_data_from_pptx_reads_slide_xml_paragraphs(tmp_path: Path) -> None:
    # Given
    from pptx_xml_translate import extract_text_boxes_data_from_pptx

    pptx_path = tmp_path / "source.pptx"
    _write_minimal_pptx(pptx_path, _slide_xml(["Hello", " world"]), _slide_xml(["Skip me"]))

    # When
    text_boxes = extract_text_boxes_data_from_pptx(pptx_path, selected_page_indices=[0])

    # Then
    assert text_boxes == [
        {
            "page_index": 0,
            "box_index": 0,
            "box_id": "xml_box_0",
            "paragraph_index": 0,
            "paragraph_id": "xml_para_0_0",
            "combined_text": "Hello world",
        }
    ]


def test_write_translated_pptx_xml_replaces_only_selected_slide_text(tmp_path: Path) -> None:
    # Given
    from pptx_xml_translate import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )

    pptx_path = tmp_path / "source.pptx"
    output_path = tmp_path / "translated.pptx"
    _write_minimal_pptx(pptx_path, _slide_xml(["Hello", " world"]), _slide_xml(["Keep me"]))
    text_boxes = extract_text_boxes_data_from_pptx(pptx_path, selected_page_indices=[0])

    # When
    write_translated_pptx_xml(
        pptx_path,
        output_path,
        text_boxes,
        {0: {"translated_fragments": {"1_1": ["Bonjour le monde"]}}},
        "translation_only",
    )

    # Then
    slide1 = _read_slide_xml(output_path, 1)
    slide2 = _read_slide_xml(output_path, 2)
    assert _texts(slide1) == ["Bonjour le monde", ""]
    assert _texts(slide2) == ["Keep me"]
    assert slide1.find(".//a:rPr[@sz='2400']", NS) is not None
    assert slide1.find(".//a:bodyPr/a:noAutofit", NS) is None
    assert slide1.find(".//a:bodyPr/a:normAutofit", NS) is None


def test_legacy_translation_only_preserves_slide_xml_for_normalized_equivalent_text(
    tmp_path: Path,
) -> None:
    from pptx_xml_translate import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )

    pptx_path = tmp_path / "source.pptx"
    output_path = tmp_path / "translated.pptx"
    _write_minimal_pptx(
        pptx_path,
        _slide_xml(
            ["Milk 72%"],
            body_pr_children="<a:normAutofit fontScale='60000' lnSpcReduction='0'/>",
        ),
    )
    text_boxes = extract_text_boxes_data_from_pptx(pptx_path)

    write_translated_pptx_xml(
        pptx_path,
        output_path,
        text_boxes,
        {0: {"translated_fragments": {"1_1": [" milk\u300072% "]}}},
        "translation_only",
    )

    with zipfile.ZipFile(pptx_path) as source, zipfile.ZipFile(output_path) as output:
        assert output.read("ppt/slides/slide1.xml") == source.read("ppt/slides/slide1.xml")


def test_translate_pptx_with_xml_appends_bilingual_text_without_removing_original_runs(
    tmp_path: Path,
) -> None:
    # Given
    from pptx_xml_translate import (
        XmlTranslationRequest,
        translate_pptx_with_xml,
    )

    pptx_path = tmp_path / "source.pptx"
    output_path = tmp_path / "translated.pptx"
    _write_minimal_pptx(pptx_path, _slide_xml(["Hello", " world"]), _slide_xml(["Second"]))

    def fake_translate(*args, **kwargs):
        return {0: {"translated_fragments": {"1_1": ["Bonjour le monde"]}}}

    request = XmlTranslationRequest(
        input_path=pptx_path,
        output_path=output_path,
        selected_page_indices=(0,),
        source_language="English",
        target_language="French",
        model="qwen",
        stop_words=(),
        custom_translations={},
        bilingual_translation="paragraph_up",
        progress_callback=None,
    )

    # When
    result_path = translate_pptx_with_xml(request, translator=fake_translate)

    # Then
    slide = _read_slide_xml(Path(result_path), 1)
    assert _texts(slide) == ["Hello", " world", "Bonjour le monde"]
    assert slide.find(".//a:br", NS) is not None


def test_legacy_writer_snapshots_legacy_normal_policy_from_flask_config(
    tmp_path: Path,
) -> None:
    # Given
    from pptx_xml_translate import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )
    from flask import Flask

    pptx_path = tmp_path / "source.pptx"
    output_path = tmp_path / "translated.pptx"
    _write_minimal_pptx(
        pptx_path,
        _slide_xml(["Hello"], body_pr_children="<a:noAutofit/>"),
    )
    text_boxes = extract_text_boxes_data_from_pptx(pptx_path, selected_page_indices=[0])

    # When
    app = Flask("pptx-autofit-policy-test")
    app.config["PPTX_XML_AUTOFIT_POLICY"] = "legacy_norm"
    with app.app_context():
        write_translated_pptx_xml(
            pptx_path,
            output_path,
            text_boxes,
            {0: {"translated_fragments": {"1_1": ["你好"]}}},
            "paragraph_up",
        )

    # Then
    slide = _read_slide_xml(output_path, 1)
    body_pr = slide.find(".//a:bodyPr", NS)
    assert body_pr is not None
    assert body_pr.find("a:normAutofit", NS) is not None
    assert body_pr.find("a:noAutofit", NS) is None


def test_write_translated_pptx_xml_keeps_prefix_required_by_compatibility_markup(
    tmp_path: Path,
) -> None:
    from pptx_xml_translate import (
        extract_text_boxes_data_from_pptx,
        write_translated_pptx_xml,
    )

    pptx_path = tmp_path / "source.pptx"
    output_path = tmp_path / "translated.pptx"
    _write_minimal_pptx(pptx_path, _slide_xml_with_p14_transition("Hello"))
    text_boxes = extract_text_boxes_data_from_pptx(pptx_path)

    write_translated_pptx_xml(
        pptx_path,
        output_path,
        text_boxes,
        {0: {"translated_fragments": {"1_1": ["Bonjour"]}}},
        "translation_only",
    )

    with zipfile.ZipFile(output_path) as archive:
        slide_data = archive.read("ppt/slides/slide1.xml")
    declared_prefixes = {
        prefix
        for _, (prefix, _) in ElementTree.iterparse(BytesIO(slide_data), events=("start-ns",))
    }
    assert "p14" in declared_prefixes, (
        'PowerPoint cannot resolve mc:Choice Requires="p14" after slide XML is rewritten'
    )


def _write_minimal_pptx(path: Path, *slides: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p='%s' />" % NS["p"])
        for index, slide_xml in enumerate(slides, 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", slide_xml)


def _slide_xml(text_runs: list[str], body_pr_children: str = "") -> str:
    runs = "".join(
        f"<a:r><a:rPr lang='en-US' sz='2400'/><a:t>{text}</a:t></a:r>"
        for text in text_runs
    )
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{NS['a']}' xmlns:p='{NS['p']}' xmlns:r='{NS['r']}'>"
        f"<p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr>{body_pr_children}</a:bodyPr><a:lstStyle/>"
        f"<a:p>{runs}</a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )


def _slide_xml_with_p14_transition(text: str) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        f"<p:sld xmlns:a='{NS['a']}' xmlns:p='{NS['p']}' xmlns:r='{NS['r']}' "
        "xmlns:mc='http://schemas.openxmlformats.org/markup-compatibility/2006' "
        "xmlns:p14='http://schemas.microsoft.com/office/powerpoint/2010/main' "
        "mc:Ignorable='p14'>"
        "<p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/><a:lstStyle/>"
        f"<a:p><a:r><a:t>{text}</a:t></a:r></a:p>"
        "</p:txBody></p:sp></p:spTree></p:cSld>"
        "<mc:AlternateContent><mc:Choice Requires='p14'>"
        "<p:transition/></mc:Choice>"
        "<mc:Fallback><p:transition/></mc:Fallback></mc:AlternateContent>"
        "</p:sld>"
    )


def _read_slide_xml(path: Path, slide_number: int) -> ElementTree.Element:
    with zipfile.ZipFile(path) as archive:
        data = archive.read(f"ppt/slides/slide{slide_number}.xml")
    return ElementTree.fromstring(data)


def _texts(root: ElementTree.Element) -> list[str]:
    return [node.text or "" for node in root.findall(".//a:t", NS)]
