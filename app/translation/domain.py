from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from app.translation.domain_types import (
    DEFAULT_PRESENTATION_DOMAIN,
    normalize_presentation_domain,
)
from app.translation.pptx_contract import PPTX_DOMAIN_DETECTION_FIELD
from app.translation.providers import ProviderRegistry
from app.translation.types import ProviderRequest


logger = logging.getLogger(__name__)

MAX_DOMAIN_SAMPLE_CHARACTERS = 4000


def build_presentation_domain_sample(
    source_texts: Iterable[str],
    max_characters: int = MAX_DOMAIN_SAMPLE_CHARACTERS,
) -> str:
    """Build a bounded, de-duplicated sample without letting one page consume it all."""
    if max_characters <= 0:
        return ""

    sources: list[str] = []
    seen: set[str] = set()
    for source_text in source_texts:
        normalized = " ".join(source_text.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        sources.append(normalized)
    if not sources:
        return ""

    complete_sample = "\n".join(sources)
    if len(complete_sample) <= max_characters:
        return complete_sample

    # Each retained source needs at least one character plus (except the first)
    # one separator. In production the sources are slide-level chunks, so this
    # gives every selected slide representation even when an early slide is long.
    source_limit = max(1, (max_characters + 1) // 2)
    sources = sources[:source_limit]
    text_budget = max_characters - (len(sources) - 1)
    fair_share = max(1, text_budget // len(sources))
    chunks = [source[:fair_share] for source in sources]
    remaining = text_budget - sum(len(chunk) for chunk in chunks)
    for index, source in enumerate(sources):
        if remaining <= 0:
            break
        extra = source[len(chunks[index]) : len(chunks[index]) + remaining]
        chunks[index] += extra
        remaining -= len(extra)
    return "\n".join(chunks)


def detect_presentation_domain(
    registry: ProviderRegistry,
    sample: str,
    source_language: str,
) -> str:
    """Classify a presentation with Qwen without making classification a hard dependency."""
    if not sample.strip():
        return DEFAULT_PRESENTATION_DOMAIN

    request = ProviderRequest.create(
        text=sample,
        source_language=source_language,
        target_language="Chinese",
        field=PPTX_DOMAIN_DETECTION_FIELD,
        output_format="structured",
        timeout_seconds=60,
    )
    try:
        response = registry.translate("qwen", request)
        payload = json.loads(response.text)
        if not isinstance(payload, dict):
            raise ValueError("domain response must be an object")
        domain = normalize_presentation_domain(payload.get("domain"))
        if domain is None:
            raise ValueError("domain response is outside the supported vocabulary")
        logger.info("presentation_domain_detected domain=%s sample_chars=%d", domain, len(sample))
        return domain
    # Domain detection is an optional enhancement. Even an unexpected SDK
    # exception must not turn an otherwise valid translation into a failed job.
    except Exception as error:
        logger.warning(
            "presentation_domain_detection_failed error_code=%s fallback=%s",
            getattr(error, "code", type(error).__name__),
            DEFAULT_PRESENTATION_DOMAIN,
        )
        return DEFAULT_PRESENTATION_DOMAIN
