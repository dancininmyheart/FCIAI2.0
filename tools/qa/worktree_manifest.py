#!/usr/bin/env python
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict, assert_never

DYNAMIC_OMO_PREFIXES: Final = (".omo/evidence/",)
DYNAMIC_OMO_FILES: Final = (".omo/plans/translation-architecture-optimization.md", ".omo/drafts/translation-architecture-optimization.md")
PROTECTED_IGNORED_MARKERS: Final = (".env", "uploads/", "app/uploads/", "logs/", "__pycache__/", ".pytest_cache/")


class RawHashEntry(TypedDict):
    path: str
    current_sha256: str | None
    current_size: int | None
    current_missing: bool


class RawFileEntry(TypedDict):
    path: str
    sha256: str | None
    size: int | None


@dataclass(frozen=True, slots=True)
class IndexEntry:
    flag: str
    mode: str
    blob: str
    stage: str
    path: str


@dataclass(frozen=True, slots=True)
class FileState:
    path: str
    sha256: str | None
    size: int | None
    missing: bool


@dataclass(frozen=True, slots=True)
class Manifest:
    root: str
    head: str
    tracked: list[FileState]
    index: list[IndexEntry]
    untracked: list[str]
    untracked_files: list[FileState]
    ignored: list[str]
    ignored_files: list[FileState]
    omo_files: list[FileState]
    plan_created: list[str]


class ManifestError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def normalized(path: str) -> str:
    candidate = path.replace("\\", "/")
    if candidate.startswith("./"):
        return candidate[2:]
    if candidate.startswith("mo/"):
        return f".o{candidate}"
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_git(root: Path, args: list[str]) -> list[str]:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise ManifestError(completed.stderr.strip() or f"git command failed: {' '.join(args)}")
    return completed.stdout.splitlines()


def parse_index(lines: list[str]) -> list[IndexEntry]:
    entries: list[IndexEntry] = []
    for line in lines:
        meta, path = line.split("\t", 1)
        flag, mode, blob, stage = meta.split(" ")
        entries.append(IndexEntry(flag=flag, mode=mode, blob=blob, stage=stage, path=normalized(path)))
    return sorted(entries, key=lambda item: item.path)


def file_state(root: Path, path: str) -> FileState:
    full = root / path
    if not full.is_file():
        return FileState(path=path, sha256=None, size=None, missing=True)
    return FileState(path=path, sha256=sha256_file(full), size=full.stat().st_size, missing=False)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise ManifestError(f"missing snapshot {path}")
    return [normalized(line) for line in read_snapshot_text(path).splitlines() if line.strip()]


def read_snapshot_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ManifestError(f"unsupported snapshot encoding: {path}")


def read_raw_hashes(path: Path) -> tuple[str, list[RawHashEntry], list[FileState]]:
    raw = json.loads(read_snapshot_text(path))
    tracked = [RawHashEntry(path=normalized(item["path"]), current_sha256=item["current_sha256"], current_size=item["current_size"], current_missing=item["current_missing"]) for item in raw["tracked_current"]]
    immutable: dict[str, FileState] = {}
    for section in ("untracked_current", "ignored_current", "omo_files"):
        for item in raw.get(section, []):
            state = raw_file_state(item)
            immutable[state.path] = state
    return str(raw["head"]), tracked, sorted(immutable.values(), key=lambda item: item.path)


def raw_file_state(item: RawFileEntry) -> FileState:
    return FileState(path=normalized(item["path"]), sha256=item["sha256"], size=item["size"], missing=False)


def verify_prebaseline(root: Path, tracked: list[RawHashEntry], index: list[IndexEntry], snapshot_index: list[IndexEntry]) -> None:
    current_index = parse_index(run_git(root, ["ls-files", "-s", "-v"]))
    if current_index != snapshot_index:
        raise ManifestError("index mode/blob/stage/flag drift")
    for item in tracked:
        state = file_state(root, item["path"])
        if state.sha256 != item["current_sha256"] or state.missing != item["current_missing"]:
            raise ManifestError(f"prebaseline hash drift: {item['path']}")
    if index != snapshot_index:
        raise ManifestError("snapshot index is inconsistent")


def is_dynamic_omo(path: str) -> bool:
    if path.startswith(DYNAMIC_OMO_PREFIXES) or path in DYNAMIC_OMO_FILES:
        return True
    prefix = ".omo/run-continuation/"
    if not path.startswith(prefix):
        return False
    child = path.removeprefix(prefix)
    return "/" not in child and child.endswith(".json") and child != ".json"


def is_protected_ignored(path: str) -> bool:
    return path == ".env" or any(marker in path for marker in PROTECTED_IGNORED_MARKERS)


def capture_manifest(root: Path, snapshot_dir: Path, plan_created: list[str]) -> Manifest:
    head, tracked_hashes, immutable_files = read_raw_hashes(snapshot_dir / "initial-raw-hashes.json")
    snapshot_index = parse_index(read_lines(snapshot_dir / "initial-index-status.txt"))
    verify_prebaseline(root, tracked_hashes, snapshot_index, snapshot_index)
    tracked = [
        FileState(path=item["path"], sha256=item["current_sha256"], size=item["current_size"], missing=item["current_missing"])
        for item in tracked_hashes
    ]
    untracked = read_lines(snapshot_dir / "initial-untracked-paths.txt")
    ignored = read_lines(snapshot_dir / "initial-ignored-paths.txt")
    immutable_by_path = {item.path: item for item in immutable_files}
    return Manifest(
        root=str(root),
        head=head,
        tracked=tracked,
        index=snapshot_index,
        untracked=untracked,
        untracked_files=[immutable_by_path[path] for path in untracked if path in immutable_by_path],
        ignored=ignored,
        ignored_files=[immutable_by_path[path] for path in ignored if path in immutable_by_path],
        omo_files=[item for item in immutable_files if item.path.startswith(".omo/")],
        plan_created=sorted(normalized(path) for path in plan_created),
    )


def write_manifest(manifest: Manifest, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> Manifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        root=raw["root"],
        head=raw["head"],
        tracked=[FileState(**item) for item in raw["tracked"]],
        index=[IndexEntry(**item) for item in raw["index"]],
        untracked=raw["untracked"],
        untracked_files=[FileState(**item) for item in raw.get("untracked_files", [])],
        ignored=raw["ignored"],
        ignored_files=[FileState(**item) for item in raw.get("ignored_files", [])],
        omo_files=[FileState(**item) for item in raw["omo_files"]],
        plan_created=raw["plan_created"],
    )


def diff_manifest(root: Path, manifest: Manifest) -> list[str]:
    problems: list[str] = []
    baseline_untracked = set(manifest.untracked)
    baseline_untracked_files = {item.path: item for item in manifest.untracked_files}
    baseline_ignored = {item.path: item for item in manifest.ignored_files}
    baseline_omo = {item.path: item for item in manifest.omo_files}
    current_index = parse_index(run_git(root, ["ls-files", "-s", "-v"]))
    if current_index != manifest.index:
        problems.append("index mode/blob/stage/flag drift")
    for baseline in manifest.tracked:
        state = file_state(root, baseline.path)
        if state != baseline and baseline.path not in manifest.plan_created:
            problems.append(f"tracked drift: {baseline.path}")
    for baseline in manifest.ignored:
        state = file_state(root, baseline)
        original = baseline_ignored.get(baseline)
        if is_protected_ignored(baseline) and original is not None and state != original:
            problems.append(f"protected ignored drift: {baseline}")
    for path in sorted(baseline_untracked):
        baseline = baseline_untracked_files.get(path) or baseline_omo.get(path)
        if baseline is None or path in manifest.plan_created or is_dynamic_omo(path):
            continue
        state = file_state(root, path)
        if state == baseline:
            continue
        if path.startswith(".omo/review-"):
            problems.append(f"pre-existing .omo drift: {path}")
        else:
            problems.append(f"untracked drift: {path}")
    for path in run_git(root, ["ls-files", "--others", "--exclude-standard"]):
        candidate = normalized(path)
        if candidate.startswith(".omo/") and candidate not in baseline_untracked and not is_dynamic_omo(candidate):
            problems.append(f"new .omo artifact outside evidence: {candidate}")
    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--root", required=True)
    capture.add_argument("--snapshots", required=True)
    capture.add_argument("--output", required=True)
    capture.add_argument("--plan-created", action="append", default=[])
    diff = sub.add_parser("diff")
    diff.add_argument("--root", required=True)
    diff.add_argument("--manifest", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        match args.command:
            case "capture":
                write_manifest(capture_manifest(Path(args.root), Path(args.snapshots), args.plan_created), Path(args.output))
            case "diff":
                problems = diff_manifest(Path(args.root), load_manifest(Path(args.manifest)))
                if problems:
                    print("\n".join(problems), file=sys.stderr)
                    return 1
            case unreachable:
                assert_never(unreachable)
    except ManifestError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
