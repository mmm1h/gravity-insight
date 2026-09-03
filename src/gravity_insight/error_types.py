"""SDK request, runtime, mutation, and pagination error types."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .error_models import ErrorCategory, ErrorCode, ErrorDetail, GravityInsightError


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

    @classmethod
    @contextmanager
    def after_dispatch(
        cls, acknowledgement: Any, marker: str | None = None
    ) -> Iterator[None]:
        try:
            yield
        except cls as error:
            if error.write_sent:
                raise
            raise cls(
                str(error),
                field=error.field,
                retry_after_ms=error.retry_after_ms,
                next_action=error.next_action,
                code=error.code,
                write_sent=True,
                acknowledgement=acknowledgement,
                marker=marker or error.marker,
            ) from error

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        retry_after_ms: int | None = None,
        next_action: str | None = None,
        code: ErrorCode | str | None = None,
        write_sent: bool = False,
        acknowledgement: Any = None,
        marker: str | None = None,
    ) -> None:
        if write_sent:
            next_action = self._post_dispatch_next_action(next_action)
        super().__init__(
            message,
            field=field,
            retry_after_ms=retry_after_ms,
            next_action=next_action,
            code=code,
        )
        self.write_sent = write_sent
        self.acknowledgement = acknowledgement
        self.marker = marker
        self.automatic_retry = False if write_sent else None
        if write_sent:
            self.retryable = False

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
            next_action=(
                self._post_dispatch_next_action(next_action)
                if next_action and self.write_sent
                else next_action or self.next_action
            ),
            write_sent=self.write_sent if self.write_sent else None,
            acknowledgement=self.acknowledgement,
            marker=self.marker,
            automatic_retry=self.automatic_retry,
        )

    @staticmethod
    def _post_dispatch_next_action(next_action: str | None) -> str:
        recovery = next_action or (
            "Read the affected resource and recover it by the reported marker or exact identifier."
        )
        if "do not retry" in recovery.casefold():
            return recovery
        return f"Do not retry this mutation. {recovery}"


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
