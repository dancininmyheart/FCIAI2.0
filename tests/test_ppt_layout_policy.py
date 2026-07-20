from __future__ import annotations

from xml.etree import ElementTree

from app.function.pynuo_fuc.pptx_xml_autofit import A_NS, enable_textbox_autofit_for_paragraph


def test_changed_textbox_has_exactly_one_normal_autofit_and_keeps_geometry() -> None:
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

    enable_textbox_autofit_for_paragraph(root, paragraph)
    enable_textbox_autofit_for_paragraph(root, paragraph)

    body_pr = root.find(f".//{{{A_NS}}}bodyPr")
    assert body_pr is not None
    assert [child.tag for child in body_pr].count(f"{{{A_NS}}}normAutofit") == 1
    normal_autofit = body_pr.find(f"{{{A_NS}}}normAutofit")
    assert normal_autofit is not None
    assert normal_autofit.attrib == {"fontScale": "100000", "lnSpcReduction": "0"}
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert body_pr.find(f"{{{A_NS}}}spAutoFit") is None
    assert ElementTree.tostring(root.find(f".//{{{A_NS}}}xfrm")) == geometry_before


def test_long_bilingual_text_persists_a_bounded_scale_for_the_textbox_size() -> None:
    short_root = _textbox_xml("Benefits of partially hydrolysed formula")
    long_root = _textbox_xml(
        "Benefits of partially hydrolysed formula for infants with an increased risk of allergy\n"
        "部分水解配方对过敏风险较高婴儿的益处，以及长期喂养期间相关临床结果的综合说明"
    )

    short_paragraph = short_root.find(f".//{{{A_NS}}}p")
    long_paragraph = long_root.find(f".//{{{A_NS}}}p")
    assert short_paragraph is not None
    assert long_paragraph is not None

    enable_textbox_autofit_for_paragraph(short_root, short_paragraph)
    enable_textbox_autofit_for_paragraph(long_root, long_paragraph)

    short_autofit = short_root.find(f".//{{{A_NS}}}normAutofit")
    long_autofit = long_root.find(f".//{{{A_NS}}}normAutofit")
    assert short_autofit is not None
    assert long_autofit is not None
    assert short_autofit.get("fontScale") == "100000"
    assert 60000 <= int(long_autofit.get("fontScale", "0")) < 100000
    assert 0 <= int(long_autofit.get("lnSpcReduction", "-1")) <= 20000


def test_missing_geometry_uses_a_deterministic_conservative_scale_for_long_text() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'><p:txBody><a:bodyPr/><a:lstStyle/>"
        "<a:p><a:r><a:rPr sz='1800'/><a:t>"
        + ("Long translated content 长篇双语译文 " * 100)
        + "</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert paragraph is not None

    enable_textbox_autofit_for_paragraph(root, paragraph)
    first_autofit = root.find(f".//{{{A_NS}}}normAutofit")
    assert first_autofit is not None
    first_attributes = dict(first_autofit.attrib)
    enable_textbox_autofit_for_paragraph(root, paragraph)
    second_autofit = root.find(f".//{{{A_NS}}}normAutofit")
    assert second_autofit is not None
    second_attributes = dict(second_autofit.attrib)

    assert first_attributes == second_attributes
    assert int(first_attributes["fontScale"]) == 60000
    assert 0 <= int(first_attributes["lnSpcReduction"]) <= 20000


def test_textbox_margins_reduce_the_available_layout_area() -> None:
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
    enable_textbox_autofit_for_paragraph(regular_root, regular_paragraph)
    enable_textbox_autofit_for_paragraph(inset_root, inset_paragraph)

    regular_autofit = regular_root.find(f".//{{{A_NS}}}normAutofit")
    inset_autofit = inset_root.find(f".//{{{A_NS}}}normAutofit")
    assert regular_autofit is not None
    assert inset_autofit is not None
    assert int(inset_autofit.get("fontScale", "0")) < int(
        regular_autofit.get("fontScale", "0")
    )


def test_textbox_with_no_usable_area_uses_the_most_conservative_autofit() -> None:
    root = _textbox_xml("Translated content 译文")
    body_properties = root.find(f".//{{{A_NS}}}bodyPr")
    paragraph = root.find(f".//{{{A_NS}}}p")
    assert body_properties is not None
    assert paragraph is not None
    body_properties.set("lIns", "2000000")
    body_properties.set("rIns", "2000000")

    enable_textbox_autofit_for_paragraph(root, paragraph)

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
