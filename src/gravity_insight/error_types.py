"""SDK request, runtime, mutation, and pagination error types."""

from __future__ import annotations

from typing import Any

from .error_models import ErrorCategory, ErrorCode, GravityInsightError


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


class UpstreamError(GravityInsightError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class SemanticRejectedError(UpstreamError):
    """A deterministic upstream rejection of an authorized request shape."""

    code = ErrorCode.INPUT_INVALID
    category = ErrorCategory.CALLER

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        next_action: str | None = None,
        http_receipts: Any = (),
    ) -> None:
        super().__init__(message, field=field, next_action=next_action)
        if http_receipts:
            from .result_audit import bind_error_receipts

            bind_error_receipts(self, http_receipts)


class UpstreamContradictedRequestError(SemanticRejectedError):
    """Upstream blamed an input the caller demonstrably sent correctly.

    Such a rejection is not deterministic and not the caller's to fix, so it
    stays catchable as a semantic rejection but classifies as retryable
    upstream.  See issue #23.
    """

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    category = ErrorCategory.UPSTREAM
    retryable = True


class ObjectAlreadyExistsError(InputValidationError):
    code = "OBJECT_ALREADY_EXISTS"
    category = ErrorCategory.CALLER


class ObjectReferencedError(InputValidationError):
    code = "OBJECT_REFERENCED"
    category = ErrorCategory.CALLER


class QuotaExceededError(InputValidationError):
    code = "QUOTA_EXCEEDED"
    category = ErrorCategory.CALLER


class ConcurrentModificationError(UpstreamError):
    code = "CONCURRENT_MODIFICATION"
    category = ErrorCategory.UPSTREAM
    retryable = True


class OwnershipMarkerRequiredError(InputValidationError):
    code = "OWNERSHIP_MARKER_REQUIRED"
    category = ErrorCategory.CALLER


class MutationReadbackError(UpstreamError):
    code = "MUTATION_READBACK_FAILED"
    category = ErrorCategory.UPSTREAM
    retryable = True


class PaginationError(GravityInsightError):
    code = ErrorCode.PAGINATION_LIMIT


class PaginationLimitError(PaginationError):
    code = ErrorCode.PAGINATION_LIMIT


class LocalIOError(GravityInsightError, OSError):
    code = ErrorCode.LOCAL_IO_ERROR


for _compat_symbol in (
    ManifestError,
    UnknownOperationError,
    InputValidationError,
    ParentRequiredError,
    PolicyViolation,
    CredentialError,
    AuthMissingError,
    AuthenticationError,
    PermissionUnavailableError,
    TransportError,
    RateLimitedError,
    UpstreamUnavailableError,
    ContractChangedError,
    UnsupportedOperationError,
    OperationNotImplementedError,
    UpstreamError,
    SemanticRejectedError,
    UpstreamContradictedRequestError,
    ObjectAlreadyExistsError,
    ObjectReferencedError,
    QuotaExceededError,
    ConcurrentModificationError,
    OwnershipMarkerRequiredError,
    MutationReadbackError,
    PaginationError,
    PaginationLimitError,
    LocalIOError,
):
    _compat_symbol.__module__ = "gravity_insight.errors"
del _compat_symbol
