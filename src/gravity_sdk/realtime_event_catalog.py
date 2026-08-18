"""Governed realtime-event catalog for one App and one explicit window."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_catalog import identity_contains, stable_operation
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .result_audit import project_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.realtime-event-catalog.v1"
OPERATION_ID = stable_operation(
    "analysis",
    "realtime_event",
    action="list",
    predicate=identity_contains("analysis"),
).operation_id
ITEM_KEYS = (
    "client_id",
    "client_time",
    "event_name",
    "event_type",
    "request_id",
    "request_time",
)
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
_ERROR_CODES = frozenset(code.value for code in ErrorCode)


def realtime_event_catalog(
    client: Any,
    app_id: int,
    *,
    start: str,
    end: str,
    event_type: str = "profile",
) -> dict[str, Any]:
    """Read one first page of the realtime-event catalog."""

    native = runtime.call_read(
        client,
        OPERATION_ID,
        {
            "app_id": app_id,
            "filters": {"event_type": event_type} if event_type else {},
            "page": 1,
            "page_size": 50,
            "request_time": [start, end],
        },
    )
    return realtime_event_catalog_result(
        native, app_id=app_id, start=start, end=end, event_type=event_type
    )


def realtime_event_catalog_result(
    native: Any,
    *,
    app_id: int,
    start: str,
    end: str,
    event_type: str,
) -> dict[str, Any]:
    if not isinstance(native, Mapping):
        return _contract_failure(native, app_id, start, end, event_type)
    status = str(native.get("status", "contract_changed"))
    if (
        native.get("schema_version") != "gravity-insight.read.v1"
        or native.get("operation_id") != OPERATION_ID
        or status not in _SUCCESS
    ):
        return _native_failure(native, app_id, start, end, event_type, status)
    items = _safe_items(native.get("data"))
    if items is None:
        return _contract_failure(native, app_id, start, end, event_type)
    product_status = "empty" if not items else "success"
    result = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": product_status,
        "exit_code": 0,
        "operation_id": OPERATION_ID,
        "app_id": app_id,
        "start": start,
        "end": end,
        "event_type": event_type,
        "item_count": len(items),
        "data": {"list": items},
        "error": None,
    }
    return project_result_audit(result, native)


def _safe_items(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, Mapping):
        return None
    rows = value.get("list")
    if not isinstance(rows, list):
        return None
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        items.append({key: copy.deepcopy(row.get(key)) for key in ITEM_KEYS})
    return items


def _native_failure(
    native: Mapping[str, Any],
    app_id: int,
    start: str,
    end: str,
    event_type: str,
    status: str,
) -> dict[str, Any]:
    error = native.get("error")
    if not isinstance(error, Mapping):
        return _contract_failure(native, app_id, start, end, event_type)
    raw_code = error.get("code")
    code = (
        raw_code
        if isinstance(raw_code, str) and raw_code in _ERROR_CODES
        else ErrorCode.CONTRACT_CHANGED
    )
    retry_after = error.get("retry_after_ms")
    detail = ErrorDetail.create(
        code,
        "Realtime-event catalog could not complete its governed read.",
        operation_id=OPERATION_ID,
        field=error.get("field") if isinstance(error.get("field"), str) else None,
        retry_after_ms=retry_after if type(retry_after) is int and retry_after >= 0 else None,
        next_action=(
            str(error["next_action"])
            if isinstance(error.get("next_action"), str) and error["next_action"]
            else None
        ),
    )
    return project_result_audit(
        _failure(app_id, start, end, event_type, status, detail), native
    )


def _contract_failure(
    native: Any, app_id: int, start: str, end: str, event_type: str
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Realtime-event catalog result no longer matches its registered contract.",
        operation_id=OPERATION_ID,
        next_action="Stop automation, refresh the shape evidence, and retry after the contract is updated.",
    )
    return project_result_audit(
        _failure(app_id, start, end, event_type, "contract_changed", detail), native
    )


def _failure(
    app_id: int,
    start: str,
    end: str,
    event_type: str,
    status: str,
    detail: ErrorDetail,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "operation_id": OPERATION_ID,
        "app_id": app_id,
        "start": start,
        "end": end,
        "event_type": event_type,
        "item_count": 0,
        "data": {"list": []},
        "error": detail.to_dict(),
    }


__all__ = [
    "ITEM_KEYS",
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "realtime_event_catalog",
    "realtime_event_catalog_result",
]
