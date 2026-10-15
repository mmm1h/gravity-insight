"""Bounded, single-day physical order directory product."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import runtime
from ._order_read import (
    ReadContractRejection,
    SAFE_ROW_FIELDS,
    complete_order_rows,
    exact_dated_safe_row,
    finite_json_scalar,
    ok_matches,
    reject_order_read,
    validate_order_read_request,
)
from .composite_catalog import stable_operation
from .errors import ErrorCode
from .order_directory_result import (
    build_contract_diagnostic as contract_diagnostic,
    native_contract_diagnostic,
    SCHEMA_VERSION,
    failure_from_native,
    failure_result,
    order_directory_item_count,
    sanitize_order_directory_result,
    success_result,
)


OPERATION_ID = stable_operation(
    "analysis", "order_detail", action="list"
).operation_id

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


def order_directory(
    client: Any,
    app_id: str | int,
    date: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read a complete natural-day order directory with four physical fields."""

    app, day, workers, pages, items = validate_order_directory_request(
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
    value = _call_directory_read(
        client, inputs, pages=pages, items=items, workers=workers
    )
    if isinstance(value, BaseException):
        return failure_from_native(
            value,
            app_id=app,
            date=day,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
        )
    return _result_from_read(
        value, app=app, day=day, pages=pages, items=items, workers=workers
    )


def _call_directory_read(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    pages: int,
    items: int,
    workers: int,
) -> Any:
    try:
        return runtime.call_read(
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
        return exc


def _result_from_read(
    value: Any,
    *,
    app: str,
    day: str,
    pages: int,
    items: int,
    workers: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        rejected = reject_order_read("envelope", (), "object", value)
        return _contract_failure(
            app, day, pages, items, workers,
            diagnostic=contract_diagnostic(rejected.layer, rejected.response_drift, product_schema_version=SCHEMA_VERSION),
        )
    status = value.get("status")
    if isinstance(status, str) and status in _CONTRACT_STATUSES:
        return _contract_failure(
            app, day, pages, items, workers,
            diagnostic=native_contract_diagnostic(value, product_schema_version=SCHEMA_VERSION),
        )
    if not isinstance(status, str) or not ok_matches(value.get("ok"), status):
        field, kind = ("ok", "boolean") if isinstance(status, str) else ("status", "string")
        rejected = reject_order_read("envelope", (field,), kind, value.get(field))
        return _contract_failure(
            app, day, pages, items, workers,
            diagnostic=contract_diagnostic(rejected.layer, rejected.response_drift, product_schema_version=SCHEMA_VERSION),
        )
    if status in _FAILURE_STATUSES:
        return failure_from_native(
            value,
            app_id=app,
            date=day,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
        )
    complete = complete_order_rows(
        value,
        operation_id=OPERATION_ID,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        project_row=lambda row: _directory_row(row, day),
    )
    if isinstance(complete, ReadContractRejection):
        return _contract_failure(
            app, day, pages, items, workers,
            diagnostic=contract_diagnostic(complete.layer, complete.response_drift, product_schema_version=SCHEMA_VERSION),
        )
    rows, page = complete
    try:
        return success_result(
            app_id=app,
            date=day,
            rows=rows,
            page=page,
            max_pages=pages,
            max_items=items,
            max_workers=workers,
        )
    except ValueError:
        return _contract_failure(app, day, pages, items, workers)


def _directory_row(value: Any, day: str) -> dict[str, Any] | ReadContractRejection:
    row = exact_dated_safe_row(value, day)
    if row is not None:
        return row
    path = ("data", "list", "*")
    if not isinstance(value, Mapping):
        return reject_order_read("row", path, "object", value)
    for field in SAFE_ROW_FIELDS:
        if field not in value:
            return reject_order_read("row", (*path, field), "json_scalar")
        if not finite_json_scalar(value[field]):
            return reject_order_read("row", (*path, field), "json_scalar", value[field])
    if set(value) != set(SAFE_ROW_FIELDS):
        return reject_order_read("row", path, "object", value)
    return reject_order_read("row", (*path, "CreateTime"), "string", value["CreateTime"])


def validate_order_directory_request(
    app_id: str | int,
    date: str,
    *,
    max_workers: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, int, int, int]:
    """Close every caller-owned value before a client can be constructed."""

    return validate_order_read_request(
        app_id,
        date,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
        product="order directory",
    )


def _contract_failure(
    app: str, day: str, pages: int, items: int, workers: int,
    *, diagnostic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if diagnostic is None:
        diagnostic = contract_diagnostic("envelope", None, product_schema_version=SCHEMA_VERSION)
    return failure_result(
        app_id=app,
        date=day,
        code=ErrorCode.CONTRACT_CHANGED,
        stage="contract",
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        contract_diagnostic=diagnostic,
    )


__all__ = [
    "OPERATION_ID",
    "SAFE_ROW_FIELDS",
    "SCHEMA_VERSION",
    "order_directory",
    "order_directory_item_count",
    "sanitize_order_directory_result",
    "validate_order_directory_request",
]
