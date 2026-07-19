#!/usr/bin/env python
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, assert_never

EXPECT_NONZERO: Final = "nonzero"


@dataclass(frozen=True, slots=True)
class CaptureArgs:
    expected: int | Literal["nonzero"]
    output: Path
    child: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunRecord:
    command: list[str]
    expected: int | str
    child_exit: int
    matched: bool
    stdout: str
    stderr: str
    elapsed_seconds: float
    started_child: bool


class CliInputError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def parse_expect(raw: str) -> int | Literal["nonzero"]:
    if raw == EXPECT_NONZERO:
        return EXPECT_NONZERO
    try:
        return int(raw)
    except ValueError as exc:
        raise CliInputError("--expect must be an integer or nonzero") from exc


def parse_args(argv: list[str]) -> CaptureArgs:
    if "--" not in argv:
        raise CliInputError("missing child separator --")
    split_at = argv.index("--")
    options = argv[:split_at]
    child = tuple(argv[split_at + 1 :])
    if not child:
        raise CliInputError("missing child command after --")
    if len(options) != 4:
        raise CliInputError("usage: run_and_capture.py --expect <code|nonzero> --output <path> -- <child...>")
    parsed: dict[str, str] = {}
    for index in range(0, len(options), 2):
        parsed[options[index]] = options[index + 1]
    if set(parsed) != {"--expect", "--output"}:
        raise CliInputError("required options are --expect and --output")
    output = Path(parsed["--output"])
    if not str(output):
        raise CliInputError("--output must not be empty")
    return CaptureArgs(expected=parse_expect(parsed["--expect"]), output=output, child=child)


def expectation_matches(expected: int | Literal["nonzero"], child_exit: int) -> bool:
    match expected:
        case "nonzero":
            return child_exit != 0
        case int() as code:
            return child_exit == code
        case unreachable:
            assert_never(unreachable)


def run_child(args: CaptureArgs) -> RunRecord:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    start = time.monotonic()
    completed = subprocess.run(args.child, capture_output=True, env=env, text=True, check=False)
    elapsed = time.monotonic() - start
    matched = expectation_matches(args.expected, completed.returncode)
    return RunRecord(
        command=list(args.child),
        expected=args.expected,
        child_exit=completed.returncode,
        matched=matched,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=elapsed,
        started_child=True,
    )


def write_record(output: Path, record: RunRecord) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
    except CliInputError as exc:
        print(exc.message, file=sys.stderr)
        return 2
    record = run_child(args)
    write_record(args.output, record)
    return 0 if record.matched else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
