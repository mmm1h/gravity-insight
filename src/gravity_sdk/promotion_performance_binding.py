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

    if _canonical_app(app_id) != app_id:
        return False
    try:
        start, end = map(date.fromisoformat, window)
    except (TypeError, ValueError):
        return False
    if start > end or (start.isoformat(), end.isoformat()) != window:
        return False
    for row in rows:
        if "app_id" in row and _canonical_app(row["app_id"]) != app_id:
            return False
        for field in ("date", "day", "stat_date"):
            if field in row and not _date_in_window(row[field], start, end):
                return False
    return True


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


__all__ = ["rows_match_performance_request"]
