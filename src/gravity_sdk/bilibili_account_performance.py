"""Bounded Bilibili account and product performance read."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import runtime
from .composite_batch import validate_composite_bounds
from .composite_catalog import identity_contains, stable_operation
from .errors import InputValidationError
from .bilibili_account_performance_result import (
    SCHEMA_VERSION,
    product_item_count,
    result_from_native,
)
from .actionable_error_values import actual_value


OPERATION_ID = stable_operation(
    "promotion",
    "account",
    action="list",
    predicate=identity_contains("bilibili"),
).operation_id

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bilibili_account_performance(
    client: Any,
    start: str,
    end: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read complete account-level Bilibili spend and delivery metrics."""

    window, workers, pages, items = validate_bilibili_account_request(
        start,
        end,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    inputs = {
        "date_list": list(window),
        "filtering": {},
        "filters": [],
        "order_by": [],
        "page": 1,
        "page_size": min(100, items),
    }
    try:
        value = runtime.call_read(
            client,
            OPERATION_ID,
            inputs,
            read_all=True,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
            forward_var_kwargs=True,
        )
    except Exception as exc:
        value = exc
    result = result_from_native(
        value,
        operation_id=OPERATION_ID,
        window=window,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
    )
    if product_item_count(result) > items:
        return result_from_native(
            RuntimeError("Bilibili account performance exceeded its item budget"),
            operation_id=OPERATION_ID,
            window=window,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
        )
    return result


def validate_bilibili_account_request(
    start: Any,
    end: Any,
    *,
    max_workers: Any = 6,
    max_pages: Any = 1_000,
    max_items: Any = 100_000,
) -> tuple[tuple[str, str], int, int, int]:
    """Close the request without constructing a client or guessing values."""

    window = normalize_bilibili_account_window(start, end)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=1
    )
    if type(max_workers) is not int or not 1 <= max_workers <= 24:
        raise InputValidationError(
            f"actual value: {actual_value(max_workers)}; " + ("Bilibili account performance max_workers must be between 1 and 24"),
            field="max_workers",
        )
    return window, max_workers, pages, items


def normalize_bilibili_account_window(start: Any, end: Any) -> tuple[str, str]:
    """Return one canonical inclusive request date range."""

    if not all(isinstance(value, str) and _ISO_DATE.fullmatch(value) for value in (start, end)):
        raise _date_error("dates must use YYYY-MM-DD", field="start/end")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise _date_error("dates must use YYYY-MM-DD", field="start/end") from None
    if first > last:
        raise _date_error("start must not follow end", field="start/end")
    if (first.isoformat(), last.isoformat()) != (start, end):
        raise _date_error("dates must use YYYY-MM-DD", field="start/end")
    return start, end


def _date_error(message: str, *, field: str) -> InputValidationError:
    return InputValidationError(
        f"Bilibili account performance {message}",
        field=field,
        next_action=(
            "Retry with explicit inclusive start and end dates; no App or metric "
            "selection belongs to this account-level product."
        ),
    )


__all__ = [
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "bilibili_account_performance",
    "normalize_bilibili_account_window",
    "validate_bilibili_account_request",
]
