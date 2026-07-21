from __future__ import annotations

from typing import Final


DEFAULT_PRESENTATION_DOMAIN: Final = "通用"

# Domain classification is deliberately a closed vocabulary.  Besides keeping
# terminology guidance consistent between batches, this prevents model output
# from becoming a second-stage instruction when it is added to a system prompt.
PRESENTATION_DOMAINS: Final = (
    "婴幼儿营养与配方奶粉",
    "营养与食品科学",
    "质量与食品安全",
    "医学与临床研究",
    "医药与生命科学",
    "乳业与食品生产",
    "化学与材料科学",
    "工程与制造",
    "信息技术与人工智能",
    "金融与投资",
    "财务与会计",
    "商业管理与市场营销",
    "消费者与市场研究",
    "人力资源与组织发展",
    "供应链与物流",
    "法律与合规",
    "教育与培训",
    "环境与可持续发展",
    "艺术与设计",
    DEFAULT_PRESENTATION_DOMAIN,
)
PRESENTATION_DOMAIN_SET: Final = frozenset(PRESENTATION_DOMAINS)


def normalize_presentation_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip(" \"'`")
    return normalized if normalized in PRESENTATION_DOMAIN_SET else None


def presentation_domain_or_default(value: object) -> str:
    return normalize_presentation_domain(value) or DEFAULT_PRESENTATION_DOMAIN


__all__ = [
    "DEFAULT_PRESENTATION_DOMAIN",
    "PRESENTATION_DOMAINS",
    "PRESENTATION_DOMAIN_SET",
    "normalize_presentation_domain",
    "presentation_domain_or_default",
]
