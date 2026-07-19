from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from flask import current_app


@dataclass(frozen=True, slots=True)
class UnsafePath(Exception):
    value: str
    reason: str

    def __str__(self) -> str:
        return f"unsafe path {self.value}: {self.reason}"


def upload_root() -> Path:
    configured = Path(current_app.config["UPLOAD_FOLDER"])
    if configured.is_absolute():
        return configured.resolve()
    return (Path(current_app.root_path) / configured).resolve()


def pdf_output_root() -> Path:
    root = upload_root() / "pdf_outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def ppt_output_root() -> Path:
    return upload_root()


def resolve_uploaded_source(raw_path: str) -> Path:
    source = _resolve_contained(raw_path, upload_root(), must_exist=True)
    if source.suffix.lower() != ".pdf":
        raise UnsafePath(value=raw_path, reason="source must be a PDF upload")
    return source


def resolve_ppt_output(raw_path: str) -> Path:
    return _resolve_contained(raw_path, ppt_output_root(), must_exist=True)


def resolve_pdf_output(raw_path: str) -> Path:
    return _resolve_contained(raw_path, pdf_output_root(), must_exist=True)


def resolve_pdf_output_target(raw_path: str) -> Path:
    return _resolve_contained(raw_path, pdf_output_root(), must_exist=False)


def service_pdf_annotation_output(source: Path) -> Path:
    return pdf_output_root() / f"{source.stem}_annotated.pdf"


def reject_route_token(raw_token: str) -> None:
    if "%" in raw_token:
        raise UnsafePath(value=raw_token, reason="encoded path bytes are not allowed")
    if any(separator in raw_token for separator in ("\\", "/")):
        raise UnsafePath(value=raw_token, reason="path separators are not allowed")
    windows = PureWindowsPath(raw_token)
    if windows.drive or raw_token.startswith("\\\\"):
        raise UnsafePath(value=raw_token, reason="drive and UNC paths are not allowed")
    if raw_token in ("", ".", "..") or ":" in raw_token:
        raise UnsafePath(value=raw_token, reason="not a ledger task id")


def _resolve_contained(raw_path: str, root: Path, must_exist: bool) -> Path:
    if not raw_path:
        raise UnsafePath(value=raw_path, reason="missing path")
    if "%" in raw_path:
        raise UnsafePath(value=raw_path, reason="encoded path bytes are not allowed")
    if "\\" in raw_path and "/" in raw_path:
        raise UnsafePath(value=raw_path, reason="mixed path separators are not allowed")
    if raw_path.startswith("\\\\"):
        raise UnsafePath(value=raw_path, reason="UNC paths are not allowed")
    try:
        resolved = Path(raw_path).resolve(strict=must_exist)
    except OSError as exc:
        raise UnsafePath(value=raw_path, reason=str(exc)) from exc
    allowed_root = root.resolve()
    if not resolved.is_relative_to(allowed_root):
        raise UnsafePath(value=raw_path, reason=f"path escapes {allowed_root}")
    if must_exist and not resolved.is_file():
        raise UnsafePath(value=raw_path, reason="path is not a regular file")
    return resolved
