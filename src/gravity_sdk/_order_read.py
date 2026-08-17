"""Private invariants shared by governed order read products."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Mapping
from datetime import date as date_type, datetime
from typing import Any

from .composite_batch import validate_composite_bounds
from .errors import InputValidationError
from .actionable_error_values import actual_value


SAFE_ROW_FIELDS = ("CreateTime", "Amount", "BackAmount", "Status")
TRACE_PARENT_FIELDS = (
    "TraceID",
    "PayEventTime",
    "ClientID",
    "$split_trace_id_list",
)
STATIC_ORDER_FIELD_PROFILES = frozenset(
    {frozenset(SAFE_ROW_FIELDS), frozenset(TRACE_PARENT_FIELDS)}
)
MAX_WORKERS = 24

_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_PAGE_KEYS = frozenset(
    {
        "number",
        "size",
        "item_count",
        "total_pages",
        "total_items",
        "has_more",
        "pages_fetched",
        "fetch_strategy",
        "max_workers",
    }
)
_FETCH_STRATEGIES = frozenset(
    {
        "single_page",
        "serial_unknown_total",
        "serial_known_total",
        "parallel_known_total",
    }
)


def validate_order_read_request(
    app_id: Any,
    date: Any,
    *,
    max_workers: Any,
    max_pages: Any,
    max_items: Any,
    product: str,
) -> tuple[str, str, int, int, int]:
    """Normalize shared caller inputs before any client can be constructed."""

    app = canonical_app(app_id, label=product)
    day = canonical_date(date, label=product)
    if type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS:
        raise InputValidationError(
            f"actual value: {actual_value(max_workers)}; " + (f"{product} max_workers must be between 1 and {MAX_WORKERS}"),
            field="max_workers",
        )
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=1
    )
    return app, day, max_workers, pages, items


def canonical_app(value: Any, *, label: str = "order read") -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _input(label, "app_id", "must be a positive integer")
    if type(value) is int and value.bit_length() > 512:
        raise _input(label, "app_id", "must be a positive integer")
    rendered = str(value).strip()
    if (
        not rendered
        or len(rendered) > 128
        or not rendered.isascii()
        or not rendered.isdecimal()
        or int(rendered) <= 0
    ):
        raise _input(label, "app_id", "must be a positive integer")
    return str(int(rendered))


def canonical_date(value: Any, *, label: str = "order read") -> str:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        raise _input(label, "date", "must use YYYY-MM-DD")
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError:
        raise _input(label, "date", "must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise _input(label, "date", "must use YYYY-MM-DD")
    return value


def exact_safe_row(
    value: Any, fields: tuple[str, ...] = SAFE_ROW_FIELDS
) -> dict[str, Any] | None:
    """Copy one exact, bounded JSON-scalar row or reject it entirely."""

    if not isinstance(value, Mapping) or set(value) != set(fields):
        return None
    if any(not finite_json_scalar(value[field]) for field in fields):
        return None
    return {field: copy.deepcopy(value[field]) for field in fields}


def exact_dated_safe_row(value: Any, day: str) -> dict[str, Any] | None:
    """Copy one safe order row only when its physical creation time is in day."""

    row = exact_safe_row(value)
    if row is None or not _creation_time_in_day(row["CreateTime"], day):
        return None
    return row


def finite_json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, str):
        return len(value) <= 8_192
    if type(value) is int:
        return value.bit_length() <= 256
    return isinstance(value, float) and math.isfinite(value)


def complete_order_rows(
    value: Any,
    *,
    operation_id: str,
    max_pages: int,
    max_items: int,
    max_workers: int,
    project_row: Callable[[Any], Mapping[str, Any] | None],
) -> tuple[list[Mapping[str, Any]], dict[str, Any]] | None:
    """Validate a complete public ``read_all`` envelope and rebuild its rows."""

    if not _valid_read_envelope(value, operation_id):
        return None
    raw_rows = _raw_order_rows(value.get("data"), max_items)
    if raw_rows is None:
        return None
    rows = _project_order_rows(raw_rows, project_row)
    if rows is None or (value.get("status") == "empty") != (not rows):
        return None
    page = complete_page_receipt(
        value.get("page"),
        len(rows),
        max_pages=max_pages,
        max_workers=max_workers,
        require_strategy=True,
    )
    return (rows, page) if page is not None else None


def complete_page_receipt(
    value: Any,
    count: int,
    *,
    max_pages: int,
    max_workers: int,
    require_strategy: bool = False,
) -> dict[str, Any] | None:
    """Return a smaller safe receipt only when the raw page is complete."""

    if not _valid_page_shape(value):
        return None
    fetched = value.get("pages_fetched")
    total_pages = value.get("total_pages")
    total_items = value.get("total_items")
    if not _valid_page_identity(value, count, max_pages, max_workers):
        return None
    if not _valid_page_totals(total_pages, total_items, fetched, count):
        return None
    strategy = value.get("fetch_strategy")
    if require_strategy and not isinstance(strategy, str):
        return None
    strategies = (strategy,) if isinstance(strategy, str) else _FETCH_STRATEGIES
    if not any(
        _valid_fetch_receipt(
            candidate,
            fetched=fetched,
            total_pages=total_pages,
            max_workers=max_workers,
            count=count,
        )
        for candidate in strategies
    ):
        return None
    return {
        "number": 1,
        "size": 100,
        "item_count": count,
        "total_pages": total_pages,
        "total_items": total_items,
        "has_more": False,
        "pages_fetched": fetched,
    }


def valid_read_status(value: Mapping[str, Any]) -> bool:
    status = value.get("status")
    return bool(
        isinstance(status, str)
        and status in {"success", "empty"}
        and ok_matches(value.get("ok"), status)
    )


def _valid_read_envelope(value: Any, operation_id: str) -> bool:
    return bool(
        isinstance(value, Mapping)
        and valid_read_status(value)
        and value.get("schema_version") == "gravity-insight.read.v1"
        and value.get("operation_id") == operation_id
        and value.get("error") is None
        and false_or_absent(value.get("truncated"))
        and value.get("next_page_input") is None
    )


def _creation_time_in_day(value: Any, day: str) -> bool:
    if not isinstance(value, str):
        return False
    if value == day:
        return True
    if not (value.startswith(f"{day} ") or value.startswith(f"{day}T")):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.date().isoformat() == day


def _raw_order_rows(value: Any, max_items: int) -> list[Any] | None:
    if not isinstance(value, Mapping) or "list" not in value:
        return None
    if set(value) - {"list", "page_info", "total"}:
        return None
    rows = value.get("list")
    return rows if isinstance(rows, list) and len(rows) <= max_items else None


def _project_order_rows(
    rows: list[Any], project: Callable[[Any], Mapping[str, Any] | None]
) -> list[Mapping[str, Any]] | None:
    result: list[Mapping[str, Any]] = []
    for value in rows:
        selected = project(value)
        if selected is None:
            return None
        result.append(dict(selected))
    return result


def _valid_page_shape(value: Any) -> bool:
    required = {
        "number",
        "size",
        "item_count",
        "total_pages",
        "total_items",
        "has_more",
        "pages_fetched",
        "max_workers",
    }
    return bool(
        isinstance(value, Mapping)
        and required <= set(value)
        and not set(value) - _PAGE_KEYS
    )


def _valid_page_identity(
    value: Mapping[str, Any], count: int, max_pages: int, max_workers: int
) -> bool:
    fetched = value.get("pages_fetched")
    return bool(
        type(value.get("number")) is int
        and value.get("number") == 1
        and type(value.get("size")) is int
        and value.get("size") == 100
        and type(value.get("item_count")) is int
        and value.get("item_count") == count
        and type(value.get("max_workers")) is int
        and value.get("max_workers") == max_workers
        and type(fetched) is int
        and 1 <= fetched <= max_pages
        and value.get("has_more") is False
    )


def _valid_page_totals(
    total_pages: Any, total_items: Any, fetched: int, count: int
) -> bool:
    return _complete_page_total(total_pages, fetched, count) and (
        _complete_item_total(total_items, count)
    )


def _valid_fetch_receipt(
    strategy: str,
    *,
    fetched: int,
    total_pages: int | None,
    max_workers: int,
    count: int,
) -> bool:
    if strategy not in _FETCH_STRATEGIES or count > 100 * fetched:
        return False
    if strategy == "single_page":
        return fetched == 1 and total_pages in {0, 1}
    if strategy == "serial_known_total":
        return bool(
            fetched >= 2
            and total_pages == fetched
            and (max_workers == 1 or fetched == 2)
        )
    if strategy == "parallel_known_total":
        return fetched >= 3 and total_pages == fetched and max_workers > 1
    return _valid_unknown_receipt(fetched, total_pages, count)


def _valid_unknown_receipt(
    fetched: int, total_pages: int | None, count: int
) -> bool:
    if fetched == 1:
        return total_pages is None and count < 100
    minimum = (fetched - 1) * 100 if total_pages is None else 100
    return total_pages in {None, fetched} and count >= minimum


def false_or_absent(value: Any) -> bool:
    return value is None or type(value) is bool and value is False


def ok_matches(value: Any, status: str) -> bool:
    if value is None:
        return True
    return value is True if status in {"success", "empty"} else value is False


def _complete_page_total(value: Any, fetched: int, count: int) -> bool:
    return value is None or type(value) is int and (
        value == fetched or not count and value in {0, 1}
    )


def _complete_item_total(value: Any, count: int) -> bool:
    return value is None or type(value) is int and value == count


def _input(label: str, field: str, requirement: str) -> InputValidationError:
    return InputValidationError(
        f"{label} {field} {requirement}", field=field
    )


__all__ = [
    "MAX_WORKERS",
    "SAFE_ROW_FIELDS",
    "STATIC_ORDER_FIELD_PROFILES",
    "TRACE_PARENT_FIELDS",
    "canonical_app",
    "canonical_date",
    "complete_order_rows",
    "complete_page_receipt",
    "exact_dated_safe_row",
    "exact_safe_row",
    "false_or_absent",
    "finite_json_scalar",
    "ok_matches",
    "validate_order_read_request",
]
