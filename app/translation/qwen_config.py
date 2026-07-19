from __future__ import annotations

import os
from typing import Final


DEFAULT_QWEN_MODEL: Final = "qwen3.7-plus"


def qwen_model_name() -> str:
    return os.getenv("QWEN_MODEL", "").strip() or DEFAULT_QWEN_MODEL
