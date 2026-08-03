from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree

sys.dont_write_bytecode = True


_UNRESOLVED_FONT_SIZE_REASON = "unresolved_inherited_font_size"
_UNMATERIALIZED_LINE_SPACING_REASON = "unmaterialized_line_spacing_reduction"


def autofit_policy_checks(
    source: Path,
    translated: Path,
    policy: str,
    *,
    slide_number: int = 1,
    fallback_warning_count: int = 0,
    line_spacing_fallback_warning_count: int = 0,
) -> dict[str, bool | int]:
    """Audit persisted AutoFit state for text bodies changed by translation."""
    source_bodies = _text_body_records(source, slide_number)
    translated_bodies = _text_body_records(translated, slide_number)
    matched_bodies, identities_equal = _match_text_bodies(source_bodies, translated_bodies)
    changed_pairs = [
        (original, target)
        for original, target in matched_bodies
        if _body_text(original) != _body_text(target)
    ]
    changed = [target for _, target in changed_pairs]
    checks = {
        "text_body_count_equal": len(source_bodies) == len(translated_bodies),
        "text_body_identity_equal": identities_equal,
        "changed_text_body_found": bool(changed),
    }
    if policy == "editable":
        unresolved_fallback_count = max(
            fallback_warning_count,
            sum(
                _is_unresolved_inherited_size_fallback(original, target)
                for original, target in changed_pairs
            ),
        )
        checks.update(
            {
                "editable_unresolved_inherited_font_size_fallback_count": (
                    unresolved_fallback_count
                ),
                "editable_unresolved_inherited_font_size_fallback_absent": (
                    unresolved_fallback_count == 0
                ),
                "editable_unmaterialized_line_spacing_fallback_count": (
                    line_spacing_fallback_warning_count
                ),
                "editable_unmaterialized_line_spacing_fallback_absent": (
                    line_spacing_fallback_warning_count == 0
                ),
                "editable_non_full_norm_autofit_remaining_zero": all(
                    not _has_non_full_normal_autofit(body) for body in changed
                ),
                "editable_changed_text_bodies_have_persisted_fit": all(
                    _has_persisted_editable_fit(body) for body in changed
                ),
            },
        )
        return checks
    if policy == "legacy_norm":
        checks["legacy_one_norm_autofit_per_changed_text_body"] = all(
            _has_one_normal_autofit_without_conflict(body) for body in changed
        )
        return checks
    raise ValueError(f"unsupported AutoFit policy: {policy}")


def _text_body_records(
    path: Path,
    slide_number: int,
) -> list[tuple[str | None, ElementTree.Element]]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read(f"ppt/slides/slide{slide_number}.xml"))
    parents = {child: parent for parent in root.iter() for child in parent}
    ordinals_by_shape: dict[ElementTree.Element, int] = {}
    records: list[tuple[str | None, ElementTree.Element]] = []
    for body in (element for element in root.iter() if _local_name(element.tag) == "txBody"):
        shape = _enclosing_shape(body, parents)
        identity: str | None = None
        if shape is not None:
            shape_id = _shape_id(shape)
            ordinal = ordinals_by_shape.get(shape, 0)
            ordinals_by_shape[shape] = ordinal + 1
            if shape_id is not None:
                identity = f"shape:{shape_id}:text-body:{ordinal}"
        records.append((identity, body))
    return records


def _match_text_bodies(
    source: list[tuple[str | None, ElementTree.Element]],
    translated: list[tuple[str | None, ElementTree.Element]],
) -> tuple[list[tuple[ElementTree.Element, ElementTree.Element]], bool]:
    source_ids = [identity for identity, _ in source]
    translated_ids = [identity for identity, _ in translated]
    stable_ids_available = (
        all(identity is not None for identity in source_ids + translated_ids)
        and len(source_ids) == len(set(source_ids))
        and len(translated_ids) == len(set(translated_ids))
    )
    if not stable_ids_available:
        count_equal = len(source) == len(translated)
        return (
            [
                (original, target)
                for (_, original), (_, target) in zip(source, translated, strict=False)
            ],
            count_equal,
        )

    translated_by_id = {identity: body for identity, body in translated}
    identities_equal = set(source_ids) == set(translated_ids)
    matched = [
        (body, translated_by_id[identity])
        for identity, body in source
        if identity in translated_by_id
    ]
    return matched, identities_equal


def _enclosing_shape(
    body: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> ElementTree.Element | None:
    current = parents.get(body)
    while current is not None:
        if _local_name(current.tag) in {"sp", "graphicFrame", "cxnSp"}:
            return current
        current = parents.get(current)
    return None


def _shape_id(shape: ElementTree.Element) -> str | None:
    properties = next(_descendants(shape, "cNvPr"), None)
    return properties.get("id") if properties is not None else None


def _body_text(body: ElementTree.Element) -> str:
    return "".join(
        element.text or ""
        for element in body.iter()
        if _local_name(element.tag) == "t"
    )


def _has_non_full_normal_autofit(body: ElementTree.Element) -> bool:
    return any(
        int(element.get("fontScale", "100000")) < 100000
        for element in _descendants(body, "normAutofit")
    )


def _has_persisted_editable_fit(body: ElementTree.Element) -> bool:
    body_properties = next(_descendants(body, "bodyPr"), None)
    if body_properties is None:
        return False
    autofit_children = [
        child
        for child in body_properties
        if _local_name(child.tag) in {"noAutofit", "normAutofit", "spAutoFit"}
    ]
    if len(autofit_children) != 1:
        return False
    autofit = autofit_children[0]
    if _local_name(autofit.tag) == "spAutoFit":
        return True
    if _local_name(autofit.tag) == "normAutofit":
        return int(autofit.get("fontScale", "100000")) >= 100000
    has_explicit_size = any(
        element.get("sz") is not None
        for local_name in ("rPr", "defRPr", "endParaRPr")
        for element in _descendants(body, local_name)
    )
    return _local_name(autofit.tag) == "noAutofit" and has_explicit_size


def _is_unresolved_inherited_size_fallback(
    source: ElementTree.Element,
    translated: ElementTree.Element,
) -> bool:
    return (
        _has_non_full_normal_autofit(translated)
        and
        _autofit_signature(source) == _autofit_signature(translated)
        and _has_unresolved_visible_font_size(translated)
    )


def _autofit_signature(body: ElementTree.Element) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    body_properties = next(_descendants(body, "bodyPr"), None)
    if body_properties is None:
        return ()
    return tuple(
        (_local_name(child.tag), tuple(sorted(child.attrib.items())))
        for child in body_properties
        if _local_name(child.tag) in {"noAutofit", "normAutofit", "spAutoFit"}
    )


def _has_unresolved_visible_font_size(body: ElementTree.Element) -> bool:
    parents = {child: parent for parent in body.iter() for child in parent}
    list_style = _direct_child(body, "lstStyle")
    for carrier in (
        element
        for element in body.iter()
        if _local_name(element.tag) in {"r", "fld"} and _body_text(element).strip()
    ):
        if _font_size_from_properties(_direct_child(carrier, "rPr")) is not None:
            continue
        if _font_size_from_properties(_direct_child(carrier, "pPr")) is not None:
            continue
        paragraph = _ancestor(carrier, parents, "p")
        paragraph_properties = _direct_child(paragraph, "pPr") if paragraph is not None else None
        if _font_size_from_properties(paragraph_properties) is not None:
            continue
        level = _paragraph_level(paragraph_properties)
        level_properties = _direct_child(list_style, f"lvl{level + 1}pPr")
        default_list_properties = _direct_child(list_style, "defPPr")
        if any(
            _font_size_from_properties(properties) is not None
            for properties in (level_properties, default_list_properties)
        ):
            continue
        return True
    return False


def _font_size_from_properties(properties: ElementTree.Element | None) -> int | None:
    if properties is None:
        return None
    if properties.get("sz") is not None:
        return int(properties.get("sz", "0"))
    default_properties = _direct_child(properties, "defRPr")
    if default_properties is not None and default_properties.get("sz") is not None:
        return int(default_properties.get("sz", "0"))
    return None


def _paragraph_level(properties: ElementTree.Element | None) -> int:
    if properties is None:
        return 0
    try:
        level = int(properties.get("lvl", "0"))
    except ValueError:
        return 0
    return max(0, min(8, level))


def _ancestor(
    element: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
    local_name: str,
) -> ElementTree.Element | None:
    current = parents.get(element)
    while current is not None:
        if _local_name(current.tag) == local_name:
            return current
        current = parents.get(current)
    return None


def _direct_child(
    element: ElementTree.Element | None,
    local_name: str,
) -> ElementTree.Element | None:
    if element is None:
        return None
    return next((child for child in element if _local_name(child.tag) == local_name), None)


def _has_one_normal_autofit_without_conflict(body: ElementTree.Element) -> bool:
    return (
        len(list(_descendants(body, "normAutofit"))) == 1
        and next(_descendants(body, "noAutofit"), None) is None
        and next(_descendants(body, "spAutoFit"), None) is None
    )


def _descendants(body: ElementTree.Element, local_name: str) -> Iterable[ElementTree.Element]:
    return (element for element in body.iter() if _local_name(element.tag) == local_name)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@contextmanager
def _capture_autofit_fallback_warnings() -> Iterator[Counter[str]]:
    counts: Counter[str] = Counter()

    class _FallbackHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            message = record.getMessage()
            prefix = "pptx_editable_autofit_skipped reason="
            if message.startswith(prefix):
                counts[message.removeprefix(prefix).split(maxsplit=1)[0]] += 1

    logger = logging.getLogger("app.function.pynuo_fuc.pptx_xml_autofit")
    handler = _FallbackHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        yield counts
    finally:
        logger.removeHandler(handler)


def main() -> int:
    arguments = _arguments()
    os.environ["PPTX_XML_AUTOFIT_POLICY"] = arguments.autofit_policy
    os.environ["PPTX_SEMANTIC_QA_MODE"] = arguments.semantic_qa_mode
    root = arguments.root.resolve()
    sys.path.insert(0, str(root))
    from tools.qa.rendered_acceptance import (
        audit_synthetic,
        copy_source,
        create_overflow_fixture,
        processes_exited,
        render_presentation,
        sha256,
        slide_xml_equal,
        translate_first_unit,
    )

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profiles = output / "libreoffice-profiles"
    process_ids: list[int] = []

    synthetic_source = output / "overflow-source.pptx"
    expected = create_overflow_fixture(synthetic_source)
    with _capture_autofit_fallback_warnings() as synthetic_fallbacks:
        synthetic_translated = translate_first_unit(
            synthetic_source,
            output / "overflow-translated.pptx",
            expected,
        )
    baseline_pdf, baseline_pid = render_presentation(
        synthetic_source,
        output / "render-source",
        arguments.libreoffice,
        profiles,
    )
    translated_pdf, translated_pid = render_presentation(
        synthetic_translated,
        output / "render-translated",
        arguments.libreoffice,
        profiles,
    )
    process_ids.extend((baseline_pid, translated_pid))
    checks = audit_synthetic(baseline_pdf, translated_pdf, expected)
    checks.update(
        autofit_policy_checks(
            synthetic_source,
            synthetic_translated,
            arguments.autofit_policy,
            fallback_warning_count=synthetic_fallbacks[_UNRESOLVED_FONT_SIZE_REASON],
            line_spacing_fallback_warning_count=(
                synthetic_fallbacks[_UNMATERIALIZED_LINE_SPACING_REASON]
            ),
        ),
    )
    checks["unselected_slide_xml_identity"] = slide_xml_equal(synthetic_source, synthetic_translated, 2)

    original_hash = sha256(arguments.ppt)
    sample_source = copy_source(arguments.ppt, output / "sample-source.pptx")
    with _capture_autofit_fallback_warnings() as sample_fallbacks:
        sample_translated = translate_first_unit(
            sample_source,
            output / "translated-sample.pptx",
            "HEAD_SAMPLE 已翻译营养内容 TAIL_SAMPLE",
        )
    sample_autofit_checks = autofit_policy_checks(
        sample_source,
        sample_translated,
        arguments.autofit_policy,
        fallback_warning_count=sample_fallbacks[_UNRESOLVED_FONT_SIZE_REASON],
        line_spacing_fallback_warning_count=(
            sample_fallbacks[_UNMATERIALIZED_LINE_SPACING_REASON]
        ),
    )
    checks.update({f"sample_{key}": value for key, value in sample_autofit_checks.items()})
    sample_pdf, sample_pid = render_presentation(
        sample_translated,
        output / "render-sample",
        arguments.libreoffice,
        profiles,
    )
    process_ids.append(sample_pid)
    sample_text, sample_pages = _pdf_text_and_pages(sample_pdf)
    checks["sample_source_sha256_unchanged"] = sha256(arguments.ppt) == original_hash
    checks["sample_markers_present_once"] = (
        sample_text.count("HEAD_SAMPLE") == 1 and sample_text.count("TAIL_SAMPLE") == 1
    )
    checks["sample_slide_count_preserved"] = sample_pages == _slide_count(sample_source)
    checks["sample_selected_slide_changed"] = not slide_xml_equal(sample_source, sample_translated, 1)
    checks["owned_libreoffice_processes_remaining_zero"] = processes_exited(process_ids)

    boolean_checks = {key: value for key, value in checks.items() if isinstance(value, bool)}
    payload = {
        "provider": arguments.provider,
        "pptx_semantic_qa_mode": arguments.semantic_qa_mode,
        "pptx_xml_autofit_policy": arguments.autofit_policy,
        "source": str(arguments.ppt),
        "source_sha256": original_hash,
        "checks": checks,
        "all_checks_passed": all(boolean_checks.values()),
        "owned_process_ids": process_ids,
    }
    (output / "acceptance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["all_checks_passed"] else 1


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provider", default="deterministic")
    parser.add_argument("--ppt", type=Path, required=True)
    parser.add_argument("--libreoffice", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--autofit-policy",
        choices=("editable", "legacy_norm"),
        default=_environment_choice(
            "PPTX_XML_AUTOFIT_POLICY",
            ("editable", "legacy_norm"),
            "editable",
        ),
    )
    parser.add_argument(
        "--semantic-qa-mode",
        choices=("enforce", "observe", "off"),
        default=_environment_choice(
            "PPTX_SEMANTIC_QA_MODE",
            ("enforce", "observe", "off"),
            "enforce",
        ),
    )
    return parser.parse_args()


def _environment_choice(name: str, allowed: tuple[str, ...], default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in allowed else default


def _pdf_text_and_pages(path: Path) -> tuple[str, int]:
    import fitz

    with fitz.open(path) as document:
        return "\n".join(page.get_text() for page in document), len(document)


def _slide_count(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        return len(
            [
                name
                for name in archive.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ],
        )


if __name__ == "__main__":
    raise SystemExit(main())
