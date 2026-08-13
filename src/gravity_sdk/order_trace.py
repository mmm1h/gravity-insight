"""Bounded parent-to-child product for one exact order split trace."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from . import runtime
from ._order_read import (
    TRACE_PARENT_FIELDS,
    complete_order_rows,
    false_or_absent,
    ok_matches,
    validate_order_read_request,
)
from .composite_catalog import stable_operation
from .errors import ErrorCode, InputValidationError
from .order_trace_result import (
    MAX_SPLIT_IDS,
    SAFE_ROW_FIELDS,
    SCHEMA_VERSION,
    failure_from_native,
    failure_result,
    order_split_trace_item_count,
    sanitize_order_split_trace_result,
    success_result,
)


PARENT_OPERATION_ID = stable_operation(
    "analysis", "order_detail", action="list"
).operation_id
CHILD_OPERATION_ID = stable_operation(
    "analysis", "order_split_detail", action="list"
).operation_id
PARENT_FIELDS = TRACE_PARENT_FIELDS
_FAILURE_STATUSES = frozenset(
    {"error", "semantic_error", "unavailable", "parent_required", "permission_unavailable"}
)
_CONTRACT_STATUSES = frozenset({"contract_changed", "contract_changed_additive"})


def order_split_trace(
    client: Any,
    app_id: str | int,
    date: str,
    trace_id: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read a complete single-day parent catalog, then one governed child."""

    app, day, trace, workers, pages, items = validate_order_split_trace_request(
        app_id, date, trace_id, max_workers=max_workers,
        max_pages=max_pages, max_items=max_items,
    )
    parent = _read_parent(
        client, app, day, workers=workers, pages=pages, items=items
    )
    if isinstance(parent, dict) and parent.get("schema_version") == SCHEMA_VERSION:
        return parent
    rows, scanned = parent
    matches = [row for row in rows if _trace_value(row.get("TraceID")) == trace]
    if not matches:
        return success_result(
            app_id=app, date=day, rows=[], scanned_items=scanned,
            split_id_count=0, max_pages=pages, max_items=items,
            max_workers=workers, parent_stage="success", child_stage="skipped",
        )
    if len(matches) != 1:
        return _contract_failure(app, day, scanned, 0, pages, items, workers)
    derived = _child_inputs(matches[0], app)
    if derived is None:
        return _contract_failure(app, day, scanned, 0, pages, items, workers)
    split_ids = tuple(derived["split_trace_ids"])
    if scanned + len(split_ids) > items:
        return failure_result(
            app_id=app, date=day, code=ErrorCode.PAGINATION_LIMIT,
            stage="budget", scanned_items=scanned,
            split_id_count=len(split_ids), max_pages=pages, max_items=items,
            max_workers=workers, parent_stage="success", child_stage="skipped",
        )
    return _read_child(
        client, derived, app=app, day=day, scanned=scanned,
        split_ids=split_ids, pages=pages, items=items, workers=workers,
    )


def validate_order_split_trace_request(
    app_id: str | int,
    date: str,
    trace_id: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, str, int, int, int]:
    """Close every caller-owned value without constructing a client."""

    app, day, workers, pages, items = validate_order_read_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
        product="order split trace",
    )
    trace = _bounded_trace(trace_id)
    return app, day, trace, workers, pages, items


def _read_parent(
    client: Any, app: str, day: str, *, workers: int, pages: int, items: int
) -> tuple[list[Mapping[str, Any]], int] | dict[str, Any]:
    inputs = {
        "app_id": app, "date": day, "fields": list(PARENT_FIELDS),
        "page": 1, "page_size": 100,
    }
    try:
        value = runtime.call_read(
            client, PARENT_OPERATION_ID, inputs, read_all=True,
            max_pages=pages, max_items=items, max_workers=workers,
            forward_var_kwargs=True,
        )
    except Exception as exc:
        return failure_from_native(
            exc, app_id=app, date=day, stage="parent", scanned_items=0,
            split_id_count=0, max_pages=pages, max_items=items,
            max_workers=workers,
        )
    if not isinstance(value, Mapping):
        return _contract_failure(app, day, 0, 0, pages, items, workers)
    status = value.get("status")
    if not isinstance(status, str) or not ok_matches(value.get("ok"), status):
        return _contract_failure(app, day, 0, 0, pages, items, workers)
    if status in _CONTRACT_STATUSES:
        return _contract_failure(app, day, 0, 0, pages, items, workers)
    if status in _FAILURE_STATUSES:
        return failure_from_native(
            value, app_id=app, date=day, stage="parent", scanned_items=0,
            split_id_count=0, max_pages=pages, max_items=items,
            max_workers=workers,
        )
    if status not in {"success", "empty"}:
        return _contract_failure(app, day, 0, 0, pages, items, workers)
    complete = complete_order_rows(
        value,
        operation_id=PARENT_OPERATION_ID,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        project_row=_trace_parent_row,
    )
    if complete is None:
        return _contract_failure(app, day, 0, 0, pages, items, workers)
    rows, _page = complete
    return rows, len(rows)


def _trace_parent_row(value: Any) -> Mapping[str, Any] | None:
    if (
        not isinstance(value, Mapping)
        or set(value) - set(PARENT_FIELDS)
        or not _trace_value(value.get("TraceID"))
    ):
        return None
    return dict(value)


def _child_inputs(row: Mapping[str, Any], app: str) -> dict[str, Any] | None:
    if any(field not in row for field in PARENT_FIELDS):
        return None
    trace = _trace_value(row.get("TraceID"))
    client = _trace_value(row.get("ClientID"))
    pay_time = row.get("PayEventTime")
    raw_ids = row.get("$split_trace_id_list")
    if not trace or not client or not _valid_datetime(pay_time):
        return None
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= MAX_SPLIT_IDS:
        return None
    ids = [_string_identity(item) for item in raw_ids]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        return None
    return {
        "app_id": app, "pay_event_time": pay_time, "trace_id": trace,
        "client_id": client, "split_trace_ids": ids,
    }


def _read_child(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    app: str,
    day: str,
    scanned: int,
    split_ids: tuple[str, ...],
    pages: int,
    items: int,
    workers: int,
) -> dict[str, Any]:
    try:
        value = runtime.call_read(client, CHILD_OPERATION_ID, inputs)
    except Exception as exc:
        return failure_from_native(
            exc, app_id=app, date=day, stage="child", scanned_items=scanned,
            split_id_count=len(split_ids), max_pages=pages, max_items=items,
            max_workers=workers, parent_stage="success",
        )
    if not isinstance(value, Mapping):
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )
    status = value.get("status")
    if not isinstance(status, str) or not ok_matches(value.get("ok"), status):
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )
    if status in _CONTRACT_STATUSES:
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )
    if status in _FAILURE_STATUSES:
        return failure_from_native(
            value, app_id=app, date=day, stage="child", scanned_items=scanned,
            split_id_count=len(split_ids), max_pages=pages, max_items=items,
            max_workers=workers, parent_stage="success",
        )
    if status not in {"success", "empty"}:
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )
    sensitive = (
        inputs["trace_id"], inputs["client_id"], inputs["pay_event_time"],
        *split_ids,
    )
    rows = _safe_child_rows(value, split_ids, sensitive)
    if rows is None or scanned + len(rows) > items:
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )
    try:
        return success_result(
            app_id=app, date=day, rows=rows, scanned_items=scanned,
            split_id_count=len(split_ids), max_pages=pages, max_items=items,
            max_workers=workers, parent_stage="success",
            child_stage="empty" if not rows else "success",
        )
    except ValueError:
        return _contract_failure(
            app, day, scanned, len(split_ids), pages, items, workers,
            parent_stage="success", child_stage="contract_changed",
        )


def _safe_child_rows(
    value: Mapping[str, Any],
    split_ids: tuple[str, ...],
    sensitive: tuple[str, ...],
) -> list[dict[str, Any]] | None:
    if (
        value.get("schema_version") != "gravity-insight.read.v1"
        or value.get("operation_id") != CHILD_OPERATION_ID
        or value.get("error") not in (None, {})
        or value.get("page") is not None
        or not false_or_absent(value.get("truncated"))
        or value.get("next_page_input") is not None
    ):
        return None
    rows = value.get("data")
    if not isinstance(rows, list) or len(rows) > len(split_ids):
        return None
    if (value.get("status") == "empty") != (not rows):
        return None
    allowed, observed, safe = set(split_ids), set(), []
    for row in rows:
        selected = _safe_child_row(row, allowed, observed, sensitive)
        if selected is None:
            return None
        identity, projected = selected
        observed.add(identity)
        safe.append(projected)
    return safe


def _safe_child_row(
    value: Any,
    allowed: set[str],
    observed: set[str],
    sensitive: tuple[str, ...],
) -> tuple[str, dict[str, Any]] | None:
    fields = SAFE_ROW_FIELDS
    if not isinstance(value, Mapping) or set(value) - {"TraceID", *fields}:
        return None
    identity = _trace_value(value.get("TraceID"))
    if (
        not identity or identity not in allowed or identity in observed
        or any(field not in value for field in fields)
    ):
        return None
    projected = {field: value[field] for field in fields}
    if any(_contains_sensitive(item, sensitive) for item in projected.values()):
        return None
    return identity, projected


def _contract_failure(
    app: str,
    day: str,
    scanned: int,
    split_count: int,
    pages: int,
    items: int,
    workers: int,
    *,
    parent_stage: str = "contract_changed",
    child_stage: str = "skipped",
) -> dict[str, Any]:
    return failure_result(
        app_id=app, date=day, code=ErrorCode.CONTRACT_CHANGED,
        stage="contract", scanned_items=scanned, split_id_count=split_count,
        max_pages=pages, max_items=items, max_workers=workers,
        parent_stage=parent_stage, child_stage=child_stage,
    )


def _bounded_trace(value: Any) -> str:
    if not isinstance(value, str):
        raise _input("trace_id", "be bounded")
    if (
        not value or value != value.strip() or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise _input("trace_id", "be bounded")
    return value


def _trace_value(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    if type(value) is int and value.bit_length() > 1_024:
        return None
    rendered = str(value)
    return (
        rendered
        if rendered and rendered == rendered.strip() and len(rendered) <= 256
        and not any(ord(character) < 32 for character in rendered)
        else None
    )


def _string_identity(value: Any) -> str | None:
    return _trace_value(value) if isinstance(value, str) else None


def _valid_datetime(value: Any) -> bool:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or len(value) > 32
    ):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _contains_sensitive(value: Any, sensitive: tuple[str, ...]) -> bool:
    if not isinstance(value, str):
        return False
    return any(secret == value or len(secret) >= 4 and secret in value for secret in sensitive)


def _input(field: str, requirement: str) -> InputValidationError:
    return InputValidationError(
        f"order split trace {field} must {requirement}", field=field
    )


__all__ = [
    "CHILD_OPERATION_ID", "PARENT_FIELDS", "PARENT_OPERATION_ID",
    "SCHEMA_VERSION", "order_split_trace", "order_split_trace_item_count",
    "sanitize_order_split_trace_result", "validate_order_split_trace_request",
]
