from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from typing import Final, assert_never

from app.translation.pptx_contract_types import (
    PptxContractError,
    PptxLineBreakStreamItem,
    PptxProtectedFieldStreamItem,
    PptxRequestUnit,
    PptxSegmentTranslation,
    PptxTextStreamItem,
    PptxUnitTranslation,
)
from app.translation.metrics import current_metrics


logger = logging.getLogger(__name__)

_RESERVED_MARKER_RE: Final = re.compile(
    r"\[\s*(?P<marker>b\s*l\s*o\s*c\s*k|块)\s*\]",
    re.IGNORECASE,
)
_LATIN_TOKEN_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:['’\-][A-Za-z0-9]+)*")
_DUPLICATE_TOKEN_RE: Final = re.compile(
    r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)*"
    r"|[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]"
    r"|[^\w\s]",
)
_CJK_CHARACTER_RE: Final = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_INTERNAL_WORD_SPACE_RE: Final = re.compile(
    r"[A-Za-z0-9][\u0020\u00a0\u202f]+[A-Za-z0-9]",
)
_ASCII_WORD_RE: Final = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
_SIMPLE_TITLE_WORD_RE: Final = re.compile(r"[A-Z][a-z]{2,}")
_LOWER_ACRONYM_LOWER_RE: Final = re.compile(r"[a-z][A-Z]{2,}[a-z]")
_URL_RE: Final = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>()]+")
_EMAIL_RE: Final = re.compile(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b")
_DOI_RE: Final = re.compile(r"(?i)\b(?:doi\s*:?\s*)?10\.\d{4,9}/[-._;()/:A-Z0-9]+\b")
_YEAR_RE: Final = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_CHEMICAL_FORMULA_RE: Final = re.compile(r"(?:[A-Z][a-z]?\d*){2,}")
_ALL_CAPS_ACRONYM_RE: Final = re.compile(r"[A-Z]{2,}(?:[0-9-][A-Z0-9-]*)?")
_CITATION_AUTHOR_LIST_RE: Final = re.compile(
    r"\b[A-Z][A-Za-z'’\-]{1,}(?:,\s*|\s+)[A-Z]{1,3}\.?\s*(?:,|;|&|\band\b)",
)
_CITATION_LOCATOR_RE: Final = re.compile(
    r"\b\d+\s*(?:\(\d+\))?\s*:\s*\d+(?:\s*[-–]\s*\d+)?\b",
)
_SHORT_ET_AL_CITATION_RE: Final = re.compile(
    r"\b[A-Z][A-Za-z'’\-]{1,}\s+et\s+al\.\s*,?\s*(?:19|20)\d{2}\b",
)
_HONORIFIC_PERSON_RE: Final = re.compile(
    r"\b(?:Dr|Prof|Mr|Mrs|Ms)\.?(?:\s+[A-Z][a-z]+(?:[-'’][A-Z][a-z]+)?){2,}\b",
)
_ORGANIZATION_NAME_RE: Final = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.'’\-]*\s+){1,5}"
    r"(?:Lab|Labs|Group|Institute|University|Foundation|Company|Corporation|Corp|Inc|LLC|Ltd|"
    r"Organization|Organisation|Association|Agency|Bank|Partners)\.?\b",
)
_TITLE_CASE_TOKEN_PATTERN: Final = r"[A-Z][a-z]+(?:[-'’][A-Z][a-z]+)?"
_TITLE_CASE_SEQUENCE_RE: Final = re.compile(
    rf"\b{_TITLE_CASE_TOKEN_PATTERN}(?:[ \t]+{_TITLE_CASE_TOKEN_PATTERN}){{1,4}}\b",
)
_TRADEMARKED_NAME_RE: Final = re.compile(
    rf"\b(?:{_TITLE_CASE_TOKEN_PATTERN}[ \t]+){{0,2}}"
    rf"{_TITLE_CASE_TOKEN_PATTERN}[ \t]*[®™℠][ \t]*{_TITLE_CASE_TOKEN_PATTERN}\b",
)
_PERSON_NAME_CONTEXT_RE: Final = re.compile(r"\b(?:by|from|with)\s*$", re.IGNORECASE)
_DESCRIPTIVE_TITLE_WORDS: Final = frozenset(
    {
        "analysis",
        "approach",
        "background",
        "benefits",
        "business",
        "challenges",
        "conclusion",
        "context",
        "development",
        "discussion",
        "economic",
        "evidence",
        "findings",
        "forecast",
        "framework",
        "future",
        "global",
        "goals",
        "growth",
        "health",
        "impact",
        "implications",
        "insights",
        "introduction",
        "key",
        "market",
        "mechanisms",
        "methods",
        "model",
        "objectives",
        "opportunities",
        "outlook",
        "overview",
        "performance",
        "plan",
        "proposed",
        "recommendations",
        "research",
        "results",
        "revenue",
        "review",
        "roadmap",
        "science",
        "solution",
        "strategy",
        "summary",
        "trends",
    },
)
_MEASUREMENT_UNITS: Final = frozenset(
    {
        "c",
        "cm",
        "g",
        "gb",
        "ghz",
        "h",
        "hz",
        "iu",
        "j",
        "kcal",
        "kg",
        "khz",
        "kj",
        "km",
        "l",
        "m",
        "mb",
        "mg",
        "mhz",
        "min",
        "ml",
        "mm",
        "mmol",
        "mol",
        "nm",
        "s",
        "tb",
        "ug",
        "w",
    },
)
_DUPLICATE_NONE: Final = 0
_DUPLICATE_PARTIAL: Final = 1
_DUPLICATE_WHOLE: Final = 2
_SAFE_JOINED_ENGLISH_SUFFIXES: Final = frozenset({"s", "es", "x"}) | _MEASUREMENT_UNITS
_SAFE_PRESERVED_WORD_SUFFIXES: Final = _SAFE_JOINED_ENGLISH_SUFFIXES | frozenset(
    {
        "able",
        "al",
        "ation",
        "ed",
        "er",
        "ers",
        "ible",
        "ic",
        "ing",
        "ise",
        "ised",
        "ising",
        "ism",
        "ist",
        "ists",
        "ity",
        "ization",
        "ize",
        "ized",
        "izing",
        "ly",
        "ment",
        "ness",
        "tion",
    },
)


def validate_request_units(units: tuple[PptxRequestUnit, ...]) -> None:
    unit_ids = [unit.unit_id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise PptxContractError("duplicate_unit_id", "request contains duplicate unit IDs")
    for unit in units:
        stream_ids = [item.stream_id for item in unit.source_stream]
        segment_ids = [item.segment_id for item in unit.text_items]
        if len(stream_ids) != len(set(stream_ids)) or len(segment_ids) != len(set(segment_ids)):
            raise PptxContractError("duplicate_stream_id", "request contains duplicate stream IDs", unit.unit_id)
        if not segment_ids:
            raise PptxContractError("missing_segment", "request unit has no text segment", unit.unit_id)
        if unit.layout_hint.width_emu is not None and unit.layout_hint.width_emu <= 0:
            raise PptxContractError("layout_hint", "width must be positive", unit.unit_id)
        if unit.layout_hint.height_emu is not None and unit.layout_hint.height_emu <= 0:
            raise PptxContractError("layout_hint", "height must be positive", unit.unit_id)


def validate_pptx_translations(
    expected_units: tuple[PptxRequestUnit, ...],
    translations: tuple[PptxUnitTranslation, ...],
) -> None:
    if len(expected_units) != len(translations):
        raise PptxContractError("unit_count", "translation count does not match request")
    for unit, translation in zip(expected_units, translations, strict=True):
        if translation.unit_id != unit.unit_id:
            raise PptxContractError("unit_order", "unit ID or order differs from request", unit.unit_id)
        expected_ids = tuple(item.segment_id for item in unit.text_items)
        actual_ids = tuple(item.segment_id for item in translation.segments)
        if expected_ids != actual_ids:
            raise PptxContractError("segment_order", "segment IDs or order differ from request", unit.unit_id)
        validate_unit_translation_structure(unit, translation)
        validate_unit_translation_boundaries(unit, translation)


def validate_unit_translation(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> None:
    validate_unit_translation_structure(unit, translation)
    validate_unit_translation_boundaries(unit, translation)
    validate_unit_translation_quality(unit, translation)


def validate_unit_translation_structure(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> None:
    if unit.source_text.strip() and not translation.target_text.strip():
        raise PptxContractError("blank_target", "nonblank source has blank target", unit.unit_id)
    reconstructed = reconstruct_target(unit, translation.segments)
    if _consistency_text(reconstructed) != _consistency_text(translation.target_text):
        raise PptxContractError("target_mismatch", "target text differs from translated stream", unit.unit_id)
    if reserved_marker_counts(unit.source_text) != reserved_marker_counts(translation.target_text):
        raise PptxContractError("reserved_marker_added", "reserved marker provenance differs", unit.unit_id)
    for source, target in zip(unit.text_items, translation.segments, strict=True):
        if reserved_marker_counts(source.source_text) != reserved_marker_counts(target.target_text):
            raise PptxContractError("reserved_marker_added", "segment marker provenance differs", unit.unit_id)


def validate_unit_translation_boundaries(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> None:
    if _has_high_confidence_missing_english_boundary(unit, translation):
        _record_quality_finding("missing_target_boundary_space")
        raise PptxContractError(
            "missing_target_boundary_space",
            "adjacent translated words are missing a required boundary space",
            unit.unit_id,
        )


def repair_missing_target_boundary_spaces(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> PptxUnitTranslation | None:
    """Insert only high-confidence spaces at text-run boundaries."""
    target_by_id = {
        segment.segment_id: segment.target_text
        for segment in translation.segments
    }
    previous: PptxTextStreamItem | None = None
    changed = False
    for item in unit.source_stream:
        if not isinstance(item, PptxTextStreamItem):
            previous = None
            continue
        if previous is not None:
            left_target = target_by_id[previous.segment_id]
            right_target = target_by_id[item.segment_id]
            if _is_suspicious_english_boundary(
                previous.source_text,
                item.source_text,
                left_target,
                right_target,
            ) and not _is_protected_target_boundary(
                unit,
                translation,
                previous.segment_id,
            ):
                target_by_id[item.segment_id] = f" {right_target}"
                changed = True
        previous = item
    if not changed:
        return None
    segments = tuple(
        PptxSegmentTranslation(
            segment.segment_id,
            target_by_id[segment.segment_id],
        )
        for segment in translation.segments
    )
    repaired = PptxUnitTranslation(
        translation.unit_id,
        reconstruct_target(unit, segments),
        segments,
    )
    try:
        validate_unit_translation_structure(unit, repaired)
        validate_unit_translation_boundaries(unit, repaired)
    except PptxContractError:
        return None
    return repaired


def validate_unit_translation_quality(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> None:
    for glossary_entry in unit.glossary:
        source_has_term = _literal_term_spans(
            unit.source_text,
            glossary_entry.source,
            ignore_case=True,
        )
        if glossary_entry.target:
            target_is_valid = bool(
                _literal_term_spans(
                    translation.target_text,
                    glossary_entry.target,
                    ignore_case=False,
                ),
            )
        else:
            target_is_valid = not _literal_term_spans(
                translation.target_text,
                glossary_entry.source,
                ignore_case=True,
            )
        if source_has_term and not target_is_valid:
            _record_quality_finding("glossary_mismatch")
            raise PptxContractError(
                "glossary_mismatch",
                "required glossary target is missing or not exact",
                unit.unit_id,
            )
    if _has_unjustified_adjacent_long_duplicate(unit, translation):
        _record_quality_finding("duplicate_target_span")
        raise PptxContractError(
            "duplicate_target_span",
            "target contains an adjacent repeated long span absent from source",
            unit.unit_id,
        )
    if not _is_english_to_chinese(unit):
        return
    retained_probable_names = tuple(
        term
        for term in _probable_proper_name_terms(unit.source_text)
        if _literal_term_spans(translation.target_text, term, ignore_case=False)
    )
    source_tokens = _classified_latin_tokens(
        unit.source_text,
        unit,
        allow_probable_names=False,
    )
    target_tokens = _classified_latin_tokens(
        translation.target_text,
        unit,
        allow_probable_names=True,
    )
    source_pairs = _unallowed_pairs(source_tokens)
    target_pairs = _unallowed_pairs(target_tokens)
    if source_pairs & target_pairs:
        _record_quality_finding("source_language_residue")
        raise PptxContractError(
            "source_language_residue",
            "target contains a high-confidence source-language phrase",
            unit.unit_id,
        )
    if retained_probable_names:
        reason_code = "possible_proper_name_retained_warning"
        _record_quality_finding(reason_code)
        logger.warning(
            "pptx_quality_warning unit_id=%s reason_code=%s candidate_count=%d",
            unit.unit_id,
            reason_code,
            len(retained_probable_names),
        )
    shared_tokens = _unallowed_token_values(source_tokens) & _unallowed_token_values(target_tokens)
    if shared_tokens:
        reason_code = "source_language_residue_warning"
        _record_quality_finding(reason_code)
        logger.warning(
            "pptx_quality_warning unit_id=%s reason_code=%s latin_token_count=%d",
            unit.unit_id,
            reason_code,
            len(shared_tokens),
        )


def _is_protected_target_boundary(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
    left_segment_id: str,
) -> bool:
    offset = 0
    boundary_offset: int | None = None
    target_by_id = {
        segment.segment_id: segment.target_text
        for segment in translation.segments
    }
    for item in unit.source_stream:
        if isinstance(item, PptxTextStreamItem):
            offset += len(target_by_id[item.segment_id])
            if item.segment_id == left_segment_id:
                boundary_offset = offset
        elif isinstance(item, PptxLineBreakStreamItem):
            offset += 1
        else:
            offset += len(item.source_text)
    if boundary_offset is None:
        return True
    target_text = translation.target_text
    for pattern in (_URL_RE, _EMAIL_RE, _DOI_RE):
        if any(
            match.start() < boundary_offset < match.end()
            for match in pattern.finditer(target_text)
        ):
            return True
    protected_terms = tuple((term, True) for term in unit.protected_terms)
    protected_terms += tuple(
        (entry.target, False)
        for entry in unit.glossary
        if entry.target
    )
    for term, ignore_case in protected_terms:
        if any(
            start < boundary_offset < end
            for start, end in _literal_term_spans(
                target_text,
                term,
                ignore_case=ignore_case,
            )
        ):
            return True
    return False


def _adjacent_long_duplicate_coverage(text: str) -> int:
    normalized = (
        unicodedata.normalize("NFKC", text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    tokens = tuple(_DUPLICATE_TOKEN_RE.finditer(normalized))
    if len(tokens) < 12:
        return _DUPLICATE_NONE
    values = tuple(match.group().casefold() for match in tokens)
    value_ids: dict[str, int] = {}
    token_ids = tuple(
        value_ids.setdefault(value, len(value_ids) + 1)
        for value in values
    )
    hash_mask = (1 << 64) - 1
    hash_base = 1_000_003
    prefix_hashes = [0]
    hash_powers = [1]
    for token_id in token_ids:
        prefix_hashes.append(((prefix_hashes[-1] * hash_base) + token_id) & hash_mask)
        hash_powers.append((hash_powers[-1] * hash_base) & hash_mask)

    def window_hash(start: int, end: int) -> int:
        return (
            prefix_hashes[end]
            - (prefix_hashes[start] * hash_powers[end - start])
        ) & hash_mask

    def is_long_duplicate(start: int, size: int) -> bool:
        middle = start + size
        end = middle + size
        if window_hash(start, middle) != window_hash(middle, end):
            return False
        if values[start:middle] != values[middle:end]:
            return False
        repeated = normalized[tokens[start].start() : tokens[middle - 1].end()]
        visible_characters = sum(not character.isspace() for character in repeated)
        latin_words = len(_LATIN_TOKEN_RE.findall(repeated))
        cjk_characters = len(_CJK_CHARACTER_RE.findall(repeated))
        return (latin_words >= 6 and visible_characters >= 32) or cjk_characters >= 16

    content_start = 0
    while content_start < len(normalized) and normalized[content_start].isspace():
        content_start += 1
    content_end = len(normalized)
    while content_end > content_start and normalized[content_end - 1].isspace():
        content_end -= 1

    if (
        len(tokens) % 2 == 0
        and tokens
        and tokens[0].start() == content_start
        and tokens[-1].end() == content_end
        and is_long_duplicate(0, len(tokens) // 2)
    ):
        return _DUPLICATE_WHOLE

    for start in range(len(tokens)):
        for size in range(6, (len(tokens) - start) // 2 + 1):
            if is_long_duplicate(start, size):
                return _DUPLICATE_PARTIAL
    return _DUPLICATE_NONE


def _has_unjustified_adjacent_long_duplicate(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> bool:
    target_coverage = _adjacent_long_duplicate_coverage(translation.target_text)
    if target_coverage == _DUPLICATE_NONE:
        return False
    if len(translation.segments) == 1:
        return not (
            target_coverage == _DUPLICATE_WHOLE
            and _adjacent_long_duplicate_coverage(unit.text_items[0].source_text)
            == _DUPLICATE_WHOLE
        )
    duplicated_segment_found = False
    for source, target in zip(unit.text_items, translation.segments, strict=True):
        segment_coverage = _adjacent_long_duplicate_coverage(target.target_text)
        if segment_coverage == _DUPLICATE_NONE:
            continue
        duplicated_segment_found = True
        if not (
            segment_coverage == _DUPLICATE_WHOLE
            and _adjacent_long_duplicate_coverage(source.source_text) == _DUPLICATE_WHOLE
        ):
            return True
    return not duplicated_segment_found


def _has_high_confidence_missing_english_boundary(
    unit: PptxRequestUnit,
    translation: PptxUnitTranslation,
) -> bool:
    if not _is_english_target(unit, translation.target_text):
        return False
    if _has_high_confidence_glued_target_token(unit, translation.target_text):
        return True
    target_by_id = {
        segment.segment_id: segment.target_text
        for segment in translation.segments
    }
    previous: PptxTextStreamItem | None = None
    glued_word_chain_length = 0
    glued_word_chain_has_cjk = False
    for item in unit.source_stream:
        if not isinstance(item, PptxTextStreamItem):
            previous = None
            glued_word_chain_length = 0
            glued_word_chain_has_cjk = False
            continue
        current_target = target_by_id[item.segment_id]
        if previous is not None and _is_suspicious_english_boundary(
            previous.source_text,
            item.source_text,
            target_by_id[previous.segment_id],
            current_target,
        ):
            return True
        if previous is None:
            glued_word_chain_length = (
                1 if _ASCII_WORD_RE.fullmatch(current_target) is not None else 0
            )
        else:
            previous_target = target_by_id[previous.segment_id]
            forms_glued_word_pair = bool(
                previous_target
                and current_target
                and not previous_target[-1].isspace()
                and not current_target[0].isspace()
                and _ASCII_WORD_RE.fullmatch(previous_target)
                and _ASCII_WORD_RE.fullmatch(current_target)
            )
            if forms_glued_word_pair:
                glued_word_chain_length = max(1, glued_word_chain_length) + 1
                glued_word_chain_has_cjk = glued_word_chain_has_cjk or bool(
                    _CJK_CHARACTER_RE.search(previous.source_text)
                    or _CJK_CHARACTER_RE.search(item.source_text)
                )
                if glued_word_chain_length >= 3 and glued_word_chain_has_cjk:
                    return True
            else:
                glued_word_chain_length = (
                    1 if _ASCII_WORD_RE.fullmatch(current_target) is not None else 0
                )
                glued_word_chain_has_cjk = False
        previous = item
    return False


def _has_high_confidence_glued_target_token(
    unit: PptxRequestUnit,
    target_text: str,
) -> bool:
    if _has_glued_preserved_source_prefix(unit, target_text):
        return True
    protected_targets = set(unit.protected_terms)
    protected_targets.update(entry.target for entry in unit.glossary if entry.target)
    for match in _ASCII_WORD_RE.finditer(target_text):
        token = match.group()
        if token in unit.source_text or token in protected_targets:
            continue
        lower_to_upper = sum(
            left.islower() and right.isupper()
            for left, right in zip(token, token[1:])
        )
        if lower_to_upper >= 2 or _LOWER_ACRONYM_LOWER_RE.search(token):
            return True
    return False


def _has_glued_preserved_source_prefix(
    unit: PptxRequestUnit,
    target_text: str,
) -> bool:
    for index, item in enumerate(unit.source_stream):
        if not isinstance(item, PptxTextStreamItem):
            continue
        source_token = item.source_text.strip()
        if not (
            _SIMPLE_TITLE_WORD_RE.fullmatch(source_token)
            or _ALL_CAPS_ACRONYM_RE.fullmatch(source_token)
        ):
            continue
        neighbors = unit.source_stream[max(0, index - 1) : index + 2]
        if not any(
            isinstance(neighbor, PptxTextStreamItem)
            and neighbor is not item
            and _CJK_CHARACTER_RE.search(neighbor.source_text)
            for neighbor in neighbors
        ):
            continue

        occurrence = target_text.find(source_token)
        while occurrence >= 0:
            end = occurrence + len(source_token)
            starts_at_word_boundary = (
                occurrence == 0 or not target_text[occurrence - 1].isalnum()
            )
            suffix = _ASCII_WORD_RE.match(target_text, end)
            if (
                starts_at_word_boundary
                and suffix is not None
                and suffix.group()[0].islower()
                and suffix.group().casefold() not in _SAFE_PRESERVED_WORD_SUFFIXES
            ):
                return True
            occurrence = target_text.find(source_token, occurrence + len(source_token))
    return False


def _is_suspicious_english_boundary(
    left_source: str,
    right_source: str,
    left_target: str,
    right_target: str,
) -> bool:
    if not (_CJK_CHARACTER_RE.search(left_source) or _CJK_CHARACTER_RE.search(right_source)):
        return False
    if not left_target or not right_target:
        return False
    if left_target[-1].isspace() or right_target[0].isspace():
        return False

    left_character = left_target[-1]
    right_character = right_target[0]
    if not right_character.isascii() or not right_character.isalpha():
        return False
    if right_target.casefold() in _SAFE_JOINED_ENGLISH_SUFFIXES:
        return False
    if left_character in ",;:!?%":
        return True
    if not left_character.isascii() or not left_character.isalnum():
        return False
    if (
        _INTERNAL_WORD_SPACE_RE.search(left_target)
        or _INTERNAL_WORD_SPACE_RE.search(right_target)
    ):
        return True

    left_word = _ASCII_WORD_RE.fullmatch(left_target)
    right_word = _ASCII_WORD_RE.fullmatch(right_target)
    if left_word is None or right_word is None:
        return False
    left_is_acronym = _ALL_CAPS_ACRONYM_RE.fullmatch(left_target) is not None
    right_is_acronym = _ALL_CAPS_ACRONYM_RE.fullmatch(right_target) is not None
    if left_is_acronym and not right_is_acronym:
        return True
    if right_is_acronym:
        return left_target.islower() or any(
            character.isupper()
            for character in left_target[1:]
        )
    return False


def _classified_latin_tokens(
    text: str,
    unit: PptxRequestUnit,
    *,
    allow_probable_names: bool,
) -> tuple[tuple[str, bool], ...]:
    allowed_spans = _allowed_latin_spans(
        text,
        unit,
        allow_probable_names=allow_probable_names,
    )
    return tuple(
        (
            match.group().casefold(),
            _overlaps_allowed_span(match.span(), allowed_spans)
            or _is_allowlisted_latin_token(match.group()),
        )
        for match in _LATIN_TOKEN_RE.finditer(text)
    )


def _allowed_latin_spans(
    text: str,
    unit: PptxRequestUnit,
    *,
    allow_probable_names: bool,
) -> tuple[tuple[int, int], ...]:
    spans = list(_citation_spans(text))
    spans.extend(
        match.span()
        for pattern in (
            _URL_RE,
            _EMAIL_RE,
            _DOI_RE,
            _YEAR_RE,
            _SHORT_ET_AL_CITATION_RE,
            _HONORIFIC_PERSON_RE,
            _ORGANIZATION_NAME_RE,
        )
        for match in pattern.finditer(text)
    )
    if allow_probable_names:
        for term in _probable_proper_name_terms(unit.source_text):
            spans.extend(_literal_term_spans(text, term, ignore_case=False))
    protected_terms = list(unit.protected_terms)
    protected_terms.extend(
        item.source_text
        for item in unit.source_stream
        if isinstance(item, PptxProtectedFieldStreamItem)
    )
    for term in protected_terms:
        spans.extend(_literal_term_spans(text, term, ignore_case=True))
    for glossary_entry in unit.glossary:
        spans.extend(_literal_term_spans(text, glossary_entry.target, ignore_case=False))
    return tuple(spans)


def _probable_proper_name_terms(source_text: str) -> tuple[str, ...]:
    trademarked_names = tuple(_TRADEMARKED_NAME_RE.finditer(source_text))
    explicit_name_spans = tuple(
        match.span()
        for pattern in (_HONORIFIC_PERSON_RE, _ORGANIZATION_NAME_RE)
        for match in pattern.finditer(source_text)
    )
    claimed_name_spans = explicit_name_spans + tuple(match.span() for match in trademarked_names)
    terms = [match.group() for match in trademarked_names]
    for match in _TITLE_CASE_SEQUENCE_RE.finditer(source_text):
        tokens = tuple(token.group().casefold() for token in _LATIN_TOKEN_RE.finditer(match.group()))
        if all(token in _DESCRIPTIVE_TITLE_WORDS for token in tokens):
            continue
        if len(tokens) == 2 and _PERSON_NAME_CONTEXT_RE.search(source_text[: match.start()]) is None:
            continue
        if _overlaps_allowed_span(match.span(), claimed_name_spans):
            continue
        terms.append(match.group())
    return tuple(terms)


def _citation_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for line in re.finditer(r"[^\r\n]+", text):
        value = line.group()
        has_author_list = _CITATION_AUTHOR_LIST_RE.search(value) is not None
        has_year = _YEAR_RE.search(value) is not None
        has_locator = _CITATION_LOCATOR_RE.search(value) is not None
        has_external_identifier = _DOI_RE.search(value) is not None or _URL_RE.search(value) is not None
        if has_author_list and has_year and (has_locator or has_external_identifier):
            spans.append(line.span())
    return tuple(spans)


def _literal_term_spans(text: str, term: str, *, ignore_case: bool) -> tuple[tuple[int, int], ...]:
    if not term:
        return ()
    left_boundary = r"(?<![A-Za-z0-9_])" if _is_ascii_word_character(term[0]) else ""
    right_boundary = r"(?![A-Za-z0-9_])" if _is_ascii_word_character(term[-1]) else ""
    pattern = re.compile(
        f"{left_boundary}{re.escape(term)}{right_boundary}",
        re.IGNORECASE if ignore_case else 0,
    )
    return tuple(match.span() for match in pattern.finditer(text))


def _is_ascii_word_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character == "_")


def _overlaps_allowed_span(
    token_span: tuple[int, int],
    allowed_spans: tuple[tuple[int, int], ...],
) -> bool:
    start, end = token_span
    return any(start < allowed_end and end > allowed_start for allowed_start, allowed_end in allowed_spans)


def _is_allowlisted_latin_token(token: str) -> bool:
    return (
        token.casefold() in _MEASUREMENT_UNITS
        or _ALL_CAPS_ACRONYM_RE.fullmatch(token) is not None
        or _CHEMICAL_FORMULA_RE.fullmatch(token) is not None
    )


def _unallowed_pairs(tokens: tuple[tuple[str, bool], ...]) -> set[tuple[str, str]]:
    return {
        (first, second)
        for (first, first_allowed), (second, second_allowed) in zip(tokens, tokens[1:])
        if not first_allowed and not second_allowed
    }


def _unallowed_token_values(tokens: tuple[tuple[str, bool], ...]) -> set[str]:
    return {token for token, allowed in tokens if not allowed}


def _record_quality_finding(code: str) -> None:
    metrics = current_metrics()
    if metrics is not None:
        metrics.record_quality_finding(code)


def _is_english_to_chinese(unit: PptxRequestUnit) -> bool:
    source = unit.source_language.strip().casefold()
    target = unit.target_language.strip().casefold()
    return (source.startswith("en") or "english" in source) and (
        target.startswith("zh") or "chinese" in target
    )


def _is_english_target(unit: PptxRequestUnit, target_text: str) -> bool:
    target = unit.target_language.strip().casefold()
    if target:
        return target.startswith("en") or "english" in target
    return bool(
        _CJK_CHARACTER_RE.search(unit.source_text)
        and re.search(r"[A-Za-z]", target_text)
        and not _CJK_CHARACTER_RE.search(target_text)
    )


def reserved_marker_counts(text: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", text)
    counts: Counter[str] = Counter()
    for match in _RESERVED_MARKER_RE.finditer(normalized):
        marker = "".join(match.group("marker").split()).casefold()
        counts[marker] += 1
    return counts


def reconstruct_target(
    unit: PptxRequestUnit,
    segments: tuple[PptxSegmentTranslation, ...],
) -> str:
    by_id = {segment.segment_id: segment.target_text for segment in segments}
    parts: list[str] = []
    for item in unit.source_stream:
        match item:
            case PptxTextStreamItem():
                parts.append(by_id[item.segment_id])
            case PptxLineBreakStreamItem():
                parts.append("\n")
            case PptxProtectedFieldStreamItem():
                parts.append(item.source_text)
            case _ as unreachable:
                assert_never(unreachable)
    return "".join(parts)


def _consistency_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
