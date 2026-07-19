from __future__ import annotations

from typing import Final
from xml.etree import ElementTree


A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"

A_BODY_PR: Final = f"{{{A_NS}}}bodyPr"
A_NORM_AUTOFIT: Final = f"{{{A_NS}}}normAutofit"
A_NO_AUTOFIT: Final = f"{{{A_NS}}}noAutofit"
A_SP_AUTO_FIT: Final = f"{{{A_NS}}}spAutoFit"
AUTOFIT_TAGS: Final = {A_NORM_AUTOFIT, A_NO_AUTOFIT, A_SP_AUTO_FIT}


def enable_textbox_autofit_for_paragraph(
    root: ElementTree.Element,
    paragraph: ElementTree.Element,
) -> None:
    text_body = _find_text_body_for_paragraph(root, paragraph)
    if text_body is None:
        return

    body_pr = _body_properties(text_body)
    for child in list(body_pr):
        if child.tag in AUTOFIT_TAGS:
            body_pr.remove(child)
    body_pr.insert(0, ElementTree.Element(A_NORM_AUTOFIT))


def _find_text_body_for_paragraph(
    root: ElementTree.Element,
    paragraph: ElementTree.Element,
) -> ElementTree.Element | None:
    for text_body in root.iter():
        if text_body.tag.rsplit("}", 1)[-1] == "txBody" and paragraph in list(text_body):
            return text_body
    return None


def _body_properties(text_body: ElementTree.Element) -> ElementTree.Element:
    body_pr = text_body.find(A_BODY_PR)
    if body_pr is not None:
        return body_pr

    body_pr = ElementTree.Element(A_BODY_PR)
    text_body.insert(0, body_pr)
    return body_pr
