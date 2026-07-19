from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from app.jobs.path_security import pdf_output_root, upload_root
from app.jobs.types import JobKind, JobSnapshot


@dataclass(frozen=True, slots=True)
class ArtifactIntegrityError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"artifact integrity failure for {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class PreparedAttempt:
    source_path: Path
    work_path: Path
    output_path: Path
    final_path: Path
    source_sha256: str


@dataclass(frozen=True, slots=True)
class PromotedArtifact:
    path: Path
    sha256: str


class JobArtifactStore:
    def ensure_source(self, snapshot: JobSnapshot) -> tuple[Path, str]:
        if not snapshot.source_path:
            raise ArtifactIntegrityError(path=Path(), reason="job has no source path")
        source = Path(snapshot.source_path).resolve(strict=True)
        immutable = self._job_root(snapshot) / f"source{source.suffix.lower()}"
        immutable.parent.mkdir(parents=True, exist_ok=True)
        if not immutable.exists():
            _atomic_copy(source, immutable)
        digest = sha256_file(immutable)
        if snapshot.source_sha256 and snapshot.source_sha256 != digest:
            raise ArtifactIntegrityError(path=immutable, reason="source SHA-256 changed")
        return immutable, digest

    def prepare_attempt(self, snapshot: JobSnapshot) -> PreparedAttempt:
        source, source_sha256 = self.ensure_source(snapshot)
        attempt_root = self._job_root(snapshot) / "attempts" / str(snapshot.attempt)
        attempt_root.mkdir(parents=True, exist_ok=True)
        work_path = attempt_root / f"working{source.suffix.lower()}"
        _atomic_copy(source, work_path)
        output_path, final_path = self._output_paths(snapshot, attempt_root, work_path)
        return PreparedAttempt(source, work_path, output_path, final_path, source_sha256)

    def promoted(self, snapshot: JobSnapshot) -> PromotedArtifact | None:
        marker = self._job_root(snapshot) / "promoted.json"
        if not marker.is_file():
            return None
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            path = Path(payload["path"]).resolve(strict=True)
            expected = str(payload["sha256"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(path=marker, reason="invalid promotion marker") from exc
        actual = sha256_file(path)
        if actual != expected:
            raise ArtifactIntegrityError(path=path, reason="promoted SHA-256 changed")
        return PromotedArtifact(path=path, sha256=actual)

    def promote(self, snapshot: JobSnapshot, prepared: PreparedAttempt, candidate: Path) -> PromotedArtifact:
        existing = self.promoted(snapshot)
        if existing is not None:
            return existing
        resolved_candidate = candidate.resolve(strict=True)
        if not resolved_candidate.is_file():
            raise ArtifactIntegrityError(path=resolved_candidate, reason="attempt output is not a file")
        final_path = prepared.final_path.resolve()
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if resolved_candidate != final_path:
            _atomic_copy(resolved_candidate, final_path)
        digest = sha256_file(final_path)
        marker = self._job_root(snapshot) / "promoted.json"
        _atomic_text(marker, json.dumps({"path": str(final_path), "sha256": digest}, sort_keys=True))
        return PromotedArtifact(path=final_path, sha256=digest)

    def _job_root(self, snapshot: JobSnapshot) -> Path:
        return upload_root() / "jobs" / snapshot.public_id

    def _output_paths(
        self,
        snapshot: JobSnapshot,
        attempt_root: Path,
        work_path: Path,
    ) -> tuple[Path, Path]:
        match snapshot.kind:
            case JobKind.PPT_TRANSLATION:
                final_path = Path(snapshot.request["output_path"] or snapshot.source_path or work_path)
                return work_path, final_path
            case JobKind.PDF_TRANSLATION:
                original = Path(snapshot.request["original_filename"] or work_path.name).stem
                filename = (
                    f"translated_{snapshot.request['source_language'].lower()}_"
                    f"{snapshot.request['target_language'].lower()}_{original}.docx"
                )
                return attempt_root / filename, pdf_output_root() / filename
            case JobKind.PDF_ANNOTATION:
                requested = snapshot.request["output_path"]
                final_path = Path(requested) if requested else pdf_output_root() / f"{work_path.stem}_annotated.pdf"
                return attempt_root / final_path.name, final_path
            case unreachable:
                assert_never(unreachable)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_text(target: Path, content: str) -> None:
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
