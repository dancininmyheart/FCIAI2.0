from __future__ import annotations

import sys
from importlib import import_module, reload

_LEGACY_ALIASES = frozenset(("base_model_file", "api_key", "data_file"))


def _load_canonical_config():
    if "app.config" in sys.modules:
        return reload(sys.modules["app.config"])
    return import_module("app.config")


_canonical_config = _load_canonical_config()
__all__ = sorted(set(_canonical_config.__all__) | _LEGACY_ALIASES)


def __getattr__(name: str):
    if name in __all__:
        return getattr(_canonical_config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
