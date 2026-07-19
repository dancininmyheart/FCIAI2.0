from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True


def main() -> int:
    arguments = _arguments()
    root = arguments.root.resolve()
    sys.path.insert(0, str(root))
    from tools.qa.rendered_acceptance import (
        audit_synthetic,
        copy_source,
        count_normal_autofit,
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
    synthetic_translated = translate_first_unit(synthetic_source, output / "overflow-translated.pptx", expected)
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
    checks["one_norm_autofit_per_changed_text_body"] = count_normal_autofit(synthetic_translated) == 1
    checks["unselected_slide_xml_identity"] = slide_xml_equal(synthetic_source, synthetic_translated, 2)

    original_hash = sha256(arguments.ppt)
    sample_source = copy_source(arguments.ppt, output / "sample-source.pptx")
    sample_translated = translate_first_unit(
        sample_source,
        output / "translated-sample.pptx",
        "HEAD_SAMPLE translated nutrition content TAIL_SAMPLE",
    )
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
    return parser.parse_args()


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
