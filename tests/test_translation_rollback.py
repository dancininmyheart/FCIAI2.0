from __future__ import annotations

from app.config import TranslationSettings


def test_translation_settings_have_exact_safe_code_defaults() -> None:
    settings = TranslationSettings.from_environment({})

    assert settings == TranslationSettings(
        arch_mode="legacy",
        quality_mode="off",
        memory_enabled=False,
        auto_recover=False,
        max_concurrency=10,
        provider_max_concurrency=10,
    )


def test_provider_limit_inherits_total_and_explicit_values_are_parsed_once() -> None:
    inherited = TranslationSettings.from_environment({"TASK_QUEUE_MAX_CONCURRENT": "6"})
    explicit = TranslationSettings.from_environment(
        {
            "TRANSLATION_ARCH_MODE": "v2",
            "TRANSLATION_QUALITY_MODE": "observe",
            "TRANSLATION_MEMORY_ENABLED": "1",
            "TRANSLATION_AUTO_RECOVER": "0",
            "TASK_QUEUE_MAX_CONCURRENT": "8",
            "TRANSLATION_PROVIDER_MAX_CONCURRENT": "3",
        },
    )

    assert inherited.provider_max_concurrency == 6
    assert explicit == TranslationSettings("v2", "observe", True, False, 8, 3)


def test_exact_four_setting_rollback_restores_legacy_without_schema_action() -> None:
    rollback_environment = {
        "TRANSLATION_ARCH_MODE": "legacy",
        "TRANSLATION_QUALITY_MODE": "off",
        "TRANSLATION_MEMORY_ENABLED": "0",
        "TRANSLATION_AUTO_RECOVER": "0",
    }

    settings = TranslationSettings.from_environment(rollback_environment)

    assert settings.arch_mode == "legacy"
    assert settings.quality_mode == "off"
    assert settings.memory_enabled is False
    assert settings.auto_recover is False
    assert set(rollback_environment) == {
        "TRANSLATION_ARCH_MODE",
        "TRANSLATION_QUALITY_MODE",
        "TRANSLATION_MEMORY_ENABLED",
        "TRANSLATION_AUTO_RECOVER",
    }
