from types import SimpleNamespace


def test_parse_vocabulary_ids_returns_ids_when_csv_is_valid():
    # Given
    from app.services.translation_jobs import parse_vocabulary_ids

    raw_ids = "1, 2,3,, "

    # When
    parsed_ids = parse_vocabulary_ids(raw_ids)

    # Then
    assert parsed_ids == [1, 2, 3]


def test_parse_vocabulary_ids_returns_empty_when_any_id_is_invalid():
    # Given
    from app.services.translation_jobs import parse_vocabulary_ids

    raw_ids = "1, bad, 3"

    # When
    parsed_ids = parse_vocabulary_ids(raw_ids)

    # Then
    assert parsed_ids == []


def test_build_custom_translation_map_uses_language_aliases_and_skips_blank_pairs():
    # Given
    from app.services.translation_jobs import build_custom_translation_map

    records = [
        SimpleNamespace(english="Milk", chinese="牛奶", dutch="Melk"),
        SimpleNamespace(english="Cream", chinese="", dutch="Room"),
        SimpleNamespace(english="Water", chinese="水", dutch=None),
    ]

    # When
    translation_map = build_custom_translation_map(
        records,
        source_language="EN",
        target_language="ZH",
    )

    # Then
    assert translation_map == {
        "Milk": "牛奶",
        "Water": "水",
    }


def test_get_upload_size_limit_uses_configured_flask_limit():
    # Given
    from app.services.translation_jobs import get_upload_size_limit

    config = {"MAX_CONTENT_LENGTH": 200 * 1024 * 1024}

    # When
    limit = get_upload_size_limit(config)

    # Then
    assert limit == 200 * 1024 * 1024


def test_build_translation_job_request_preserves_selected_model_and_request_fields():
    # Given
    from app.services.translation_jobs import TranslationJobSpec, build_translation_job_request

    spec = TranslationJobSpec(
        file_type="pdf",
        source_language="english",
        target_language="chinese",
        model="qwen",
        selected_pages=(2,),
        enable_image_ocr=True,
        vocabulary_ids=(4, 5),
    )

    # When
    request = build_translation_job_request(spec)

    # Then
    assert request.to_json()["model"] == "qwen"
    assert request.to_json()["selected_pages"] == [2]
    assert request.to_json()["vocabulary_ids"] == [4, 5]


def test_build_translation_job_request_rejects_dormant_gpt_aliases():
    # Given
    import pytest

    from app.services.translation_jobs import (
        InvalidTranslationJobSpec,
        TranslationJobSpec,
        build_translation_job_request,
    )

    spec = TranslationJobSpec(
        file_type="pdf",
        source_language="english",
        target_language="chinese",
        model="gpt4o",
    )

    # When / Then
    with pytest.raises(InvalidTranslationJobSpec):
        build_translation_job_request(spec)


def test_ppt_upload_limit_uses_current_flask_config():
    # Given
    from flask import Flask

    from app.views import main as main_module

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

    # When
    with app.app_context():
        limit = main_module.get_ppt_upload_limit()

    # Then
    assert limit == 200 * 1024 * 1024
