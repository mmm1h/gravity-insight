"""Controlled error projection for Promotion Performance results."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail


_FAILURE_CODES = {
    "contract_changed": frozenset({ErrorCode.CONTRACT_CHANGED.value}),
    "parent_required": frozenset({ErrorCode.PARENT_REQUIRED.value}),
    "permission_unavailable": frozenset(
        {ErrorCode.PERMISSION_UNAVAILABLE.value}
    ),
    "semantic_error": frozenset({ErrorCode.INPUT_INVALID.value}),
    "unavailable": frozenset(
        {
            ErrorCode.NOT_IMPLEMENTED.value,
            ErrorCode.UNKNOWN_OPERATION.value,
            ErrorCode.UNSUPPORTED.value,
        }
    ),
}
_SPECIAL_FAILURE_CODES = frozenset(
    code
    for status, codes in _FAILURE_CODES.items()
    if status != "semantic_error"
    for code in codes
)
_ERROR_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_CATEGORIES = frozenset(item.value for item in ErrorCategory)
_MAX_RECEIPT_INTEGER = (1 << 31) - 1
_BUILTIN_DEFAULTS = {
    code.value: (
        ErrorDetail.create(code, "default check").category,
        ErrorDetail.create(code, "default check").retryable,
    )
    for code in ErrorCode
}
_SAFE_CODE_DEFAULTS = {
    **_BUILTIN_DEFAULTS,
    "BATCH_RESULT_MISSING": (ErrorCategory.LOCAL.value, False),
}


def safe_batch_error(detail: ErrorDetail) -> ErrorDetail:
    """Map a whole-batch exception to a built-in public error identity."""

    if detail.code in _BUILTIN_DEFAULTS:
        code = detail.code
    else:
        code = {
            ErrorCategory.CALLER.value: ErrorCode.INPUT_INVALID.value,
            ErrorCategory.UPSTREAM.value: ErrorCode.UPSTREAM_UNAVAILABLE.value,
            ErrorCategory.LOCAL.value: ErrorCode.LOCAL_IO_ERROR.value,
        }.get(detail.category, ErrorCode.LOCAL_IO_ERROR.value)
    expected = _BUILTIN_DEFAULTS[code]
    retry_after = (
        detail.retry_after_ms
        if expected[1]
        and type(detail.retry_after_ms) is int
        and 0 <= detail.retry_after_ms <= _MAX_RECEIPT_INTEGER
        else None
    )
    return ErrorDetail.create(
        code,
        "Promotion performance batch read failed.",
        category=expected[0],
        retryable=expected[1],
        retry_after_ms=retry_after,
        next_action="Inspect the controlled Gravity error and retry only when indicated.",
    )


def safe_performance_error(value: Any, platform: str) -> dict[str, Any] | None:
    """Rebuild a batch error without retaining upstream text or identifiers."""

    if not isinstance(value, Mapping):
        return None
    code = value.get("code")
    category = value.get("category")
    if (
        not isinstance(code, str)
        or code not in _SAFE_CODE_DEFAULTS
        or not isinstance(category, str)
        or category not in _CATEGORIES
        or category != _SAFE_CODE_DEFAULTS[code][0]
    ):
        return None
    field = value.get("field")
    if field is not None and (
        not isinstance(field, str) or not _ERROR_FIELD.fullmatch(field)
    ):
        return None
    retryable = value.get("retryable", False)
    retry_after = value.get("retry_after_ms")
    if not _valid_retry_receipt(code, retryable, retry_after):
        return None
    return {
        "code": code,
        "category": category,
        "message": f"Promotion performance query failed for {platform}.",
        "field": "result" if field is not None else None,
        "retryable": retryable,
        "retry_after_ms": retry_after,
        "next_action": _failure_action(code, category),
    }


def failure_matches(status: str, code: str) -> bool:
    expected = _FAILURE_CODES.get(status)
    if expected is not None:
        return code in expected
    return code not in _SPECIAL_FAILURE_CODES


def error_exit_code(error: Mapping[str, Any]) -> int:
    return {
        ErrorCategory.CALLER.value: 2,
        ErrorCategory.UPSTREAM.value: 3,
        ErrorCategory.LOCAL.value: 4,
    }.get(str(error.get("category")), 4)


def _valid_retry_receipt(code: str, retryable: Any, retry_after: Any) -> bool:
    if not isinstance(retryable, bool):
        return False
    default = _SAFE_CODE_DEFAULTS.get(code)
    if default is None or retryable is not default[1]:
        return False
    if retry_after is None:
        return True
    return bool(
        retryable
        and type(retry_after) is int
        and 0 <= retry_after <= _MAX_RECEIPT_INTEGER
    )


def _failure_action(code: str, category: str) -> str:
    if code == ErrorCode.CONTRACT_CHANGED.value:
        return "Stop this Plan until the promotion performance contract is re-verified."
    if code in {ErrorCode.AUTH_MISSING.value, ErrorCode.AUTH_REJECTED.value}:
        return "Run `gravity auth status`, then retry the same platform query."
    if category == ErrorCategory.CALLER.value:
        return "Correct the selected App, dates, platforms, or metrics and retry."
    return "Retry only the failed platform; do not replay successful siblings."


__all__ = [
    "error_exit_code",
    "failure_matches",
    "safe_batch_error",
    "safe_performance_error",
]
