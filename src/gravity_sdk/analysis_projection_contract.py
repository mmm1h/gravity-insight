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
# Funnel aggregate_date.group keys are observed OS / empty-bucket labels, not
# request field names. Keep this closed: short identifier-like tokens only,
# and only under a ``group`` container so uid / group_cols stay fail-closed.
ANALYSIS_GROUP_LABEL_KEY_RE = re.compile(
    r"^(?:null|(?!uid$|group_cols$)[A-Za-z][A-Za-z0-9_]{0,31})$"
)
# Event-query innermost rows name the group with the property display name
# (``用户.设备类型`` for ``$os``), not the request field. Only that row
# container is opened; ``union_groups`` / ``y`` stay omitted as chart helpers,
# and uid / group_cols stay fail-closed because they are not 用户./事件. keys.
ANALYSIS_GROUP_DISPLAY_KEY_RE = re.compile(r"^(?:用户|事件)\.[^\x00-\x1f]{1,64}$")
# Scatter cells compose the group as ``{type}{field}`` (``user$os``). Only
# the innermost aggregate_date cell is opened; proc_zone / stat_total /
# aggregate_date_group stay omitted until they are themselves group labels.
ANALYSIS_COMPOSED_GROUP_KEY_RE = re.compile(
    r"^(?:user|event|default_event|default_user|user_property|user_re_attribute)"
    r"\$[A-Za-z][A-Za-z0-9_]{0,31}$"
)
_EVENT_QUERY_GROUP_ROW_PATH = ("list", "[]", "[]", "list", "[]")
_SCATTER_GROUP_ROW_PATH = ("aggregate_date", "[]", "[]")


def allowed_analysis_response_key(name: str, response_keys: set[str], path: tuple[str, ...] = ()) -> bool:
    if name in response_keys or ANALYSIS_DATE_RESPONSE_KEY_RE.fullmatch(name) or ANALYSIS_INDEX_RESPONSE_KEY_RE.fullmatch(name):
        return True
    return _allowed_dynamic_group_label_key(name, path)


def _allowed_dynamic_group_label_key(name: str, path: tuple[str, ...]) -> bool:
    if len(path) >= 2 and path[-2:] == ("aggregate_date", "group"):
        return bool(ANALYSIS_GROUP_LABEL_KEY_RE.fullmatch(name))
    if path == _EVENT_QUERY_GROUP_ROW_PATH:
        return bool(ANALYSIS_GROUP_DISPLAY_KEY_RE.fullmatch(name))
    return path == _SCATTER_GROUP_ROW_PATH and bool(
        ANALYSIS_COMPOSED_GROUP_KEY_RE.fullmatch(name)
    )


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
    "ANALYSIS_COMPOSED_GROUP_KEY_RE",
    "ANALYSIS_DATE_RESPONSE_KEY_RE",
    "ANALYSIS_GROUP_DISPLAY_KEY_RE",
    "ANALYSIS_GROUP_LABEL_KEY_RE",
    "ANALYSIS_INDEX_RESPONSE_KEY_RE",
    "ANALYSIS_SAFE_RESPONSE_SCALARS",
    "allowed_analysis_response_key",
    "funnel_mode_shape_changed",
]
