"""Request-bound result contract for Order Directory v1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from functools import lru_cache
from .composite_catalog import stable_operation
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT
from .result_audit import result_response_drift

from ._order_read import (
    SAFE_ROW_FIELDS,
    canonical_app,
    canonical_date,
    complete_page_receipt,
    exact_dated_safe_row,
)
from ._order_directory_failure import (
    _bounded_drift,
    build_contract_diagnostic as _build_contract_diagnostic,
    sanitize_contract_diagnostic,
    failure_message,
    is_builtin_code,
    native_failure_receipt,
    normalize_code,
    safe_retry_after,
    stage_for_code,
    valid_retry_receipt,
)
from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .result_source import GOVERNED_PRODUCT, result_source
from .contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, EnvelopeObligations,
    ExecutionState, ExecutionStatus, MutationCertainty, MutationState,
    SemanticState, SemanticValidity, diagnostic_evidence, serialize_envelope,
)


SCHEMA_VERSION = "gravity-insight.order-directory.v1"

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
_ERROR_KEYS = frozenset(
    {
        "code",
        "category",
        "message",
        "field",
        "retryable",
        "retry_after_ms",
        "next_action",
    }
)
_SUCCESS_ACTION = "Consume the complete registered physical order rows."
_ACTIONS = {
    "read": "Inspect the safe read category and retry this bounded natural day.",
    "caller": "Correct the rejected App or date input before retrying.",
    "budget": "Increase the bounded page or item limit and retry the same day.",
    "contract": "Stop automation until the Order Directory contract is re-verified.",
}




@lru_cache(maxsize=1)
def _operation_contract() -> tuple[str, str]:
    identity = stable_operation("analysis", "order_detail", action="list").operation_id
    spec = next(
        spec for path in sorted(MANIFEST_ROOT.glob("*.json"))
        for spec in load_operation_manifest(path) if spec.operation_id == identity
    )
    return identity, str(spec.contract_version)


def build_contract_diagnostic(
    layer: str, response_drift: Any, *, product_schema_version: str
) -> dict[str, Any]:
    return _build_contract_diagnostic(
        layer, response_drift, operation_contract=_operation_contract(),
        product_schema_version=product_schema_version,
    )

def native_contract_diagnostic(value: Any, *, product_schema_version: str) -> dict[str, Any]:
    audit = value.get("result_audit") if isinstance(value, Mapping) else None
    raw = audit.get("response_drift") if isinstance(audit, Mapping) else None
    # Bound work before the general audit normalizer can inspect native fields.
    drift = result_response_drift(value) if _bounded_drift(raw) else None
    return build_contract_diagnostic("leaf_projection", drift, product_schema_version=product_schema_version)




def success_result(
    *,
    app_id: str,
    date: str,
    rows: list[Mapping[str, Any]],
    page: Mapping[str, Any],
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    safe_rows = [_required_safe_row(row, date) for row in rows]
    limits = _limits(max_pages, max_items, max_workers)
    receipt = _validated_public_page(
        page, len(safe_rows), limits["max_pages"], limits["max_workers"]
    )
    if receipt is None or len(safe_rows) > limits["max_items"]:
        raise ValueError("order directory success receipt is invalid")
    status = "empty" if not safe_rows else "success"
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "exit_code": 0,
        "app_id": app_id,
        "date": date,
        "returned_items": len(safe_rows),
        "limits": limits,
        "page": receipt,
        "data": {"list": safe_rows},
        "error": None,
        "next_action": _SUCCESS_ACTION,
    }


def failure_result(
    *,
    app_id: str,
    date: str,
    code: ErrorCode | str,
    stage: str,
    max_pages: int,
    max_items: int,
    max_workers: int,
    retry_after_ms: int | None = None,
    contract_diagnostic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_code(code)
    resolved_stage = (
        "caller" if normalized == ErrorCode.INPUT_INVALID.value
        else stage if stage in _ACTIONS else "contract"
    )
    detail = ErrorDetail.create(
        normalized,
        failure_message(normalized),
        field=resolved_stage,
        retry_after_ms=safe_retry_after(normalized, retry_after_ms),
        next_action=_ACTIONS[resolved_stage],
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": (
            "contract_changed"
            if normalized == ErrorCode.CONTRACT_CHANGED.value
            else "error"
        ),
        "exit_code": exit_code_for_error(detail),
        "app_id": app_id,
        "date": date,
        "returned_items": 0,
        "limits": _limits(max_pages, max_items, max_workers),
        "page": None,
        "data": {"list": []},
        "error": detail.to_dict(),
        "next_action": detail.next_action,
    }
    diagnostic = sanitize_contract_diagnostic(
        contract_diagnostic, operation_contract=_operation_contract(),
        product_schema_version=SCHEMA_VERSION,
    )
    if normalized == ErrorCode.CONTRACT_CHANGED.value and diagnostic is not None:
        result["contract_diagnostic"] = diagnostic
    return serialize_envelope(result, _failure_obligations(detail.to_dict()))


def _failure_obligations(error: Mapping[str, Any]) -> EnvelopeObligations:
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.FAILED, "ORDER_DIRECTORY_RESULT_REJECTED"),
        DataCompleteness(CompletenessState.UNKNOWN, "ORDER_DIRECTORY_NO_ACCEPTED_ROWS"),
        SemanticValidity(SemanticState.UNKNOWN, ("ORDER_DIRECTORY_RESULT_REJECTED",)),
        diagnostic_evidence(error),
        MutationCertainty(MutationState.NOT_APPLICABLE, "ORDER_DIRECTORY_READ_ONLY"),
    )


def failure_from_native(
    value: Any,
    *,
    app_id: str,
    date: str,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    code, stage, retry_after = native_failure_receipt(value)
    diagnostic = (
        build_contract_diagnostic("native_read", None, product_schema_version=SCHEMA_VERSION)
        if code == ErrorCode.CONTRACT_CHANGED.value else None
    )
    return failure_result(
        app_id=app_id,
        date=date,
        code=code,
        stage=stage,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
        retry_after_ms=retry_after,
        contract_diagnostic=diagnostic,
    )


def sanitize_order_directory_result(
    value: Any,
    expected_app_id: str | int,
    expected_date: str,
    *,
    max_pages: int,
    max_items: int,
    max_workers: int,
) -> dict[str, Any]:
    """Rebuild a result against request-bound identity, limits, and receipts."""

    app_id = _expected_app(expected_app_id)
    date = _expected_date(expected_date)
    limits = _limits(max_pages, max_items, max_workers)
    if (
        not _valid_result_fields(value)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("app_id") != app_id
        or value.get("date") != date
        or value.get("limits") != limits
    ):
        return _contract_result(app_id, date, limits)
    status = value.get("status")
    if (
        value.get("ok") is True
        and isinstance(status, str)
        and status in {"success", "empty"}
    ):
        return _sanitize_success(value, app_id, date, limits)
    if (
        value.get("ok") is False
        and isinstance(status, str)
        and status in {"error", "contract_changed"}
    ):
        return _sanitize_failure(value, app_id, date, limits)
    return _contract_result(app_id, date, limits)


def _valid_result_fields(value: Any) -> bool:
    if not isinstance(value, Mapping) or not _ENVELOPE_KEYS <= set(value):
        return False
    extra = set(value) - _ENVELOPE_KEYS
    if extra - {"contract_diagnostic", "obligations"}:
        return False
    status = value.get("status")
    if extra and (not isinstance(status, str) or status not in {"error", "contract_changed"}):
        return False
    return "contract_diagnostic" not in extra or value.get("status") == "contract_changed"


def order_directory_item_count(value: Any) -> int:
    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return 0
    status = value.get("status")
    if (
        value.get("ok") is not True
        or not isinstance(status, str)
        or status not in {"success", "empty"}
    ):
        return 0
    rows = _rows(value)
    returned = value.get("returned_items")
    page = value.get("page")
    if (
        rows is None
        or not _valid_count_rows(rows, value.get("date"))
        or type(returned) is not int
        or returned != len(rows)
        or not isinstance(page, Mapping)
        or page.get("item_count") != returned
    ):
        return 0
    return returned


def _sanitize_success(
    value: Mapping[str, Any],
    app_id: str,
    date: str,
    limits: dict[str, int],
) -> dict[str, Any]:
    selected = _validated_success_parts(value, date, limits)
    if selected is None:
        return _contract_result(app_id, date, limits)
    safe_rows, page = selected
    return success_result(
        app_id=app_id,
        date=date,
        rows=safe_rows,
        page=page,
        **limits,
    )


def _validated_success_parts(
    value: Mapping[str, Any], date: str, limits: Mapping[str, int]
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    rows = _rows(value)
    if rows is None:
        return None
    safe_rows = [exact_dated_safe_row(row, date) for row in rows]
    returned = value.get("returned_items")
    expected_status = "empty" if not rows else "success"
    page = _validated_public_page(
        value.get("page"), len(rows), limits["max_pages"], limits["max_workers"]
    )
    if not _valid_success_shape(
        value,
        safe_rows=safe_rows,
        returned=returned,
        row_count=len(rows),
        max_items=limits["max_items"],
        expected_status=expected_status,
        page=page,
    ):
        return None
    return [row for row in safe_rows if row is not None], page


def _valid_success_shape(
    value: Mapping[str, Any],
    *,
    safe_rows: list[dict[str, Any] | None],
    returned: Any,
    row_count: int,
    max_items: int,
    expected_status: str,
    page: Any,
) -> bool:
    return bool(
        all(row is not None for row in safe_rows)
        and type(returned) is int
        and returned == row_count
        and returned <= max_items
        and value.get("status") == expected_status
        and type(value.get("exit_code")) is int
        and value.get("exit_code") == 0
        and value.get("error") is None
        and page is not None
    )


def _sanitize_failure(
    value: Mapping[str, Any],
    app_id: str,
    date: str,
    limits: dict[str, int],
) -> dict[str, Any]:
    selected = _validated_failure_parts(value)
    if selected is None:
        return _contract_result(app_id, date, limits)
    code, stage, retry_after = selected
    rebuilt = failure_result(
        app_id=app_id,
        date=date,
        code=code,
        stage=stage,
        retry_after_ms=retry_after,
        contract_diagnostic=value.get("contract_diagnostic"),
        **limits,
    )
    if "obligations" in value and value["obligations"] != rebuilt["obligations"]:
        return _contract_result(app_id, date, limits)
    return rebuilt


def _validated_failure_parts(
    value: Mapping[str, Any],
) -> tuple[str, str, int | None] | None:
    raw_error = value.get("error")
    if not _valid_failure_shape(value, raw_error):
        return None
    identity = _failure_identity(raw_error)
    if identity is None:
        return None
    code, stage = identity
    expected_status = (
        "contract_changed" if code == ErrorCode.CONTRACT_CHANGED.value else "error"
    )
    retry_after = raw_error.get("retry_after_ms")
    if not valid_retry_receipt(code, retry_after):
        return None
    expected = ErrorDetail.create(
        code,
        failure_message(code),
        field=stage,
        retry_after_ms=retry_after,
        next_action=_ACTIONS[stage],
    )
    if not _valid_failure_receipt(
        value, raw_error, code, stage, expected_status, expected
    ):
        return None
    return code, stage, retry_after


def _valid_failure_shape(value: Mapping[str, Any], error: Any) -> bool:
    returned = value.get("returned_items")
    return bool(
        type(returned) is int
        and returned == 0
        and value.get("page") is None
        and _rows(value) == []
        and isinstance(error, Mapping)
        and set(error) == _ERROR_KEYS
    )


def _failure_identity(error: Mapping[str, Any]) -> tuple[str, str] | None:
    raw_code = error.get("code")
    code = raw_code if isinstance(raw_code, str) else ""
    stage = error.get("field")
    if (
        not is_builtin_code(code)
        or not isinstance(stage, str)
        or stage not in _ACTIONS
    ):
        return None
    return code, stage


def _valid_failure_receipt(
    value: Mapping[str, Any],
    error: Mapping[str, Any],
    code: str,
    stage: str,
    status: str,
    detail: ErrorDetail,
) -> bool:
    expected_stage = stage_for_code(code)
    return bool(
        value.get("status") == status
        and type(value.get("exit_code")) is int
        and value.get("exit_code") == exit_code_for_error(detail)
        and stage == expected_stage
        and error == detail.to_dict()
        and value.get("next_action") == detail.next_action
    )


def _validated_public_page(
    value: Any, count: int, max_pages: int, max_workers: int
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "number",
        "size",
        "item_count",
        "total_pages",
        "total_items",
        "has_more",
        "pages_fetched",
    }:
        return None
    raw = {**value, "max_workers": max_workers}
    return complete_page_receipt(
        raw, count, max_pages=max_pages, max_workers=max_workers
    )


def _rows(value: Mapping[str, Any]) -> list[Any] | None:
    data = value.get("data")
    if not isinstance(data, Mapping) or set(data) != {"list"}:
        return None
    rows = data.get("list")
    return rows if isinstance(rows, list) else None


def _required_safe_row(value: Any, date: str) -> dict[str, Any]:
    row = exact_dated_safe_row(value, date)
    if row is None:
        raise ValueError("order directory row invariant failed")
    return row


def _valid_count_rows(rows: list[Any], value: Any) -> bool:
    try:
        date = canonical_date(value, label="order directory result")
    except ValueError:
        return False
    return all(exact_dated_safe_row(row, date) is not None for row in rows)


def _limits(max_pages: Any, max_items: Any, max_workers: Any) -> dict[str, int]:
    return {
        "max_pages": _bounded_integer(max_pages, 1_000, "max_pages"),
        "max_items": _bounded_integer(max_items, 100_000, "max_items"),
        "max_workers": _bounded_integer(max_workers, 24, "max_workers"),
    }


def _bounded_integer(value: Any, maximum: int, field: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{field} is outside the order directory contract")
    return value


def _expected_app(value: Any) -> str:
    try:
        return canonical_app(value, label="order directory")
    except ValueError:
        raise ValueError("expected_app_id must be a positive integer") from None


def _expected_date(value: Any) -> str:
    try:
        return canonical_date(value, label="order directory")
    except ValueError:
        raise ValueError("expected_date must use YYYY-MM-DD") from None


def _contract_result(
    app_id: str, date: str, limits: Mapping[str, int]
) -> dict[str, Any]:
    return failure_result(
        app_id=app_id,
        date=date,
        code=ErrorCode.CONTRACT_CHANGED,
        stage="contract",
        max_pages=limits["max_pages"],
        max_items=limits["max_items"],
        max_workers=limits["max_workers"],
    )


__all__ = [
    "SAFE_ROW_FIELDS",
    "SCHEMA_VERSION",
    "failure_from_native",
    "failure_result",
    "order_directory_item_count",
    "sanitize_order_directory_result",
    "success_result",
]
