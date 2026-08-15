"""Narrow dispatcher for domain-owned unavailable journey recognizers."""

from __future__ import annotations

from typing import Any


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


__all__ = ["unavailable_journey_gap"]
