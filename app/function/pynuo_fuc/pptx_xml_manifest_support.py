from __future__ import annotations

import re
from typing import Final, assert_never
from xml.etree import ElementTree

from app.translation.pptx_contract_types import (
    PptxLayoutHint,
    PptxLineBreakStreamItem,
    PptxProtectedFieldStreamItem,
    PptxSourceStreamItem,
    PptxTextStreamItem,
)


SHAPE_OWNER_NAMES: Final = frozenset({"sp", "graphicFrame", "cxnSp", "pic", "contentPart"})


def text_bodies(root: ElementTree.Element) -> tuple[ElementTree.Element, ...]:
    return tuple(item for item in root.iter() if local_name(item.tag) == "txBody")


def shape_owner(
    text_body: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> ElementTree.Element | None:
    current = parents.get(text_body)
    while current is not None:
        if local_name(current.tag) in SHAPE_OWNER_NAMES:
            return current
        current = parents.get(current)
    return None


def shape_id(owner: ElementTree.Element | None) -> str | None:
    node = _shape_properties(owner)
    return node.get("id") if node is not None else None


def is_title(owner: ElementTree.Element | None) -> bool:
    node = _shape_properties(owner)
    if node is not None and any(
        token in node.get("name", "").casefold()
        for token in ("title", "标题")
    ):
        return True
    if owner is None:
        return False
    placeholder = next((item for item in owner.iter() if local_name(item.tag) == "ph"), None)
    return placeholder is not None and placeholder.get("type", "") in ("title", "ctrTitle")


def layout_hint(owner: ElementTree.Element | None) -> PptxLayoutHint:
    if owner is None:
        return PptxLayoutHint()
    transform = next((item for item in owner.iter() if local_name(item.tag) == "xfrm"), None)
    if transform is None:
        return PptxLayoutHint()
    offset = next((item for item in transform if local_name(item.tag) == "off"), None)
    extent = next((item for item in transform if local_name(item.tag) == "ext"), None)
    return PptxLayoutHint(
        x_emu=_optional_int(offset.get("x")) if offset is not None else None,
        y_emu=_optional_int(offset.get("y")) if offset is not None else None,
        width_emu=_optional_positive_int(extent.get("cx")) if extent is not None else None,
        height_emu=_optional_positive_int(extent.get("cy")) if extent is not None else None,
    )


def stream_text(stream: tuple[PptxSourceStreamItem, ...]) -> str:
    parts: list[str] = []
    for item in stream:
        match item:
            case PptxTextStreamItem():
                parts.append(item.source_text)
            case PptxLineBreakStreamItem():
                parts.append("\n")
            case PptxProtectedFieldStreamItem():
                parts.append(item.source_text)
            case _ as unreachable:
                assert_never(unreachable)
    return "".join(parts)


def is_translatable_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or re.fullmatch(r"[\d\s.,%+\-]+", stripped):
        return False
    return not re.fullmatch(r"[\W_]+", stripped, re.UNICODE)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _shape_properties(owner: ElementTree.Element | None) -> ElementTree.Element | None:
    if owner is None:
        return None
    return next((item for item in owner.iter() if local_name(item.tag) == "cNvPr"), None)


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _optional_positive_int(value: str | None) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed is not None and parsed > 0 else None
