from __future__ import annotations

import math
import logging
import os
import unicodedata
from typing import Final, Literal, TypeAlias
from xml.etree import ElementTree


A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"

A_BODY_PR: Final = f"{{{A_NS}}}bodyPr"
A_LST_STYLE: Final = f"{{{A_NS}}}lstStyle"
A_P: Final = f"{{{A_NS}}}p"
A_P_PR: Final = f"{{{A_NS}}}pPr"
A_DEF_P_PR: Final = f"{{{A_NS}}}defPPr"
A_DEF_R_PR: Final = f"{{{A_NS}}}defRPr"
A_R_PR: Final = f"{{{A_NS}}}rPr"
A_END_PARA_R_PR: Final = f"{{{A_NS}}}endParaRPr"
A_T: Final = f"{{{A_NS}}}t"
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
MIN_FONT_SIZE_HUNDREDTHS: Final = 100

AutofitPolicy: TypeAlias = Literal["legacy_norm", "editable"]

logger = logging.getLogger(__name__)


def resolve_autofit_policy(policy: AutofitPolicy | str | None = None) -> AutofitPolicy:
    configured = policy
    if configured is None:
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                configured = current_app.config.get("PPTX_XML_AUTOFIT_POLICY")
        except (ImportError, RuntimeError):
            configured = None
    if configured is None:
        configured = os.environ.get("PPTX_XML_AUTOFIT_POLICY", "editable")
    return (
        "legacy_norm"
        if str(configured).strip().lower() == "legacy_norm"
        else "editable"
    )


def enable_textbox_autofit_for_paragraph(
    root: ElementTree.Element,
    paragraph: ElementTree.Element,
    *,
    policy: AutofitPolicy = "editable",
) -> None:
    text_body = _find_text_body_for_paragraph(root, paragraph)
    if text_body is None:
        return

    apply_textbox_autofit(root, text_body, policy=policy)


def apply_textbox_autofit(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    *,
    policy: AutofitPolicy,
) -> None:
    body_pr = _body_properties(text_body)
    if policy == "legacy_norm":
        _apply_legacy_normal_autofit(root, text_body, body_pr)
        return
    _apply_editable_autofit(root, text_body, body_pr)


def _apply_legacy_normal_autofit(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    body_pr: ElementTree.Element,
) -> None:
    font_scale, line_spacing_reduction = _estimate_autofit(root, text_body, body_pr)
    _replace_autofit_child(
        body_pr,
        ElementTree.Element(
            A_NORM_AUTOFIT,
            {
                "fontScale": str(font_scale),
                "lnSpcReduction": str(line_spacing_reduction),
            },
        ),
    )


def _apply_editable_autofit(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    body_pr: ElementTree.Element,
) -> None:
    autofit_children = [child for child in body_pr if child.tag in AUTOFIT_TAGS]
    estimated_scale = _estimate_editable_font_scale(root, text_body, body_pr)
    if (
        len(autofit_children) == 1
        and autofit_children[0].tag == A_SP_AUTO_FIT
        and estimated_scale == MAX_FONT_SCALE
    ):
        return

    effective_scale = min(estimated_scale, _persisted_normal_font_scale(body_pr))
    if effective_scale == MAX_FONT_SCALE:
        return
    if not _all_visible_font_sizes_resolved(text_body):
        logger.warning(
            "pptx_editable_autofit_skipped "
            "reason=unresolved_inherited_font_size",
        )
        return
    if (
        _persisted_line_spacing_reduction(body_pr) > 0
        and not _has_usable_text_area(root, text_body, body_pr)
    ):
        logger.warning(
            "pptx_editable_autofit_skipped "
            "reason=unmaterialized_line_spacing_reduction",
        )
        return
    _bake_font_scale(text_body, effective_scale)

    _replace_autofit_child(body_pr, ElementTree.Element(A_NO_AUTOFIT))


def _all_visible_font_sizes_resolved(text_body: ElementTree.Element) -> bool:
    for paragraph in (child for child in text_body if child.tag == A_P):
        paragraph_default = _paragraph_default_font_size_hundredths(text_body, paragraph)
        for child in paragraph:
            if _local_name(child.tag) not in {"r", "fld"}:
                continue
            if not any((node.text or "") for node in child.iter(A_T)):
                continue
            run_properties = child.find(A_R_PR)
            if run_properties is not None and _positive_int(run_properties.get("sz")):
                continue
            content_default = paragraph_default
            content_properties = child.find(A_P_PR)
            if content_properties is not None:
                default_properties = content_properties.find(A_DEF_R_PR)
                if default_properties is not None:
                    content_default = (
                        _positive_int(default_properties.get("sz")) or content_default
                    )
            if content_default is None:
                return False
    return True


def _estimate_editable_font_scale(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    body_pr: ElementTree.Element,
) -> int:
    extent = _textbox_extent(root, text_body)
    if extent is None:
        return _fallback_font_scale(text_body)

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
        return 1

    low = 1
    high = MAX_FONT_SCALE
    best = 1
    while low <= high:
        candidate = (low + high) // 2
        estimated_height = _estimated_text_height(
            text_body,
            available_width,
            candidate,
            minimum_font_size=MIN_FONT_SIZE_HUNDREDTHS / 100,
        )
        if estimated_height <= available_height:
            best = candidate
            low = candidate + 1
        else:
            high = candidate - 1
    return best


def _replace_autofit_child(
    body_pr: ElementTree.Element,
    replacement: ElementTree.Element,
) -> None:
    children = list(body_pr)
    existing_indices = [
        index for index, child in enumerate(children) if child.tag in AUTOFIT_TAGS
    ]
    insertion_index = (
        min(existing_indices)
        if existing_indices
        else sum(1 for child in children if _local_name(child.tag) == "prstTxWarp")
    )
    for child in list(body_pr):
        if child.tag in AUTOFIT_TAGS:
            body_pr.remove(child)
    body_pr.insert(min(insertion_index, len(body_pr)), replacement)


def _persisted_normal_font_scale(body_pr: ElementTree.Element) -> int:
    scales = [
        _bounded_font_scale(child.get("fontScale"))
        for child in body_pr
        if child.tag == A_NORM_AUTOFIT
    ]
    return min(scales, default=MAX_FONT_SCALE)


def _persisted_line_spacing_reduction(body_pr: ElementTree.Element) -> int:
    reductions = [
        min(
            MAX_FONT_SCALE,
            _non_negative_int(child.get("lnSpcReduction"), 0),
        )
        for child in body_pr
        if child.tag == A_NORM_AUTOFIT
    ]
    return max(reductions, default=0)


def _has_usable_text_area(
    root: ElementTree.Element,
    text_body: ElementTree.Element,
    body_pr: ElementTree.Element,
) -> bool:
    extent = _textbox_extent(root, text_body)
    if extent is None:
        return False
    width_emu, height_emu = extent
    horizontal_margins = _non_negative_int(
        body_pr.get("lIns"), DEFAULT_HORIZONTAL_MARGIN_EMU
    ) + _non_negative_int(body_pr.get("rIns"), DEFAULT_HORIZONTAL_MARGIN_EMU)
    vertical_margins = _non_negative_int(
        body_pr.get("tIns"), DEFAULT_VERTICAL_MARGIN_EMU
    ) + _non_negative_int(body_pr.get("bIns"), DEFAULT_VERTICAL_MARGIN_EMU)
    return (
        (width_emu - horizontal_margins) / EMU_PER_POINT > 1
        and (height_emu - vertical_margins) / EMU_PER_POINT > 1
    )


def _bounded_font_scale(value: str | None) -> int:
    try:
        parsed = int(value) if value is not None else MAX_FONT_SCALE
    except ValueError:
        return MAX_FONT_SCALE
    return max(1, min(MAX_FONT_SCALE, parsed))


def _bake_font_scale(text_body: ElementTree.Element, font_scale: int) -> None:
    for paragraph in (child for child in text_body if child.tag == A_P):
        default_size = _paragraph_default_font_size_hundredths(text_body, paragraph)
        paragraph_properties = paragraph.find(A_P_PR)
        if paragraph_properties is not None:
            default_properties = paragraph_properties.find(A_DEF_R_PR)
            if default_properties is not None and default_size is not None:
                _set_scaled_font_size(default_properties, default_size, font_scale)

        for child in paragraph:
            if _local_name(child.tag) not in {"r", "fld", "br"}:
                continue
            content_default_size = default_size
            content_properties = child.find(A_P_PR)
            if content_properties is not None:
                content_default_properties = content_properties.find(A_DEF_R_PR)
                if content_default_properties is not None:
                    explicit_content_default = _positive_int(
                        content_default_properties.get("sz"),
                    )
                    if explicit_content_default is not None:
                        content_default_size = explicit_content_default
                        _set_scaled_font_size(
                            content_default_properties,
                            explicit_content_default,
                            font_scale,
                        )
            run_properties = child.find(A_R_PR)
            run_size = (
                _positive_int(run_properties.get("sz"))
                if run_properties is not None
                else None
            )
            resolved_size = run_size or content_default_size
            if resolved_size is None:
                continue
            if run_properties is None:
                run_properties = ElementTree.Element(A_R_PR)
                child.insert(0, run_properties)
            _set_scaled_font_size(
                run_properties,
                resolved_size,
                font_scale,
            )

        end_properties = paragraph.find(A_END_PARA_R_PR)
        if end_properties is not None:
            end_size = _positive_int(end_properties.get("sz")) or default_size
            if end_size is not None:
                _set_scaled_font_size(end_properties, end_size, font_scale)


def _set_scaled_font_size(
    properties: ElementTree.Element,
    size_hundredths: int,
    font_scale: int,
) -> None:
    scaled = max(
        MIN_FONT_SIZE_HUNDREDTHS,
        round(size_hundredths * font_scale / MAX_FONT_SCALE),
    )
    properties.set("sz", str(scaled))


def _paragraph_default_font_size_hundredths(
    text_body: ElementTree.Element,
    paragraph: ElementTree.Element,
) -> int | None:
    paragraph_properties = paragraph.find(A_P_PR)
    if paragraph_properties is not None:
        default_properties = paragraph_properties.find(A_DEF_R_PR)
        if default_properties is not None:
            explicit_size = _positive_int(default_properties.get("sz"))
            if explicit_size is not None:
                return explicit_size

    list_style = text_body.find(A_LST_STYLE)
    if list_style is not None:
        level = _paragraph_level(paragraph_properties)
        level_properties = list_style.find(f"{{{A_NS}}}lvl{level + 1}pPr")
        for inherited_properties in (level_properties, list_style.find(A_DEF_P_PR)):
            if inherited_properties is None:
                continue
            default_properties = inherited_properties.find(A_DEF_R_PR)
            if default_properties is not None:
                explicit_size = _positive_int(default_properties.get("sz"))
                if explicit_size is not None:
                    return explicit_size

    return None


def _paragraph_level(paragraph_properties: ElementTree.Element | None) -> int:
    if paragraph_properties is None:
        return 0
    try:
        level = int(paragraph_properties.get("lvl", "0"))
    except ValueError:
        return 0
    return max(0, min(8, level))


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
    *,
    minimum_font_size: float = 0.0,
) -> float:
    scale = font_scale / MAX_FONT_SCALE
    total_height = 0.0
    paragraphs = [child for child in text_body if child.tag == f"{{{A_NS}}}p"]
    for paragraph in paragraphs:
        default_size = (
            _paragraph_default_font_size_hundredths(text_body, paragraph)
            or DEFAULT_FONT_SIZE_HUNDREDTHS
        ) / 100
        line_width = 0.0
        scaled_default_size = max(minimum_font_size, default_size * scale)
        line_font_size = scaled_default_size
        paragraph_height = 0.0

        def finish_line() -> None:
            nonlocal line_width, line_font_size, paragraph_height
            paragraph_height += line_font_size * ESTIMATED_LINE_HEIGHT
            line_width = 0.0
            line_font_size = scaled_default_size

        for child in paragraph:
            if child.tag == f"{{{A_NS}}}br":
                finish_line()
                continue
            if _local_name(child.tag) not in {"r", "fld"}:
                continue
            run_size = max(
                minimum_font_size,
                _run_font_size(child, default_size) * scale,
            )
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


def _run_font_size(run: ElementTree.Element, default: float) -> float:
    run_properties = run.find(f"{{{A_NS}}}rPr")
    explicit_size = (
        _positive_int(run_properties.get("sz")) if run_properties is not None else None
    )
    if explicit_size is not None:
        return explicit_size / 100
    content_properties = run.find(A_P_PR)
    if content_properties is not None:
        default_properties = content_properties.find(A_DEF_R_PR)
        if default_properties is not None:
            explicit_size = _positive_int(default_properties.get("sz"))
            if explicit_size is not None:
                return explicit_size / 100
    return default


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
