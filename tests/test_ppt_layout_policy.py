from __future__ import annotations

from xml.etree import ElementTree

from app.function.pynuo_fuc.pptx_xml_autofit import A_NS, enable_textbox_autofit_for_paragraph


def test_changed_textbox_has_exactly_one_normal_autofit_and_keeps_geometry() -> None:
    xml = (
        f"<p:sp xmlns:p='urn:p' xmlns:a='{A_NS}'>"
        "<p:spPr><a:xfrm><a:off x='10' y='20'/><a:ext cx='300' cy='400'/></a:xfrm></p:spPr>"
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
    assert body_pr.find(f"{{{A_NS}}}noAutofit") is None
    assert body_pr.find(f"{{{A_NS}}}spAutoFit") is None
    assert ElementTree.tostring(root.find(f".//{{{A_NS}}}xfrm")) == geometry_before
