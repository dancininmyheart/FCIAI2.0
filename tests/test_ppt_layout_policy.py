from __future__ import annotations

import logging
from xml.etree import ElementTree

import pytest

from app.function.pynuo_fuc.pptx_xml_autofit import A_NS, enable_textbox_autofit_for_paragraph


def test_legacy_policy_writes_exactly_one_normal_autofit_and_keeps_geometry() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:off x='10' y='20'/><a:ext cx='3000000' cy='400000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:noAutofit/><a:spAutoFit/><a:normAutofit/></a:bodyPr>"
        "<a:lstStyle/><a:p><a:r><a:t>HEAD long TAIL</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None
    geometry_before = ElementTree.tostring(root.find(f".//{{{A_NS}}}xfrm"))

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="legacy_norm")
    enable_textbox_autofit_for_paragraph(root, paragraph, policy="legacy_norm")

    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    assert body_pr is not None
    assert [child.tag for child in body_pr].count(f"{{{A_NS}}}normAutofit") == 1
    normal_autofit = body_pr.find(f"{{{A_NS}}}normAutofit")
    assert normal_autofit is not None
    assert normal_autofit.attrib == {"fontScale": "100000", "lnSpcReduction": "0"}
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert body_pr.find(f"{{{A_NS}}}spAutoFit") is None
    assert ElementTree.tostring(root.find(f".//{{{A_NS}}}xfrm")) == geometry_before


def test_legacy_policy_persists_a_bounded_scale_for_long_bilingual_text() -> None:
    short_root = _textbox_xml("Benefits of partially hydrolysed formula")
    long_root = _textbox_xml(
        "Benefits of partially hydrolysed formula for infants with an increased risk of allergy\n"
        "部分水解配方对过敏风险较高婴儿的益处，以及长期喂养期间相关临床结果的综合说明"
    )

    short_paragraph = short_root.find(f".//{{{A_NS}}}p")
    long_paragraph = long_root.find(f".//{{{A_NS}}}p")
    assert short_paragraph is not None
    assert long_paragraph is not None

    enable_textbox_autofit_for_paragraph(short_root, short_paragraph, policy="legacy_norm")
    enable_textbox_autofit_for_paragraph(long_root, long_paragraph, policy="legacy_norm")

    short_autofit = short_root.find(f".//{{{A_NS}}}normAutofit")
    long_autofit = long_root.find(f".//{{{A_NS}}}normAutofit")
    assert short_autofit is not None
    assert long_autofit is not None
    assert short_autofit.get("fontScale") == "100000"
    assert 60000 <= int(long_autofit.get("fontScale", "0")) < 100000
    assert 0 <= int(long_autofit.get("lnSpcReduction", "-1")) <= 20000


def test_editable_policy_bakes_a_needed_scale_into_the_font_size() -> None:
    root = _textbox_xml("Long translated content with wide glyphs 译文 " * 20)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert run_properties is not None
    assert body_pr.find(f"{{{A_NS}}}normAutofit") is None
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is not None
    assert 100 <= int(run_properties.get("sz", "0")) < 2000


def test_editable_policy_keeps_shrinking_when_legacy_line_reduction_would_be_needed() -> None:
    root = _textbox_xml("Crowded translated content 译文 " * 80)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert run_properties is not None
    assert 100 <= int(run_properties.get("sz", "0")) < 1200
    assert root.find(f".//{{{A_NS}}}normAutofit") is None


def test_editable_policy_preserves_low_norm_when_inherited_font_is_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:ext cx='3657600' cy='400000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:normAutofit fontScale='60000'/></a:bodyPr>"
        "<a:lstStyle/><a:p><a:r><a:rPr b='1'/><a:t>"
        + ("Inherited ten point text " * 20)
        + "</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert paragraph is not None
    assert run_properties is not None
    body_properties_before = ElementTree.tostring(body_pr)
    run_attributes_before = dict(run_properties.attrib)

    with caplog.at_level(logging.WARNING):
        enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(body_pr) == body_properties_before
    assert run_properties.attrib == run_attributes_before
    normal_autofit = body_pr.find(f"{{{A_NS}}}normAutofit")
    assert normal_autofit is not None
    assert normal_autofit.get("fontScale") == "60000"
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert "pptx_editable_autofit_skipped reason=unresolved_inherited_font_size" in caplog.text
    assert "Inherited ten point text" not in caplog.text


def test_editable_policy_does_not_partially_bake_a_mixed_resolution_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:ext cx='3657600' cy='400000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:normAutofit fontScale='60000'/></a:bodyPr>"
        "<a:lstStyle/><a:p>"
        "<a:r><a:rPr sz='2000' lang='en-US'/><a:t>Resolved private text</a:t></a:r>"
        "<a:r><a:rPr b='1'/><a:t>Unresolved private text</a:t></a:r>"
        "</a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_pr is not None
    assert paragraph is not None
    paragraph_before = ElementTree.tostring(paragraph)

    with caplog.at_level(logging.WARNING):
        enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(paragraph) == paragraph_before
    normal_autofit = body_pr.find(f"{{{A_NS}}}normAutofit")
    assert normal_autofit is not None
    assert normal_autofit.get("fontScale") == "60000"
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert caplog.text.count(
        "pptx_editable_autofit_skipped reason=unresolved_inherited_font_size",
    ) == 1
    assert "Resolved private text" not in caplog.text
    assert "Unresolved private text" not in caplog.text


@pytest.mark.parametrize(
    "autofit_markup",
    (
        "<a:normAutofit fontScale='60000' lnSpcReduction='10000'/>",
        "<a:spAutoFit/>",
        "<a:noAutofit/>",
        "",
    ),
)
def test_editable_policy_preserves_every_autofit_boundary_when_baking_is_unsafe(
    autofit_markup: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_text = "Unresolved boundary text " * 30
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:ext cx='3657600' cy='400000'/></a:xfrm></p:spPr>"
        f"<p:txBody><a:bodyPr>{autofit_markup}</a:bodyPr><a:lstStyle/>"
        f"<a:p><a:r><a:rPr lang='en-US'/><a:t>{private_text}</a:t></a:r></a:p>"
        "</p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert paragraph is not None
    assert run_properties is not None
    body_properties_before = ElementTree.tostring(body_pr)
    run_attributes_before = dict(run_properties.attrib)

    with caplog.at_level(logging.WARNING):
        enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(body_pr) == body_properties_before
    assert run_properties.attrib == run_attributes_before
    assert "pptx_editable_autofit_skipped reason=unresolved_inherited_font_size" in caplog.text
    assert private_text.strip() not in caplog.text


@pytest.mark.parametrize(
    "autofit_markup",
    (
        "<a:normAutofit fontScale='100000' lnSpcReduction='0'/>",
        "<a:spAutoFit/>",
        "<a:noAutofit/>",
        "",
    ),
)
def test_editable_policy_keeps_full_scale_autofit_boundaries_unchanged(
    autofit_markup: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:ext cx='10000000' cy='5000000'/></a:xfrm></p:spPr>"
        f"<p:txBody><a:bodyPr>{autofit_markup}</a:bodyPr><a:lstStyle/>"
        "<a:p><a:r><a:rPr lang='en-US'/><a:t>Short inherited text</a:t></a:r></a:p>"
        "</p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert paragraph is not None
    assert run_properties is not None
    body_properties_before = ElementTree.tostring(body_pr)
    run_attributes_before = dict(run_properties.attrib)

    with caplog.at_level(logging.WARNING):
        enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(body_pr) == body_properties_before
    assert run_properties.attrib == run_attributes_before
    assert "pptx_editable_autofit_skipped" not in caplog.text


def test_editable_policy_preserves_full_font_scale_with_line_spacing_reduction() -> None:
    root = _textbox_xml("Short translated text")
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert paragraph is not None
    assert run_properties is not None
    body_pr.append(
        ElementTree.Element(
            f"{{{A_NS}}}normAutofit",
            {"fontScale": "100000", "lnSpcReduction": "12000"},
        ),
    )
    body_properties_before = ElementTree.tostring(body_pr)
    run_attributes_before = dict(run_properties.attrib)

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(body_pr) == body_properties_before
    assert run_properties.attrib == run_attributes_before


def test_editable_policy_preserves_line_reduction_when_geometry_is_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_text = "Private content without resolvable geometry " * 20
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:txBody><a:bodyPr>"
        "<a:normAutofit fontScale='100000' lnSpcReduction='12000'/>"
        "</a:bodyPr><a:lstStyle/><a:p>"
        f"<a:r><a:rPr sz='2000'/><a:t>{private_text}</a:t></a:r>"
        "</a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    run_properties = root.find(f".//{{{A_NS}}}rPr")
    assert body_pr is not None
    assert paragraph is not None
    assert run_properties is not None
    body_properties_before = ElementTree.tostring(body_pr)
    run_attributes_before = dict(run_properties.attrib)

    with caplog.at_level(logging.WARNING):
        enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert ElementTree.tostring(body_pr) == body_properties_before
    assert run_properties.attrib == run_attributes_before
    assert (
        "pptx_editable_autofit_skipped reason=unmaterialized_line_spacing_reduction"
        in caplog.text
    )
    assert private_text.strip() not in caplog.text


def test_editable_policy_bakes_effective_sizes_without_flattening_rich_text() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}' xmlns:r='urn:r'>"
        "<p:spPr><a:xfrm><a:ext cx='10000000' cy='5000000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:normAutofit fontScale='80000'/></a:bodyPr>"
        "<a:lstStyle><a:lvl1pPr><a:defRPr sz='1000'/></a:lvl1pPr></a:lstStyle>"
        "<a:p><a:pPr algn='ctr'><a:buChar char='•'/><a:defRPr sz='1600' lang='en-US'/></a:pPr>"
        "<a:r><a:rPr sz='2000' b='1' i='1' lang='fr-FR'><a:solidFill><a:srgbClr val='AA0000'/></a:solidFill><a:hlinkClick r:id='rId7'/></a:rPr><a:t>One</a:t></a:r>"
        "<a:fld id='{A}' type='slidenum'><a:rPr lang='en-US'/><a:pPr><a:defRPr sz='1400' lang='de-DE'/></a:pPr><a:t>1</a:t></a:fld>"
        "<a:r><a:t>Two</a:t></a:r><a:endParaRPr sz='1200' lang='en-US'/></a:p>"
        "<a:p><a:pPr lvl='0'><a:buChar char='-'/></a:pPr><a:r><a:t>Three</a:t></a:r>"
        "<a:endParaRPr lang='en-US'/></a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert root.find(f".//{{{A_NS}}}normAutofit") is None
    assert root.find(f".//{{{A_NS}}}noAutofit") is not None
    assert [node.text for node in root.findall(f".//{{{A_NS}}}t")] == [
        "One",
        "1",
        "Two",
        "Three",
    ]
    assert [node.get("sz") for node in root.findall(f".//{{{A_NS}}}r/{{{A_NS}}}rPr")] == [
        "1600",
        "1280",
        "800",
    ]
    assert root.find(f".//{{{A_NS}}}fld/{{{A_NS}}}rPr").get("sz") == "1120"
    assert root.find(
        f".//{{{A_NS}}}fld/{{{A_NS}}}pPr/{{{A_NS}}}defRPr",
    ).get("sz") == "1120"
    assert [
        node.get("sz") for node in root.findall(f".//{{{A_NS}}}endParaRPr")
    ] == ["960", "800"]
    assert root.find(f".//{{{A_NS}}}pPr/{{{A_NS}}}defRPr").get("sz") == "1280"
    assert root.find(f".//{{{A_NS}}}lvl1pPr/{{{A_NS}}}defRPr").get("sz") == "1000"
    rich_properties = root.find(f".//{{{A_NS}}}r/{{{A_NS}}}rPr[@b='1']")
    assert rich_properties is not None
    assert rich_properties.get("i") == "1"
    assert rich_properties.get("lang") == "fr-FR"
    assert rich_properties.find(f"{{{A_NS}}}solidFill") is not None
    assert rich_properties.find(f"{{{A_NS}}}hlinkClick").get("{urn:r}id") == "rId7"
    assert len(root.findall(f".//{{{A_NS}}}buChar")) == 2


def test_editable_policy_materializes_local_default_list_style_size() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:ext cx='10000000' cy='5000000'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr><a:normAutofit fontScale='80000'/></a:bodyPr>"
        "<a:lstStyle><a:defPPr><a:defRPr sz='1500'/></a:defPPr></a:lstStyle>"
        "<a:p><a:r><a:t>Inherited locally</a:t></a:r><a:endParaRPr/></a:p>"
        "</p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert root.find(f".//{{{A_NS}}}r/{{{A_NS}}}rPr").get("sz") == "1200"
    assert root.find(f".//{{{A_NS}}}endParaRPr").get("sz") == "1200"


def test_editable_policy_keeps_autofit_in_the_body_property_schema_slot() -> None:
    root = _textbox_xml("Schema ordered text")
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_pr is not None
    assert paragraph is not None
    body_pr.extend(
        (
            ElementTree.Element(f"{{{A_NS}}}prstTxWarp", {"prst": "textNoShape"}),
            ElementTree.Element(f"{{{A_NS}}}normAutofit", {"fontScale": "80000"}),
            ElementTree.Element(f"{{{A_NS}}}scene3d"),
        ),
    )

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert [child.tag.rsplit("}", 1)[-1] for child in body_pr] == [
        "prstTxWarp",
        "noAutofit",
        "scene3d",
    ]


def test_editable_policy_preserves_sp_autofit_when_translated_text_already_fits() -> None:
    root = _textbox_xml("Short translated text")
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_pr is not None
    assert paragraph is not None
    body_pr.append(ElementTree.Element(f"{{{A_NS}}}spAutoFit"))

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert body_pr.find(f"{{{A_NS}}}spAutoFit") is not None
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert body_pr.find(f"{{{A_NS}}}normAutofit") is None
    assert root.find(f".//{{{A_NS}}}rPr").get("sz") == "2000"


def test_editable_policy_freezes_geometry_when_sp_autofit_expansion_would_be_needed() -> None:
    root = _textbox_xml("Translated content that cannot expand safely 译文 " * 20)
    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_pr is not None
    assert paragraph is not None
    body_pr.append(ElementTree.Element(f"{{{A_NS}}}spAutoFit"))

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="editable")

    assert body_pr.find(f"{{{A_NS}}}spAutoFit") is None
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is not None
    assert body_pr.find(f"{{{A_NS}}}normAutofit") is None
    assert 100 <= int(root.find(f".//{{{A_NS}}}rPr").get("sz")) < 2000


def test_legacy_policy_uses_a_deterministic_scale_when_geometry_is_missing() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'><p:txBody><a:bodyPr/><a:lstStyle/>"
        "<a:p><a:r><a:rPr sz='1800'/><a:t>"
        + ("Long translated content 长篇双语译文 " * 100)
        + "</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="legacy_norm")
    first_autofit = root.find(f".//{{{A_NS}}}normAutofit")
    assert first_autofit is not None
    first_attributes = dict(first_autofit.attrib)
    enable_textbox_autofit_for_paragraph(root, paragraph, policy="legacy_norm")
    second_autofit = root.find(f".//{{{A_NS}}}normAutofit")
    assert second_autofit is not None
    second_attributes = dict(second_autofit.attrib)

    assert first_attributes == second_attributes
    assert int(first_attributes["fontScale"]) == 60000
    assert 0 <= int(first_attributes["lnSpcReduction"]) <= 20000


def test_legacy_policy_accounts_for_textbox_margins() -> None:
    text = "Bilingual translated content 双语翻译内容 " * 5
    regular_root = _textbox_xml(text)
    inset_root = _textbox_xml(text)
    inset_body_properties = inset_root.find(f".//{{{A_NS}}}bodyPr")
    assert inset_body_properties is not None
    inset_body_properties.set("lIns", "700000")
    inset_body_properties.set("rIns", "700000")

    regular_paragraph = regular_root.find(f".//{{{A_NS}}}p")
    inset_paragraph = inset_root.find(f".//{{{A_NS}}}p")
    assert regular_paragraph is not None
    assert inset_paragraph is not None
    enable_textbox_autofit_for_paragraph(regular_root, regular_paragraph, policy="legacy_norm")
    enable_textbox_autofit_for_paragraph(inset_root, inset_paragraph, policy="legacy_norm")

    regular_autofit = regular_root.find(f".//{{{A_NS}}}normAutofit")
    inset_autofit = inset_root.find(f".//{{{A_NS}}}normAutofit")
    assert regular_autofit is not None
    assert inset_autofit is not None
    assert int(inset_autofit.get("fontScale", "0")) < int(
        regular_autofit.get("fontScale", "0")
    )


def test_legacy_policy_uses_conservative_autofit_when_no_area_is_usable() -> None:
    root = _textbox_xml("Translated content 译文")
    body_properties = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_properties is not None
    assert paragraph is not None
    body_properties.set("lIns", "2000000")
    body_properties.set("rIns", "2000000")

    enable_textbox_autofit_for_paragraph(root, paragraph, policy="legacy_norm")

    normal_autofit = root.find(f".//{{{A_NS}}}normAutofit")
    assert normal_autofit is not None
    assert normal_autofit.attrib == {
        "fontScale": "60000",
        "lnSpcReduction": "20000",
    }


def _textbox_xml(text: str) -> ElementTree.Element:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:off x='0' y='0'/><a:ext cx='3657600' cy='1097280'/></a:xfrm></p:spPr>"
        "<p:txBody><a:bodyPr lIns='91440' rIns='91440' tIns='45720' bIns='45720'/>"
        "<a:lstStyle/><a:p><a:r><a:rPr sz='2000'/><a:t>"
        f"{text}</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    return ElementTree.fromstring(xml)
