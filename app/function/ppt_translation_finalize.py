from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


logger = logging.getLogger(__name__)


class ProgressCallback(Protocol):
    def __call__(self, current: int, total: int) -> None: ...


@dataclass(frozen=True, slots=True)
class FinalizePresentationRequest:
    translated_path: Path
    original_path: Path
    selected_pages: Sequence[int]
    source_language: str
    target_language: str
    enable_text_splitting: str
    progress_callback: ProgressCallback | None


def finalize_translated_presentation(request: FinalizePresentationRequest) -> bool:
    final_path = _apply_ocr_if_enabled(request)
    if final_path.resolve() == request.original_path.resolve():
        return True
    if request.original_path.exists():
        request.original_path.unlink()
    shutil.move(str(final_path), str(request.original_path))
    if request.progress_callback:
        request.progress_callback(1, 1)
    logger.info("Translated presentation moved over original file: %s", request.original_path)
    return True


def _apply_ocr_if_enabled(request: FinalizePresentationRequest) -> Path:
    if request.enable_text_splitting == "False":
        logger.info("OCR disabled by enable_text_splitting=%s", request.enable_text_splitting)
        return request.translated_path

    logger.info("OCR enabled by enable_text_splitting=%s", request.enable_text_splitting)
    try:
        from .image_ocr.ocr_controller import ocr_controller
    except ImportError as error:
        logger.error("OCR module unavailable: %s", error)
        return request.translated_path

    try:
        ocr_path = ocr_controller(
            str(request.translated_path),
            selected_pages=list(request.selected_pages),
            output_path=None,
            source_language=request.source_language,
            target_language=request.target_language,
            enable_text_splitting=request.enable_text_splitting,
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.error("OCR processing failed: %s", error)
        return request.translated_path

    return Path(ocr_path) if ocr_path else request.translated_path
