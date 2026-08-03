#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Final, Iterator, Protocol, Sequence

DEFAULT_SHAPE_IDS: Final = (43, 17, 33, 50, 14, 11)
DEFAULT_COMMAND_ID: Final = "FontSizeIncrease"
EXIT_PASSED: Final = 0
EXIT_ACCEPTANCE_FAILED: Final = 1
EXIT_INPUT_ERROR: Final = 2
EXIT_ENVIRONMENT_ERROR: Final = 3


class CliInputError(ValueError):
    """Raised when command-line input cannot describe a safe acceptance run."""


class PowerPointOperationError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        self.message = message
        super().__init__(message)


class PowerPointEnvironmentError(RuntimeError):
    """Raised when this machine cannot start the required PowerPoint automation boundary."""


@dataclass(frozen=True, slots=True)
class TargetSelector:
    shape_id: int
    slide_number: int | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceArguments:
    source: Path
    selectors: tuple[TargetSelector, ...]
    increase_count: int
    keep_copy: bool
    json_output: Path | None


@dataclass(frozen=True, slots=True)
class WorkingCopy:
    path: Path
    directory: Path


@dataclass(frozen=True, slots=True)
class OpenObservation:
    full_name: str
    read_only: bool
    saved: bool
    repair_suspected: bool


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    slide_number: int
    shape_id: int
    shape_name: str


@dataclass(frozen=True, slots=True)
class FontObservation:
    body_autosize: int | None
    body_autosize_name: str | None
    logical_font_size_pt: float | None
    display_font_size_pt: float | None
    display_font_size_source: str | None
    text_frame_autosize: int | None = None
    text_frame2_autosize: int | None = None
    logical_font_size_source: str | None = None


class PowerPointAutomation(Protocol):
    def open_presentation(self, path: Path) -> OpenObservation: ...

    def resolve_target(self, selector: TargetSelector) -> ResolvedTarget: ...

    def select_all_text(self, target: ResolvedTarget) -> FontObservation: ...

    def execute_mso(self, command_id: str) -> None: ...

    def observe_selected_text(self, target: ResolvedTarget) -> FontObservation: ...

    def save_presentation(self) -> None: ...

    def close_presentation(self) -> None: ...

    def quit(self) -> None: ...


class Win32PowerPointAutomation:
    """Thin pywin32 adapter that drives a dedicated visible PowerPoint instance."""

    def __init__(
        self,
        application: Any,
        *,
        co_uninitialize: Callable[[], None],
        command_delay_seconds: float = 0.1,
    ) -> None:
        self._application = application
        self._co_uninitialize = co_uninitialize
        self._command_delay_seconds = command_delay_seconds
        self._presentation: Any | None = None
        self._selected_target: ResolvedTarget | None = None
        self._co_initialized = True

    def open_presentation(self, path: Path) -> OpenObservation:
        if self._presentation is not None:
            raise PowerPointOperationError("open", "a presentation is already open in this automation session")
        expected = path.resolve()
        try:
            presentation = self._application.Presentations.Open(str(expected), 0, 0, -1)
            self._presentation = presentation
            full_name = str(presentation.FullName)
            read_only = _office_true(presentation.ReadOnly)
            saved = _office_true(presentation.Saved)
            has_window = int(presentation.Windows.Count) > 0
        except Exception as exc:
            self._presentation = None
            raise PowerPointOperationError("open", _exception_message(exc)) from exc
        repair_suspected = not saved or not has_window or not _same_path(Path(full_name), expected)
        return OpenObservation(
            full_name=full_name,
            read_only=read_only,
            saved=saved,
            repair_suspected=repair_suspected,
        )

    def resolve_target(self, selector: TargetSelector) -> ResolvedTarget:
        presentation = self._require_presentation("resolve_target")
        try:
            slides = (
                [_collection_item(presentation.Slides, selector.slide_number)]
                if selector.slide_number is not None
                else [_collection_item(presentation.Slides, index) for index in range(1, int(presentation.Slides.Count) + 1)]
            )
        except Exception as exc:
            raise PowerPointOperationError(
                "resolve_target",
                f"slide {selector.slide_number} does not exist: {_exception_message(exc)}",
            ) from exc

        matches: list[tuple[Any, Any]] = []
        try:
            for slide in slides:
                for index in range(1, int(slide.Shapes.Count) + 1):
                    shape = _collection_item(slide.Shapes, index)
                    if int(shape.Id) == selector.shape_id:
                        matches.append((slide, shape))
        except Exception as exc:
            raise PowerPointOperationError("resolve_target", _exception_message(exc)) from exc
        if not matches:
            scope = f"slide {selector.slide_number}" if selector.slide_number is not None else "the presentation"
            raise PowerPointOperationError(
                "resolve_target",
                f"shape id {selector.shape_id} was not found in {scope}",
            )
        if len(matches) > 1:
            slide_numbers = [int(slide.SlideIndex) for slide, _shape in matches]
            raise PowerPointOperationError(
                "resolve_target",
                f"shape id {selector.shape_id} is ambiguous on slides {slide_numbers}; use --slide-shape",
            )
        slide, shape = matches[0]
        if not _office_true(shape.HasTextFrame) or not _office_true(shape.TextFrame.HasText):
            raise PowerPointOperationError(
                "resolve_target",
                f"shape id {selector.shape_id} on slide {int(slide.SlideIndex)} has no selectable text",
            )
        return ResolvedTarget(
            slide_number=int(slide.SlideIndex),
            shape_id=int(shape.Id),
            shape_name=str(shape.Name),
        )

    def select_all_text(self, target: ResolvedTarget) -> FontObservation:
        presentation = self._require_presentation("select_text")
        try:
            slide = _collection_item(presentation.Slides, target.slide_number)
            shape = _shape_by_id(slide, target.shape_id)
            window = _collection_item(presentation.Windows, 1)
            window.Activate()
            window.ViewType = 9  # ppViewNormal; text ranges cannot be selected in slide-sorter view.
            window.View.GotoSlide(target.slide_number)
            try:
                shape.TextFrame2.TextRange.Select()
            except Exception:
                shape.TextFrame.TextRange.Select()
            self._selected_target = target
        except Exception as exc:
            raise PowerPointOperationError("select_text", _exception_message(exc)) from exc
        return self.observe_selected_text(target)

    def execute_mso(self, command_id: str) -> None:
        if self._selected_target is None:
            raise PowerPointOperationError("ribbon_command", "no text is selected")
        try:
            if not bool(self._application.CommandBars.GetEnabledMso(command_id)):
                raise RuntimeError(f"Ribbon command {command_id!r} is not enabled or visible")
            self._application.CommandBars.ExecuteMso(command_id)
            if self._command_delay_seconds > 0:
                time.sleep(self._command_delay_seconds)
        except Exception as exc:
            raise PowerPointOperationError("ribbon_command", _exception_message(exc)) from exc

    def observe_selected_text(self, target: ResolvedTarget) -> FontObservation:
        presentation = self._require_presentation("observe_text")
        try:
            slide = _collection_item(presentation.Slides, target.slide_number)
            shape = _shape_by_id(slide, target.shape_id)
            selection = self._application.ActiveWindow.Selection
            display_size, display_source = _first_font_size(
                ("selection.text_range2.font.size", lambda: selection.TextRange2.Font.Size),
                ("selection.text_range.font.size", lambda: selection.TextRange.Font.Size),
            )
            logical_size, logical_source = _first_font_size(
                ("shape.text_frame.text_range.font.size", lambda: shape.TextFrame.TextRange.Font.Size),
                ("shape.text_frame2.text_range.font.size", lambda: shape.TextFrame2.TextRange.Font.Size),
            )
            text_frame_autosize = _optional_int(lambda: shape.TextFrame.AutoSize)
            text_frame2_autosize = _optional_int(lambda: shape.TextFrame2.AutoSize)
            body_autosize = text_frame2_autosize if text_frame2_autosize is not None else text_frame_autosize
            body_source = "text_frame2" if text_frame2_autosize is not None else "text_frame"
        except Exception as exc:
            raise PowerPointOperationError("observe_text", _exception_message(exc)) from exc
        return FontObservation(
            body_autosize=body_autosize,
            body_autosize_name=_autosize_name(body_autosize, body_source),
            logical_font_size_pt=logical_size,
            display_font_size_pt=display_size,
            display_font_size_source=display_source,
            text_frame_autosize=text_frame_autosize,
            text_frame2_autosize=text_frame2_autosize,
            logical_font_size_source=logical_source,
        )

    def save_presentation(self) -> None:
        presentation = self._require_presentation("save")
        try:
            presentation.Save()
        except Exception as exc:
            raise PowerPointOperationError("save", _exception_message(exc)) from exc

    def close_presentation(self) -> None:
        presentation = self._presentation
        self._presentation = None
        self._selected_target = None
        if presentation is None:
            return
        try:
            if not _office_true(presentation.Saved):
                presentation.Saved = -1
            presentation.Close()
        except Exception as exc:
            raise PowerPointOperationError("close", _exception_message(exc)) from exc

    def quit(self) -> None:
        presentation = self._presentation
        self._presentation = None
        self._selected_target = None
        if presentation is not None:
            try:
                presentation.Saved = -1
                presentation.Close()
            except Exception:
                pass
        try:
            self._application.Quit()
        except Exception:
            pass
        finally:
            if self._co_initialized:
                self._co_initialized = False
                try:
                    self._co_uninitialize()
                except Exception:
                    pass

    def _require_presentation(self, stage: str) -> Any:
        if self._presentation is None:
            raise PowerPointOperationError(stage, "no presentation is open")
        return self._presentation


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliInputError(message)


def _positive_integer(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _slide_shape(raw: str) -> TargetSelector:
    try:
        slide, shape = raw.split(":", 1)
        return TargetSelector(shape_id=_positive_integer(shape), slide_number=_positive_integer(slide))
    except (ValueError, argparse.ArgumentTypeError) as exc:
        raise argparse.ArgumentTypeError("must use SLIDE:SHAPE_ID with positive integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="Exercise PowerPoint text editability on a temporary PPTX copy.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--shape-id", action="append", default=[], type=_positive_integer)
    parser.add_argument("--slide-shape", action="append", default=[], type=_slide_shape, metavar="SLIDE:SHAPE_ID")
    parser.add_argument("--increase-count", default=3, type=_positive_integer)
    parser.add_argument("--keep-copy", action="store_true", help="Retain the edited temporary PPTX for inspection.")
    parser.add_argument("--json-output", type=Path, help="Also write the JSON result to this path.")
    return parser


def parse_arguments(argv: Sequence[str]) -> AcceptanceArguments:
    namespace = build_parser().parse_args(list(argv))
    selectors = tuple(TargetSelector(shape_id=value) for value in namespace.shape_id)
    selectors += tuple(namespace.slide_shape)
    if not selectors:
        selectors = tuple(TargetSelector(shape_id=value) for value in DEFAULT_SHAPE_IDS)
    return AcceptanceArguments(
        source=namespace.source,
        selectors=selectors,
        increase_count=namespace.increase_count,
        keep_copy=namespace.keep_copy,
        json_output=namespace.json_output,
    )


@contextmanager
def temporary_working_copy(
    source: Path,
    *,
    temp_root: Path | None = None,
    keep: bool = False,
) -> Iterator[WorkingCopy]:
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="powerpoint-editability-", dir=root))
    copy_path = directory / source.name
    working_copy = WorkingCopy(path=copy_path, directory=directory)
    try:
        shutil.copy2(source, copy_path)
        yield working_copy
    finally:
        if not keep:
            resolved_root = root.resolve()
            resolved_directory = directory.resolve()
            if resolved_directory.parent != resolved_root:
                raise RuntimeError(f"refusing to clean unexpected temporary directory: {resolved_directory}")
            shutil.rmtree(resolved_directory)


def run_editability_acceptance(
    working_copy: Path,
    *,
    selectors: Sequence[TargetSelector],
    increase_count: int,
    command_id: str,
    automation: PowerPointAutomation,
) -> dict[str, Any]:
    target_results: list[dict[str, Any]] = []
    open_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        opened = automation.open_presentation(working_copy)
        open_results.append({"phase": "initial", **asdict(opened)})
        if not _open_observation_is_healthy(opened):
            errors.append({"code": "repair_or_unsafe_open", "phase": "initial", **asdict(opened)})
            automation.close_presentation()
            return {
                "status": "failed",
                "passed": False,
                "command_id": command_id,
                "increase_count": increase_count,
                "opens": open_results,
                "targets": [],
                "checks": {
                    "all_steps_strictly_increased": False,
                    "saved_values_survived_reopen": False,
                    "opens_healthy_without_repair": False,
                },
                "errors": errors,
            }
        for selector in selectors:
            target = automation.resolve_target(selector)
            initial = automation.select_all_text(target)
            previous = initial
            increments: list[dict[str, Any]] = []
            for step in range(1, increase_count + 1):
                automation.execute_mso(command_id)
                current = automation.observe_selected_text(target)
                increased = _strictly_increased(previous.display_font_size_pt, current.display_font_size_pt)
                increments.append({"step": step, **asdict(current), "strictly_increased": increased})
                if not increased:
                    errors.append(
                        {
                            "code": "font_size_not_increased",
                            "selector": asdict(selector),
                            "step": step,
                            "before_display_font_size_pt": previous.display_font_size_pt,
                            "after_display_font_size_pt": current.display_font_size_pt,
                        },
                    )
                previous = current
            target_results.append(
                {
                    "selector": asdict(selector),
                    "resolved": asdict(target),
                    "initial": asdict(initial),
                    "increments": increments,
                    "final_before_save": asdict(previous),
                },
            )
        automation.save_presentation()
        automation.close_presentation()

        reopened = automation.open_presentation(working_copy)
        open_results.append({"phase": "reopen", **asdict(reopened)})
        if not _open_observation_is_healthy(reopened):
            errors.append({"code": "repair_or_unsafe_open", "phase": "reopen", **asdict(reopened)})
            automation.close_presentation()
            return {
                "status": "failed",
                "passed": False,
                "command_id": command_id,
                "increase_count": increase_count,
                "opens": open_results,
                "targets": target_results,
                "checks": {
                    "all_steps_strictly_increased": all(
                        step["strictly_increased"]
                        for target in target_results
                        for step in target["increments"]
                    ),
                    "saved_values_survived_reopen": False,
                    "opens_healthy_without_repair": False,
                },
                "errors": errors,
            }
        for target_result, selector in zip(target_results, selectors, strict=True):
            target = automation.resolve_target(selector)
            observation = automation.select_all_text(target)
            target_result["reopened"] = asdict(observation)
            survived_reopen = _same_observation(
                target_result["final_before_save"],
                observation,
            )
            target_result["saved_values_survived_reopen"] = survived_reopen
            if not survived_reopen:
                errors.append(
                    {
                        "code": "saved_value_changed_after_reopen",
                        "selector": asdict(selector),
                        "before_save": target_result["final_before_save"],
                        "after_reopen": asdict(observation),
                    },
                )
        automation.close_presentation()
    except PowerPointOperationError as exc:
        errors.append(
            {
                "code": "powerpoint_operation_failed",
                "stage": exc.stage,
                "message": exc.message,
            },
        )
        return {
            "status": "failed",
            "passed": False,
            "command_id": command_id,
            "increase_count": increase_count,
            "opens": open_results,
            "targets": target_results,
            "checks": {
                "all_steps_strictly_increased": False,
                "saved_values_survived_reopen": False,
                "opens_healthy_without_repair": False,
            },
            "errors": errors,
        }
    finally:
        automation.quit()

    all_steps_increased = all(
        step["strictly_increased"]
        for target in target_results
        for step in target["increments"]
    )
    values_survived = all(target["saved_values_survived_reopen"] for target in target_results)
    opens_healthy = bool(open_results) and all(
        not item["read_only"] and item["saved"] and not item["repair_suspected"] for item in open_results
    )
    checks = {
        "all_steps_strictly_increased": all_steps_increased,
        "saved_values_survived_reopen": values_survived,
        "opens_healthy_without_repair": opens_healthy,
    }
    passed = bool(target_results) and all(checks.values())
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "command_id": command_id,
        "increase_count": increase_count,
        "opens": open_results,
        "targets": target_results,
        "checks": checks,
        "errors": errors,
    }


def run_cli(
    argv: Sequence[str],
    *,
    automation_factory: Callable[[], PowerPointAutomation],
    temp_root: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    arguments = parse_arguments(argv)
    source = arguments.source.expanduser().resolve()
    if not source.is_file():
        raise CliInputError(f"source PPTX does not exist or is not a file: {source}")
    if source.suffix.lower() != ".pptx":
        raise CliInputError(f"source must be a .pptx file: {source}")
    if arguments.json_output is not None and arguments.json_output.expanduser().resolve() == source:
        raise CliInputError("--json-output must not overwrite the source PPTX")
    source_hash_before = _sha256(source)
    payload: dict[str, Any]
    exit_code: int
    working_path: Path
    with temporary_working_copy(source, temp_root=temp_root, keep=arguments.keep_copy) as working_copy:
        working_path = working_copy.path.resolve()
        try:
            automation = automation_factory()
        except PowerPointEnvironmentError as exc:
            payload = {
                "schema_version": 1,
                "tool": "powerpoint_editability_acceptance",
                "status": "environment_error",
                "passed": False,
                "skipped": True,
                "source": {"path": str(source), "sha256": source_hash_before},
                "working_copy": {"path": str(working_path)},
                "selectors": [asdict(selector) for selector in arguments.selectors],
                "checks": {},
                "errors": [{"code": "powerpoint_unavailable", "message": str(exc)}],
            }
            exit_code = EXIT_ENVIRONMENT_ERROR
        else:
            result = run_editability_acceptance(
                working_path,
                selectors=arguments.selectors,
                increase_count=arguments.increase_count,
                command_id=DEFAULT_COMMAND_ID,
                automation=automation,
            )
            payload = {
                "schema_version": 1,
                "tool": "powerpoint_editability_acceptance",
                "skipped": False,
                "source": {"path": str(source), "sha256": source_hash_before},
                "working_copy": {"path": str(working_path)},
                "selectors": [asdict(selector) for selector in arguments.selectors],
                **result,
            }
            exit_code = EXIT_PASSED if result["passed"] else EXIT_ACCEPTANCE_FAILED

    source_unchanged = source.is_file() and _sha256(source) == source_hash_before
    payload["checks"]["source_sha256_unchanged"] = source_unchanged
    payload["working_copy"].update(
        {
            "retained": arguments.keep_copy,
            "exists_after_run": working_path.exists(),
        },
    )
    if not source_unchanged:
        payload["passed"] = False
        payload["status"] = "failed"
        payload["errors"].append({"code": "source_changed", "message": "the input PPTX changed during acceptance"})
        exit_code = EXIT_ACCEPTANCE_FAILED
    if arguments.json_output is not None:
        _write_json(arguments.json_output.expanduser().resolve(), payload)
    return exit_code, payload


def main(
    argv: Sequence[str] | None = None,
    *,
    automation_factory: Callable[[], PowerPointAutomation] | None = None,
    temp_root: Path | None = None,
) -> int:
    factory = automation_factory or create_powerpoint_automation
    try:
        exit_code, payload = run_cli(
            sys.argv[1:] if argv is None else argv,
            automation_factory=factory,
            temp_root=temp_root,
        )
    except CliInputError as exc:
        exit_code = EXIT_INPUT_ERROR
        payload = {
            "schema_version": 1,
            "tool": "powerpoint_editability_acceptance",
            "status": "input_error",
            "passed": False,
            "skipped": False,
            "checks": {},
            "errors": [{"code": "invalid_input", "message": str(exc)}],
        }
    except Exception as exc:
        exit_code = EXIT_ACCEPTANCE_FAILED
        payload = {
            "schema_version": 1,
            "tool": "powerpoint_editability_acceptance",
            "status": "failed",
            "passed": False,
            "skipped": False,
            "checks": {},
            "errors": [{"code": "unexpected_error", "message": _exception_message(exc)}],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _strictly_increased(before: float | None, after: float | None) -> bool:
    return before is not None and after is not None and math.isfinite(before) and math.isfinite(after) and after > before


def _open_observation_is_healthy(observation: OpenObservation) -> bool:
    return not observation.read_only and observation.saved and not observation.repair_suspected


def _same_observation(expected: dict[str, Any], actual: FontObservation) -> bool:
    return (
        _same_optional_number(expected["logical_font_size_pt"], actual.logical_font_size_pt)
        and _same_optional_number(expected["display_font_size_pt"], actual.display_font_size_pt)
        and expected["body_autosize"] == actual.body_autosize
    )


def _same_optional_number(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is second
    return math.isclose(first, second, rel_tol=0.0, abs_tol=0.01)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_powerpoint_automation() -> PowerPointAutomation:
    if os.name != "nt":
        raise PowerPointEnvironmentError("Windows desktop PowerPoint is required")
    try:
        import pythoncom
        from win32com import client as win32_client
    except ImportError as exc:
        raise PowerPointEnvironmentError(
            "pywin32 is required; install it in this Python environment before running PowerPoint acceptance",
        ) from exc

    try:
        pythoncom.CoInitialize()
    except Exception as exc:
        raise PowerPointEnvironmentError(f"COM initialization failed: {_exception_message(exc)}") from exc
    application: Any | None = None
    try:
        application = win32_client.DispatchEx("PowerPoint.Application")
        application.Visible = -1
        application.DisplayAlerts = 1
        try:
            application.AutomationSecurity = 3
        except Exception:
            pass
    except Exception as exc:
        try:
            if application is not None:
                try:
                    application.Quit()
                except Exception:
                    pass
            pythoncom.CoUninitialize()
        finally:
            raise PowerPointEnvironmentError(
                f"Microsoft PowerPoint could not be started through COM: {_exception_message(exc)}",
            ) from exc
    return Win32PowerPointAutomation(application, co_uninitialize=pythoncom.CoUninitialize)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _collection_item(collection: Any, index: int) -> Any:
    return collection.Item(index)


def _shape_by_id(slide: Any, shape_id: int) -> Any:
    for index in range(1, int(slide.Shapes.Count) + 1):
        shape = _collection_item(slide.Shapes, index)
        if int(shape.Id) == shape_id:
            return shape
    raise LookupError(f"shape id {shape_id} no longer exists on slide {int(slide.SlideIndex)}")


def _office_true(value: Any) -> bool:
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first.resolve())) == os.path.normcase(str(second.resolve()))


def _exception_message(exc: BaseException) -> str:
    message = " ".join(str(exc).split()) or type(exc).__name__
    return message[:2000]


def _first_font_size(*readers: tuple[str, Callable[[], Any]]) -> tuple[float | None, str | None]:
    for source, reader in readers:
        try:
            value = float(reader())
        except Exception:
            continue
        if value > 0 and math.isfinite(value):
            return value, source
    return None, None


def _optional_int(reader: Callable[[], Any]) -> int | None:
    try:
        return int(reader())
    except Exception:
        return None


def _autosize_name(value: int | None, source: str) -> str | None:
    if value is None:
        return None
    if source == "text_frame2":
        return {-2: "mixed", 0: "none", 1: "shape_to_fit_text", 2: "text_to_fit_shape"}.get(
            value,
            f"unknown_{value}",
        )
    return {-2: "mixed", 0: "none", 1: "shape_to_fit_text"}.get(value, f"unknown_{value}")


if __name__ == "__main__":
    raise SystemExit(main())
