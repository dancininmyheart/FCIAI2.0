from __future__ import annotations

import re
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

from app.translation.pptx_contract_types import (
    PptxContext,
    PptxGlossaryEntry,
    PptxLineBreakStreamItem,
    PptxProtectedFieldStreamItem,
    PptxRequestUnit,
    PptxSourceStreamItem,
    PptxTextStreamItem,
)

from .pptx_xml_types import (
    PptxXmlDuplicateShapeIdError,
    PptxXmlReadError,
    PptxXmlUnsupportedStructureError,
)
from .pptx_xml_manifest_support import (
    is_title as _is_title,
    is_translatable_text as _is_translatable_text,
    layout_hint as _layout_hint,
    local_name as _local_name,
    shape_id as _shape_id,
    shape_owner as _shape_owner,
    stream_text as _stream_text,
    text_bodies as _text_bodies,
)


A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
A_P: Final = f"{{{A_NS}}}p"
A_R: Final = f"{{{A_NS}}}r"
A_T: Final = f"{{{A_NS}}}t"
A_BR: Final = f"{{{A_NS}}}br"
A_FLD: Final = f"{{{A_NS}}}fld"
A_P_PR: Final = f"{{{A_NS}}}pPr"
A_END_PARA_RPR: Final = f"{{{A_NS}}}endParaRPr"
SLIDE_PATH_RE: Final = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


@dataclass(frozen=True, slots=True)
class StructuredParagraphTarget:
    unit: PptxRequestUnit
    page_index: int
    box_index: int
    paragraph_index: int
    paragraph: ElementTree.Element
    text_body: ElementTree.Element
    content_nodes: tuple[ElementTree.Element, ...]
    segment_nodes: tuple[tuple[str, ElementTree.Element], ...]
    is_title: bool


def extract_structured_units_from_pptx(
    pptx_path: Path | str,
    selected_page_indices: Sequence[int] | None = None,
    *,
    source_language: str,
    target_language: str,
    stop_words: Sequence[str] = (),
    custom_translations: Mapping[str, str] | None = None,
) -> tuple[PptxRequestUnit, ...]:
    selected = set(selected_page_indices) if selected_page_indices else None
    glossary = tuple(
        PptxGlossaryEntry(source, target)
        for source, target in sorted((custom_translations or {}).items())
    )
    units: list[PptxRequestUnit] = []
    try:
        with zipfile.ZipFile(pptx_path) as archive:
            for page_index, slide_path in enumerate(slide_paths(archive)):
                if selected is not None and page_index not in selected:
                    continue
                root = ElementTree.fromstring(archive.read(slide_path))
                targets = structured_slide_targets(
                    root,
                    page_index,
                    slide_path,
                    source_language,
                    target_language,
                    tuple(stop_words),
                    glossary,
                )
                units.extend(target.unit for target in _with_context(targets))
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise PptxXmlReadError("archive or slide XML is invalid") from exc
    return tuple(units)


def structured_slide_targets(
    root: ElementTree.Element,
    page_index: int,
    slide_path: str,
    source_language: str,
    target_language: str,
    stop_words: tuple[str, ...],
    glossary: tuple[PptxGlossaryEntry, ...],
) -> tuple[StructuredParagraphTarget, ...]:
    parents = {child: parent for parent in root.iter() for child in parent}
    owner_ordinals: defaultdict[ElementTree.Element, int] = defaultdict(int)
    ownerless_ordinal = 0
    shape_owners: dict[str, ElementTree.Element] = {}
    targets: list[StructuredParagraphTarget] = []
    for box_index, text_body in enumerate(_text_bodies(root)):
        owner = _shape_owner(text_body, parents)
        shape_id = _shape_id(owner)
        if owner is not None and shape_id is not None:
            previous_owner = shape_owners.get(shape_id)
            if previous_owner is not None and previous_owner is not owner:
                raise PptxXmlDuplicateShapeIdError(slide_path, shape_id)
            shape_owners[shape_id] = owner
            text_body_key = f"shapeId{shape_id}:tbOrdinal{owner_ordinals[owner]}"
            owner_ordinals[owner] += 1
        else:
            text_body_key = f"slideTbOrdinal{ownerless_ordinal}"
            ownerless_ordinal += 1
        unit_prefix = f"pptx:slide{slide_number(slide_path)}:{text_body_key}"
        paragraph_index = 0
        for paragraph in list(text_body):
            if paragraph.tag != A_P:
                continue
            target = _paragraph_target(
                paragraph,
                text_body,
                owner,
                page_index,
                box_index,
                paragraph_index,
                f"{unit_prefix}:p{paragraph_index}",
                slide_path,
                source_language,
                target_language,
                stop_words,
                glossary,
            )
            if target is not None:
                targets.append(target)
            paragraph_index += 1
    return tuple(targets)


def slide_paths(archive: zipfile.ZipFile) -> list[str]:
    paths = [name for name in archive.namelist() if SLIDE_PATH_RE.match(name)]
    return sorted(paths, key=slide_number)


def slide_number(path: str) -> int:
    match = SLIDE_PATH_RE.match(path)
    return int(match.group(1)) if match else 0


def _paragraph_target(
    paragraph: ElementTree.Element,
    text_body: ElementTree.Element,
    owner: ElementTree.Element | None,
    page_index: int,
    box_index: int,
    paragraph_index: int,
    unit_id: str,
    slide_path: str,
    source_language: str,
    target_language: str,
    stop_words: tuple[str, ...],
    glossary: tuple[PptxGlossaryEntry, ...],
) -> StructuredParagraphTarget | None:
    stream: list[PptxSourceStreamItem] = []
    content_nodes: list[ElementTree.Element] = []
    segment_nodes: list[tuple[str, ElementTree.Element]] = []
    content_index = 0
    for child in list(paragraph):
        if child.tag in (A_P_PR, A_END_PARA_RPR):
            continue
        stream_id = f"{unit_id}:stream{content_index}"
        if child.tag == A_R:
            text_nodes = list(child.iter(A_T))
            if len(text_nodes) != 1:
                raise PptxXmlUnsupportedStructureError(slide_path, "text run must contain exactly one a:t")
            segment_id = f"{unit_id}:segment{content_index}"
            source_text = text_nodes[0].text or ""
            stream.append(PptxTextStreamItem(stream_id, segment_id, source_text))
            segment_nodes.append((segment_id, text_nodes[0]))
            content_nodes.append(child)
            content_index += 1
            continue
        if child.tag == A_BR:
            stream.append(PptxLineBreakStreamItem(stream_id))
            content_nodes.append(child)
            content_index += 1
            continue
        if child.tag == A_FLD:
            source_text = "".join(node.text or "" for node in child.iter(A_T))
            stream.append(PptxProtectedFieldStreamItem(stream_id, source_text))
            content_nodes.append(child)
            content_index += 1
            continue
        if any(True for _ in child.iter(A_T)):
            raise PptxXmlUnsupportedStructureError(slide_path, f"unsupported text node {_local_name(child.tag)}")
    text = _stream_text(tuple(stream))
    if not segment_nodes or not _is_translatable_text(text):
        return None
    unit = PptxRequestUnit(
        unit_id=unit_id,
        source_text=text,
        source_stream=tuple(stream),
        source_language=source_language,
        target_language=target_language,
        layout_hint=_layout_hint(owner),
        glossary=glossary,
        protected_terms=stop_words,
    )
    return StructuredParagraphTarget(
        unit,
        page_index,
        box_index,
        paragraph_index,
        paragraph,
        text_body,
        tuple(content_nodes),
        tuple(segment_nodes),
        _is_title(owner),
    )


def _with_context(
    targets: tuple[StructuredParagraphTarget, ...],
) -> tuple[StructuredParagraphTarget, ...]:
    title = next((target.unit.source_text for target in targets if target.is_title), "")
    enriched: list[StructuredParagraphTarget] = []
    for index, target in enumerate(targets):
        context = PptxContext(
            previous_text=targets[index - 1].unit.source_text if index else "",
            next_text=targets[index + 1].unit.source_text if index + 1 < len(targets) else "",
            title_text=title,
        )
        enriched.append(replace(target, unit=replace(target.unit, context=context)))
    return tuple(enriched)
