"""Compatibility exports for structured, caller-safe Gravity errors."""

from __future__ import annotations

# These standard-library names were importable from this module before it became
# a facade. Keep them available for strict additive compatibility.
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .error_mapping import (
    error_detail_from_exception,
    error_envelope,
    error_for_status,
    semantic_envelope_ok,
)
from .error_models import (
    SUCCESS_STATUSES,
    _CODE_DEFAULTS,
    _EXTENSION_CODE_RE,
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    GravityInsightError,
    _code_value,
    _default_next_action,
    _input_field,
    _single_line,
    is_success_status,
)
from .error_sql import (
    ExportTimeoutError,
    GravityExportError,
    SqlResponseError,
    SqlValidationError,
)
from .error_types import (
    AuthMissingError,
    AuthenticationError,
    ConcurrentModificationError,
    ContractChangedError,
    CredentialError,
    InputValidationError,
    LocalIOError,
    ManifestError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
    ObjectReferencedError,
    OperationNotImplementedError,
    OwnershipMarkerRequiredError,
    PaginationError,
    PaginationLimitError,
    ParentRequiredError,
    PermissionUnavailableError,
    PolicyViolation,
    QuotaExceededError,
    RateLimitedError,
    SemanticRejectedError,
    TransportError,
    UnknownOperationError,
    UnsupportedOperationError,
    UpstreamContradictedRequestError,
    UpstreamError,
    UpstreamUnavailableError,
)


CALLER_ERROR_EXIT = 2
UPSTREAM_ERROR_EXIT = 3
LOCAL_ERROR_EXIT = 4


def exit_code_for_category(
    category: ErrorCategory | str,
    *,
    default: ErrorCategory | str | None = None,
) -> int:
    """Return the public process exit for one validated error category."""

    normalized = (
        category.value if isinstance(category, ErrorCategory) else str(category)
    )
    exits = {
        ErrorCategory.CALLER.value: CALLER_ERROR_EXIT,
        ErrorCategory.UPSTREAM.value: UPSTREAM_ERROR_EXIT,
        ErrorCategory.LOCAL.value: LOCAL_ERROR_EXIT,
    }
    try:
        return exits[normalized]
    except KeyError as exc:
        if default is not None:
            fallback = default.value if isinstance(default, ErrorCategory) else str(default)
            if fallback in exits:
                return exits[fallback]
        raise ValueError("error category must be caller, upstream, or local") from exc


def exit_code_for_error(error: BaseException | ErrorDetail) -> int:
    detail = (
        error if isinstance(error, ErrorDetail) else error_detail_from_exception(error)
    )
    return exit_code_for_category(detail.category)


def exit_code_for_status(
    status: Any,
    *,
    ok: Any = None,
    error: Mapping[str, Any] | None = None,
    default: ErrorCategory | str = ErrorCategory.LOCAL,
) -> int:
    """Map one envelope status and optional structured error to a process exit."""

    if is_success_status(status) and ok is not False:
        return 0
    if status == "contract_changed":
        return exit_code_for_category(ErrorCategory.UPSTREAM)
    if status in {"invalid", "stale", "needs_parent"}:
        return exit_code_for_category(ErrorCategory.CALLER)
    category = error.get("category") if isinstance(error, Mapping) else default
    return exit_code_for_category(str(category), default=default)
