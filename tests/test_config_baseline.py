from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path


def test_root_config_does_not_default_to_api_key(monkeypatch) -> None:
    # Given
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("API_KEY", raising=False)
    sys.modules.pop("config", None)

    # When
    import config

    reloaded_config = importlib.reload(config)

    # Then
    assert reloaded_config.api_key == ""


def test_root_config_reexports_every_canonical_name_and_legacy_alias() -> None:
    # Given
    canonical = importlib.import_module("app.config")
    import config as root_config

    expected_names = set(canonical.__all__) | {"base_model_file", "api_key", "data_file", "config", "app_config"}

    # When / Then
    assert set(root_config.__all__) == expected_names
    assert expected_names <= set(dir(root_config))
    for name in expected_names:
        assert getattr(root_config, name) == getattr(canonical, name)


def test_config_compatibility_aliases_are_native_strings(monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BASE_MODEL_FILE", r"D:\native\model")
    monkeypatch.setenv("API_KEY", "native-key")
    monkeypatch.setenv("DATA_FILE", r"D:\native\data.json")
    import config

    root_config = importlib.reload(config)

    # When
    keyed = {root_config.api_key: "found"}

    # Then
    assert type(root_config.api_key) is str
    assert type(root_config.base_model_file) is str
    assert type(root_config.data_file) is str
    assert json.loads(json.dumps({"api_key": root_config.api_key})) == {"api_key": "native-key"}
    assert Path(root_config.base_model_file).name == "model"
    assert root_config.api_key + "-suffix" == "native-key-suffix"
    assert root_config.api_key.startswith("native")
    assert f"{root_config.api_key}" == "native-key"
    assert keyed[root_config.api_key] == "found"


def test_root_reload_updates_new_imports_but_not_already_bound_snapshots(monkeypatch) -> None:
    # Given
    monkeypatch.setenv("BASE_MODEL_FILE", r"D:\compat\model-a")
    monkeypatch.setenv("API_KEY", "compat-key-a")
    monkeypatch.setenv("DATA_FILE", r"D:\compat\data-a.json")
    sys.modules.pop("config", None)
    import config
    from config import api_key as snapshot_api_key
    from config import base_model_file as snapshot_base_model_file
    from config import data_file as snapshot_data_file

    assert snapshot_api_key == "compat-key-a"

    # When
    monkeypatch.setenv("BASE_MODEL_FILE", r"D:\compat\model-b")
    monkeypatch.setenv("API_KEY", "compat-key-b")
    monkeypatch.setenv("DATA_FILE", r"D:\compat\data-b.json")
    canonical = importlib.reload(importlib.import_module("app.config"))
    root_config = importlib.reload(config)
    from config import api_key as refreshed_api_key
    from config import base_model_file as refreshed_base_model_file
    from config import data_file as refreshed_data_file

    # Then
    assert root_config.api_key == canonical.api_key == refreshed_api_key == "compat-key-b"
    assert root_config.base_model_file == refreshed_base_model_file == r"D:\compat\model-b"
    assert root_config.data_file == refreshed_data_file == r"D:\compat\data-b.json"
    assert snapshot_api_key == "compat-key-a"
    assert snapshot_base_model_file == r"D:\compat\model-a"
    assert snapshot_data_file == r"D:\compat\data-a.json"


def test_root_reload_does_not_mutate_unrelated_module_globals(monkeypatch) -> None:
    # Given
    monkeypatch.setenv("API_KEY", "module-global-key")
    unrelated = types.ModuleType("unrelated_config_consumer")
    unrelated.api_key = "leave-me-alone"
    monkeypatch.setitem(sys.modules, unrelated.__name__, unrelated)
    import config

    # When
    importlib.reload(config)

    # Then
    assert unrelated.api_key == "leave-me-alone"
