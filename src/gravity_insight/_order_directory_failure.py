"""Private fixed failure policy for the Order Directory result contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ErrorCode, ErrorDetail
from .response_drift import normalize_response_drift


_BUILTIN_CODES = frozenset(item.value for item in ErrorCode)
_FAILURE_STATUSES = frozenset(
    {"error", "semantic_error", "unavailable", "parent_required", "permission_unavailable"}
)
_STATUS_CODES = {
    "contract_changed": ErrorCode.CONTRACT_CHANGED.value,
    "contract_changed_additive": ErrorCode.CONTRACT_CHANGED.value,
    "parent_required": ErrorCode.PARENT_REQUIRED.value,
    "permission_unavailable": ErrorCode.PERMISSION_UNAVAILABLE.value,
    "semantic_error": ErrorCode.INPUT_INVALID.value,
}
_SPECIAL_STATUS_CODES = {
    "parent_required": frozenset({ErrorCode.PARENT_REQUIRED.value}),
    "permission_unavailable": frozenset({ErrorCode.PERMISSION_UNAVAILABLE.value}),
    "semantic_error": frozenset({ErrorCode.INPUT_INVALID.value}),
    "unavailable": frozenset(
        {ErrorCode.NOT_IMPLEMENTED.value, ErrorCode.UNKNOWN_OPERATION.value,
         ErrorCode.UNSUPPORTED.value}
    ),
}
_SPECIAL_CODES = frozenset(code for codes in _SPECIAL_STATUS_CODES.values() for code in codes)
_MAX_RECEIPT_INTEGER = (1 << 31) - 1


_DIAGNOSTIC_SCHEMA = "gravity.order-directory-diagnostic.v1"
_DIAGNOSTIC_REASONS = {
    "native_read": "ORDER_DIRECTORY_NATIVE_READ_REJECTED",
    "leaf_projection": "ORDER_DIRECTORY_LEAF_PROJECTION_REJECTED",
    "envelope": "ORDER_DIRECTORY_ENVELOPE_REJECTED",
    "row": "ORDER_DIRECTORY_ROW_PROJECTION_REJECTED",
    "pagination": "ORDER_DIRECTORY_PAGINATION_UNVERIFIED",
}
_DIAGNOSTIC_KEYS = frozenset({
    "schema_version", "layer", "reason_code", "operation_id",
    "operation_contract_version", "product_schema_version",
    "field_evidence", "response_drift",
})
_DIAGNOSTIC_PATHS = frozenset({
    "", "/schema_version", "/operation_id", "/status", "/ok", "/error",
    "/truncated", "/next_page_input", "/data", "/data/list",
    "/data/list/*", "/page", "/data/page_info",
    *(f"/data/list/*/{field}" for field in ("CreateTime", "Amount", "BackAmount", "Status")),
    *(f"/data/page_info/{field}" for field in ("page", "page_size", "total_page", "total_number")),
})



def build_contract_diagnostic(
    layer: str, response_drift: Any, *, operation_contract: tuple[str, str], product_schema_version: str
) -> dict[str, Any]:
    identity, version = operation_contract
    drift = _safe_diagnostic_drift(response_drift)
    return {
        "schema_version": _DIAGNOSTIC_SCHEMA,
        "layer": layer,
        "reason_code": _DIAGNOSTIC_REASONS[layer],
        "operation_id": identity,
        "operation_contract_version": version,
        "product_schema_version": product_schema_version,
        "field_evidence": "observed" if drift is not None else "unavailable",
        "response_drift": drift,
    }



def sanitize_contract_diagnostic(value: Any, *, operation_contract: tuple[str, str], product_schema_version: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _DIAGNOSTIC_KEYS:
        return None
    layer = value.get("layer")
    if not isinstance(layer, str) or layer not in _DIAGNOSTIC_REASONS:
        return None
    expected = build_contract_diagnostic(layer, value.get("response_drift"), operation_contract=operation_contract, product_schema_version=product_schema_version)
    return expected if value == expected else None





def _bounded_drift(value: Any) -> bool:
    return bool(isinstance(value, Mapping) and isinstance(value.get("fields"), list) and 0 < len(value["fields"]) <= 8)


def _safe_diagnostic_drift(value: Any) -> dict[str, Any] | None:
    if not _bounded_drift(value):
        return None
    try:
        normalized = normalize_response_drift(value)
    except ValueError:
        return None
    fields = [
        {key: item[key] for key in ("classification", "path", "expected_type", "observed_type") if key in item}
        for item in normalized["fields"] if item["path"] in _DIAGNOSTIC_PATHS
    ]
    if not fields:
        return None
    breaking = any(item.get("classification") == "breaking" for item in fields)
    if not breaking:
        fields = [{"path": item["path"], "observed_type": item["observed_type"]} for item in fields]
    return normalize_response_drift({
        "schema_version": "gravity.response-drift.v2" if breaking else "gravity.response-drift.v1",
        "direction": "response", "classification": "breaking" if breaking else "additive",
        "fields": fields,
    })


def native_failure_receipt(value: Any) -> tuple[str, str, int | None]:
    raw = _native_error(value)
    raw_code = raw.get("code")
    candidate = raw_code.strip().upper() if isinstance(raw_code, str) else ""
    raw_status = value.get("status") if isinstance(value, Mapping) else None
    code = candidate if candidate in _BUILTIN_CODES else _fallback_code(
        value, raw_status, candidate
    )
    if isinstance(raw_status, str) and not _failure_matches(raw_status, code):
        code = ErrorCode.CONTRACT_CHANGED.value
    retry_after = raw.get("retry_after_ms")
    if not valid_retry_receipt(code, retry_after):
        return ErrorCode.CONTRACT_CHANGED.value, "contract", None
    return code, stage_for_code(code), retry_after if type(retry_after) is int else None


def normalize_code(value: ErrorCode | str) -> str:
    candidate = (value.value if isinstance(value, ErrorCode) else
                 value.strip().upper() if isinstance(value, str) else "")
    return candidate if candidate in _BUILTIN_CODES else ErrorCode.LOCAL_IO_ERROR.value


def is_builtin_code(value: str) -> bool:
    return value in _BUILTIN_CODES


def safe_retry_after(code: str, value: Any) -> int | None:
    if code != ErrorCode.RATE_LIMITED.value:
        return None
    return value if valid_retry_receipt(code, value) else None


def valid_retry_receipt(code: str, value: Any) -> bool:
    if value is None:
        return True
    return bool(code == ErrorCode.RATE_LIMITED.value and type(value) is int
                and 0 <= value <= _MAX_RECEIPT_INTEGER)


def stage_for_code(code: str) -> str:
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return "budget"
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "contract"
    return "read"


def failure_message(code: str) -> str:
    if code == ErrorCode.PAGINATION_LIMIT.value:
        return "Order Directory stopped at its complete-read safety bound."
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "Order Directory observed an unverified result contract."
    return "Order Directory read failed without exposing order identifiers."


def _fallback_code(value: Any, status: Any, candidate: str) -> str:
    if isinstance(value, BaseException) and not candidate:
        return ErrorCode.LOCAL_IO_ERROR.value
    if isinstance(status, str):
        return _STATUS_CODES.get(status, ErrorCode.UPSTREAM_UNAVAILABLE.value)
    return ErrorCode.UPSTREAM_UNAVAILABLE.value


def _native_error(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BaseException):
        try:
            detail = getattr(value, "to_error_detail", None)
            if callable(detail):
                candidate = detail()
                return candidate.to_dict() if isinstance(candidate, ErrorDetail) else {}
        except BaseException:
            return {}
        return {}
    if isinstance(value, Mapping):
        nested = value.get("error")
        return nested if isinstance(nested, Mapping) else value
    return {}


def _failure_matches(status: str, code: str) -> bool:
    expected = _SPECIAL_STATUS_CODES.get(status)
    if expected is not None:
        return code in expected
    if status in _FAILURE_STATUSES:
        return code not in _SPECIAL_CODES
    return status in {"contract_changed", "contract_changed_additive"} and (
        code == ErrorCode.CONTRACT_CHANGED.value
    )


__all__ = ["failure_message", "is_builtin_code", "native_failure_receipt",
           "normalize_code", "safe_retry_after", "stage_for_code",
           "valid_retry_receipt"]
