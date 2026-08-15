"""Request-bound result contract for Order Split Trace v1."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date as date_type
from typing import Any

from ._order_read import finite_json_scalar
from .errors import ErrorCode, ErrorDetail, exit_code_for_error


SCHEMA_VERSION = "gravity-insight.order-split-trace.v1"
SAFE_ROW_FIELDS = ("Amount", "BackAmount", "Status", "CreateTime")
MAX_SPLIT_IDS = 100

_BUILTIN_CODES = frozenset(item.value for item in ErrorCode)
_SUCCESS_STATUSES = frozenset({"success", "empty"})
_FAILURE_STATUSES = frozenset({"contract_changed", "error"})
_STATUS_CODES = {
    "contract_changed": ErrorCode.CONTRACT_CHANGED.value,
    "contract_changed_additive": ErrorCode.CONTRACT_CHANGED.value,
    "parent_required": ErrorCode.PARENT_REQUIRED.value,
    "permission_unavailable": ErrorCode.PERMISSION_UNAVAILABLE.value,
}
_FAILURE_CODES = {
    "parent_required": frozenset({ErrorCode.PARENT_REQUIRED.value}),
    "permission_unavailable": frozenset({ErrorCode.PERMISSION_UNAVAILABLE.value}),
    "semantic_error": frozenset({ErrorCode.UPSTREAM_UNAVAILABLE.value}),
    "unavailable": frozenset(
        {
            ErrorCode.NOT_IMPLEMENTED.value,
            ErrorCode.UNKNOWN_OPERATION.value,
            ErrorCode.UNSUPPORTED.value,
        }
    ),
}
_SPECIAL_FAILURE_CODES = frozenset(
    code for codes in _FAILURE_CODES.values() for code in codes
)
_STAGE_STATUSES = frozenset(
    {"pending", "success", "empty", "skipped", "error", "contract_changed"}
)
_SAFE_ACTIONS = {
    "parent": "Inspect the parent read receipt and retry this bounded natural day.",
    "child": "Inspect the child read category and retry the same bounded trace.",
    "contract": "Stop automation until the Order Split Trace contract is re-verified.",
    "budget": "Increase max_items within the documented bound and retry.",
}
_MAX_RECEIPT_INTEGER = (1 << 31) - 1


def order_split_trace_item_count(value: Any) -> int:
    """Count only registered child rows in a product envelope."""

    if not isinstance(value, Mapping) or value.get("ok") is not True:
        return 0
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        return 0
    return len(rows) if all(_safe_row(row) is not None for row in rows) else 0


def success_result(
    *,
    app_id: str,
    date: str,
    rows: list[dict[str, Any]],
    scanned_items: int,
    split_id_count: int,
    max_pages: int,
    max_items: int,
    max_workers: int,
    parent_stage: str,
    child_stage: str,
) -> dict[str, Any]:
    """Build one controlled successful or empty product envelope."""

    safe_rows = [_required_safe_row(row) for row in rows]
    returned = len(safe_rows)
    status = "empty" if returned == 0 else "success"
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": status,
        "exit_code": 0,
        "app_id": app_id,
        "date": date,
        "scanned_items": scanned_items,
        "split_id_count": split_id_count,
        "returned_items": returned,
        "limits": _limits(max_pages, max_items, max_workers),
        "stages": _stages(parent_stage, child_stage),
        "data": {"list": safe_rows},
        "error": None,
        "next_action": "Consume the registered physical split-order rows.",
    }


def failure_result(
    *,
    app_id: str,
    date: str,
    code: ErrorCode | str,
    stage: str,
    scanned_items: int,
    split_id_count: int,
    max_pages: int,
    max_items: int,
    max_workers: int,
    retry_after_ms: int | None = None,
    parent_stage: str | None = None,
    child_stage: str | None = None,
) -> dict[str, Any]:
    """Build a value-free failure without copying native text or inputs."""

    normalized_code = _safe_code(code)
    action_key = "budget" if normalized_code == ErrorCode.PAGINATION_LIMIT.value else stage
    action = _SAFE_ACTIONS.get(action_key, _SAFE_ACTIONS["contract"])
    detail = ErrorDetail.create(
        normalized_code,
        _failure_message(stage, normalized_code),
        field=stage if stage in {"parent", "child"} else "contract",
        retry_after_ms=_safe_retry_after(normalized_code, retry_after_ms),
        next_action=action,
    )
    status = (
        "contract_changed"
        if normalized_code == ErrorCode.CONTRACT_CHANGED.value
        else "error"
    )
    resolved_parent = parent_stage or (
        status if stage == "parent" else "success" if stage == "child" else "error"
    )
    resolved_child = child_stage or (
        status if stage == "child" else "skipped"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": status,
        "exit_code": exit_code_for_error(detail),
        "app_id": app_id,
        "date": date,
        "scanned_items": _bounded_count(scanned_items, max_items),
        "split_id_count": _bounded_count(split_id_count, MAX_SPLIT_IDS),
        "returned_items": 0,
        "limits": _limits(max_pages, max_items, max_workers),
        "stages": _stages(resolved_parent, resolved_child),
        "data": {"list": []},
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }


def failure_from_native(
    value: Any,
    *,
    app_id: str,
    date: str,
    stage: str,
    scanned_items: int,
    split_id_count: int,
    max_pages: int,
    max_items: int,
    max_workers: int,
    parent_stage: str | None = None,
) -> dict[str, Any]:
    """Reduce a native error envelope or exception to built-in safe receipts."""

    raw = _native_error(value)
    raw_code = raw.get("code")
    candidate = raw_code.strip().upper() if isinstance(raw_code, str) else ""
    raw_status = value.get("status") if isinstance(value, Mapping) else None
    fallback = ErrorCode.LOCAL_IO_ERROR.value if isinstance(value, BaseException) else (
        _STATUS_CODES.get(raw_status, ErrorCode.UPSTREAM_UNAVAILABLE.value)
        if isinstance(raw_status, str) else ErrorCode.UPSTREAM_UNAVAILABLE.value
    )
    code = candidate if candidate in _BUILTIN_CODES else fallback
    if isinstance(raw_status, str) and not _failure_matches(raw_status, code):
        code = ErrorCode.CONTRACT_CHANGED.value
    retry_after = raw.get("retry_after_ms")
    return failure_result(
        app_id=app_id,
        date=date,
        code=code,
        stage=stage,
        scanned_items=scanned_items,
        split_id_count=split_id_count,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
        retry_after_ms=retry_after if type(retry_after) is int else None,
        parent_stage=parent_stage,
    )


def sanitize_order_split_trace_result(
    value: Any,
    expected_app_id: str | int,
    expected_date: str,
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild a core result against Plan/request-bound identity and limits."""

    app_id = _canonical_app(expected_app_id)
    date = _canonical_date(expected_date)
    expected_limits = _limits(max_pages, max_items, max_workers)
    if not isinstance(value, Mapping):
        return _contract_result(app_id, date, expected_limits)
    if value.get("schema_version") != SCHEMA_VERSION:
        return _contract_result(app_id, date, expected_limits)
    if value.get("app_id") != app_id or value.get("date") != date:
        return _contract_result(app_id, date, expected_limits)
    if value.get("limits") != expected_limits:
        return _contract_result(app_id, date, expected_limits)
    counts = _validated_counts(value, max_items)
    stages = _validated_stages(value.get("stages"))
    if counts is None or stages is None:
        return _contract_result(app_id, date, expected_limits)
    status = value.get("status")
    if not isinstance(status, str):
        return _contract_result(app_id, date, expected_limits)
    if value.get("ok") is True and status in _SUCCESS_STATUSES:
        return _sanitize_success(value, app_id, date, expected_limits, counts, stages)
    if value.get("ok") is False and status in _FAILURE_STATUSES:
        return _sanitize_failure(value, app_id, date, expected_limits, counts, stages)
    return _contract_result(app_id, date, expected_limits)


def _sanitize_success(
    value: Mapping[str, Any],
    app_id: str,
    date: str,
    limits: dict[str, int],
    counts: tuple[int, int, int],
    stages: dict[str, str],
) -> dict[str, Any]:
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list):
        return _contract_result(app_id, date, limits)
    safe_rows = [_safe_row(row) for row in rows]
    scanned, split_ids, returned = counts
    expected_status = "empty" if not rows else "success"
    if not _valid_success_receipt(
        value, safe_rows=safe_rows, rows=rows, returned=returned,
        scanned=scanned, split_ids=split_ids, max_items=limits["max_items"],
        stages=stages, expected_status=expected_status,
    ):
        return _contract_result(app_id, date, limits)
    return success_result(
        app_id=app_id,
        date=date,
        rows=[row for row in safe_rows if row is not None],
        scanned_items=scanned,
        split_id_count=split_ids,
        max_pages=limits["max_pages"],
        max_items=limits["max_items"],
        max_workers=limits["max_workers"],
        parent_stage=stages["parent"],
        child_stage=stages["child"],
    )


def _valid_success_receipt(
    value: Mapping[str, Any],
    *,
    safe_rows: list[dict[str, Any] | None],
    rows: list[Any],
    returned: int,
    scanned: int,
    split_ids: int,
    max_items: int,
    stages: Mapping[str, str],
    expected_status: str,
) -> bool:
    expected_child = "success" if rows else "empty" if split_ids else "skipped"
    child_reachable = split_ids == 0 if expected_child == "skipped" else scanned > 0 and split_ids > 0
    return bool(
        all(row is not None for row in safe_rows)
        and returned == len(rows)
        and scanned + split_ids <= max_items
        and child_reachable
        and value.get("status") == expected_status
        and type(value.get("exit_code")) is int
        and value.get("exit_code") == 0
        and value.get("error") is None
        and stages["parent"] == "success"
        and stages["child"] == expected_child
    )


def _sanitize_failure(
    value: Mapping[str, Any],
    app_id: str,
    date: str,
    limits: dict[str, int],
    counts: tuple[int, int, int],
    stages: dict[str, str],
) -> dict[str, Any]:
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    raw_error = value.get("error")
    if not _valid_failure_shape(rows, counts, raw_error, value.get("ok")):
        return _contract_result(app_id, date, limits)
    raw_code = raw_error.get("code")
    candidate = raw_code.strip().upper() if isinstance(raw_code, str) else ""
    if candidate not in _BUILTIN_CODES:
        return _contract_result(app_id, date, limits)
    if not _valid_failure_budget(counts, stages, limits["max_items"], candidate):
        return _contract_result(app_id, date, limits)
    field = raw_error.get("field")
    stage = field if isinstance(field, str) and field in {"parent", "child"} else "contract"
    expected_status = (
        "contract_changed" if candidate == ErrorCode.CONTRACT_CHANGED.value else "error"
    )
    detail = ErrorDetail.create(candidate, "safe")
    if (
        value.get("status") != expected_status
        or type(value.get("exit_code")) is not int
        or value.get("exit_code") != exit_code_for_error(detail)
        or not _valid_failure_stages(stage, candidate, stages, expected_status)
    ):
        return _contract_result(app_id, date, limits)
    return failure_result(
        app_id=app_id,
        date=date,
        code=candidate,
        stage=stage,
        scanned_items=counts[0],
        split_id_count=counts[1],
        max_pages=limits["max_pages"],
        max_items=limits["max_items"],
        max_workers=limits["max_workers"],
        retry_after_ms=(
            raw_error.get("retry_after_ms")
            if type(raw_error.get("retry_after_ms")) is int
            else None
        ),
        parent_stage=stages["parent"],
        child_stage=stages["child"],
    )


def _valid_failure_shape(rows: Any, counts: tuple[int, int, int], error: Any, ok: Any) -> bool:
    return rows == [] and counts[2] == 0 and isinstance(error, Mapping) and ok is False


def _valid_failure_budget(
    counts: tuple[int, int, int],
    stages: Mapping[str, str],
    max_items: int,
    code: str,
) -> bool:
    scanned, split_ids, _returned = counts
    if stages["parent"] == "error":
        return scanned == 0 and split_ids == 0
    if stages["parent"] == "success":
        if scanned == 0 or split_ids == 0:
            return False
        exceeds = scanned + split_ids > max_items
        budget_failure = stages["child"] == "skipped"
        return exceeds is budget_failure and budget_failure is (
            code == ErrorCode.PAGINATION_LIMIT.value
        )
    return code == ErrorCode.CONTRACT_CHANGED.value and split_ids == 0


def _failure_matches(status: str, code: str) -> bool:
    expected = _FAILURE_CODES.get(status)
    return code in expected if expected is not None else code not in _SPECIAL_FAILURE_CODES


def _valid_failure_stages(
    stage: str, code: str, stages: Mapping[str, str], status: str
) -> bool:
    if stage == "parent":
        return stages == {"parent": status, "child": "skipped"}
    if stage == "child":
        return stages == {"parent": "success", "child": status}
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return stages == {"parent": "success", "child": "skipped"}
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return stages in (
            {"parent": "contract_changed", "child": "skipped"},
            {"parent": "success", "child": "contract_changed"},
        )
    return False


def _contract_result(
    app_id: str, date: str, limits: Mapping[str, int]
) -> dict[str, Any]:
    return failure_result(
        app_id=app_id,
        date=date,
        code=ErrorCode.CONTRACT_CHANGED,
        stage="contract",
        scanned_items=0,
        split_id_count=0,
        max_pages=limits["max_pages"],
        max_items=limits["max_items"],
        max_workers=limits["max_workers"],
        parent_stage="contract_changed",
        child_stage="skipped",
    )


def _validated_counts(
    value: Mapping[str, Any], max_items: int
) -> tuple[int, int, int] | None:
    counts = (
        value.get("scanned_items"),
        value.get("split_id_count"),
        value.get("returned_items"),
    )
    if any(type(item) is not int or item < 0 for item in counts):
        return None
    scanned, split_ids, returned = counts
    if scanned > max_items or split_ids > MAX_SPLIT_IDS or returned > split_ids:
        return None
    if scanned + returned > max_items:
        return None
    return scanned, split_ids, returned


def _validated_stages(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping) or set(value) != {"parent", "child"}:
        return None
    if any(
        not isinstance(value.get(name), str)
        or value.get(name) not in _STAGE_STATUSES
        for name in ("parent", "child")
    ):
        return None
    return {"parent": value["parent"], "child": value["child"]}


def _safe_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != set(SAFE_ROW_FIELDS):
        return None
    if any(not finite_json_scalar(value[field]) for field in SAFE_ROW_FIELDS):
        return None
    return {field: copy.deepcopy(value[field]) for field in SAFE_ROW_FIELDS}


def _required_safe_row(value: Any) -> dict[str, Any]:
    selected = _safe_row(value)
    if selected is None:
        raise ValueError("order split trace safe row invariant failed")
    return selected


def _limits(max_pages: Any, max_items: Any, max_workers: Any) -> dict[str, int]:
    return {
        "max_pages": _bounded_integer(max_pages, 1_000, "max_pages"),
        "max_items": _bounded_integer(max_items, 100_000, "max_items"),
        "max_workers": _bounded_integer(max_workers, 24, "max_workers"),
    }


def _stages(parent: str, child: str) -> dict[str, str]:
    if parent not in _STAGE_STATUSES or child not in _STAGE_STATUSES:
        raise ValueError("order split trace stage invariant failed")
    return {"parent": parent, "child": child}


def _bounded_integer(value: Any, maximum: int, field: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{field} is outside the product contract")
    return value


def _bounded_count(value: Any, maximum: int) -> int:
    return value if type(value) is int and 0 <= value <= maximum else 0


def _canonical_app(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("expected_app_id must be a positive integer")
    if type(value) is int and value.bit_length() > 512:
        raise ValueError("expected_app_id must be a positive integer")
    rendered = str(value)
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise ValueError("expected_app_id must be a positive integer")
    return str(int(rendered))


def _canonical_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected_date must use YYYY-MM-DD")
    try:
        parsed = date_type.fromisoformat(value)
    except ValueError:
        raise ValueError("expected_date must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError("expected_date must be canonical")
    return value


def _safe_code(value: ErrorCode | str) -> str:
    candidate = value.value if isinstance(value, ErrorCode) else (
        value.strip().upper() if isinstance(value, str) else ""
    )
    return candidate if candidate in _BUILTIN_CODES else ErrorCode.LOCAL_IO_ERROR.value


def _safe_retry_after(code: str, value: Any) -> int | None:
    if code != ErrorCode.RATE_LIMITED.value:
        return None
    return (
        value
        if type(value) is int and 0 <= value <= _MAX_RECEIPT_INTEGER
        else None
    )


def _native_error(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseException):
        detail = getattr(value, "to_error_detail", None)
        if callable(detail):
            candidate = detail()
            return candidate.to_dict() if isinstance(candidate, ErrorDetail) else {}
        return {}
    if isinstance(value, Mapping):
        nested = value.get("error")
        return nested if isinstance(nested, Mapping) else value
    return {}


def _failure_message(stage: str, code: str) -> str:
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return "Order Split Trace stopped at its aggregate safety bound."
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "Order Split Trace observed an unverified result contract."
    if stage == "child":
        return "Order Split Trace child read failed without exposing identifiers."
    return "Order Split Trace parent read failed without exposing identifiers."


__all__ = [
    "SAFE_ROW_FIELDS",
    "SCHEMA_VERSION",
    "failure_from_native",
    "failure_result",
    "order_split_trace_item_count",
    "sanitize_order_split_trace_result",
    "success_result",
]
