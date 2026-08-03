from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qa import powerpoint_editability_acceptance as acceptance


class ScriptedPowerPointAutomation:
    def __init__(self, sizes: list[float]) -> None:
        self._sizes = iter(sizes)
        self._current_size = next(self._sizes)
        self._open_count = 0

    def open_presentation(self, path: Path) -> acceptance.OpenObservation:
        self._open_count += 1
        return acceptance.OpenObservation(
            full_name=str(path.resolve()),
            read_only=False,
            saved=True,
            repair_suspected=False,
        )

    def resolve_target(self, selector: acceptance.TargetSelector) -> acceptance.ResolvedTarget:
        return acceptance.ResolvedTarget(slide_number=2, shape_id=selector.shape_id, shape_name="Editable body")

    def select_all_text(self, target: acceptance.ResolvedTarget) -> acceptance.FontObservation:
        return self._observation()

    def execute_mso(self, command_id: str) -> None:
        self._current_size = next(self._sizes)

    def observe_selected_text(self, target: acceptance.ResolvedTarget) -> acceptance.FontObservation:
        return self._observation()

    def save_presentation(self) -> None:
        return None

    def close_presentation(self) -> None:
        return None

    def quit(self) -> None:
        return None

    def _observation(self) -> acceptance.FontObservation:
        return acceptance.FontObservation(
            body_autosize=2,
            body_autosize_name="text_to_fit_shape",
            logical_font_size_pt=self._current_size,
            display_font_size_pt=self._current_size,
            display_font_size_source="selection.text_range2.font.size",
        )


class ReopenChangesFontAutomation(ScriptedPowerPointAutomation):
    def open_presentation(self, path: Path) -> acceptance.OpenObservation:
        opened = super().open_presentation(path)
        if self._open_count == 2:
            self._current_size -= 1.0
        return opened


class RepairDetectedAutomation(ScriptedPowerPointAutomation):
    def open_presentation(self, path: Path) -> acceptance.OpenObservation:
        opened = super().open_presentation(path)
        return acceptance.OpenObservation(
            full_name=opened.full_name,
            read_only=False,
            saved=False,
            repair_suspected=True,
        )

    def resolve_target(self, selector: acceptance.TargetSelector) -> acceptance.ResolvedTarget:
        raise AssertionError("a repaired presentation must not be edited")


class OpenFailsAutomation(ScriptedPowerPointAutomation):
    def open_presentation(self, path: Path) -> acceptance.OpenObservation:
        raise acceptance.PowerPointOperationError("open", "PowerPoint rejected the PPTX")


class RepairOnReopenAutomation(ScriptedPowerPointAutomation):
    def open_presentation(self, path: Path) -> acceptance.OpenObservation:
        opened = super().open_presentation(path)
        if self._open_count == 2:
            return acceptance.OpenObservation(
                full_name=opened.full_name,
                read_only=False,
                saved=False,
                repair_suspected=True,
            )
        return opened

    def resolve_target(self, selector: acceptance.TargetSelector) -> acceptance.ResolvedTarget:
        if self._open_count == 2:
            raise AssertionError("a repaired reopened presentation must not be inspected as healthy")
        return super().resolve_target(selector)


def unavailable_powerpoint() -> acceptance.PowerPointAutomation:
    raise acceptance.PowerPointEnvironmentError("pywin32 is not installed")


class ComCollection:
    def __init__(self, *items: object) -> None:
        self._items = items
        self.Count = len(items)

    def Item(self, index: int) -> object:
        return self._items[index - 1]


class ComFont:
    def __init__(self, size: float) -> None:
        self.Size = size


class ComTextRange:
    def __init__(self, application: "ComApplication", font: ComFont) -> None:
        self._application = application
        self.Font = font

    def Select(self) -> None:
        self._application.ActiveWindow.Selection.TextRange = self
        self._application.ActiveWindow.Selection.TextRange2 = self


class ComShape:
    def __init__(self, application: "ComApplication", shape_id: int, size: float) -> None:
        font = ComFont(size)
        text_range = ComTextRange(application, font)
        self.Id = shape_id
        self.Name = "Editable body"
        self.HasTextFrame = -1
        self.TextFrame = type("TextFrame", (), {"HasText": -1, "AutoSize": 0, "TextRange": text_range})()
        self.TextFrame2 = type("TextFrame2", (), {"AutoSize": 2, "TextRange": text_range})()


class ComPresentation:
    def __init__(self, application: "ComApplication", path: Path) -> None:
        self.FullName = str(path.resolve())
        self.ReadOnly = 0
        self.Saved = -1
        shape = ComShape(application, 43, 12.0)
        slide = type("Slide", (), {"SlideIndex": 1, "Shapes": ComCollection(shape)})()
        self.Slides = ComCollection(slide)
        self.Windows = ComCollection(application.ActiveWindow)

    def Save(self) -> None:
        self.Saved = -1

    def Close(self) -> None:
        return None


class ComCommandBars:
    def __init__(self, application: "ComApplication") -> None:
        self._application = application
        self.executed: list[str] = []

    def GetEnabledMso(self, command_id: str) -> bool:
        return command_id == "FontSizeIncrease"

    def ExecuteMso(self, command_id: str) -> None:
        self.executed.append(command_id)
        self._application.ActiveWindow.Selection.TextRange2.Font.Size += 2.0
        self._application.presentation.Saved = 0


class ComApplication:
    def __init__(self, path: Path) -> None:
        selection = type("Selection", (), {})()
        view = type("View", (), {"GotoSlide": lambda self, slide_number: None})()
        self.ActiveWindow = type(
            "Window",
            (),
            {"Selection": selection, "View": view, "Activate": lambda self: None},
        )()
        self.presentation = ComPresentation(self, path)
        self.Presentations = type(
            "Presentations",
            (),
            {"Open": lambda owner, *args: self.presentation},
        )()
        self.CommandBars = ComCommandBars(self)
        self.quit_called = False

    def Quit(self) -> None:
        self.quit_called = True


def test_cli_defaults_to_known_sample_shape_ids(tmp_path: Path) -> None:
    source = tmp_path / "sample.pptx"
    source.write_bytes(b"pptx")

    arguments = acceptance.parse_arguments([str(source)])

    assert [selector.shape_id for selector in arguments.selectors] == [43, 17, 33, 50, 14, 11]
    assert all(selector.slide_number is None for selector in arguments.selectors)
    assert arguments.increase_count == 3


def test_cli_accepts_global_and_slide_scoped_shape_selectors(tmp_path: Path) -> None:
    source = tmp_path / "sample.pptx"
    source.write_bytes(b"pptx")

    arguments = acceptance.parse_arguments(
        [str(source), "--shape-id", "43", "--slide-shape", "2:17", "--increase-count", "4"],
    )

    assert [(selector.slide_number, selector.shape_id) for selector in arguments.selectors] == [
        (None, 43),
        (2, 17),
    ]
    assert arguments.increase_count == 4


@pytest.mark.parametrize("value", ["0:17", "2:0", "two:17", "2-17"])
def test_cli_rejects_invalid_slide_shape_selector(tmp_path: Path, value: str) -> None:
    source = tmp_path / "sample.pptx"
    source.write_bytes(b"pptx")

    with pytest.raises(acceptance.CliInputError, match="SLIDE:SHAPE_ID"):
        acceptance.parse_arguments([str(source), "--slide-shape", value])


def test_working_copy_is_isolated_and_cleaned_by_default(tmp_path: Path) -> None:
    source = tmp_path / "customer sample.pptx"
    original = b"customer bytes"
    source.write_bytes(original)
    temp_root = tmp_path / "safe-temp"

    with acceptance.temporary_working_copy(source, temp_root=temp_root) as working_copy:
        assert working_copy.path != source
        assert working_copy.path.parent.parent == temp_root
        assert working_copy.path.read_bytes() == original
        working_copy.path.write_bytes(b"edited copy")
        working_path = working_copy.path

    assert source.read_bytes() == original
    assert not working_path.exists()


def test_working_copy_can_be_retained_for_manual_inspection(tmp_path: Path) -> None:
    source = tmp_path / "sample.pptx"
    source.write_bytes(b"pptx")

    with acceptance.temporary_working_copy(source, temp_root=tmp_path, keep=True) as working_copy:
        retained_path = working_copy.path

    assert retained_path.is_file()
    assert retained_path.read_bytes() == b"pptx"


def test_acceptance_passes_only_after_strict_increases_survive_reopen(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")
    automation = ScriptedPowerPointAutomation([12.0, 14.0, 16.0, 18.0])

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=43, slide_number=2),),
        increase_count=3,
        command_id="FontSizeIncrease",
        automation=automation,
    )

    assert result["passed"] is True
    assert result["status"] == "passed"
    assert [step["display_font_size_pt"] for step in result["targets"][0]["increments"]] == [
        14.0,
        16.0,
        18.0,
    ]
    assert result["targets"][0]["reopened"]["display_font_size_pt"] == 18.0
    assert result["checks"]["all_steps_strictly_increased"] is True
    assert result["checks"]["saved_values_survived_reopen"] is True


def test_acceptance_fails_when_ribbon_command_leaves_display_size_unchanged(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")
    automation = ScriptedPowerPointAutomation([12.0, 12.0, 14.0])

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=17, slide_number=1),),
        increase_count=2,
        command_id="FontSizeIncrease",
        automation=automation,
    )

    assert result["passed"] is False
    assert result["status"] == "failed"
    assert result["targets"][0]["increments"][0]["strictly_increased"] is False
    assert {error["code"] for error in result["errors"]} == {"font_size_not_increased"}


def test_acceptance_fails_when_font_size_does_not_survive_reopen(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=33),),
        increase_count=1,
        command_id="FontSizeIncrease",
        automation=ReopenChangesFontAutomation([12.0, 14.0]),
    )

    assert result["passed"] is False
    assert result["checks"]["saved_values_survived_reopen"] is False
    assert result["targets"][0]["reopened"]["display_font_size_pt"] == 13.0
    assert {error["code"] for error in result["errors"]} == {"saved_value_changed_after_reopen"}


def test_acceptance_stops_when_powerpoint_reports_a_repair(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=50),),
        increase_count=1,
        command_id="FontSizeIncrease",
        automation=RepairDetectedAutomation([12.0]),
    )

    assert result["passed"] is False
    assert result["checks"]["opens_healthy_without_repair"] is False
    assert {error["code"] for error in result["errors"]} == {"repair_or_unsafe_open"}
    assert result["targets"] == []


def test_acceptance_reports_powerpoint_open_error_instead_of_crashing(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=14),),
        increase_count=1,
        command_id="FontSizeIncrease",
        automation=OpenFailsAutomation([12.0]),
    )

    assert result["passed"] is False
    assert result["status"] == "failed"
    assert result["errors"] == [
        {
            "code": "powerpoint_operation_failed",
            "stage": "open",
            "message": "PowerPoint rejected the PPTX",
        },
    ]


def test_acceptance_stops_when_reopen_requires_repair(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=11),),
        increase_count=1,
        command_id="FontSizeIncrease",
        automation=RepairOnReopenAutomation([12.0, 14.0]),
    )

    assert result["passed"] is False
    assert result["checks"]["opens_healthy_without_repair"] is False
    assert result["errors"][-1]["code"] == "repair_or_unsafe_open"
    assert result["errors"][-1]["phase"] == "reopen"


def test_cli_returns_nonzero_environment_error_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "customer.pptx"
    original = b"original pptx bytes"
    source.write_bytes(original)

    exit_code, payload = acceptance.run_cli(
        [str(source), "--shape-id", "43"],
        automation_factory=unavailable_powerpoint,
        temp_root=tmp_path / "temp-root",
    )

    assert exit_code == acceptance.EXIT_ENVIRONMENT_ERROR
    assert payload["status"] == "environment_error"
    assert payload["passed"] is False
    assert payload["skipped"] is True
    assert payload["errors"] == [
        {"code": "powerpoint_unavailable", "message": "pywin32 is not installed"},
    ]
    assert source.read_bytes() == original
    assert payload["checks"]["source_sha256_unchanged"] is True
    assert payload["working_copy"]["path"] != str(source.resolve())
    assert payload["working_copy"]["retained"] is False
    assert payload["working_copy"]["exists_after_run"] is False


def test_cli_keep_copy_retains_the_edited_temporary_pptx(tmp_path: Path) -> None:
    source = tmp_path / "customer.pptx"
    source.write_bytes(b"original pptx bytes")

    exit_code, payload = acceptance.run_cli(
        [
            str(source),
            "--slide-shape",
            "2:43",
            "--increase-count",
            "1",
            "--keep-copy",
        ],
        automation_factory=lambda: ScriptedPowerPointAutomation([12.0, 14.0]),
        temp_root=tmp_path / "temp-root",
    )

    retained_path = Path(payload["working_copy"]["path"])
    assert exit_code == acceptance.EXIT_PASSED
    assert payload["passed"] is True
    assert payload["working_copy"]["retained"] is True
    assert payload["working_copy"]["exists_after_run"] is True
    assert retained_path.is_file()
    assert retained_path != source.resolve()


def test_main_emits_machine_readable_json_and_optional_result_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "customer.pptx"
    source.write_bytes(b"pptx")
    result_file = tmp_path / "results" / "acceptance.json"

    exit_code = acceptance.main(
        [str(source), "--shape-id", "43", "--json-output", str(result_file)],
        automation_factory=unavailable_powerpoint,
        temp_root=tmp_path / "temp-root",
    )

    captured = capsys.readouterr()
    stdout_payload = json.loads(captured.out)
    assert exit_code == acceptance.EXIT_ENVIRONMENT_ERROR
    assert captured.err == ""
    assert stdout_payload["status"] == "environment_error"
    assert json.loads(result_file.read_text(encoding="utf-8")) == stdout_payload


def test_main_reports_missing_input_as_json_input_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.pptx"

    exit_code = acceptance.main(
        [str(missing)],
        automation_factory=lambda: pytest.fail("PowerPoint must not start for invalid input"),
        temp_root=tmp_path / "temp-root",
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == acceptance.EXIT_INPUT_ERROR
    assert payload["status"] == "input_error"
    assert payload["passed"] is False
    assert payload["skipped"] is False
    assert payload["errors"][0]["code"] == "invalid_input"
    assert str(missing.resolve()) in payload["errors"][0]["message"]


def test_win32com_backend_executes_real_ribbon_command_boundary(tmp_path: Path) -> None:
    working_copy = tmp_path / "copy.pptx"
    working_copy.write_bytes(b"pptx")
    application = ComApplication(working_copy)
    uninitialized: list[bool] = []
    automation = acceptance.Win32PowerPointAutomation(
        application,
        co_uninitialize=lambda: uninitialized.append(True),
        command_delay_seconds=0.0,
    )

    result = acceptance.run_editability_acceptance(
        working_copy,
        selectors=(acceptance.TargetSelector(shape_id=43),),
        increase_count=2,
        command_id="FontSizeIncrease",
        automation=automation,
    )

    assert result["passed"] is True
    assert application.CommandBars.executed == ["FontSizeIncrease", "FontSizeIncrease"]
    assert result["targets"][0]["initial"]["body_autosize"] == 2
    assert result["targets"][0]["increments"][-1]["display_font_size_pt"] == 16.0
    assert application.quit_called is True
    assert uninitialized == [True]
