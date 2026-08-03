import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.qa.run_translation_acceptance import autofit_policy_checks


ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_cli_exposes_quality_and_autofit_rollback_modes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/qa/run_translation_acceptance.py"), "--help"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    assert "--autofit-policy {editable,legacy_norm}" in result.stdout
    assert "--semantic-qa-mode {enforce,observe,off}" in result.stdout


@pytest.mark.parametrize(
    "path",
    [
        ROOT / "README.md",
        ROOT / "docs/TRANSLATION_ARCHITECTURE.md",
        ROOT / "docs/PROJECT_ARCHITECTURE_AND_REQUIREMENTS.md",
    ],
)
def test_operator_docs_describe_pptx_quality_and_autofit_controls(path: Path) -> None:
    documentation = path.read_text(encoding="utf-8")

    assert "PPTX_SEMANTIC_QA_MODE=enforce" in documentation
    assert "PPTX_XML_AUTOFIT_POLICY=editable" in documentation
    assert "legacy_norm" in documentation


def test_editable_acceptance_requires_persisted_fit_without_hidden_font_scale(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:normAutofit fontScale='60000' lnSpcReduction='10000'/>",
        font_size=1800,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后的长文本",
        body_properties="<a:noAutofit/>",
        font_size=900,
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks == {
        "text_body_count_equal": True,
        "text_body_identity_equal": True,
        "changed_text_body_found": True,
        "editable_unresolved_inherited_font_size_fallback_count": 0,
        "editable_unresolved_inherited_font_size_fallback_absent": True,
        "editable_unmaterialized_line_spacing_fallback_count": 0,
        "editable_unmaterialized_line_spacing_fallback_absent": True,
        "editable_non_full_norm_autofit_remaining_zero": True,
        "editable_changed_text_bodies_have_persisted_fit": True,
    }


def test_editable_acceptance_rejects_non_full_normal_autofit(tmp_path: Path) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:noAutofit/>",
        font_size=1800,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:normAutofit fontScale='70000' lnSpcReduction='5000'/>",
        font_size=1800,
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["editable_non_full_norm_autofit_remaining_zero"] is False
    assert checks["editable_changed_text_bodies_have_persisted_fit"] is False


def test_acceptance_rejects_text_body_count_drift(tmp_path: Path) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:noAutofit/>",
        font_size=1800,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:noAutofit/>",
        font_size=900,
        extra_text_body=(
            "<p:sp><p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr>"
            "<a:p><a:r><a:rPr sz='900'/><a:t>多出的文本体</a:t></a:r></a:p>"
            "</p:txBody></p:sp>"
        ),
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["text_body_count_equal"] is False
    boolean_checks = {key: value for key, value in checks.items() if isinstance(value, bool)}
    assert all(boolean_checks.values()) is False


def test_editable_acceptance_reports_unresolved_inherited_size_fallback(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:normAutofit fontScale='60000' lnSpcReduction='10000'/>",
        font_size=None,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:normAutofit fontScale='60000' lnSpcReduction='10000'/>",
        font_size=None,
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["editable_unresolved_inherited_font_size_fallback_count"] == 1
    assert checks["editable_unresolved_inherited_font_size_fallback_absent"] is False
    assert checks["editable_non_full_norm_autofit_remaining_zero"] is False


def test_editable_acceptance_uses_warning_signal_for_non_norm_fallback(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:noAutofit/>",
        font_size=None,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:noAutofit/>",
        font_size=None,
    )

    checks = autofit_policy_checks(
        source,
        translated,
        "editable",
        fallback_warning_count=1,
    )

    assert checks["editable_unresolved_inherited_font_size_fallback_count"] == 1
    assert checks["editable_unresolved_inherited_font_size_fallback_absent"] is False


def test_editable_acceptance_does_not_infer_non_norm_fallback_without_warning(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:noAutofit/>",
        font_size=None,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:noAutofit/>",
        font_size=None,
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["editable_unresolved_inherited_font_size_fallback_count"] == 0
    assert checks["editable_unresolved_inherited_font_size_fallback_absent"] is True


def test_editable_acceptance_reports_line_spacing_safety_fallback(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:normAutofit fontScale='70000' lnSpcReduction='10000'/>",
        font_size=1800,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:normAutofit fontScale='70000' lnSpcReduction='10000'/>",
        font_size=1800,
    )

    checks = autofit_policy_checks(
        source,
        translated,
        "editable",
        line_spacing_fallback_warning_count=1,
    )

    assert checks["editable_unmaterialized_line_spacing_fallback_count"] == 1
    assert checks["editable_unmaterialized_line_spacing_fallback_absent"] is False


def test_line_spacing_fallback_is_not_misreported_as_unresolved_list_style_size(
    tmp_path: Path,
) -> None:
    list_style = "<a:defPPr><a:defRPr sz='1800'/></a:defPPr>"
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:normAutofit fontScale='70000' lnSpcReduction='10000'/>",
        font_size=None,
        list_style=list_style,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:normAutofit fontScale='70000' lnSpcReduction='10000'/>",
        font_size=None,
        list_style=list_style,
    )

    checks = autofit_policy_checks(
        source,
        translated,
        "editable",
        line_spacing_fallback_warning_count=1,
    )

    assert checks["editable_unresolved_inherited_font_size_fallback_count"] == 0
    assert checks["editable_unmaterialized_line_spacing_fallback_count"] == 1


def test_editable_acceptance_allows_preserved_full_scale_norm_with_line_reduction(
    tmp_path: Path,
) -> None:
    body_properties = (
        "<a:normAutofit fontScale='100000' lnSpcReduction='10000'/>"
    )
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties=body_properties,
        font_size=None,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties=body_properties,
        font_size=None,
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["editable_unresolved_inherited_font_size_fallback_count"] == 0
    assert checks["editable_non_full_norm_autofit_remaining_zero"] is True
    assert checks["editable_changed_text_bodies_have_persisted_fit"] is True


def test_acceptance_matches_reordered_text_bodies_by_stable_shape_id(
    tmp_path: Path,
) -> None:
    source = _write_shapes_pptx(
        tmp_path / "source.pptx",
        [
            (10, "Unchanged", "<a:noAutofit/>", 1800),
            (20, "Original target", "<a:noAutofit/>", 1800),
        ],
    )
    translated = _write_shapes_pptx(
        tmp_path / "translated.pptx",
        [
            (20, "翻译后文本", "<a:noAutofit/>", 900),
            (
                10,
                "Unchanged",
                "<a:normAutofit fontScale='60000' lnSpcReduction='10000'/>",
                1800,
            ),
        ],
    )

    checks = autofit_policy_checks(source, translated, "editable")

    assert checks["text_body_count_equal"] is True
    assert checks["text_body_identity_equal"] is True
    assert checks["editable_non_full_norm_autofit_remaining_zero"] is True


def test_legacy_acceptance_requires_one_unconflicted_normal_autofit(
    tmp_path: Path,
) -> None:
    source = _write_pptx(
        tmp_path / "source.pptx",
        text="Original target",
        body_properties="<a:noAutofit/>",
        font_size=1800,
    )
    translated = _write_pptx(
        tmp_path / "translated.pptx",
        text="翻译后文本",
        body_properties="<a:normAutofit fontScale='65000' lnSpcReduction='10000'/>",
        font_size=1800,
    )

    checks = autofit_policy_checks(source, translated, "legacy_norm")

    assert checks == {
        "text_body_count_equal": True,
        "text_body_identity_equal": True,
        "changed_text_body_found": True,
        "legacy_one_norm_autofit_per_changed_text_body": True,
    }


def _write_pptx(
    path: Path,
    *,
    text: str,
    body_properties: str,
    font_size: int | None,
    extra_text_body: str = "",
    list_style: str = "",
) -> Path:
    run_properties = f"<a:rPr sz='{font_size}'/>" if font_size is not None else "<a:rPr/>"
    slide_xml = f"""<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
       xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>
  <p:cSld><p:spTree><p:sp><p:txBody>
    <a:bodyPr>{body_properties}</a:bodyPr><a:lstStyle>{list_style}</a:lstStyle>
    <a:p><a:r>{run_properties}<a:t>{text}</a:t></a:r></a:p>
  </p:txBody></p:sp>{extra_text_body}</p:spTree></p:cSld>
</p:sld>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
    return path


def _write_shapes_pptx(
    path: Path,
    shapes: list[tuple[int, str, str, int]],
) -> Path:
    shape_xml = "".join(
        (
            f"<p:sp><p:nvSpPr><p:cNvPr id='{shape_id}' name='shape-{shape_id}'/>"
            "</p:nvSpPr><p:txBody>"
            f"<a:bodyPr>{body_properties}</a:bodyPr>"
            f"<a:p><a:r><a:rPr sz='{font_size}'/><a:t>{value}</a:t></a:r></a:p>"
            "</p:txBody></p:sp>"
        )
        for shape_id, value, body_properties, font_size in shapes
    )
    slide_xml = f"""<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
       xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>
  <p:cSld><p:spTree>{shape_xml}</p:spTree></p:cSld>
</p:sld>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
    return path
