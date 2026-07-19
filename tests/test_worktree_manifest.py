from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.qa.worktree_manifest import ManifestError, capture_manifest, diff_manifest, file_state


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".env\n.pytest_cache/\n__pycache__/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "add", ".gitignore", "tracked.txt")
    git(root, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "baseline", "-q")


def write_snapshots(
    root: Path,
    snapshots: Path,
    *,
    immutable_paths: list[str] | None = None,
    malformed_omo_prefix: bool = False,
) -> None:
    snapshots.mkdir(parents=True)
    tracked = ["tracked.txt", ".gitignore"]
    records = [file_state(root, path) for path in tracked]
    immutable = [file_state(root, path) for path in immutable_paths or []]
    raw_records = [
        {
            "path": item.path,
            "current_sha256": item.sha256,
            "current_size": item.size,
            "current_missing": item.missing,
        }
        for item in records
    ]
    raw_immutable = [
        {
            "path": item.path.removeprefix(".o") if malformed_omo_prefix and item.path.startswith(".omo/") else item.path,
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in immutable
    ]
    (snapshots / "initial-raw-hashes.json").write_text(
        json.dumps(
            {
                "head": git(root, "rev-parse", "HEAD").strip(),
                "tracked_current": raw_records,
                "untracked_current": raw_immutable,
                "ignored_current": raw_immutable,
                "omo_files": raw_immutable,
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "initial-index-status.txt").write_text(git(root, "ls-files", "-s", "-v"), encoding="utf-8")
    (snapshots / "initial-untracked-paths.txt").write_text("", encoding="utf-8")
    (snapshots / "initial-ignored-paths.txt").write_text(".env\n", encoding="utf-8")


def test_capture_rejects_prebaseline_hash_drift(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots)
    (tmp_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    # When / Then
    with pytest.raises(ManifestError, match="prebaseline hash drift"):
        capture_manifest(tmp_path, snapshots, [])


def test_capture_rejects_staged_deletion_or_index_flag_drift(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots)
    git(tmp_path, "update-index", "--assume-unchanged", "tracked.txt")

    # When / Then
    with pytest.raises(ManifestError, match="index mode/blob/stage/flag drift"):
        capture_manifest(tmp_path, snapshots, [])


def test_diff_rejects_added_modified_or_deleted_protected_ignored_path(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    ignored = tmp_path / ".env"
    ignored.write_text("TOKEN=before\n", encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots, immutable_paths=[".env"])
    manifest = capture_manifest(tmp_path, snapshots, [])
    ignored.write_text("TOKEN=after\n", encoding="utf-8")

    # When
    problems = diff_manifest(tmp_path, manifest)

    # Then
    assert "protected ignored drift: .env" in problems


def test_diff_rejects_new_omo_artifact_outside_evidence(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots)
    manifest = capture_manifest(tmp_path, snapshots, [])
    new_artifact = tmp_path / ".omo" / "review-new" / "state.json"
    new_artifact.parent.mkdir(parents=True)
    new_artifact.write_text("{}", encoding="utf-8")

    # When
    problems = diff_manifest(tmp_path, manifest)

    # Then
    assert "new .omo artifact outside evidence: .omo/review-new/state.json" in problems


def test_diff_rejects_prebaseline_untracked_product_drift(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    untracked = tmp_path / "untracked_product.txt"
    untracked.write_text("before\n", encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots, immutable_paths=["untracked_product.txt"])
    (snapshots / "initial-untracked-paths.txt").write_text("untracked_product.txt\n", encoding="utf-8")
    manifest = capture_manifest(tmp_path, snapshots, [])
    untracked.write_text("after\n", encoding="utf-8")

    # When
    problems = diff_manifest(tmp_path, manifest)

    # Then
    assert "untracked drift: untracked_product.txt" in problems


def test_diff_rejects_prebaseline_omo_review_drift(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    review = tmp_path / ".omo" / "review-existing" / "state.json"
    review.parent.mkdir(parents=True)
    review.write_text('{"before": true}\n', encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots, immutable_paths=[".omo/review-existing/state.json"])
    (snapshots / "initial-untracked-paths.txt").write_text(".omo/review-existing/state.json\n", encoding="utf-8")
    manifest = capture_manifest(tmp_path, snapshots, [])
    review.write_text('{"after": true}\n', encoding="utf-8")

    # When
    problems = diff_manifest(tmp_path, manifest)

    # Then
    assert "pre-existing .omo drift: .omo/review-existing/state.json" in problems


def test_diff_exempts_only_direct_json_run_continuation_files(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots)
    manifest = capture_manifest(tmp_path, snapshots, [])
    session = tmp_path / ".omo" / "run-continuation" / "session.json"
    session.parent.mkdir(parents=True)
    session.write_text("{}\n", encoding="utf-8")

    # When
    session_problems = diff_manifest(tmp_path, manifest)
    resume = tmp_path / ".omo" / "run-continuation" / "resume.txt"
    resume.write_text("unexpected\n", encoding="utf-8")
    resume_problems = diff_manifest(tmp_path, manifest)

    # Then
    assert session_problems == []
    assert "new .omo artifact outside evidence: .omo/run-continuation/resume.txt" in resume_problems


def test_capture_uses_immutable_untracked_hash_when_live_bytes_changed(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    untracked = tmp_path / "untracked_product.txt"
    untracked.write_text("immutable\n", encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    write_snapshots(tmp_path, snapshots, immutable_paths=["untracked_product.txt"])
    immutable = file_state(tmp_path, "untracked_product.txt")
    (snapshots / "initial-untracked-paths.txt").write_text("untracked_product.txt\n", encoding="utf-8")
    untracked.write_text("live mutation\n", encoding="utf-8")

    # When
    manifest = capture_manifest(tmp_path, snapshots, [])

    # Then
    by_path = {item.path: item for item in manifest.untracked_files}
    assert by_path["untracked_product.txt"].sha256 == immutable.sha256
    assert by_path["untracked_product.txt"].sha256 != file_state(tmp_path, "untracked_product.txt").sha256


def test_capture_preserves_omo_path_roundtrip_from_malformed_raw_prefix(tmp_path: Path) -> None:
    # Given
    init_repo(tmp_path)
    review = tmp_path / ".omo" / "review-x" / "result.txt"
    review.parent.mkdir(parents=True)
    review.write_text("immutable\n", encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    write_snapshots(
        tmp_path,
        snapshots,
        immutable_paths=[".omo/review-x/result.txt"],
        malformed_omo_prefix=True,
    )
    (snapshots / "initial-untracked-paths.txt").write_text(".omo/review-x/result.txt\n", encoding="utf-8")

    # When
    manifest = capture_manifest(tmp_path, snapshots, [])

    # Then
    assert [item.path for item in manifest.omo_files] == [".omo/review-x/result.txt"]
    assert all(not item.path.startswith(".oo/") for item in manifest.omo_files)


def test_initial_manifest_preserves_dirty_worktree_inventory() -> None:
    # Given
    manifest_path = Path(".omo/evidence/initial-worktree.json")

    # When
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Then
    tracked_paths = {item["path"] for item in manifest["tracked"]}
    untracked = set(manifest["untracked"])
    assert {"app/function/ppt_translate_async.py", "app/function/pynuo_fuc/pyuno_controller.py", "app/templates/auth/login.html", "app/views/main.py", "config.py"} <= tracked_paths
    assert ".omo/boulder.json" in untracked
    assert ".omo/start-work/ledger.jsonl" in untracked
