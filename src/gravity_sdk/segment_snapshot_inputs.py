"""Local input normalization shared by Segment snapshot surfaces."""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from .composite_batch import validate_composite_bounds
from .errors import InputValidationError
from .actionable_error_values import actual_value


DEFAULT_CONCURRENCY = 3
MAX_CONCURRENCY = 24
MIN_SNAPSHOT_ITEMS = 4


def validate_segment_snapshot_request(
    app_id: str | int,
    ref: str | int,
    *,
    date: str,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, str, int, int, int]:
    """Normalize all caller-controlled values without constructing a client."""

    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=MIN_SNAPSHOT_ITEMS
    )
    return (
        positive_id(app_id, "app_id"),
        reference(ref),
        canonical_date(date),
        workers(max_workers),
        pages,
        items,
    )


def positive_id(value: Any, field: str) -> str:
    rendered = (
        str(value).strip()
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else ""
    )
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"segment snapshot {field} must be a positive integer"), field=field
        )
    return str(int(rendered))


def reference(value: Any) -> str:
    selected = bounded_text(value) if not isinstance(value, bool) else None
    if selected is None:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; " + ("segment snapshot ref must be a bounded id or exact name"), field="ref"
        )
    return selected


def bounded_text(value: Any) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    rendered = str(value).strip()
    return rendered if 0 < len(rendered) <= 256 else None


def canonical_date(value: Any) -> str:
    if not isinstance(value, str):
        raise _date_error()
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError:
        raise _date_error() from None
    if parsed.isoformat() != value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("segment snapshot date must use canonical YYYY-MM-DD"), field="date"
        )
    return value


def workers(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CONCURRENCY
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + (f"segment snapshot max_workers must be between 1 and {MAX_CONCURRENCY}"),
            field="max_workers",
        )
    return value


def matches_app(value: Any, app_id: str) -> bool:
    try:
        return positive_id(value, "app_id") == app_id
    except InputValidationError:
        return False


def _date_error() -> InputValidationError:
    return InputValidationError(
        "segment snapshot date must be an ISO natural day", field="date"
    )


__all__ = [
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "MIN_SNAPSHOT_ITEMS",
    "bounded_text",
    "matches_app",
    "positive_id",
    "validate_segment_snapshot_request",
]
