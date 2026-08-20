"""Map exceptions and result statuses to stable caller-safe errors."""

from __future__ import annotations

from typing import Any, Mapping

from .error_models import (
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    GravityInsightError,
    is_success_status,
)
from .error_types import PolicyViolation, TransportError


def error_detail_from_exception(
    error: BaseException,
    *,
    operation_id: str | None = None,
    next_action: str | None = None,
) -> ErrorDetail:
    if isinstance(error, GravityInsightError):
        if isinstance(error, TransportError) and "HTTP 429" in str(error).upper():
            return ErrorDetail.create(
                ErrorCode.RATE_LIMITED,
                error,
                operation_id=operation_id,
                field=error.field,
                retry_after_ms=error.retry_after_ms,
                next_action=next_action or error.next_action,
            )
        if isinstance(error, PolicyViolation) and "catalog-only" in str(error):
            return ErrorDetail.create(
                ErrorCode.NOT_IMPLEMENTED,
                error,
                operation_id=operation_id,
                field=error.field,
                next_action=next_action or error.next_action,
            )
        return error.to_error_detail(
            operation_id=operation_id, next_action=next_action
        )
    if isinstance(error, (OSError, UnicodeEncodeError)):
        code = ErrorCode.LOCAL_IO_ERROR
    elif isinstance(error, (ValueError, TypeError, KeyError)):
        code = ErrorCode.INPUT_INVALID
    else:
        code = ErrorCode.LOCAL_IO_ERROR
    return ErrorDetail.create(
        code,
        error,
        operation_id=operation_id,
        next_action=next_action,
    )


def error_envelope(
    error: BaseException,
    *,
    operation_id: str | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    envelope = ErrorEnvelope(
        operation_id=operation_id,
        error=error_detail_from_exception(
            error, operation_id=operation_id, next_action=next_action
        ),
    ).to_dict()
    from .result_audit import add_result_audit, error_receipt_references

    return add_result_audit(envelope, error_receipt_references(error))


def semantic_envelope_ok(value: Mapping[str, Any]) -> bool:
    """Derive semantic success without treating a completed call as a successful read."""

    return is_success_status(value.get("status")) and value.get("ok") is not False


def error_for_status(
    status: Any, *, operation_id: str | None = None
) -> Mapping[str, Any] | None:
    """Return the canonical structured error implied by a failure status."""

    if status != "contract_changed":
        return None
    return ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "The upstream response no longer matches the registered response contract.",
        operation_id=operation_id,
    ).to_dict()


for _compat_symbol in (
    error_detail_from_exception,
    error_envelope,
    error_for_status,
    semantic_envelope_ok,
):
    _compat_symbol.__module__ = "gravity_sdk.errors"
del _compat_symbol
