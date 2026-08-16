"""Narrow dispatcher for domain-owned unavailable journey recognizers."""

from __future__ import annotations

from typing import Any


_REGISTERED_GAP_QUERIES = (
    "real time event catalog",
    "current table schema",
    "analysis export results",
    "media reports",
    "monetization aggregate",
    "readable app projects",
    "onelink public store binding",
    "non bytedance campaign group creative performance",
    "platform specific creative fields",
    "registered sql analysis product",
)


def unavailable_journey_gap(query: str) -> dict[str, Any] | None:
    from .agent_sql_product_gap import registered_sql_product_gap
    from .agent_unavailable_analysis import unavailable_analysis_gap
    from .agent_unavailable_app import unavailable_app_gap
    from .agent_unavailable_promotion import unavailable_promotion_gap
    from .agent_unavailable_report import unavailable_report_gap

    for recognize in (
        unavailable_analysis_gap,
        unavailable_app_gap,
        unavailable_report_gap,
        unavailable_promotion_gap,
        registered_sql_product_gap,
    ):
        gap = recognize(query)
        if gap is not None:
            return gap
    return None


def registered_unavailable_gaps() -> tuple[dict[str, Any], ...]:
    """Materialize each existing gap once for offline lexical indexing."""

    gaps = tuple(
        gap
        for query in _REGISTERED_GAP_QUERIES
        if (gap := unavailable_journey_gap(query)) is not None
    )
    if len(gaps) != len(_REGISTERED_GAP_QUERIES):
        raise RuntimeError("registered unavailable gap inventory is incomplete")
    if len({str(gap["code"]) for gap in gaps}) != len(gaps):
        raise RuntimeError("registered unavailable gap codes must be unique")
    return gaps


__all__ = ["registered_unavailable_gaps", "unavailable_journey_gap"]
