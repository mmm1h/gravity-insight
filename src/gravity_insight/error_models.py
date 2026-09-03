"""Stable error models and normalization for Gravity Insight surfaces."""

from __future__ import annotations

import re
from collections.abc import Mapping
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


SUCCESS_STATUSES = frozenset({"success", "empty", "contract_changed_additive"})

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


def is_success_status(status: Any) -> bool:
    """Return whether an envelope status represents semantic success."""

    return isinstance(status, str) and status in SUCCESS_STATUSES


def _single_line(message: Any, *, limit: int = 500) -> str:
    rendered = " ".join(str(message).splitlines()).strip()
    return (rendered or "Gravity Insight operation failed")[:limit]


def _safe_acknowledgement(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("acknowledgement must be an object")
    result: dict[str, Any] = {"received": True}
    operation = value.get("operation_id")
    status = value.get("status")
    attempts = value.get("attempts")
    if isinstance(operation, str) and operation.strip():
        result["operation_id"] = _single_line(operation, limit=128)
    if isinstance(status, str) and status.strip():
        result["status"] = _single_line(status, limit=64)
    if type(attempts) is int and attempts >= 0:
        result["attempts"] = attempts
    return result


def _optional_boolean(value: Any, field: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


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
            "username and password, or place them in the ignored "
            "`.env.gravity.local` and run `gravity insight auth refresh`."
        ),
        ErrorCode.AUTH_REJECTED.value: (
            "Run `gravity insight auth refresh`, then retry once."
        ),
        ErrorCode.PERMISSION_UNAVAILABLE.value: (
            f"actual value: authenticated account lacks {operation}; "
            "allowed next action: request that Gravity capability from the "
            "workspace owner, then retry with the same input."
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
        "OBJECT_ALREADY_EXISTS": (
            "Choose a different object name, or reuse the existing SDK-owned object."
        ),
        "OBJECT_REFERENCED": (
            "Remove the reported references, then retry the delete once."
        ),
        "QUOTA_EXCEEDED": (
            "Remove an unused SDK-owned object or ask the workspace owner to raise the quota."
        ),
        "CONCURRENT_MODIFICATION": (
            "Read the object again, review the new state, then issue a new explicit write."
        ),
        "OWNERSHIP_MARKER_REQUIRED": (
            "Do not retry through the SDK; manage this unmarked object in Gravity Web with its owner."
        ),
        "OWNERSHIP_REQUIRED": (
            "Choose an SDK-marked object or one whose upstream owner matches the current gravity_id."
        ),
        "MUTATION_READBACK_FAILED": (
            "Read the target by its exact identifier before deciding whether to issue another write."
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
    write_sent: bool | None = None
    acknowledgement: dict[str, Any] | None = None
    marker: str | None = None
    automatic_retry: bool | None = None

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
        write_sent: bool | None = None,
        acknowledgement: Mapping[str, Any] | None = None,
        marker: str | None = None,
        automatic_retry: bool | None = None,
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
        normalized_acknowledgement = _safe_acknowledgement(acknowledgement)
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
            write_sent=_optional_boolean(write_sent, "write_sent"),
            acknowledgement=normalized_acknowledgement,
            marker=_single_line(marker, limit=64) if marker else None,
            automatic_retry=_optional_boolean(automatic_retry, "automatic_retry"),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "field": self.field,
            "retryable": self.retryable,
            "retry_after_ms": self.retry_after_ms,
            "next_action": self.next_action,
        }
        if self.write_sent is not None:
            result["write_sent"] = self.write_sent
        if self.acknowledgement is not None:
            result["acknowledgement"] = dict(self.acknowledgement)
        if self.marker is not None:
            result["marker"] = self.marker
        if self.automatic_retry is not None:
            result["automatic_retry"] = self.automatic_retry
        return result


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
    retryable: bool | None = None

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
            retryable=self.retryable,
            retry_after_ms=self.retry_after_ms,
            next_action=next_action or self.next_action,
        )


for _compat_symbol in (
    ErrorCode,
    ErrorCategory,
    ErrorDetail,
    ErrorEnvelope,
    GravityInsightError,
    _code_value,
    _default_next_action,
    _input_field,
    _single_line,
    is_success_status,
):
    _compat_symbol.__module__ = "gravity_insight.errors"
del _compat_symbol
