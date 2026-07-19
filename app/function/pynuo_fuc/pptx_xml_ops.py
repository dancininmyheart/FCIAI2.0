from __future__ import annotations

import copy
import logging
import re
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, assert_never
from xml.etree import ElementTree

try:
    from .pptx_xml_autofit import enable_textbox_autofit_for_paragraph
    from .pptx_xml_types import TextBoxData, TranslationPageResult, WriteMode, XmlParagraphTarget
except ImportError:
    from pptx_xml_autofit import enable_textbox_autofit_for_paragraph
    from pptx_xml_types import TextBoxData, TranslationPageResult, WriteMode, XmlParagraphTarget


logger = logging.getLogger(__name__)

A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS: Final = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
NS: Final = {"a": A_NS, "p": P_NS, "r": R_NS}

for _prefix, _uri in NS.items():
    ElementTree.register_namespace(_prefix, _uri)

A_R: Final = f"{{{A_NS}}}r"
A_T: Final = f"{{{A_NS}}}t"
A_P: Final = f"{{{A_NS}}}p"
A_BR: Final = f"{{{A_NS}}}br"
A_END_PARA_RPR: Final = f"{{{A_NS}}}endParaRPr"
XML_SPACE: Final = f"{{{XML_NS}}}space"
SLIDE_PATH_RE: Final = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


def extract_text_boxes_data_from_pptx(
    pptx_path: Path | str,
    selected_page_indices: Sequence[int] | None = None,
) -> list[TextBoxData]:
    selected = set(selected_page_indices) if selected_page_indices else None
    text_boxes: list[TextBoxData] = []
    with zipfile.ZipFile(pptx_path) as archive:
        for page_index, slide_path in enumerate(_slide_paths(archive)):
            if selected is not None and page_index not in selected:
                continue
            root = ElementTree.fromstring(archive.read(slide_path))
            for target in _paragraph_targets(root, page_index, slide_path):
                text_boxes.append(
                    {
                        "page_index": target.page_index,
                        "box_index": target.box_index,
                        "box_id": f"xml_box_{target.box_index}",
                        "paragraph_index": target.paragraph_index,
                        "paragraph_id": f"xml_para_{target.box_index}_{target.paragraph_index}",
                        "combined_text": target.text,
                    }
                )
    return text_boxes


def write_translated_pptx_xml(
    input_path: Path | str,
    output_path: Path | str,
    text_boxes_data: Sequence[TextBoxData],
    translation_results: Mapping[int, TranslationPageResult],
    bilingual_translation: str,
) -> str:
    input_file = Path(input_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    translation_lookup = _build_translation_lookup(text_boxes_data, translation_results)
    pages_to_modify = {page for page, _, _ in translation_lookup}

    with zipfile.ZipFile(input_file) as source, zipfile.ZipFile(
        output_file,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as target:
        slide_paths = _slide_paths(source)
        slide_index_by_path = {slide_path: index for index, slide_path in enumerate(slide_paths)}
        for item in source.infolist():
            data = source.read(item.filename)
            page_index = slide_index_by_path.get(item.filename)
            if page_index in pages_to_modify:
                data = _translated_slide_xml(
                    data,
                    item.filename,
                    page_index,
                    translation_lookup,
                    _resolve_write_mode(bilingual_translation),
                )
            target.writestr(item, data)
    return str(output_file)


def _slide_paths(archive: zipfile.ZipFile) -> list[str]:
    paths = [name for name in archive.namelist() if SLIDE_PATH_RE.match(name)]
    return sorted(paths, key=_slide_number)


def _slide_number(path: str) -> int:
    match = SLIDE_PATH_RE.match(path)
    return int(match.group(1)) if match else 0


def _paragraph_targets(
    root: ElementTree.Element,
    page_index: int,
    slide_path: str,
) -> list[XmlParagraphTarget]:
    targets: list[XmlParagraphTarget] = []
    box_index = 0
    for text_body in root.iter():
        if _local_name(text_body.tag) != "txBody":
            continue
        paragraph_index = 0
        for paragraph in list(text_body):
            if paragraph.tag != A_P:
                continue
            runs, text_nodes = _text_runs(paragraph)
            text = "".join(node.text or "" for node in text_nodes).strip()
            if _is_translatable_text(text):
                targets.append(
                    XmlParagraphTarget(
                        page_index=page_index,
                        slide_path=slide_path,
                        box_index=box_index,
                        paragraph_index=paragraph_index,
                        paragraph=paragraph,
                        runs=runs,
                        text_nodes=text_nodes,
                        text=text,
                    )
                )
            paragraph_index += 1
        box_index += 1
    return targets


def _text_runs(
    paragraph: ElementTree.Element,
) -> tuple[tuple[ElementTree.Element, ...], tuple[ElementTree.Element, ...]]:
    runs: list[ElementTree.Element] = []
    text_nodes: list[ElementTree.Element] = []
    for run in paragraph.iter(A_R):
        text_node = run.find(A_T)
        if text_node is not None:
            runs.append(run)
            text_nodes.append(text_node)
    return tuple(runs), tuple(text_nodes)


def _is_translatable_text(text: str) -> bool:
    if not text:
        return False
    if re.fullmatch(r"[\d\s.,%+\-]+", text):
        return False
    return not re.fullmatch(r"[\W_]+", text, re.UNICODE)


def _build_translation_lookup(
    text_boxes_data: Sequence[TextBoxData],
    translation_results: Mapping[int, TranslationPageResult],
) -> dict[tuple[int, int, int], tuple[str, ...]]:
    lookup: dict[tuple[int, int, int], tuple[str, ...]] = {}
    for item in text_boxes_data:
        page_index = item["page_index"]
        page_result = translation_results.get(page_index, {})
        fragments_by_key = page_result.get("translated_fragments", {})
        key = f"{item['box_index'] + 1}_{item['paragraph_index'] + 1}"
        fragments = tuple(fragment for fragment in fragments_by_key.get(key, ()) if fragment)
        if fragments:
            lookup[(page_index, item["box_index"], item["paragraph_index"])] = fragments
    return lookup


def _translated_slide_xml(
    slide_data: bytes,
    slide_path: str,
    page_index: int,
    translation_lookup: Mapping[tuple[int, int, int], Sequence[str]],
    mode: WriteMode,
) -> bytes:
    root = ElementTree.fromstring(slide_data)
    for target in _paragraph_targets(root, page_index, slide_path):
        fragments = translation_lookup.get((page_index, target.box_index, target.paragraph_index))
        if fragments:
            enable_textbox_autofit_for_paragraph(root, target.paragraph)
            _apply_translation(target, tuple(fragments), mode)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _apply_translation(
    target: XmlParagraphTarget,
    translated_fragments: tuple[str, ...],
    mode: WriteMode,
) -> None:
    original_fragments = tuple(node.text or "" for node in target.text_nodes)
    match mode:
        case WriteMode.PARAGRAPH_UP:
            _append_break_and_runs(target.paragraph, target.runs, translated_fragments)
        case WriteMode.PARAGRAPH_DOWN:
            _replace_text_nodes(target.text_nodes, translated_fragments)
            _append_break_and_runs(target.paragraph, target.runs, original_fragments)
        case WriteMode.TRANSLATION_ONLY:
            _replace_text_nodes(target.text_nodes, translated_fragments)
        case unreachable:
            assert_never(unreachable)


def _replace_text_nodes(
    text_nodes: Sequence[ElementTree.Element],
    fragments: Sequence[str],
) -> None:
    if len(fragments) == len(text_nodes):
        for node, fragment in zip(text_nodes, fragments, strict=True):
            _set_text(node, fragment)
        return
    merged = " ".join(fragments)
    for index, node in enumerate(text_nodes):
        _set_text(node, merged if index == 0 else "")


def _append_break_and_runs(
    paragraph: ElementTree.Element,
    source_runs: Sequence[ElementTree.Element],
    fragments: Sequence[str],
) -> None:
    insert_index = _paragraph_insert_index(paragraph)
    paragraph.insert(insert_index, ElementTree.Element(A_BR))
    insert_index += 1
    for run in _runs_for_fragments(source_runs, fragments):
        paragraph.insert(insert_index, run)
        insert_index += 1


def _runs_for_fragments(
    source_runs: Sequence[ElementTree.Element],
    fragments: Sequence[str],
) -> list[ElementTree.Element]:
    if len(source_runs) == len(fragments):
        return [_clone_run_with_text(run, text) for run, text in zip(source_runs, fragments, strict=True)]
    template = source_runs[0] if source_runs else None
    return [_clone_run_with_text(template, " ".join(fragments))]


def _clone_run_with_text(
    source_run: ElementTree.Element | None,
    text: str,
) -> ElementTree.Element:
    run = copy.deepcopy(source_run) if source_run is not None else ElementTree.Element(A_R)
    text_nodes = list(run.iter(A_T))
    if not text_nodes:
        text_nodes = [ElementTree.SubElement(run, A_T)]
    for index, text_node in enumerate(text_nodes):
        _set_text(text_node, text if index == 0 else "")
    return run


def _paragraph_insert_index(paragraph: ElementTree.Element) -> int:
    for index, child in enumerate(list(paragraph)):
        if child.tag == A_END_PARA_RPR:
            return index
    return len(paragraph)


def _set_text(node: ElementTree.Element, text: str) -> None:
    node.text = text
    node.set(XML_SPACE, "preserve")


def _resolve_write_mode(raw_mode: str) -> WriteMode:
    aliases = {
        "paragraph_down": WriteMode.PARAGRAPH_DOWN,
        "translation_only": WriteMode.TRANSLATION_ONLY,
        "0": WriteMode.TRANSLATION_ONLY,
        "paragraph_up": WriteMode.PARAGRAPH_UP,
        "1": WriteMode.PARAGRAPH_UP,
        "bilingual": WriteMode.PARAGRAPH_UP,
        "paragraph": WriteMode.PARAGRAPH_UP,
    }
    mode = aliases.get(raw_mode)
    if mode is not None:
        return mode
    logger.warning("Unknown bilingual mode %s, using paragraph_up", raw_mode)
    return WriteMode.PARAGRAPH_UP


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
