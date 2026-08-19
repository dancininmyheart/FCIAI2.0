from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from typing import Protocol, TypedDict

from flask import current_app


class LegacyBoundaryError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class LegacyTask(Protocol):
    file_path: str
    annotation_json: dict[str, list[str]] | None
    annotations: list[dict[str, str]]
    output_path: str
    select_page: list[int]
    source_language: str
    target_language: str
    bilingual_translation: str
    model: str
    enable_text_splitting: str
    enable_uno_conversion: bool
    custom_translations: dict[str, str] | None


class ProgressCallback(Protocol):
    def __call__(self, current: int, total: int) -> None: ...


class PdfCacheStatus(TypedDict, total=False):
    status: str
    filename: str
    stored_filename: str
    original_filename: str
    download_name: str
    message: str
    error: str


class LegacyQueueBoundary:
    def execute_ppt_translation_task(self, task: LegacyTask, progress_callback: ProgressCallback) -> bool:
        from app.function.ppt_translate_async import process_presentation, process_presentation_add_annotations

        custom_translations = task.custom_translations or {}
        if task.annotation_json:
            return process_presentation_add_annotations(
                presentation_path=task.file_path,
                annotations=task.annotation_json,
                stop_words=[],
                custom_translations=custom_translations,
                source_language=task.source_language,
                target_language=task.target_language,
                bilingual_translation=task.bilingual_translation,
                progress_callback=progress_callback,
                model=task.model,
            )
        return process_presentation(
            presentation_path=task.file_path,
            stop_words=[],
            custom_translations=custom_translations,
            select_page=task.select_page,
            source_language=task.source_language,
            target_language=task.target_language,
            bilingual_translation=task.bilingual_translation,
            progress_callback=progress_callback,
            model=task.model,
            enable_text_splitting=task.enable_text_splitting,
            enable_uno_conversion=task.enable_uno_conversion,
        )

    def execute_pdf_annotation_task(self, task: LegacyTask, progress_callback: ProgressCallback) -> bool:
        import asyncio  # noqa: ANYIO_OK

        from app.function.pdf_annotate_async import process_pdf_annotations_async

        output_path = task.output_path or f"{os.path.splitext(task.file_path)[0]}_annotated.pdf"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                process_pdf_annotations_async(
                    pdf_path=task.file_path,
                    annotations=task.annotations,
                    output_path=output_path,
                    progress_callback=progress_callback,
                ),
            )
        finally:
            loop.close()


def legacy_pdf_translation_status(
    pdf_path: str,
    original_filename: str,
    unique_filename: str,
    source_lang: str,
    target_lang: str,
    enable_image_ocr: bool,
    custom_translations: dict[str, str],
    user_id: int,
    task_id: str,
) -> tuple[bool, PdfCacheStatus]:
    from app import create_app, db
    from app.models import UploadRecord

    cache: dict[str, PdfCacheStatus] = {}
    app = create_app()
    with app.app_context():
        project_root = Path(__file__).resolve().parents[1] / "app"
        upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
        if not upload_folder.is_absolute():
            upload_folder = project_root / upload_folder
        pdf_output_dir = upload_folder / "pdf_outputs"
        task_work_dir = pdf_output_dir / f"{Path(unique_filename).stem}_work"
        task_work_dir.mkdir(parents=True, exist_ok=True)
        md_file = _legacy_extract_markdown(pdf_path, enable_image_ocr, task_work_dir)
        docx_filename = f"translated_{source_lang.lower()}_{target_lang.lower()}_{Path(original_filename).stem}.docx"
        docx_path = pdf_output_dir / docx_filename
        _legacy_translate_markdown(md_file, docx_path, source_lang, target_lang, custom_translations, enable_image_ocr)
        record = UploadRecord(
            filename=docx_filename,
            stored_filename=docx_filename,
            file_path=str(pdf_output_dir),
            user_id=user_id,
            file_size=docx_path.stat().st_size,
            status="completed",
        )
        db.session.add(record)
        db.session.commit()
        cache[task_id] = {
            "status": "completed",
            "filename": docx_filename,
            "stored_filename": docx_filename,
            "original_filename": original_filename,
            "download_name": docx_filename,
            "message": "缈昏瘧瀹屾垚",
        }
        return True, cache[task_id]


def _legacy_extract_markdown(pdf_path: str, enable_image_ocr: bool, task_work_dir: Path) -> Path:
    from app.function.image_ocr.ocr_api import MinerUAPI
    from app.function.image_ocr.oss_pdf_processor import OSSPDFProcessor

    result = OSSPDFProcessor().process_pdf_with_mineru(
        pdf_path,
        MinerUAPI(),
        bucket="ppt-agent-studio",
        region="cn-beijing",
        enable_ocr=enable_image_ocr,
    )
    if not result:
        from app.function.local_pdf_processor import LocalPDFProcessor

        result = LocalPDFProcessor().process_pdf(pdf_path)
    if not result:
        raise LegacyBoundaryError("鎵€鏈塒DF澶勭悊鏂规硶閮藉け璐ヤ簡")
    if "code" in result and result["code"] != 0:
        raise LegacyBoundaryError(f"PDF澶勭悊澶辫触: {result.get('msg', '鏈煡閿欒')}")
    data = result.get("data")
    if not data or "task_id" not in data:
        raise LegacyBoundaryError("MinerU杩斿洖缁撴灉缂哄皯task_id")
    if "full_zip_url" not in data:
        raise LegacyBoundaryError("MinerU杩斿洖缁撴灉缂哄皯full_zip_url")
    zip_path = task_work_dir / f"mineru_result_{data['task_id']}.zip"
    _copy_legacy_zip(data["full_zip_url"], zip_path)
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(task_work_dir)
    matches = [path for path in task_work_dir.rglob("*.md") if data["task_id"] in path.name]
    return matches[0] if matches else next(task_work_dir.rglob("*.md"))


def _copy_legacy_zip(zip_url: str, zip_path: Path) -> None:
    if not zip_url.startswith("file://"):
        raise LegacyBoundaryError("network ZIP download is outside this parity fixture")
    source_path = Path(zip_url[7:])
    if not source_path.exists():
        raise LegacyBoundaryError(f"婧愭枃浠朵笉瀛樺湪: {source_path}")
    shutil.copy2(source_path, zip_path)


def _legacy_translate_markdown(
    md_file: Path,
    docx_path: Path,
    source_lang: str,
    target_lang: str,
    custom_translations: dict[str, str],
    enable_image_ocr: bool,
) -> None:
    from app.utils.document_generator import translate_markdown_to_bilingual_doc

    lang_mapping = {"EN": "en", "en": "en", "ZH": "zh", "zh": "zh", "JA": "ja", "ja": "ja"}
    content = md_file.read_text(encoding="utf-8")
    source_language = lang_mapping.get(source_lang, "en")
    target_language = lang_mapping.get(target_lang, "zh")
    ocr_results: list[dict[str, str | bool]] = []
    if enable_image_ocr:
        from app.function.image_ocr.ocr_controller import process_markdown_images_ocr_and_translate

        ocr_results = process_markdown_images_ocr_and_translate(
            markdown_content=content,
            markdown_dir=str(md_file.parent),
            target_language=target_language,
            source_language=source_language,
        )
    ok = translate_markdown_to_bilingual_doc(
        content,
        str(docx_path),
        source_language=source_language,
        target_language=target_language,
        image_base_dir=str(md_file.parent),
        custom_translations=custom_translations,
        image_ocr_results=ocr_results,
    )
    if not ok:
        raise LegacyBoundaryError("缈昏瘧鐢熸垚Word鏂囨。澶辫触")
