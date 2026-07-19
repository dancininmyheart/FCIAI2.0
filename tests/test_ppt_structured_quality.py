from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.translation.providers import ProviderRegistry
from app.translation.structured import parse_ppt_source, translate_ppt_page
from app.translation.types import ProviderName, ProviderRequest, ProviderResult


@dataclass(slots=True)
class SequencedProvider:
    responses: list[str]
    requests: list[ProviderRequest] = field(default_factory=list)

    @property
    def name(self) -> ProviderName:
        return "qwen"

    def translate(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult(self.responses[len(self.requests) - 1], "qwen", "qwen")


def _request() -> ProviderRequest:
    return ProviderRequest.create(
        "第1页内容：\n\n【文本框1-段落1】\nMilk [block]\n\n【文本框2-段落1】\nGrowth",
        "English",
        "Chinese",
    )


def test_parse_ppt_source_builds_stable_units_in_run_order() -> None:
    units = parse_ppt_source(_request())

    assert [unit.stable_id for unit in units] == ["ppt:b1:p1", "ppt:b2:p1"]
    assert [unit.source_text for unit in units] == ["Milk [block]", "Growth"]
    assert units[0].placeholders == ("[block]",)


def test_observe_returns_provider_bytes_unchanged() -> None:
    raw = '[ {"box_index":1,"paragraph_index":1,"source_language":"Milk","target_language":"母乳"} ]'
    provider = SequencedProvider([raw])

    result = translate_ppt_page(ProviderRegistry((provider,)), "qwen", _request(), "observe")

    assert result.text == raw
    assert result.provider_calls == 1
    assert result.quality_findings > 0


def test_enforce_retries_only_invalid_structured_unit() -> None:
    first = json.dumps(
        [
            {"box_index": 1, "paragraph_index": 1, "source_language": "Milk", "target_language": "母乳 [block]"},
            {"box_index": 2, "paragraph_index": 1, "source_language": "Growth", "target_language": ""},
        ],
        ensure_ascii=False,
    )
    repaired = json.dumps(
        [{"box_index": 2, "paragraph_index": 1, "source_language": "Growth", "target_language": "生长"}],
        ensure_ascii=False,
    )
    provider = SequencedProvider([first, repaired])

    result = translate_ppt_page(ProviderRegistry((provider,)), "qwen", _request(), "enforce")
    payload = json.loads(result.text)

    assert result.provider_calls == 2
    assert "文本框2-段落1" in provider.requests[1].text
    assert "文本框1-段落1" not in provider.requests[1].text
    assert [item["target_language"] for item in payload] == ["母乳 [block]", "生长"]
