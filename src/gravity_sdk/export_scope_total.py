"""Pin a managed-list total to one monetization export create."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .agent_monetization_guard import MONETIZATION_DETAIL_RAW_SELECTOR
from .export_completion import MONETIZATION_EXPORT_OPERATION, UPSTREAM_FILE_ROW_LIMIT
from .export_models import _export_error
from .monetization_projection import SAFE_ROW_FIELDS


_RANGE_FIELD = "create_time"
_RANGE_OPERATOR = "RANGE_IN"
_RANGE_TYPE = "event"
_DAY_START = " 00:00:00"
_DAY_END = " 23:59:59"


def pin_export_scope_total(
    client: Any,
    operation_id: str,
    payload: Mapping[str, Any],
    *,
    clock: Any | None = None,
) -> Mapping[str, Any] | None:
    """Read one page of the matching list and keep that create-time total."""

    if operation_id != MONETIZATION_EXPORT_OPERATION:
        return None
    inputs = _list_inputs(payload)
    envelope = client.read(MONETIZATION_DETAIL_RAW_SELECTOR, inputs)
    return _scope_total(envelope, clock)


def classify_export_rows(
    rows: int,
    completeness: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Compare file rows with the pinned total; refuse an invented denominator."""

    if completeness is None:
        return None
    total = completeness.get("known_total_items")
    if type(total) is not int or total < 0 or type(rows) is not int or rows < 0:
        raise _export_error(
            "export completeness snapshot is not a comparable row count pair",
            code="EXPORT_PROTOCOL_ERROR",
            stage="finalizer",
        )
    truncated = total > UPSTREAM_FILE_ROW_LIMIT and rows == UPSTREAM_FILE_ROW_LIMIT
    complete = rows == total and rows > 0 and not truncated
    missing = None if truncated is False and rows != total else max(total - rows, 0)
    return {
        **dict(completeness),
        "file_rows": rows,
        "known_total_items": total,
        "missing_rows": missing,
        "truncated": truncated,
        "complete": complete,
        "row_limit": UPSTREAM_FILE_ROW_LIMIT,
    }


def _list_inputs(payload: Mapping[str, Any]) -> dict[str, Any]:
    app_id = payload.get("app_id")
    conditions = payload.get("global_conditions")
    if type(app_id) is not int or app_id < 1:
        raise _export_error(
            "monetization export app_id is not a positive integer",
            code="EXPORT_JOB_INVALID",
            stage="creating",
        )
    day = _single_day(conditions)
    if day is None:
        raise _export_error(
            "monetization export requires one create_time RANGE_IN day",
            code="EXPORT_JOB_INVALID",
            stage="creating",
        )
    return {
        "app_id": str(app_id),
        "date": day,
        "fields": list(SAFE_ROW_FIELDS),
        "page": 1,
        "page_size": 100,
    }


def _single_day(conditions: Any) -> str | None:
    if not isinstance(conditions, list) or len(conditions) != 1:
        return None
    item = conditions[0]
    if not isinstance(item, Mapping):
        return None
    values = item.get("value")
    if (
        item.get("field") != _RANGE_FIELD
        or item.get("operator") != _RANGE_OPERATOR
        or item.get("type") != _RANGE_TYPE
        or not isinstance(values, list)
        or len(values) != 2
        or not all(isinstance(value, str) for value in values)
    ):
        return None
    start, end = values
    if not start.endswith(_DAY_START) or not end.endswith(_DAY_END):
        return None
    day = start[: -len(_DAY_START)]
    if day != end[: -len(_DAY_END)] or len(day) != 10:
        return None
    return day


def _scope_total(envelope: Any, clock: Any | None) -> dict[str, Any]:
    if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
        raise _export_error(
            "monetization list preflight did not return a successful total",
            code="EXPORT_CREATE_FAILED",
            stage="creating",
        )
    page = envelope.get("page")
    total = page.get("total_items") if isinstance(page, Mapping) else None
    if type(total) is not int or total < 0:
        raise _export_error(
            "monetization list preflight omitted a comparable total_items",
            code="EXPORT_CREATE_FAILED",
            stage="creating",
        )
    observed_at = clock() if clock is not None else datetime.now(timezone.utc)
    if isinstance(observed_at, datetime):
        stamp = observed_at.astimezone(timezone.utc).isoformat()
    else:
        stamp = str(observed_at)
    return {
        "known_total_items": total,
        "known_total_source": f"{MONETIZATION_DETAIL_RAW_SELECTOR}.page.total_items",
        "known_total_observed_at": stamp,
        "known_total_freshness": "create_time_preflight",
        "known_total_binding": "same_app_and_create_time_day_as_export_create",
    }


__all__ = ["classify_export_rows", "pin_export_scope_total"]
