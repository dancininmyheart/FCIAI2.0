from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

from app.function import ppt_translate_async
from app.translation.pptx_contract import PptxContractError


def test_pptx_contract_failure_never_enters_outer_legacy_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = importlib.import_module("app.function.pynuo_fuc.pyuno_controller")
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"not-used")
    legacy_layout_calls: list[str] = []

    def fail_contract(*args, **kwargs):
        raise PptxContractError("malformed_json", "response is not valid JSON")

    async def record_legacy_layout(path: str) -> bool:
        legacy_layout_calls.append(path)
        return False

    monkeypatch.setattr(controller, "pyuno_controller", fail_contract)
    monkeypatch.setattr(ppt_translate_async, "_adjust_ppt_layout_async", record_legacy_layout)

    with pytest.raises(PptxContractError) as raised:
        asyncio.run(
            ppt_translate_async.process_presentation_async(
                presentation_path=str(source),
                stop_words_list=[],
                custom_translations={},
                select_page=[1],
                source_language="English",
                target_language="Chinese",
                bilingual_translation="translation_only",
                progress_callback=None,
                model="qwen",
                enable_text_splitting="False",
                enable_uno_conversion=False,
            )
        )

    assert raised.value.code == "malformed_json"
    assert legacy_layout_calls == []
