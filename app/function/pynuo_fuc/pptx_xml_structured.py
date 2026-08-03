from __future__ import annotations

import copy
import os
import tempfile
import unicodedata
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
    BILINGUAL_TRANSLATION_EXT_URI,
    StructuredParagraphTarget,
    extract_structured_units_from_pptx,
    is_bilingual_translation_paragraph,
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
A_P: Final = f"{{{A_NS}}}p"
A_P_PR: Final = f"{{{A_NS}}}pPr"
A_R: Final = f"{{{A_NS}}}r"
A_T: Final = f"{{{A_NS}}}t"
A_BR: Final = f"{{{A_NS}}}br"
A_END_PARA_RPR: Final = f"{{{A_NS}}}endParaRPr"
A_EXT_LST: Final = f"{{{A_NS}}}extLst"
A_EXT: Final = f"{{{A_NS}}}ext"
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
    write_mode = _resolve_write_mode(bilingual_translation)

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
            write_mode,
        )
        with zipfile.ZipFile(input_file) as source:
            expected_members = tuple(source.namelist())
        validate_pptx_package(temporary_path, expected_members)
        _validate_bilingual_writeback(
            input_file,
            temporary_path,
            translations,
            write_mode,
        )
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


def _validate_bilingual_writeback(
    input_path: Path,
    output_path: Path,
    translations: tuple[PptxUnitTranslation, ...],
    mode: WriteMode,
) -> None:
    if mode is WriteMode.TRANSLATION_ONLY:
        return
    source_targets = _package_targets(input_path)
    output_targets = _package_targets(output_path)
    for translation in translations:
        source = source_targets.get(translation.unit_id)
        output = output_targets.get(translation.unit_id)
        if source is None or output is None:
            raise PptxContractError(
                "bilingual_source_missing",
                "could not locate the translated paragraph to confirm its source text",
                translation.unit_id,
            )
        if _normalized_text(source.unit.source_text) == _normalized_text(
            translation.target_text,
        ):
            continue

        source_runs = _normalized_run_texts(source)
        translated_runs = _normalized_translated_runs(source, translation)
        translation_paragraph = _adjacent_translation_paragraph(output, mode)
        if translation_paragraph is not None:
            source_present = _normalized_run_texts(output) == source_runs
            translation_present = (
                _normalized_paragraph_run_texts(translation_paragraph) == translated_runs
            )
        else:
            output_runs = _normalized_run_texts(output)
            if mode is WriteMode.PARAGRAPH_UP:
                source_present = output_runs[: len(source_runs)] == source_runs
                translation_present = output_runs[-len(translated_runs) :] == translated_runs
            else:
                source_present = output_runs[-len(source_runs) :] == source_runs
                translation_present = output_runs[: len(translated_runs)] == translated_runs

        if not source_present:
            raise PptxContractError(
                "bilingual_source_missing",
                "bilingual writeback did not preserve the source text",
                translation.unit_id,
            )
        if not translation_present:
            raise PptxContractError(
                "bilingual_translation_missing",
                "bilingual writeback did not preserve the translated text",
                translation.unit_id,
            )


def _package_targets(path: Path) -> dict[str, StructuredParagraphTarget]:
    targets: dict[str, StructuredParagraphTarget] = {}
    with zipfile.ZipFile(path) as archive:
        for page_index, slide_path in enumerate(slide_paths(archive)):
            root = ElementTree.fromstring(archive.read(slide_path))
            for target in structured_slide_targets(
                root,
                page_index,
                slide_path,
                "",
                "",
                (),
                (),
            ):
                targets[target.unit.unit_id] = target
    return targets


def _normalized_run_texts(
    target: StructuredParagraphTarget,
) -> tuple[str, ...]:
    return tuple(_normalized_text(node.text or "") for _, node in target.segment_nodes)


def _normalized_translated_runs(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
) -> tuple[str, ...]:
    repeated = _repeated_full_sentence_translation(target, translation)
    if repeated is not None:
        return (_normalized_text(repeated),)
    return tuple(_normalized_text(segment.target_text) for segment in translation.segments)


def _normalized_paragraph_run_texts(
    paragraph: ElementTree.Element,
) -> tuple[str, ...]:
    texts: list[str] = []
    for child in paragraph:
        if child.tag != A_R:
            continue
        text_node = child.find(A_T)
        if text_node is not None:
            texts.append(_normalized_text(text_node.text or ""))
    return tuple(texts)


def _adjacent_translation_paragraph(
    target: StructuredParagraphTarget,
    mode: WriteMode,
) -> ElementTree.Element | None:
    children = list(target.text_body)
    source_index = children.index(target.paragraph)
    translation_index = source_index + (1 if mode is WriteMode.PARAGRAPH_UP else -1)
    if not 0 <= translation_index < len(children):
        return None
    candidate = children[translation_index]
    if candidate.tag != A_P or not is_bilingual_translation_paragraph(candidate):
        return None
    return candidate


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
        changed = _apply_translation(target, translation, mode)
        if changed:
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
) -> bool:
    if (
        mode is not WriteMode.TRANSLATION_ONLY
        and _normalized_text(target.unit.source_text)
        == _normalized_text(translation.target_text)
    ):
        return False
    original_content = tuple(copy.deepcopy(node) for node in target.content_nodes)
    match mode:
        case WriteMode.TRANSLATION_ONLY:
            translated_content = _translated_content(target, translation)
            _replace_content(target.paragraph, target.content_nodes, translated_content)
        case WriteMode.PARAGRAPH_UP:
            translated_content = _translated_content(target, translation)
            if _needs_separate_translation_paragraph(target.paragraph):
                _insert_translation_paragraph(target, translated_content, after=True)
            else:
                _append_content(target.paragraph, translated_content)
        case WriteMode.PARAGRAPH_DOWN:
            translated_content = _translated_content(target, translation)
            if _needs_separate_translation_paragraph(target.paragraph):
                _insert_translation_paragraph(target, translated_content, after=False)
            else:
                _replace_content(target.paragraph, target.content_nodes, translated_content)
                _append_content(target.paragraph, original_content)
        case _ as unreachable:
            assert_never(unreachable)
    return True


def _replace_content(
    paragraph: ElementTree.Element,
    original: tuple[ElementTree.Element, ...],
    replacement: tuple[ElementTree.Element, ...],
) -> None:
    children = list(paragraph)
    insert_at = min(
        (children.index(node) for node in original),
        default=_paragraph_insert_index(paragraph),
    )
    for node in original:
        paragraph.remove(node)
    for node in replacement:
        paragraph.insert(insert_at, node)
        insert_at += 1


def _translated_content(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
) -> tuple[ElementTree.Element, ...]:
    repeated_translation = _repeated_full_sentence_translation(target, translation)
    if repeated_translation is not None:
        for source in target.content_nodes:
            if source.tag != A_R:
                continue
            clone = copy.deepcopy(source)
            text_node = clone.find(A_T)
            if text_node is None:
                raise PptxContractError(
                    "writeback_segment",
                    "cloned run has no text",
                    target.unit.unit_id,
                )
            _set_text(text_node, repeated_translation)
            return (clone,)

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


def _repeated_full_sentence_translation(
    target: StructuredParagraphTarget,
    translation: PptxUnitTranslation,
) -> str | None:
    if len(translation.segments) < 2:
        return None
    # Collapsing several runs into one would discard protected fields. Keep the
    # normal stream-preserving path for paragraphs that contain anything other
    # than translatable runs and explicit line breaks.
    if any(node.tag not in {A_R, A_BR} for node in target.content_nodes):
        return None
    source_texts = {_normalized_text(item.source_text) for item in target.unit.text_items}
    translated_texts = {_normalized_text(item.target_text) for item in translation.segments}
    if len(source_texts) > 1 and len(translated_texts) == 1 and "" not in translated_texts:
        return translation.segments[0].target_text
    return None


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def _needs_separate_translation_paragraph(paragraph: ElementTree.Element) -> bool:
    properties = paragraph.find(A_P_PR)
    return (
        properties is not None
        and properties.get("algn") in {"just", "justLow", "dist", "thaiDist"}
    )


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


def _insert_translation_paragraph(
    target: StructuredParagraphTarget,
    content: tuple[ElementTree.Element, ...],
    *,
    after: bool,
) -> None:
    paragraph = ElementTree.Element(A_P)
    paragraph_properties = target.paragraph.find(A_P_PR)
    paragraph_properties = (
        copy.deepcopy(paragraph_properties)
        if paragraph_properties is not None
        else ElementTree.Element(A_P_PR)
    )
    extension_list = paragraph_properties.find(A_EXT_LST)
    if extension_list is None:
        extension_list = ElementTree.SubElement(paragraph_properties, A_EXT_LST)
    ElementTree.SubElement(
        extension_list,
        A_EXT,
        {"uri": BILINGUAL_TRANSLATION_EXT_URI},
    )
    paragraph.append(paragraph_properties)
    for child in content:
        paragraph.append(child)
    end_properties = target.paragraph.find(A_END_PARA_RPR)
    if end_properties is not None:
        paragraph.append(copy.deepcopy(end_properties))
    source_index = list(target.text_body).index(target.paragraph)
    target.text_body.insert(source_index + (1 if after else 0), paragraph)


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
