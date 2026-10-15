"""Request-bound result contract for governed Monetization Detail reads."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

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
from .account_permission_profile import PERMISSION_EMPTY_NEXT_ACTION
from .composite_catalog import stable_operation
from .contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    diagnostic_evidence,
    serialize_envelope,
)
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .monetization_projection import (
    DEVICE_INFO_FIELDS,
    SAFE_RE_ATTRIBUTE_FIELDS,
    SAFE_ROW_FIELDS,
    safe_monetization_total,
)
from .monetization_query import normalize_monetization_query
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
        "query",
        "returned_items",
        "limits",
        "page",
        "data",
        "error",
        "next_action",
        "obligations",
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


def result_from_read(
    value: Any,
    *,
    app: str,
    day: str,
    pages: int,
    items: int,
    workers: int,
    query: Mapping[str, Any],
) -> dict[str, Any]:
    limits = _limits(pages, items, workers)
    if isinstance(value, BaseException):
        return _failure_from_native(value, app, day, limits, query)
    if not isinstance(value, Mapping):
        return _contract_failure(app, day, limits, query=query)
    status = value.get("status")
    if not isinstance(status, str) or not ok_matches(value.get("ok"), status):
        return _contract_failure(app, day, limits, query=query)
    if status in _CONTRACT_STATUSES:
        return _contract_failure(app, day, limits, query=query)
    if status in _FAILURE_STATUSES:
        return _failure_from_native(value, app, day, limits, query)
    complete = complete_order_rows(
        value,
        operation_id=OPERATION_ID,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
        project_row=lambda row: _raw_row(row, day, query.get("fields", ())),
    )
    if complete is None:
        return _contract_failure(app, day, limits, query=query)
    rows, page = complete
    data = value.get("data")
    total = safe_monetization_total(
        data.get("total") if isinstance(data, Mapping) else None,
        tuple(query.get("fields", ())),
    )
    if total is None:
        return _contract_failure(app, day, limits, query=query)
    return _success_result(app, day, rows, total, page, limits, query)


def sanitize_monetization_detail_result(
    value: Any,
    expected_app_id: str | int,
    expected_date: str,
    *,
    fields: Sequence[str] = SAFE_ROW_FIELDS,
    global_conditions: Sequence[Mapping[str, Any]] = (),
    cond_logic: str = "AND",
    local_conditions: Sequence[Mapping[str, Any]] = (),
    local_cond_logic: str = "AND",
    order_by: Sequence[Mapping[str, Any]] = (),
    segment_id: str | int | None = None,
    tmp_segment_id: str | int | None = None,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild an envelope against its canonical request and safety bounds."""

    app = canonical_app(expected_app_id, label="monetization detail result")
    day = canonical_date(expected_date, label="monetization detail result")
    limits = _limits(max_pages, max_items, max_workers)
    query = normalize_monetization_query(
        fields=fields,
        global_conditions=global_conditions,
        cond_logic=cond_logic,
        local_conditions=local_conditions,
        local_cond_logic=local_cond_logic,
        order_by=order_by,
        segment_id=segment_id,
        tmp_segment_id=tmp_segment_id,
    ).receipt()
    if not _bound_envelope(value, app, day, limits, query):
        return _contract_failure(app, day, limits, query=query)
    if value.get("ok") is True and value.get("status") in {"success", "empty"}:
        return _sanitize_success(value, app, day, limits, query)
    if value.get("ok") is False and value.get("status") in {
        "error",
        "contract_changed",
    }:
        return _sanitize_failure(value, app, day, limits, query)
    return _contract_failure(app, day, limits, query=query)


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
        or any(
            _public_row(row, value.get("date"), value.get("query")) is None
            for row in rows
        )
    ):
        return 0
    return returned


def _raw_row(
    value: Any, day: str, fields: Sequence[str] = SAFE_ROW_FIELDS
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    selected: dict[str, Any] = {}
    for field in fields:
        if field not in value:
            continue
        raw = value[field]
        nested = _raw_nested(field, raw)
        if nested is not None:
            selected[field] = nested
        elif field in {"re_attribute_info", "device_info"} or not finite_json_scalar(raw):
            return None
        else:
            selected[field] = copy.deepcopy(raw)
    if not selected or not _row_matches_day(selected, day):
        return None
    return selected


def _raw_nested(field: str, value: Any) -> dict[str, Any] | None:
    fields = {
        "re_attribute_info": SAFE_RE_ATTRIBUTE_FIELDS,
        "device_info": DEVICE_INFO_FIELDS,
    }.get(field)
    if fields is None or not isinstance(value, Mapping):
        return None
    if any(name in value and not finite_json_scalar(value[name]) for name in fields):
        return None
    return {
        name: copy.deepcopy(value[name])
        for name in fields
        if name in value
    }


def _public_row(value: Any, day: Any, query: Any = None) -> dict[str, Any] | None:
    if not isinstance(day, str) or not isinstance(value, Mapping):
        return None
    if not value or not set(value) <= _SAFE_FIELDS:
        return None
    fields = query.get("fields") if isinstance(query, Mapping) else SAFE_ROW_FIELDS
    selected = _raw_row(value, day, fields)
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
    total: list[Mapping[str, Any]],
    page: Mapping[str, Any],
    limits: Mapping[str, int],
    query: Mapping[str, Any],
) -> dict[str, Any]:
    safe_rows = [_public_row(row, day, query) for row in rows]
    receipt = _public_page(page, len(rows), limits)
    if any(row is None for row in safe_rows) or receipt is None or len(rows) > limits["max_items"]:
        return _contract_failure(app, day, limits, query=query)
    status = "empty" if not rows else "success"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "exit_code": 0,
        "app_id": app,
        "date": day,
        "query": copy.deepcopy(dict(query)),
        "returned_items": len(rows),
        "limits": dict(limits),
        "page": receipt,
        "data": {
            "list": [row for row in safe_rows if row is not None],
            "total": copy.deepcopy(total),
        },
        "error": None,
        "next_action": _EMPTY_ACTION if not rows else _SUCCESS_ACTION,
    }
    return serialize_envelope(payload, _result_obligations(True, status, len(rows), None))


def _sanitize_success(
    value: Mapping[str, Any],
    app: str,
    day: str,
    limits: Mapping[str, int],
    query: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _public_rows(value)
    total = _public_total(value, query)
    if rows is None or total is None:
        return _contract_failure(app, day, limits, query=query)
    safe_rows = [_public_row(row, day, query) for row in rows]
    receipt = _public_page(value.get("page"), len(rows), limits)
    expected = "empty" if not rows else "success"
    invalid = (
        any(row is None for row in safe_rows)
        or receipt is None
        or value.get("status") != expected
        or value.get("exit_code") != 0
        or value.get("returned_items") != len(rows)
        or value.get("error") is not None
        or len(rows) > limits["max_items"]
    )
    if invalid:
        return _contract_failure(app, day, limits, query=query)
    return _success_result(
        app, day, [row for row in safe_rows if row], total, receipt, limits, query
    )


def _public_total(
    value: Mapping[str, Any], query: Mapping[str, Any]
) -> list[dict[str, Any]] | None:
    data = value.get("data")
    return safe_monetization_total(
        data.get("total") if isinstance(data, Mapping) else None,
        tuple(query.get("fields", ())),
    )


def _sanitize_failure(
    value: Mapping[str, Any],
    app: str,
    day: str,
    limits: Mapping[str, int],
    query: Mapping[str, Any],
) -> dict[str, Any]:
    error = value.get("error")
    if not isinstance(error, Mapping):
        return _contract_failure(app, day, limits, query=query)
    code, stage, retry = error.get("code"), error.get("field"), error.get("retry_after_ms")
    if (
        not isinstance(code, str)
        or not is_builtin_code(code)
        or stage != stage_for_code(code)
        or not valid_retry_receipt(code, retry)
    ):
        return _contract_failure(app, day, limits, query=query)
    rebuilt = _failure_result(app, day, code, stage, limits, retry, query=query)
    return rebuilt if value == rebuilt else _contract_failure(app, day, limits, query=query)


def _failure_from_native(
    value: Any,
    app: str,
    day: str,
    limits: Mapping[str, int],
    query: Mapping[str, Any],
) -> dict[str, Any]:
    code, stage, retry = native_failure_receipt(value)
    return _failure_result(app, day, code, stage, limits, retry, query=query)


def _failure_result(
    app: str,
    day: str,
    code: ErrorCode | str,
    stage: str,
    limits: Mapping[str, int],
    retry_after_ms: int | None = None,
    *,
    query: Mapping[str, Any] | None = None,
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
    status = (
        "contract_changed"
        if normalized == ErrorCode.CONTRACT_CHANGED.value
        else "error"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "app_id": app,
        "date": day,
        "query": copy.deepcopy(dict(query or normalize_monetization_query().receipt())),
        "returned_items": 0,
        "limits": dict(limits),
        "page": None,
        "data": {"list": [], "total": []},
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }
    return serialize_envelope(payload, _result_obligations(False, status, 0, payload["error"]))


def _result_obligations(
    ok: bool, status: str, rows: int, error: Mapping[str, Any] | None
) -> EnvelopeObligations:
    semantic_state = SemanticState.VALID if ok else (
        SemanticState.INVALID if status == "contract_changed" else SemanticState.UNKNOWN
    )
    semantic_code = (
        "MONETIZATION_QUERY_PROFILE_VALIDATED"
        if ok
        else "MONETIZATION_CONTRACT_REJECTED"
        if status == "contract_changed"
        else "MONETIZATION_SEMANTICS_UNCONFIRMED"
    )
    return EnvelopeObligations(
        ExecutionStatus(
            ExecutionState.COMPLETE if ok else ExecutionState.FAILED,
            "MONETIZATION_READ_COMPLETE" if ok else "MONETIZATION_READ_FAILED",
        ),
        DataCompleteness(
            CompletenessState.COMPLETE if ok else CompletenessState.UNKNOWN,
            "MONETIZATION_PAGINATION_COMPLETE" if ok else "MONETIZATION_COMPLETENESS_UNKNOWN",
            {"returned_rows": rows},
        ),
        SemanticValidity(semantic_state, (semantic_code,)),
        DiagnosticEvidence(DiagnosticState.NONE)
        if error is None
        else diagnostic_evidence(error),
        MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY_MONETIZATION_DETAIL"),
    )


def _bound_envelope(
    value: Any,
    app: str,
    day: str,
    limits: Mapping[str, int],
    query: Mapping[str, Any],
) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == _ENVELOPE_KEYS
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("app_id") == app
        and value.get("date") == day
        and value.get("limits") == limits
        and value.get("query") == query
    )


def _public_rows(value: Mapping[str, Any]) -> list[Any] | None:
    data = value.get("data")
    if not isinstance(data, Mapping) or set(data) != {"list", "total"}:
        return None
    rows = data.get("list")
    return rows if isinstance(rows, list) else None


def _public_page(
    value: Any, count: int, limits: Mapping[str, int]
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return complete_page_receipt(
        {**value, "max_workers": limits["max_workers"]},
        count,
        max_pages=limits["max_pages"],
        max_workers=limits["max_workers"],
    )


def _limits(max_pages: Any, max_items: Any, max_workers: Any) -> dict[str, int]:
    _app, _day, workers, pages, items = validate_order_read_request(
        1,
        "2000-01-01",
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
        product="monetization detail",
    )
    return {"max_pages": pages, "max_items": items, "max_workers": workers}


def _contract_failure(
    app: str,
    day: str,
    limits: Mapping[str, int],
    *,
    query: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return _failure_result(
        app, day, ErrorCode.CONTRACT_CHANGED, "contract", limits, query=query
    )


__all__ = [
    "OPERATION_ID",
    "SCHEMA_VERSION",
    "monetization_detail_item_count",
    "result_from_read",
    "sanitize_monetization_detail_result",
]
