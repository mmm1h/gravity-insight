"""Complete, single-day monetization detail product."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from . import runtime
from ._order_directory_failure import (
    is_builtin_code,
    native_failure_receipt,
    safe_retry_after,
    stage_for_code,
    valid_retry_receipt,
)
from ._order_read import (
    canonical_app,
    canonical_date,
    complete_order_rows,
    complete_page_receipt,
    finite_json_scalar,
    ok_matches,
    validate_order_read_request,
)
from ._field_policy_shared import parse_iso_calendar_date
from .composite_catalog import stable_operation
from .errors import ErrorCode, ErrorDetail, InputValidationError, exit_code_for_error
from .models import OperationSpec
from .monetization_projection import (
    DEVICE_INFO_FIELDS,
    SAFE_RE_ATTRIBUTE_FIELDS,
    SAFE_ROW_FIELDS,
)
from .account_permission_profile import PERMISSION_EMPTY_NEXT_ACTION
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.monetization-detail.v1"
OPERATION_ID = stable_operation(
    "analysis", "monetization_detail", action="list"
).operation_id

_SAFE_FIELDS = frozenset(SAFE_ROW_FIELDS)
_SAFE_RE_ATTRIBUTE = frozenset(SAFE_RE_ATTRIBUTE_FIELDS)
_DEVICE_INFO_FIELDS = frozenset(DEVICE_INFO_FIELDS)
_TIME_FIELDS = ("CreateTime", "AdEventTime")
_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "result_source",
        "ok",
        "status",
        "exit_code",
        "app_id",
        "date",
        "returned_items",
        "limits",
        "page",
        "data",
        "error",
        "next_action",
    }
)
_FAILURE_STATUSES = frozenset(
    {
        "error",
        "semantic_error",
        "unavailable",
        "parent_required",
        "permission_unavailable",
    }
)
_CONTRACT_STATUSES = frozenset(
    {"contract_changed", "contract_changed_additive"}
)
_ACTIONS = {
    "read": "Inspect the safe read category and retry the same bounded day.",
    "budget": "Increase the bounded page or item limit and retry the same day.",
    "contract": "Stop automation until the Monetization Detail contract is re-verified.",
}
_SUCCESS_ACTION = "Consume the complete contracted monetization rows."
_EMPTY_ACTION = PERMISSION_EMPTY_NEXT_ACTION


def monetization_detail(
    client: Any,
    app_id: str | int,
    date: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read all contracted monetization rows for one natural day."""

    app, day, workers, pages, items = validate_monetization_detail_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    inputs = {
        "app_id": app,
        "date": day,
        "fields": list(SAFE_ROW_FIELDS),
        "page": 1,
        "page_size": 100,
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
    return _result_from_read(
        value,
        app=app,
        day=day,
        pages=pages,
        items=items,
        workers=workers,
    )


def validate_monetization_detail_request(
    app_id: str | int,
    date: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, int, int, int]:
    """Validate the only caller-owned product inputs before client creation."""

    return validate_order_read_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
        product="monetization detail",
    )


def validate_monetization_operation_request(
    operation: OperationSpec, inputs: Mapping[str, Any]
) -> None:
    """Validate wire-level detail bounds before static or metadata validation."""

    fields = inputs.get("fields")
    if (
        not isinstance(fields, (list, tuple))
        or not fields
        or any(not isinstance(field, str) or not field for field in fields)
        or len(fields) != len(set(fields))
    ):
        raise InputValidationError(
            "monetization detail fields are invalid; request was not sent"
        )
    parse_iso_calendar_date(inputs.get("date"), "date")
    page, size = inputs.get("page", 1), inputs.get("page_size", 20)
    if (
        type(page) is not int
        or page < 1
        or type(size) is not int
        or not 1 <= size <= 1_000
    ):
        raise InputValidationError(
            "monetization detail pagination is outside its contract; request was not sent"
        )


def sanitize_monetization_detail_result(
    value: Any,
    expected_app_id: str | int,
    expected_date: str,
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild an envelope against its canonical request and safety bounds."""

    app = canonical_app(expected_app_id, label="monetization detail result")
    day = canonical_date(expected_date, label="monetization detail result")
    limits = _limits(max_pages, max_items, max_workers)
    if not _bound_envelope(value, app, day, limits):
        return _contract_failure(app, day, limits)
    if value.get("ok") is True and value.get("status") in {"success", "empty"}:
        return _sanitize_success(value, app, day, limits)
    if value.get("ok") is False and value.get("status") in {
        "error",
        "contract_changed",
    }:
        return _sanitize_failure(value, app, day, limits)
    return _contract_failure(app, day, limits)


def monetization_detail_item_count(value: Any) -> int:
    """Count only structurally valid public result rows."""

    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return 0
    rows = _public_rows(value)
    returned = value.get("returned_items")
    if (
        value.get("ok") is not True
        or value.get("status") not in {"success", "empty"}
        or rows is None
        or type(returned) is not int
        or returned != len(rows)
        or any(_public_row(row, value.get("date")) is None for row in rows)
    ):
        return 0
    return returned


def _result_from_read(
    value: Any,
    *,
    app: str,
    day: str,
    pages: int,
    items: int,
    workers: int,
) -> dict[str, Any]:
    if isinstance(value, BaseException):
        return _failure_from_native(value, app, day, pages, items, workers)
    if not isinstance(value, Mapping):
        return _contract_failure(app, day, _limits(pages, items, workers))
    status = value.get("status")
    if not isinstance(status, str) or not ok_matches(value.get("ok"), status):
        return _contract_failure(app, day, _limits(pages, items, workers))
    if status in _CONTRACT_STATUSES:
        return _contract_failure(app, day, _limits(pages, items, workers))
    if status in _FAILURE_STATUSES:
        return _failure_from_native(value, app, day, pages, items, workers)
    complete = complete_order_rows(
        value,
        operation_id=OPERATION_ID,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        project_row=lambda row: _raw_row(row, day),
    )
    if complete is None:
        return _contract_failure(app, day, _limits(pages, items, workers))
    rows, page = complete
    return _success_result(app, day, rows, page, _limits(pages, items, workers))


def _raw_row(value: Any, day: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected: dict[str, Any] = {}
    for field in SAFE_ROW_FIELDS:
        if field not in value:
            continue
        raw = value[field]
        if field == "re_attribute_info":
            nested = _raw_re_attribute(raw)
            if nested is None:
                return None
            selected[field] = nested
        elif field == "device_info":
            nested = _raw_device_info(raw)
            if nested is None:
                return None
            selected[field] = nested
        elif not finite_json_scalar(raw):
            return None
        else:
            selected[field] = copy.deepcopy(raw)
    if not selected or not _row_matches_day(selected, day):
        return None
    return selected


def _raw_re_attribute(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected = {
        field: copy.deepcopy(value[field])
        for field in SAFE_RE_ATTRIBUTE_FIELDS
        if field in value and finite_json_scalar(value[field])
    }
    invalid = any(
        field in value and not finite_json_scalar(value[field])
        for field in SAFE_RE_ATTRIBUTE_FIELDS
    )
    return None if invalid else selected


def _raw_device_info(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected = {
        field: copy.deepcopy(value[field])
        for field in DEVICE_INFO_FIELDS
        if field in value and finite_json_scalar(value[field])
    }
    invalid = any(
        field in value and not finite_json_scalar(value[field])
        for field in DEVICE_INFO_FIELDS
    )
    return None if invalid else selected


def _public_row(value: Any, day: Any) -> dict[str, Any] | None:
    if not isinstance(day, str) or not isinstance(value, Mapping):
        return None
    if not value or not set(value) <= _SAFE_FIELDS:
        return None
    selected = _raw_row(value, day)
    if selected is None or set(selected) != set(value):
        return None
    nested = value.get("re_attribute_info")
    if isinstance(nested, Mapping) and not set(nested) <= _SAFE_RE_ATTRIBUTE:
        return None
    device = value.get("device_info")
    if isinstance(device, Mapping) and not set(device) <= _DEVICE_INFO_FIELDS:
        return None
    return selected


def _row_matches_day(row: Mapping[str, Any], day: str) -> bool:
    values = [row[field] for field in _TIME_FIELDS if field in row]
    return bool(values) and all(_time_in_day(value, day) for value in values)


def _time_in_day(value: Any, day: str) -> bool:
    if not isinstance(value, str) or not (
        value == day or value.startswith(f"{day} ") or value.startswith(f"{day}T")
    ):
        return False
    try:
        return datetime.fromisoformat(value).date().isoformat() == day
    except ValueError:
        return value == day


def _success_result(
    app: str,
    day: str,
    rows: list[Mapping[str, Any]],
    page: Mapping[str, Any],
    limits: Mapping[str, int],
) -> dict[str, Any]:
    safe_rows = [_public_row(row, day) for row in rows]
    receipt = _public_page(page, len(rows), limits)
    if (
        any(row is None for row in safe_rows)
        or receipt is None
        or len(rows) > limits["max_items"]
    ):
        return _contract_failure(app, day, limits)
    status = "empty" if not rows else "success"
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "exit_code": 0,
        "app_id": app,
        "date": day,
        "returned_items": len(rows),
        "limits": dict(limits),
        "page": receipt,
        "data": {"list": [row for row in safe_rows if row is not None]},
        "error": None,
        "next_action": _EMPTY_ACTION if not rows else _SUCCESS_ACTION,
    }


def _sanitize_success(
    value: Mapping[str, Any],
    app: str,
    day: str,
    limits: Mapping[str, int],
) -> dict[str, Any]:
    rows = _public_rows(value)
    if rows is None:
        return _contract_failure(app, day, limits)
    safe_rows = [_public_row(row, day) for row in rows]
    receipt = _public_page(value.get("page"), len(rows), limits)
    expected = "empty" if not rows else "success"
    if (
        any(row is None for row in safe_rows)
        or receipt is None
        or value.get("status") != expected
        or value.get("exit_code") != 0
        or value.get("returned_items") != len(rows)
        or value.get("error") is not None
        or len(rows) > limits["max_items"]
    ):
        return _contract_failure(app, day, limits)
    return _success_result(app, day, [row for row in safe_rows if row], receipt, limits)


def _sanitize_failure(
    value: Mapping[str, Any],
    app: str,
    day: str,
    limits: Mapping[str, int],
) -> dict[str, Any]:
    error = value.get("error")
    if not isinstance(error, Mapping):
        return _contract_failure(app, day, limits)
    code = error.get("code")
    stage = error.get("field")
    retry = error.get("retry_after_ms")
    if (
        not isinstance(code, str)
        or not is_builtin_code(code)
        or stage != stage_for_code(code)
        or not valid_retry_receipt(code, retry)
    ):
        return _contract_failure(app, day, limits)
    rebuilt = _failure_result(app, day, code, stage, limits, retry)
    return rebuilt if value == rebuilt else _contract_failure(app, day, limits)


def _failure_from_native(
    value: Any, app: str, day: str, pages: int, items: int, workers: int
) -> dict[str, Any]:
    code, stage, retry = native_failure_receipt(value)
    return _failure_result(
        app, day, code, stage, _limits(pages, items, workers), retry
    )


def _failure_result(
    app: str,
    day: str,
    code: ErrorCode | str,
    stage: str,
    limits: Mapping[str, int],
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    candidate = code.value if isinstance(code, ErrorCode) else code
    normalized = candidate if is_builtin_code(candidate) else ErrorCode.LOCAL_IO_ERROR.value
    selected_stage = stage if stage in _ACTIONS else "contract"
    messages = {
        "budget": "Monetization Detail stopped at its complete-read safety bound.",
        "contract": "Monetization Detail observed an unverified result contract.",
        "read": "Monetization Detail read failed without exposing upstream row values.",
    }
    detail = ErrorDetail.create(
        normalized,
        messages[selected_stage],
        field=selected_stage,
        retry_after_ms=safe_retry_after(normalized, retry_after_ms),
        next_action=_ACTIONS[selected_stage],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "contract_changed" if normalized == ErrorCode.CONTRACT_CHANGED.value else "error",
        "exit_code": exit_code_for_error(detail),
        "app_id": app,
        "date": day,
        "returned_items": 0,
        "limits": dict(limits),
        "page": None,
        "data": {"list": []},
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }


def _bound_envelope(
    value: Any, app: str, day: str, limits: Mapping[str, int]
) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == _ENVELOPE_KEYS
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("app_id") == app
        and value.get("date") == day
        and value.get("limits") == limits
    )


def _public_rows(value: Mapping[str, Any]) -> list[Any] | None:
    data = value.get("data")
    if not isinstance(data, Mapping) or set(data) != {"list"}:
        return None
    rows = data.get("list")
    return rows if isinstance(rows, list) else None


def _public_page(
    value: Any, count: int, limits: Mapping[str, int]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw = {**value, "max_workers": limits["max_workers"]}
    receipt = complete_page_receipt(
        raw,
        count,
        max_pages=limits["max_pages"],
        max_workers=limits["max_workers"],
    )
    return receipt


def _limits(max_pages: Any, max_items: Any, max_workers: Any) -> dict[str, int]:
    _app, _day, workers, pages, items = validate_monetization_detail_request(
        1,
        "2000-01-01",
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    return {"max_pages": pages, "max_items": items, "max_workers": workers}


def _contract_failure(
    app: str, day: str, limits: Mapping[str, int]
) -> dict[str, Any]:
    return _failure_result(
        app, day, ErrorCode.CONTRACT_CHANGED, "contract", limits
    )


__all__ = [
    "DEVICE_INFO_FIELDS",
    "OPERATION_ID",
    "SAFE_RE_ATTRIBUTE_FIELDS",
    "SAFE_ROW_FIELDS",
    "SCHEMA_VERSION",
    "monetization_detail",
    "monetization_detail_item_count",
    "sanitize_monetization_detail_result",
    "validate_monetization_detail_request",
    "validate_monetization_operation_request",
]
