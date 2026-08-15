"""Structured, caller-safe errors for Gravity Insight surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable built-in codes; ``ErrorDetail`` also accepts extension codes."""

    UNKNOWN_OPERATION = "UNKNOWN_OPERATION"
    INPUT_INVALID = "INPUT_INVALID"
    PARENT_REQUIRED = "PARENT_REQUIRED"
    AUTH_MISSING = "AUTH_MISSING"
    AUTH_REJECTED = "AUTH_REJECTED"
    PERMISSION_UNAVAILABLE = "PERMISSION_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    CONTRACT_CHANGED = "CONTRACT_CHANGED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    PAGINATION_LIMIT = "PAGINATION_LIMIT"
    EXPORT_TIMEOUT = "EXPORT_TIMEOUT"
    LOCAL_IO_ERROR = "LOCAL_IO_ERROR"


class ErrorCategory(str, Enum):
    CALLER = "caller"
    UPSTREAM = "upstream"
    LOCAL = "local"


CALLER_ERROR_EXIT = 2
UPSTREAM_ERROR_EXIT = 3
LOCAL_ERROR_EXIT = 4

_EXTENSION_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_CODE_DEFAULTS: dict[str, tuple[ErrorCategory, bool]] = {
    ErrorCode.UNKNOWN_OPERATION.value: (ErrorCategory.CALLER, False),
    ErrorCode.INPUT_INVALID.value: (ErrorCategory.CALLER, False),
    ErrorCode.PARENT_REQUIRED.value: (ErrorCategory.CALLER, False),
    ErrorCode.AUTH_MISSING.value: (ErrorCategory.CALLER, False),
    ErrorCode.AUTH_REJECTED.value: (ErrorCategory.CALLER, False),
    ErrorCode.PERMISSION_UNAVAILABLE.value: (ErrorCategory.UPSTREAM, False),
    ErrorCode.RATE_LIMITED.value: (ErrorCategory.UPSTREAM, True),
    ErrorCode.UPSTREAM_UNAVAILABLE.value: (ErrorCategory.UPSTREAM, True),
    ErrorCode.CONTRACT_CHANGED.value: (ErrorCategory.UPSTREAM, False),
    ErrorCode.UNSUPPORTED.value: (ErrorCategory.LOCAL, False),
    ErrorCode.NOT_IMPLEMENTED.value: (ErrorCategory.LOCAL, False),
    ErrorCode.PAGINATION_LIMIT.value: (ErrorCategory.CALLER, False),
    ErrorCode.EXPORT_TIMEOUT.value: (ErrorCategory.UPSTREAM, True),
    ErrorCode.LOCAL_IO_ERROR.value: (ErrorCategory.LOCAL, False),
}


def _code_value(code: ErrorCode | str) -> str:
    value = code.value if isinstance(code, ErrorCode) else str(code).strip().upper()
    if not _EXTENSION_CODE_RE.fullmatch(value):
        raise ValueError("error code must be an uppercase extension identifier")
    return value


def _single_line(message: Any, *, limit: int = 500) -> str:
    rendered = " ".join(str(message).splitlines()).strip()
    return (rendered or "Gravity Insight operation failed")[:limit]


def _input_field(message: str) -> str | None:
    patterns = (
        r"argument --([a-z][a-z0-9-]*)\b",
        r"input ['\"]([a-z][a-z0-9_.-]*)['\"]",
        r"(?:required|path) input:\s*([a-z][a-z0-9_.-]*)\b",
        r"unknown operation input fields:\s*([a-z][a-z0-9_.-]*)\b",
        r"^([a-z][a-z0-9_]*)\s+(?:must|has|is|exceeds|contains)\b",
    )
    lowered = message.casefold()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).replace("-", "_")
    if "requested page size" in lowered:
        return "page_size"
    if "input" in lowered or "json" in lowered:
        return "input"
    return None


def _default_next_action(code: str, operation_id: str | None) -> str:
    operation = operation_id or "<operation-id>"
    describe = (
        "Run `gravity insight operations describe "
        f"{operation}` and retry with the documented input."
    )
    actions = {
        ErrorCode.UNKNOWN_OPERATION.value: (
            "Run `gravity insight operations search <query>` "
            "and use an operation_id from the results."
        ),
        ErrorCode.INPUT_INVALID.value: describe,
        ErrorCode.PARENT_REQUIRED.value: describe,
        ErrorCode.AUTH_MISSING.value: (
            "Run `gravity` in an interactive terminal to configure the Gravity "
            "username and password."
        ),
        ErrorCode.AUTH_REJECTED.value: (
            "Run `gravity insight auth refresh`, then retry once."
        ),
        ErrorCode.PERMISSION_UNAVAILABLE.value: (
            f"Run `gravity insight operations describe {operation}` "
            "and request the listed Gravity permission before retrying."
        ),
        ErrorCode.RATE_LIMITED.value: "Wait retry_after_ms, then retry the same request once.",
        ErrorCode.UPSTREAM_UNAVAILABLE.value: (
            "Retry the same request once; if it fails again, run "
            "`gravity doctor --live`."
        ),
        ErrorCode.CONTRACT_CHANGED.value: (
            f"Run `gravity insight operations describe {operation}` "
            "and stop automation until the contract is re-verified."
        ),
        ErrorCode.UNSUPPORTED.value: describe,
        ErrorCode.NOT_IMPLEMENTED.value: (
            "Run `gravity insight operations search <query>` "
            "and select an executable operation."
        ),
        ErrorCode.PAGINATION_LIMIT.value: (
            "Retry with `--output <path>` or `--format ndjson`; use next_page_input "
            "to continue from the reported page."
        ),
        ErrorCode.EXPORT_TIMEOUT.value: (
            "Resume the export with its status operation; do not start a duplicate export."
        ),
        ErrorCode.LOCAL_IO_ERROR.value: (
            "Check local console and filesystem I/O, then retry the same request."
        ),
    }
    return actions.get(code, describe)


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    category: str
    message: str
    field: str | None = None
    retryable: bool = False
    retry_after_ms: int | None = None
    next_action: str = ""

    @classmethod
    def create(
        cls,
        code: ErrorCode | str,
        message: Any,
        *,
        operation_id: str | None = None,
        category: ErrorCategory | str | None = None,
        field: str | None = None,
        retryable: bool | None = None,
        retry_after_ms: int | None = None,
        next_action: str | None = None,
    ) -> "ErrorDetail":
        normalized_code = _code_value(code)
        normalized_message = _single_line(message)
        default_category, default_retryable = _CODE_DEFAULTS.get(
            normalized_code, (ErrorCategory.LOCAL, False)
        )
        normalized_category = (
            category.value if isinstance(category, ErrorCategory) else str(category)
            if category is not None
            else default_category.value
        )
        if normalized_category not in {item.value for item in ErrorCategory}:
            raise ValueError("error category must be caller, upstream, or local")
        normalized_retry_after = retry_after_ms
        if normalized_retry_after is not None:
            if (
                isinstance(normalized_retry_after, bool)
                or not isinstance(normalized_retry_after, int)
                or normalized_retry_after < 0
            ):
                raise ValueError("retry_after_ms must be a non-negative integer")
        return cls(
            code=normalized_code,
            category=normalized_category,
            message=normalized_message,
            field=(
                _single_line(field, limit=128)
                if field
                else _input_field(normalized_message)
                if normalized_code == ErrorCode.INPUT_INVALID.value
                else None
            ),
            retryable=default_retryable if retryable is None else bool(retryable),
            retry_after_ms=normalized_retry_after,
            next_action=_single_line(
                next_action or _default_next_action(normalized_code, operation_id),
                limit=500,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "field": self.field,
            "retryable": self.retryable,
            "retry_after_ms": self.retry_after_ms,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class ErrorEnvelope:
    operation_id: str | None
    error: ErrorDetail
    schema_version: str = "gravity-insight.error.v1"
    ok: bool = False
    status: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "status": self.status,
            "operation_id": self.operation_id,
            "error": self.error.to_dict(),
        }


class GravityInsightError(RuntimeError):
    """Base class for structured errors that are safe to show to callers."""

    code: ErrorCode | str = ErrorCode.UPSTREAM_UNAVAILABLE
    category: ErrorCategory | str | None = None

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        retry_after_ms: int | None = None,
        next_action: str | None = None,
        code: ErrorCode | str | None = None,
    ) -> None:
        super().__init__(_single_line(message))
        self.field = field
        self.retry_after_ms = retry_after_ms
        self.next_action = next_action
        if code is not None:
            self.code = code

    def to_error_detail(
        self,
        *,
        operation_id: str | None = None,
        next_action: str | None = None,
    ) -> ErrorDetail:
        return ErrorDetail.create(
            self.code,
            str(self),
            operation_id=operation_id,
            category=self.category,
            field=self.field,
            retry_after_ms=self.retry_after_ms,
            next_action=next_action or self.next_action,
        )


class ManifestError(GravityInsightError, ValueError):
    code = ErrorCode.CONTRACT_CHANGED


class UnknownOperationError(GravityInsightError, LookupError):
    code = ErrorCode.UNKNOWN_OPERATION


class InputValidationError(GravityInsightError, ValueError):
    code = ErrorCode.INPUT_INVALID


class ParentRequiredError(InputValidationError):
    code = ErrorCode.PARENT_REQUIRED


class PolicyViolation(GravityInsightError, PermissionError):
    code = ErrorCode.UNSUPPORTED
    category = ErrorCategory.LOCAL


class CredentialError(GravityInsightError):
    code = ErrorCode.AUTH_MISSING


class AuthMissingError(CredentialError):
    code = ErrorCode.AUTH_MISSING


class AuthenticationError(CredentialError):
    code = ErrorCode.AUTH_REJECTED


class PermissionUnavailableError(GravityInsightError, PermissionError):
    code = ErrorCode.PERMISSION_UNAVAILABLE


class TransportError(GravityInsightError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class RateLimitedError(TransportError):
    code = ErrorCode.RATE_LIMITED


class UpstreamUnavailableError(TransportError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class ContractChangedError(GravityInsightError):
    code = ErrorCode.CONTRACT_CHANGED


class UnsupportedOperationError(PolicyViolation):
    code = ErrorCode.UNSUPPORTED


class OperationNotImplementedError(PolicyViolation):
    code = ErrorCode.NOT_IMPLEMENTED


class SqlValidationError(InputValidationError):
    """A SQL request is malformed or exceeds a local safety bound."""


class SqlResponseError(GravityInsightError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class GravityExportError(GravityInsightError):
    code = ErrorCode.EXPORT_TIMEOUT


class ExportTimeoutError(GravityExportError):
    code = ErrorCode.EXPORT_TIMEOUT


class UpstreamError(GravityInsightError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class PaginationError(GravityInsightError):
    code = ErrorCode.PAGINATION_LIMIT


class PaginationLimitError(PaginationError):
    code = ErrorCode.PAGINATION_LIMIT


class LocalIOError(GravityInsightError, OSError):
    code = ErrorCode.LOCAL_IO_ERROR


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
    return ErrorEnvelope(
        operation_id=operation_id,
        error=error_detail_from_exception(
            error, operation_id=operation_id, next_action=next_action
        ),
    ).to_dict()


def exit_code_for_error(error: BaseException | ErrorDetail) -> int:
    detail = (
        error if isinstance(error, ErrorDetail) else error_detail_from_exception(error)
    )
    return {
        ErrorCategory.CALLER.value: CALLER_ERROR_EXIT,
        ErrorCategory.UPSTREAM.value: UPSTREAM_ERROR_EXIT,
        ErrorCategory.LOCAL.value: LOCAL_ERROR_EXIT,
    }[detail.category]
