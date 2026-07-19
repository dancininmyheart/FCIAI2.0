from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


RUNNER = Path("tools/qa/run_and_capture.py")


def test_runner_records_child_exit_when_expectation_matches(tmp_path: Path) -> None:
    # Given
    output = tmp_path / "capture.json"

    # When
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--expect", "nonzero", "--output", str(output), "--", sys.executable, "-c", "raise SystemExit(7)"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    record = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert record["child_exit"] == 7
    assert record["matched"] is True
    assert record["started_child"] is True


def test_runner_uses_exit_status_not_success_looking_output(tmp_path: Path) -> None:
    # Given
    output = tmp_path / "capture.json"

    # When
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--expect", "0", "--output", str(output), "--", sys.executable, "-c", "print('PASS 12 passed'); raise SystemExit(9)"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    record = json.loads(output.read_text(encoding="utf-8"))
    assert completed.returncode == 1
    assert record["child_exit"] == 9
    assert record["matched"] is False
    assert "PASS 12 passed" in record["stdout"]


def test_runner_rejects_malformed_input_without_starting_child(tmp_path: Path) -> None:
    # Given
    output = tmp_path / "must_not_exist.json"

    # When
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--expect", "zero", "--output", str(output), "--", sys.executable, "-c", "raise SystemExit(99)"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert completed.returncode == 2
    assert not output.exists()
    assert "--expect must be an integer or nonzero" in completed.stderr
