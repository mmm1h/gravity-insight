"""Pure lexical matching shared by Agent discovery products."""

from __future__ import annotations

import re
from typing import Mapping


_MATCH_ALIASES: Mapping[str, tuple[str, ...]] = {
    "app": ("应用", "application"),
    "campaign": ("活动", "推广", "广告"),
    "cohort": ("分群", "segment"),
    "event": ("事件",),
    "funnel": ("漏斗",),
    "material": ("素材", "creative"),
    "metadata": ("元数据",),
    "report": ("报表", "metric", "指标"),
    "retention": ("留存",),
    "segment": ("分群", "cohort"),
    "user": ("用户", "account"),
    "事件": ("event",),
    "分群": ("segment", "cohort"),
    "应用": ("app", "application"),
    "报表": ("report", "metric"),
    "推广": ("promotion", "campaign"),
    "活动": ("campaign",),
    "用户": ("user", "account"),
    "留存": ("retention",),
    "素材": ("material", "creative"),
}


def _query_concepts(query: str) -> list[tuple[str, frozenset[str]]]:
    fragments = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", query.casefold())
    labels: list[str] = []
    for fragment in fragments:
        if fragment.isascii():
            if len(fragment) >= 3:
                labels.append(fragment)
            continue
        aliases = [
            key for key in _MATCH_ALIASES if not key.isascii() and key in fragment
        ]
        labels.extend(aliases or [fragment])
    return [
        (label, frozenset((label, *_MATCH_ALIASES.get(label, ()))))
        for label in dict.fromkeys(labels)
    ]


def query_match(
    query: str, *values: object, score: int = 0
) -> dict[str, object]:
    """Measure whether every meaningful query concept is represented."""

    concepts = _query_concepts(query)
    haystack = " ".join(str(value).casefold() for value in values if value is not None)
    matched = [
        label
        for label, alternatives in concepts
        if any(term in haystack for term in alternatives)
    ]
    coverage = len(matched) / len(concepts) if concepts else 0.0
    return {
        "confidence": "strong" if coverage >= 0.8 else "partial" if coverage else "none",
        "coverage": round(coverage, 3),
        "matched_terms": matched,
        "missing_terms": [label for label, _ in concepts if label not in matched],
        "score": int(score),
    }


__all__ = ["query_match"]
