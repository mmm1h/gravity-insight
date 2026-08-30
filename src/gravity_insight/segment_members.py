"""Complete member rows for one exact Analysis segment."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from . import runtime
from ._field_policy_operations import ANALYSIS_SEGMENT, ANALYSIS_SEGMENT_USER_DETAIL
from .errors import (
    ContractChangedError,
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    exit_code_for_category,
    exit_code_for_error,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value
from .process_limits import MAX_CONCURRENCY


SCHEMA_VERSION = "gravity-insight.segment-members.v1"
DEFAULT_CONCURRENCY = 6
_SUCCESS = frozenset({"success", "empty"})
_CONTRACT_CHANGED = frozenset({"contract_changed", "contract_changed_additive"})


def validate_segment_members_request(
    app_id: str | int,
    ref: str | int,
    *,
    fields: Sequence[str] | None = None,
    segment_version_id: str | int | None = None,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[str, str, tuple[str, ...], str | None, int, int, int]:
    """Validate every caller-owned value before client construction."""

    app = _bounded_identifier(app_id, "app_id", 64)
    selected_ref = _bounded_identifier(ref, "ref", 256)
    selected_fields = _fields(fields)
    version = (
        None
        if segment_version_id in (None, "")
        else _bounded_identifier(segment_version_id, "segment_version_id", 64)
    )
    if type(max_workers) is not int or not 1 <= max_workers <= MAX_CONCURRENCY:
        raise InputValidationError("segment members max_workers is outside 1..24", field="max_workers", next_action="Set max_workers to an integer from 1 through 24.")
    if type(max_pages) is not int or not 1 <= max_pages <= 10_000:
        raise InputValidationError("segment members max_pages is outside 1..10000", field="max_pages", next_action="Set max_pages to an integer from 1 through 10000.")
    if type(max_items) is not int or not 1 <= max_items <= 1_000_000:
        raise InputValidationError("segment members max_items is outside 1..1000000", field="max_items", next_action="Omit either --limit or --max-items, then retry.")
    return app, selected_ref, selected_fields, version, max_workers, max_pages, max_items


def segment_members(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    fields: Sequence[str] | None = None,
    segment_version_id: str | int | None = None,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Return complete upstream member rows, or an explicit bounded prefix."""

    app, selected_ref, selected_fields, version, workers, pages, items = (
        validate_segment_members_request(
            app_id,
            ref,
            fields=fields,
            segment_version_id=segment_version_id,
            max_workers=max_workers,
            max_pages=max_pages,
            max_items=max_items,
        )
    )
    identity = _direct_identity(selected_ref)
    if identity is None:
        identity = _resolve_identity(client, app, selected_ref, pages, items)
    inputs: dict[str, Any] = {"app_id": app, "segment_id": identity["id"]}
    if selected_fields:
        inputs["fields"] = list(selected_fields)
    if version is not None:
        inputs["segment_version_id"] = version
    try:
        value = runtime.call_read(
            client,
            ANALYSIS_SEGMENT_USER_DETAIL,
            inputs,
            max_pages=pages,
            max_items=items,
            max_workers=1,
            forward_var_kwargs=True,
        )
    except Exception as exc:
        return _failure(app, identity, selected_fields, version, pages, items, workers, exc)
    return _from_read(
        value,
        app=app,
        identity=identity,
        fields=selected_fields,
        version=version,
        pages=pages,
        items=items,
        workers=workers,
    )


def _resolve_identity(
    client: Any, app: str, ref: str, pages: int, items: int
) -> dict[str, str]:
    value = runtime.call_read(
        client,
        ANALYSIS_SEGMENT,
        {"app_id": app, "page": 1, "page_size": min(100, items)},
        read_all=True,
        max_pages=pages,
        max_items=items,
        max_workers=1,
        forward_var_kwargs=True,
    )
    rows = _rows(value, ANALYSIS_SEGMENT)
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise InputValidationError(
            f"actual value: {actual_value(value.get('truncated'))}; " + ("segment catalog is incomplete within the supplied limits"),
            field="limits",
            next_action="Increase max_pages/max_items, then retry the exact name.",
        )
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        segment_id = _row_id(row)
        name = row.get("segment_name")
        if not isinstance(name, str) or not name.strip() or segment_id in seen:
            raise ContractChangedError("segment catalog returned an invalid identity")
        seen.add(segment_id)
        if row.get("app_id") is not None and str(row["app_id"]) != app:
            raise ContractChangedError("segment catalog returned an App identity mismatch")
        if segment_id == ref or name == ref:
            matches.append({"id": segment_id, "name": name})
    if len(matches) != 1:
        reason = "matches more than one exact name" if matches else "was not found"
        raise InputValidationError(
            f"actual value: {actual_value(matches)}; " + (f"segment ref {reason}"),
            field="ref",
            next_action="Use the stable segment id from the complete segment catalog.",
        )
    return matches[0]


def _from_read(
    value: Any,
    *,
    app: str,
    identity: Mapping[str, str],
    fields: tuple[str, ...],
    version: str | None,
    pages: int,
    items: int,
    workers: int,
) -> dict[str, Any]:
    if _unusable_read(value):
        return _failure(app, identity, fields, version, pages, items, workers, value)
    try:
        rows, page_info = _member_data(value)
    except ContractChangedError:
        return _failure(app, identity, fields, version, pages, items, workers)
    selected = _select_rows(rows[:items], fields)
    truncated = value.get("truncated") is True
    result_status = "partial" if truncated else ("empty" if not selected else "success")
    detail = (
        ErrorDetail.create(
            ErrorCode.PAGINATION_LIMIT,
            "Segment member rows exceeded the supplied item limit.",
            operation_id=ANALYSIS_SEGMENT_USER_DETAIL,
            next_action=(
                "Raise max_items within the documented limit and retry the same request."
            ),
        )
        if truncated
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": not truncated,
        "status": result_status,
        "exit_code": exit_code_for_error(detail) if detail is not None else 0,
        "operation_id": ANALYSIS_SEGMENT_USER_DETAIL,
        "app_id": app,
        "segment": dict(identity),
        "segment_version_id": version,
        "fields": list(fields),
        "returned_items": len(selected),
        "total_items": _total_items(value, len(rows)),
        "complete": not truncated,
        "limits": {"max_workers": workers, "max_pages": pages, "max_items": items},
        "data": {"list": selected, "page_info": copy.deepcopy(page_info)},
        "error": detail.to_dict() if detail is not None else None,
        "next_action": detail.next_action if detail is not None else None,
    }


def _unusable_read(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return True
    status = _status(value)
    return (
        status in _CONTRACT_CHANGED
        or status not in _SUCCESS
        or value.get("ok") is not True
    )


def _member_data(value: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], Any]:
    rows = _rows(value, ANALYSIS_SEGMENT_USER_DETAIL)
    data = value.get("data")
    page_info = data.get("page_info") if isinstance(data, Mapping) else None
    if page_info is not None and not isinstance(page_info, Mapping):
        raise ContractChangedError("segment members page_info changed shape")
    return rows, copy.deepcopy(page_info)


def _select_rows(
    rows: Sequence[Mapping[str, Any]], fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    if not fields:
        return [copy.deepcopy(dict(row)) for row in rows]
    return [
        {key: copy.deepcopy(row[key]) for key in fields if key in row}
        for row in rows
    ]


def _total_items(value: Mapping[str, Any], fallback: int) -> int:
    total = value.get("total")
    if isinstance(total, Mapping) and type(total.get("items")) is int:
        return int(total["items"])
    return fallback


def _rows(value: Any, operation_id: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        raise ContractChangedError(f"{operation_id} returned an invalid envelope")
    status = _status(value)
    if value.get("ok") is not True or status not in _SUCCESS:
        raise ContractChangedError(f"{operation_id} did not return a usable contract")
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(f"{operation_id} no longer returns data.list")
    return rows


def _failure(
    app: str,
    identity: Mapping[str, str],
    fields: tuple[str, ...],
    version: str | None,
    pages: int,
    items: int,
    workers: int,
    native: Any = None,
) -> dict[str, Any]:
    detail = _failure_detail(native)
    category = str(detail.get("category", ErrorCategory.UPSTREAM.value))
    exit_code = exit_code_for_category(category, default=ErrorCategory.LOCAL)
    native_status = _status(native) if isinstance(native, Mapping) else ""
    status = "contract_changed" if native_status in _CONTRACT_CHANGED else (
        native_status if native_status in {
            "error", "semantic_error", "unavailable", "parent_required",
            "permission_unavailable",
        } else "error"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": status,
        "exit_code": exit_code,
        "operation_id": ANALYSIS_SEGMENT_USER_DETAIL,
        "app_id": app,
        "segment": dict(identity),
        "segment_version_id": version,
        "fields": list(fields),
        "returned_items": 0,
        "total_items": None,
        "complete": False,
        "limits": {"max_workers": workers, "max_pages": pages, "max_items": items},
        "data": None,
        "error": copy.deepcopy(detail),
        "next_action": detail.get("next_action"),
    }


def _failure_detail(native: Any) -> dict[str, Any]:
    if isinstance(native, Mapping) and isinstance(native.get("error"), Mapping):
        return copy.deepcopy(dict(native["error"]))
    if isinstance(native, GravityInsightError):
        return native.to_error_detail(operation_id=ANALYSIS_SEGMENT_USER_DETAIL).to_dict()
    return ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED if native is None else ErrorCode.LOCAL_IO_ERROR,
        (
            "Segment member rows were not delivered because their contract changed."
            if native is None else "Segment member client failed locally."
        ),
        operation_id=ANALYSIS_SEGMENT_USER_DETAIL,
    ).to_dict()


def _direct_identity(ref: str) -> dict[str, str] | None:
    return {"id": ref} if ref.isdecimal() and int(ref) > 0 else None


def _row_id(row: Mapping[str, Any]) -> str:
    value = row.get("segment_id", row.get("id"))
    return _bounded_identifier(value, "segment_id", 64)


def _bounded_identifier(value: Any, field: str, limit: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputValidationError(f"segment members {field} is invalid", field=field, next_action="Correct that field to a documented value and retry.")
    selected = str(value).strip()
    if not selected or len(selected) > limit:
        raise InputValidationError(f"segment members {field} is invalid", field=field, next_action="Correct that field to a documented value and retry.")
    return selected


def _fields(value: Sequence[str] | None) -> tuple[str, ...]:
    if value in (None, (), []):
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InputValidationError(f"actual value: {actual_value(value)}; " + ("segment members fields must be a list"), field="fields")
    selected = tuple(value)
    if len(selected) > 100 or len(set(selected)) != len(selected) or any(
        not isinstance(item, str) or not item or len(item) > 256 for item in selected
    ):
        raise InputValidationError("segment members fields are invalid", field="fields", next_action="Use live user-property names from `gravity metadata properties \"\"`.")
    return selected


def _status(value: Mapping[str, Any]) -> str:
    status = value.get("status")
    return status.strip().casefold() if isinstance(status, str) else ""


__all__ = [
    "ANALYSIS_SEGMENT_USER_DETAIL",
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "SCHEMA_VERSION",
    "segment_members",
    "validate_segment_members_request",
]
