"""Fail-closed natural-language discovery for raw Monetization detail.

Canonical selectors remain available as explicit expert-only entry points.
"""

from __future__ import annotations

import re


MONETIZATION_DETAIL_RAW_SELECTOR = ".".join(
    ("analysis", "monetization_detail", "list")
)
MONETIZATION_EXPORT_RAW_SELECTOR = ".".join(
    ("export", "analysis", "monetization_detail", "start")
)
MONETIZATION_SAFE_QUERY = "monetization_detail"
MONETIZATION_GAP_REASON = (
    "no identifier-free Monetization Agent product is registered; use an "
    "exact governed selector only in expert workflows"
)

_ASCII_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_COMPACT_SEPARATORS = re.compile(r"[\s_-]+")
_NEAR_RAW_SELECTOR = re.compile(
    r"(?<![a-z0-9_])(?:analysis\.)?monetization_detail"
    r"(?:\.list)?(?![a-z0-9_])",
    re.IGNORECASE,
)
_ENGLISH_STRONG_SHAPES = frozenset({"detail", "details", "directory"})
_ENGLISH_ADJACENT_SHAPES = frozenset({"list", "rows"})
_CHINESE_SHAPES = (
    "变现明细",
    "变现目录",
    "变现列表",
    "广告变现明细",
)
_EXACT_EXPERT_SELECTORS = frozenset(
    {
        MONETIZATION_DETAIL_RAW_SELECTOR,
        MONETIZATION_EXPORT_RAW_SELECTOR,
    }
)


def monetization_guard_blocks_operation_fallback(query: str) -> bool:
    """Claim only explicit detail-shaped requests and near-raw selectors."""

    selected = _normalize(query)
    if _is_exact_expert_selector(selected):
        return False
    if _contains_near_raw_selector(selected):
        return True
    words = tuple(_ASCII_WORD.findall(selected))
    compact = _COMPACT_SEPARATORS.sub("", selected)
    return _english_detail_shape(words) or _chinese_detail_shape(compact)


def monetization_guard_safe_query(query: str) -> str:
    """Replace a claimed query before suffix values reach Agent output."""

    return (
        MONETIZATION_SAFE_QUERY
        if monetization_guard_blocks_operation_fallback(query)
        else query
    )


def _normalize(query: str) -> str:
    return " ".join(str(query or "").strip().casefold().split())


def _is_exact_expert_selector(selected: str) -> bool:
    return selected in _EXACT_EXPERT_SELECTORS


def _contains_near_raw_selector(selected: str) -> bool:
    return bool(_NEAR_RAW_SELECTOR.search(selected))


def _english_detail_shape(words: tuple[str, ...]) -> bool:
    if "monetization" not in words:
        return False
    if _ENGLISH_STRONG_SHAPES.intersection(words):
        return True
    return any(
        left == "monetization" and right in _ENGLISH_ADJACENT_SHAPES
        for left, right in zip(words, words[1:])
    )


def _chinese_detail_shape(compact: str) -> bool:
    return any(shape in compact for shape in _CHINESE_SHAPES)


__all__ = [
    "MONETIZATION_DETAIL_RAW_SELECTOR",
    "MONETIZATION_EXPORT_RAW_SELECTOR",
    "MONETIZATION_GAP_REASON",
    "MONETIZATION_SAFE_QUERY",
    "monetization_guard_blocks_operation_fallback",
    "monetization_guard_safe_query",
]
