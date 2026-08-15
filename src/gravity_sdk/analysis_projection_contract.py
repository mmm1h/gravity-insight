"""Shared value-shape rules for dynamic Analysis response projection."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .models import OperationSpec


ANALYSIS_SAFE_RESPONSE_SCALARS = frozenset(
    {
        "day",
        "hour",
        "minute",
        "month",
        "total",
        "week",
        "PresetAllCount",
        "PresetUserCount",
        # Retention v2 reports its aggregation mode alongside the buckets.
        "SUM",
        "WEIGHTED_AVG",
        "DAY",
        "WEEK",
        "MONTH",
    }
)
# Time-bucket keys: day with optional timestamp, plus the month (``2026-08``)
# and ISO week (``2026-W32``) buckets Retention v2 reports.
ANALYSIS_DATE_RESPONSE_KEY_RE = re.compile(
    r"^\d{4}-(?:W\d{2}"
    r"|\d{2}(?:-\d{2}(?:[T ]\d{2}(?::\d{2}){0,2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)?)$"
)
ANALYSIS_INDEX_RESPONSE_KEY_RE = re.compile(r"^(?:-?\d+(?:\.\d+)?%?|[xX]\d{1,3})$")


def funnel_mode_shape_changed(
    operation: OperationSpec,
    data: Mapping[str, Any],
    values: Mapping[str, Any],
) -> bool:
    """Require the aggregate root selected by the requested funnel mode."""

    if operation.domain != "analysis" or operation.resource != "funnel":
        return False
    required_projection = (
        "aggregate_by_date" if values.get("to_calc_each_day") is True else "aggregate_date"
    )
    return not isinstance(data.get(required_projection), Mapping)


__all__ = [
    "ANALYSIS_DATE_RESPONSE_KEY_RE",
    "ANALYSIS_INDEX_RESPONSE_KEY_RE",
    "ANALYSIS_SAFE_RESPONSE_SCALARS",
    "funnel_mode_shape_changed",
]
