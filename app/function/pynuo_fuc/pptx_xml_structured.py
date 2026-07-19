from __future__ import annotations

import copy
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Final, assert_never
from xml.etree import ElementTree

from app.translation.pptx_contract import (
    PptxContractError,
    PptxUnitTranslation,
    validate_pptx_translations,
)

from .pptx_xml_autofit import enable_textbox_autofit_for_paragraph
from .pptx_xml_manifest import (
    StructuredParagraphTarget,
    extract_structured_units_from_pptx,
    slide_paths,
    structured_slide_targets,
)
from .pptx_xml_package import serialize_slide_xml, validate_pptx_package
from .pptx_xml_types import (
    PptxXmlFallbackEligibleError,
    PptxXmlWriteError,
    WriteMode,
)


A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
A_R: Final = f"{{{A_NS}}}r"
A_T: Final = f"{{{A_NS}}}t"
A_BR: Final = f"{{{A_NS}}}br"
A_END_PARA_RPR: Final = f"{{{A_NS}}}endParaRPr"
XML_SPACE: Final = f"{{{XML_NS}}}space"


def write_structured_translated_pptx(
    input_path: Path | str,
    output_path: Path | str,
    translations: tuple[PptxUnitTranslation, ...],
    bilingual_translation: str,
) -> str:
    input_file = Path(input_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    expected = extract_structured_units_from_pptx(
        input_file,
        source_language="",
        target_language="",
    )
    requested_ids = frozenset(item.unit_id for item in translations)
    expected_subset = tuple(unit for unit in expected if unit.unit_id in requested_ids)
    validate_pptx_translations(expected_subset, translations)

    with tempfile.NamedTemporaryFile(
        prefix=f".{output_file.stem}.",
        suffix=".tmp.pptx",
        dir=output_file.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        _write_package(
            input_file,
            temporary_path,
            translations,
            _resolve_write_mode(bilingual_translation),
        )
        with zipfile.ZipFile(input_file) as source:
            expected_members = tuple(source.namelist())
        validate_pptx_package(temporary_path, expected_members)
        os.replace(temporary_path, output_file)
    except (PptxContractError, PptxXmlFallbackEligibleError):
        temporary_path.unlink(missing_ok=True)
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise PptxXmlWriteError("could not create a valid translated package") from exc
    return str(output_file)


def _write_package(
    input_path: Path,
    output_path: Path,
    translations: tuple[PptxUnitTranslation, ...],
    mode: WriteMode,
) -> None:
    by_id = {translation.unit_id: translation for translation in translations}
    written_ids: set[str] = set()
    with zipfile.ZipFile(input_path) as source, zipfile.ZipFile(
        output_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as target:
        target.comment = source.comment
        indexed_slides = {name: index for index, name in enumerate(slide_paths(source))}
        for item in source.infolist():
            data = source.read(item.filename)
            page_index = indexed_slides.get(item.filename)
            if page_index is not None:
                data, slide_written = _translated_slide(
                    data,
                    item.filename,
                    page_index,
                    by_id,
                    mode,
                )
                written_ids.update(slide_written)
            target.writestr(item, data)
    if written_ids != set(by_id):
        raise PptxContractError("writeback_unit_mismatch", "not every translation unit was written")


def _translated_slide(
    slide_data: bytes,
    slide_path: str,
    page_index: int,
    translations: dict[str, PptxUnitTranslation],
    mode: WriteMode,
) -> tuple[bytes, set[str]]:
    root = ElementTree.fromstring(slide_data)
    targets = structured_slide_targets(
        root,
        page_index,
        slide_path,
        "",
        "",
        (),
        (),
    )
    written: set[str] = set()
    autofit_targets: dict[ElementTree.Element, ElementTree.Element] = {}
    for target in targets:
        translation = translations.get(target.unit.unit_id)
        if translation is None:
            continue
        _apply_translation(target, translation, mode)
        _ = autofit_targets.setdefault(target.text_body, target.paragraph)
        written.add(target.unit.unit_id)
    if not written:
        return slide_data, written
    for paragraph in autofit_targets.values():
        enable_textbox_autofit_for_paragraph(root, paragraph)
    return serialize_slide_xml(slide_data, root), written


def _apply_translation(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
    mode: WriteMode,
) -> None:
    original_content = tuple(copy.deepcopy(node) for node in target.content_nodes)
    match mode:
        case WriteMode.TRANSLATION_ONLY:
            _replace_segments(target, translation)
        case WriteMode.PARAGRAPH_UP:
            translated_content = _translated_content(target, translation)
            _append_content(target.paragraph, translated_content)
        case WriteMode.PARAGRAPH_DOWN:
            _replace_segments(target, translation)
            _append_content(target.paragraph, original_content)
        case _ as unreachable:
            assert_never(unreachable)


def _replace_segments(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
) -> None:
    translated = {item.segment_id: item.target_text for item in translation.segments}
    for segment_id, text_node in target.segment_nodes:
        _set_text(text_node, translated[segment_id])


def _translated_content(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
) -> tuple[ElementTree.Element, ...]:
    segment_iter = iter(translation.segments)
    translated: list[ElementTree.Element] = []
    for source in target.content_nodes:
        clone = copy.deepcopy(source)
        if source.tag == A_R:
            segment = next(segment_iter)
            text_node = clone.find(A_T)
            if text_node is None:
                raise PptxContractError("writeback_segment", "cloned run has no text", target.unit.unit_id)
            _set_text(text_node, segment.target_text)
        translated.append(clone)
    return tuple(translated)


def _append_content(
    paragraph: ElementTree.Element,
    content: tuple[ElementTree.Element, ...],
) -> None:
    insert_at = _paragraph_insert_index(paragraph)
    paragraph.insert(insert_at, ElementTree.Element(A_BR))
    insert_at += 1
    for child in content:
        paragraph.insert(insert_at, child)
        insert_at += 1


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
    return aliases.get(raw_mode, WriteMode.PARAGRAPH_UP)


__all__ = ["extract_structured_units_from_pptx", "write_structured_translated_pptx"]
