"""Governed realtime-event catalog for one App and one explicit window."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import runtime
from .composite_catalog import identity_contains, stable_operation
from .contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, EnvelopeObligations, ExecutionState,
    ExecutionStatus, MutationCertainty, MutationState, SemanticState,
    SemanticValidity, diagnostic_evidence, serialize_envelope,
)
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .list_row_projection import _is_json_scalar
from .realtime_event_diagnostics import FILTER_FIELDS, ITEM_KEYS, MAX_REALTIME_ROWS, PUBLIC_FILTER_FIELDS, _PROPERTY_NAME, _private_property, realtime_event_inputs
from .result_audit import project_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.realtime-event-catalog.v2"
OPERATION_ID = stable_operation(
    "analysis",
    "realtime_event",
    action="list",
    predicate=identity_contains("analysis"),
).operation_id
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})
_ERROR_CODES = frozenset(code.value for code in ErrorCode)


def realtime_event_catalog(
    client: Any,
    app_id: int,
    *,
    start: str,
    end: str,
    event_type: str = "profile",
    event_name: str | None = None,
    client_lib: str | None = None,
    client_lib_version: str | None = None,
    client_id: str | None = None,
    request_id: str | None = None,
    properties: list[Mapping[str, Any]] | None = None,
    property_fields: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Read bounded diagnostics without enabling realtime warehousing."""
    supplied = locals()
    inputs = realtime_event_inputs(app_id, start, end, event_type, {key: supplied[key] for key in (*FILTER_FIELDS, "property_fields")})
    native = runtime.call_read(
        client, OPERATION_ID, inputs,
    )
    return realtime_event_catalog_result(
        native, app_id=app_id, start=start, end=end, event_type=event_type,
        property_fields=property_fields, filter_fields=tuple(sorted(inputs["filters"])),
        public_filters={key: value for key, value in inputs["filters"].items() if key in PUBLIC_FILTER_FIELDS},
    )


def realtime_event_catalog_result(
    native: Any,
    *,
    app_id: int,
    start: str,
    end: str,
    event_type: str,
    property_fields: tuple[str, ...] | list[str] = (),
    filter_fields: tuple[str, ...] = (),
    public_filters: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(native, Mapping):
        return _contract_failure(native, app_id, start, end, event_type)
    status = str(native.get("status", "contract_changed"))
    if (
        native.get("schema_version") != "gravity-insight.read.v1"
        or native.get("operation_id") != OPERATION_ID
        or native.get("contract_version") != "2"
        or status not in _SUCCESS
    ):
        return _native_failure(native, app_id, start, end, event_type, status)
    items = _safe_items(native.get("data"), property_fields)
    if items is None:
        return _contract_failure(native, app_id, start, end, event_type)
    product_status = "empty" if not items else "success"
    result = serialize_envelope({
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
        "diagnostic_scope": _diagnostic_scope(filter_fields, property_fields, len(items), public_filters),
        "completeness": "unknown",
        "allowed_claims": ["returned-realtime-event-observation"],
        "forbidden_claims": ["complete-event-history", "ingestion-completeness", "empty-proves-no-delivery"],
        "error": None,
    }, _diagnostic_obligations(True, len(items)))
    return project_result_audit(result, native)


def _safe_items(value: Any, property_fields: tuple[str, ...] | list[str]) -> list[dict[str, Any]] | None:
    if not _valid_property_fields(property_fields) or not isinstance(value, Mapping):
        return None
    rows = value.get("list")
    if not isinstance(rows, list) or len(rows) > MAX_REALTIME_ROWS:
        return None
    items: list[dict[str, Any]] = []
    for row in rows:
        item = _safe_item(row, property_fields)
        if item is None:
            return None
        items.append(item)
    return items


def _valid_property_fields(value: Any) -> bool:
    return (
        isinstance(value, (tuple, list)) and len(value) <= 20
        and all(isinstance(name, str) and _PROPERTY_NAME.fullmatch(name) and not _private_property(name) for name in value)
        and len(value) == len(set(value))
    )


def _safe_item(row: Any, property_fields: tuple[str, ...] | list[str]) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    if any(not isinstance(row.get(key), str) for key in ("event_name", "request_time")):
        return None
    if any(row.get(key) is not None and not isinstance(row[key], str) for key in ITEM_KEYS):
        return None
    item = {key: copy.deepcopy(row.get(key)) for key in ITEM_KEYS}
    if property_fields:
        properties, coverage = row.get("properties"), row.get("property_coverage")
        if not _safe_selected_properties(properties, coverage, property_fields):
            return None
        item.update(properties=copy.deepcopy(dict(properties)), property_coverage=copy.deepcopy(dict(coverage)))
    return item


def _safe_selected_properties(properties: Any, coverage: Any, fields: tuple[str, ...] | list[str]) -> bool:
    if not isinstance(properties, Mapping) or not isinstance(coverage, Mapping):
        return False
    if set(properties) - set(fields) or set(coverage) != set(fields):
        return False
    return all(_safe_property_value(value) for value in properties.values()) and all(isinstance(value, str) and value in {"returned", "null", "unavailable"} for value in coverage.values())


def _safe_property_value(value: Any) -> bool:
    return _is_json_scalar(value) and (not isinstance(value, str) or len(value) <= 8192)


def _diagnostic_scope(filter_fields: tuple[str, ...] | list[str], property_fields: tuple[str, ...] | list[str], rows: int, public_filters: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "filter_fields": sorted(filter_fields), "property_fields": list(property_fields),
        "public_filters": dict(public_filters or {}),
        "time_zone": "Asia/Shanghai", "row_limit": MAX_REALTIME_ROWS,
        "limit_reached": rows == MAX_REALTIME_ROWS,
        "pagination": "unavailable", "ordering": "native_return_order",
        "empty_semantics": "no_rows_returned_does_not_prove_no_ingestion",
        "properties_semantics": "explicit_metadata_typed_scalar_selection",
    }


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
    return serialize_envelope({
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
    }, _diagnostic_obligations(False, 0, detail))


def _diagnostic_obligations(ok: bool, rows: int, error: ErrorDetail | Mapping[str, Any] | None = None) -> EnvelopeObligations:
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.COMPLETE if ok else ExecutionState.FAILED, "REALTIME_DIAGNOSTIC_READ_RETURNED" if ok else "REALTIME_DIAGNOSTIC_READ_FAILED"),
        DataCompleteness(CompletenessState.UNKNOWN, "REALTIME_CONTENT_CLOSURE_UNPROVEN", {"returned_rows": rows, "native_row_limit": MAX_REALTIME_ROWS}),
        SemanticValidity(SemanticState.UNKNOWN if ok else SemanticState.INVALID, ("REALTIME_INGESTION_SCOPE_UNVERIFIED" if ok else "REALTIME_COMPONENT_REJECTED",)),
        diagnostic_evidence(error.to_dict() if isinstance(error, ErrorDetail) else error),
        MutationCertainty(MutationState.NOT_APPLICABLE, "REALTIME_DIAGNOSTICS_READ_ONLY"),
    )


__all__ = [
    "ITEM_KEYS",
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "realtime_event_catalog",
    "realtime_event_catalog_result",
]
