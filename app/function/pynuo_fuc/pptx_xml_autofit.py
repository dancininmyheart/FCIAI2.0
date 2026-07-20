from __future__ import annotations

import math
import unicodedata
from typing import Final
from xml.etree import ElementTree


A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"

A_BODY_PR: Final = f"{{{A_NS}}}bodyPr"
A_NORM_AUTOFIT: Final = f"{{{A_NS}}}normAutofit"
A_NO_AUTOFIT: Final = f"{{{A_NS}}}noAutofit"
A_SP_AUTO_FIT: Final = f"{{{A_NS}}}spAutoFit"
AUTOFIT_TAGS: Final = {A_NORM_AUTOFIT, A_NO_AUTOFIT, A_SP_AUTO_FIT}

EMU_PER_POINT: Final = 12700
DEFAULT_FONT_SIZE_HUNDREDTHS: Final = 1800
DEFAULT_HORIZONTAL_MARGIN_EMU: Final = 91440
DEFAULT_VERTICAL_MARGIN_EMU: Final = 45720
MIN_FONT_SCALE: Final = 60000
MAX_FONT_SCALE: Final = 100000
MAX_LINE_SPACING_REDUCTION: Final = 20000
ESTIMATED_LINE_HEIGHT: Final = 1.2
FALLBACK_FULL_SCALE_TEXT_UNITS: Final = 120.0


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
    font_scale, line_spacing_reduction = _estimate_autofit(root, text_body, body_pr)
    body_pr.insert(
        0,
        ElementTree.Element(
            A_NORM_AUTOFIT,
            {
                "fontScale": str(font_scale),
                "lnSpcReduction": str(line_spacing_reduction),
            },
        ),
    )


def _estimate_autofit(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    body_pr: ElementTree.Element,
) -> tuple[int, int]:
    extent = _textbox_extent(root, text_body)
    if extent is None:
        return _fallback_font_scale(text_body), 0

    width_emu, height_emu = extent
    horizontal_margins = _non_negative_int(
        body_pr.get("lIns"), DEFAULT_HORIZONTAL_MARGIN_EMU
    ) + _non_negative_int(body_pr.get("rIns"), DEFAULT_HORIZONTAL_MARGIN_EMU)
    vertical_margins = _non_negative_int(
        body_pr.get("tIns"), DEFAULT_VERTICAL_MARGIN_EMU
    ) + _non_negative_int(body_pr.get("bIns"), DEFAULT_VERTICAL_MARGIN_EMU)
    available_width = (width_emu - horizontal_margins) / EMU_PER_POINT
    available_height = (height_emu - vertical_margins) / EMU_PER_POINT
    if available_width <= 1 or available_height <= 1:
        return MIN_FONT_SCALE, MAX_LINE_SPACING_REDUCTION

    if _estimated_text_height(text_body, available_width, MAX_FONT_SCALE) <= available_height:
        return MAX_FONT_SCALE, 0

    low = MIN_FONT_SCALE
    high = MAX_FONT_SCALE - 1
    best = MIN_FONT_SCALE
    while low <= high:
        candidate = (low + high) // 2
        if _estimated_text_height(text_body, available_width, candidate) <= available_height:
            best = candidate
            low = candidate + 1
        else:
            high = candidate - 1

    height_at_best = _estimated_text_height(text_body, available_width, best)
    if height_at_best <= available_height:
        return best, 0

    reduction = math.ceil((1 - available_height / height_at_best) * 100000)
    return best, max(0, min(MAX_LINE_SPACING_REDUCTION, reduction))


def _fallback_font_scale(text_body: ElementTree.Element) -> int:
    text_units = sum(
        _character_width_factor(character)
        for text_node in text_body.iter(f"{{{A_NS}}}t")
        for character in (text_node.text or "")
    )
    if text_units <= FALLBACK_FULL_SCALE_TEXT_UNITS:
        return MAX_FONT_SCALE
    scale = round(
        MAX_FONT_SCALE * math.sqrt(FALLBACK_FULL_SCALE_TEXT_UNITS / text_units)
    )
    return max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, scale))


def _textbox_extent(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
) -> tuple[int, int] | None:
    parents = {child: parent for parent in root.iter() for child in parent}
    ancestor = parents.get(text_body)
    while ancestor is not None:
        shape_properties = next(
            (child for child in ancestor if _local_name(child.tag) == "spPr"), None
        )
        if shape_properties is not None:
            transform = next(
                (child for child in shape_properties if _local_name(child.tag) == "xfrm"),
                None,
            )
            if transform is not None:
                extent = next(
                    (child for child in transform if _local_name(child.tag) == "ext"),
                    None,
                )
                if extent is not None:
                    width = _positive_int(extent.get("cx"))
                    height = _positive_int(extent.get("cy"))
                    if width is not None and height is not None:
                        return width, height
        ancestor = parents.get(ancestor)
    return None


def _estimated_text_height(
    text_body: ElementTree.Element,
    available_width: float,
    font_scale: int,
) -> float:
    scale = font_scale / MAX_FONT_SCALE
    total_height = 0.0
    paragraphs = [child for child in text_body if child.tag == f"{{{A_NS}}}p"]
    for paragraph in paragraphs:
        default_size = _paragraph_default_font_size(paragraph)
        line_width = 0.0
        line_font_size = default_size * scale
        paragraph_height = 0.0

        def finish_line() -> None:
            nonlocal line_width, line_font_size, paragraph_height
            paragraph_height += line_font_size * ESTIMATED_LINE_HEIGHT
            line_width = 0.0
            line_font_size = default_size * scale

        for child in paragraph:
            if child.tag == f"{{{A_NS}}}br":
                finish_line()
                continue
            if _local_name(child.tag) not in {"r", "fld"}:
                continue
            run_size = _run_font_size(child, default_size) * scale
            for text_node in child.iter(f"{{{A_NS}}}t"):
                for character in text_node.text or "":
                    if character in "\r\n":
                        finish_line()
                        continue
                    character_width = run_size * _character_width_factor(character)
                    if line_width and line_width + character_width > available_width:
                        finish_line()
                    line_width += character_width
                    line_font_size = max(line_font_size, run_size)
        finish_line()
        total_height += paragraph_height
    return total_height


def _paragraph_default_font_size(paragraph: ElementTree.Element) -> float:
    paragraph_properties = paragraph.find(f"{{{A_NS}}}pPr")
    if paragraph_properties is not None:
        default_properties = paragraph_properties.find(f"{{{A_NS}}}defRPr")
        if default_properties is not None:
            return _font_size(default_properties.get("sz"), DEFAULT_FONT_SIZE_HUNDREDTHS)
    return DEFAULT_FONT_SIZE_HUNDREDTHS / 100


def _run_font_size(run: ElementTree.Element, default: float) -> float:
    run_properties = run.find(f"{{{A_NS}}}rPr")
    if run_properties is None:
        return default
    return _font_size(run_properties.get("sz"), round(default * 100))


def _font_size(value: str | None, default_hundredths: int) -> float:
    size = _positive_int(value)
    return (size if size is not None else default_hundredths) / 100


def _character_width_factor(character: str) -> float:
    if character == "\t":
        return 2.0
    if character.isspace():
        return 0.33
    if unicodedata.east_asian_width(character) in {"W", "F"}:
        return 1.0
    if unicodedata.category(character).startswith("P"):
        return 0.35
    if character.isupper():
        return 0.62
    return 0.52


def _positive_int(value: str | None) -> int | None:
    try:
        parsed = int(value) if value is not None else 0
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _non_negative_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


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
