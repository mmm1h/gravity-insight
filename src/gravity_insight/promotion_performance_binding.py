"""Request-bound native row checks for Promotion Performance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


def rows_match_performance_request(
    rows: Sequence[Mapping[str, Any]],
    app_id: str,
    window: tuple[str, str],
) -> bool:
    """Verify every optional App/date identity against the canonical request."""

    return performance_request_mismatch_path(rows, app_id, window) is None


def performance_request_mismatch_path(
    rows: Sequence[Mapping[str, Any]],
    app_id: str,
    window: tuple[str, str],
) -> str | None:
    """Return only the structural path of the first request-binding mismatch."""

    if _canonical_app(app_id) != app_id:
        return "$.request.app_id"
    try:
        start, end = map(date.fromisoformat, window)
    except (TypeError, ValueError):
        return "$.request.date_range"
    if start > end or (start.isoformat(), end.isoformat()) != window:
        return "$.request.date_range"
    for index, row in enumerate(rows):
        if "app_id" in row and _canonical_app(row["app_id"]) != app_id:
            return f"$.data.data.list[{index}].app_id"
        for field in ("date", "day", "stat_date"):
            if field in row and not _date_in_window(row[field], start, end):
                return f"$.data.data.list[{index}].{field}"
    return None


def _canonical_app(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if isinstance(value, int) and (value <= 0 or value.bit_length() > 426):
        return None
    rendered = str(value)
    if (
        not rendered
        or len(rendered) > 128
        or not rendered.isascii()
        or not rendered.isdecimal()
        or int(rendered) <= 0
    ):
        return None
    return str(int(rendered))


def _date_in_window(value: Any, start: date, end: date) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        selected = date.fromisoformat(value)
    except ValueError:
        return False
    return selected.isoformat() == value and start <= selected <= end


__all__ = [
    "performance_request_mismatch_path",
    "rows_match_performance_request",
]
