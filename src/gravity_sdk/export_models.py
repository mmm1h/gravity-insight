"""Export protocol values, state vocabulary, and policy predicates."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .blob import AuthorizedBlobSource, BlobReceipt, BlobTransferError

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_NON_EXPORTABLE_CLASSIFICATIONS = frozenset({"restricted"})

class ExportState(str, Enum):
    CREATING = "CREATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    READY = "READY"
    DOWNLOADING = "DOWNLOADING"
    VERIFIED = "VERIFIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class ExportCompletionStatus(str, Enum):
    """Machine-decidable completeness of the requested export file journey."""

    EMPTY = "empty"
    PARTIAL = "partial"
    TRUNCATED = "truncated"
    EXPIRED = "expired"
    COMPLETE = "complete"
    GAP = "gap"


_TERMINAL_STATES = frozenset(
    {
        ExportState.COMMITTED,
        ExportState.FAILED,
        ExportState.TIMED_OUT,
        ExportState.CANCELLED,
    }
)
_POLLABLE_STATES = frozenset(
    {ExportState.QUEUED, ExportState.RUNNING, ExportState.CANCEL_REQUESTED}
)
_TRANSITIONS: Mapping[ExportState, frozenset[ExportState]] = {
    ExportState.CREATING: frozenset(
        {
            ExportState.QUEUED,
            ExportState.RUNNING,
            ExportState.READY,
            ExportState.FAILED,
            ExportState.TIMED_OUT,
            ExportState.CANCEL_REQUESTED,
            ExportState.CANCELLED,
        }
    ),
    ExportState.QUEUED: frozenset(
        {
            ExportState.RUNNING,
            ExportState.READY,
            ExportState.FAILED,
            ExportState.TIMED_OUT,
            ExportState.CANCEL_REQUESTED,
            ExportState.CANCELLED,
        }
    ),
    ExportState.RUNNING: frozenset(
        {
            ExportState.READY,
            ExportState.FAILED,
            ExportState.TIMED_OUT,
            ExportState.CANCEL_REQUESTED,
            ExportState.CANCELLED,
        }
    ),
    ExportState.READY: frozenset(
        {ExportState.DOWNLOADING, ExportState.FAILED, ExportState.TIMED_OUT}
    ),
    ExportState.DOWNLOADING: frozenset({ExportState.VERIFIED, ExportState.FAILED}),
    ExportState.VERIFIED: frozenset({ExportState.COMMITTED, ExportState.FAILED}),
    ExportState.CANCEL_REQUESTED: frozenset(
        {
            ExportState.QUEUED,
            ExportState.RUNNING,
            ExportState.READY,
            ExportState.FAILED,
            ExportState.TIMED_OUT,
            ExportState.CANCELLED,
        }
    ),
    ExportState.COMMITTED: frozenset(),
    ExportState.FAILED: frozenset(),
    ExportState.TIMED_OUT: frozenset(),
    ExportState.CANCELLED: frozenset(),
}


class ExportRuntimeError(BlobTransferError):
    """Structured Export SDK failure using the blob core error contract."""


@dataclass(frozen=True)
class ExportPrivacyContract:
    allowed_columns: tuple[str, ...]
    required_columns: tuple[str, ...]
    redact_fields: tuple[str, ...] = ()
    format: str = "csv"
    classification: str = "aggregate"
    allow_contracted_identifiers: bool = False
    encoding: str = "utf-8"
    delimiter: str = ","

    def __post_init__(self) -> None:
        if not self.allowed_columns:
            raise ValueError("export privacy contract requires allowed columns")
        if len(set(self.allowed_columns)) != len(self.allowed_columns):
            raise ValueError("export allowed columns cannot contain duplicates")
        if len(set(self.required_columns)) != len(self.required_columns):
            raise ValueError("export required columns cannot contain duplicates")
        if not set(self.required_columns).issubset(self.allowed_columns):
            raise ValueError("required export columns must be allowed")
        if any(not column or not isinstance(column, str) for column in self.allowed_columns):
            raise ValueError("export columns must be non-empty strings")
        if self.format not in {"csv", "jsonl", "xlsx"}:
            raise ValueError("only csv, jsonl, and xlsx finalizers are implemented")
        if len(self.delimiter) != 1:
            raise ValueError("CSV delimiter must be one character")
        if not self.classification.strip():
            raise ValueError("export classification cannot be empty")

    @property
    def contracted_identifiers_allowed(self) -> bool:
        return (
            self.allow_contracted_identifiers
            or self.classification.casefold() == "user_level"
        )


@dataclass(frozen=True)
class ExportCreationRequest:
    payload: Mapping[str, Any]
    requested_columns: tuple[str, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class ExportJobSnapshot:
    job_id: str
    state: ExportState | str
    download_source: AuthorizedBlobSource | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    failure_retryable: bool = False


class AuthorizedExportGateway(Protocol):
    """Stage-authorized adapter; each method must consume its own receipt."""

    supports_cancel: bool

    def create(
        self,
        request: ExportCreationRequest,
        *,
        timeout_seconds: float,
    ) -> ExportJobSnapshot: ...

    def status(self, job_id: str, *, timeout_seconds: float) -> ExportJobSnapshot: ...

    def cancel(self, job_id: str, *, timeout_seconds: float) -> ExportJobSnapshot: ...


@dataclass(frozen=True)
class ExportPollingPolicy:
    timeout_seconds: float = 600.0
    initial_interval_seconds: float = 1.0
    multiplier: float = 2.0
    max_interval_seconds: float = 30.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("export timeout must be positive")
        if self.initial_interval_seconds <= 0:
            raise ValueError("initial poll interval must be positive")
        if self.multiplier < 1:
            raise ValueError("poll multiplier cannot be below one")
        if self.max_interval_seconds < self.initial_interval_seconds:
            raise ValueError("max poll interval cannot be below the initial interval")
        if not 0 <= self.jitter_ratio < 1:
            raise ValueError("poll jitter ratio must be in [0, 1)")


@dataclass(frozen=True)
class ExportResult:
    state: ExportState
    job_id: str | None
    history: tuple[ExportState, ...]
    receipt: BlobReceipt | None = None
    error: BlobTransferError | None = None
    resumable: bool = False
def _validate_creation_request(
    request: ExportCreationRequest,
    contract: ExportPrivacyContract,
) -> None:
    _assert_exportable_classification(contract)
    if not _IDEMPOTENCY_KEY.fullmatch(request.idempotency_key):
        raise _export_error(
            "export creation requires a caller-generated idempotency key",
            code="EXPORT_IDEMPOTENCY_KEY_INVALID",
            stage="creating",
        )
    if not request.requested_columns:
        raise _export_error(
            "export creation requires an explicit column projection",
            code="EXPORT_COLUMNS_INVALID",
            stage="creating",
        )
    requested = set(request.requested_columns)
    if len(requested) != len(request.requested_columns):
        raise _export_error(
            "requested export columns contain duplicates",
            code="EXPORT_COLUMNS_INVALID",
            stage="creating",
        )
    unknown = sorted(requested - set(contract.allowed_columns))
    missing = sorted(set(contract.required_columns) - requested)
    if unknown or missing:
        raise _export_error(
            "requested export columns violate the privacy contract",
            code="EXPORT_COLUMNS_INVALID",
            stage="creating",
            details={"unknown_columns": unknown, "missing_required_columns": missing},
        )


def _assert_exportable_classification(contract: ExportPrivacyContract) -> None:
    if contract.classification.casefold() in _NON_EXPORTABLE_CLASSIFICATIONS:
        raise _export_error(
            "privacy classification is not exportable",
            code="EXPORT_PRIVACY_DENIED",
            stage="privacy_policy",
            details={"classification": contract.classification},
        )
def _export_error(
    message: str,
    *,
    code: str,
    stage: str,
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
) -> ExportRuntimeError:
    return ExportRuntimeError(
        message,
        code=code,
        stage=stage,
        retryable=retryable,
        details=details,
    )


def _safe_failure_code(value: str | None) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value):
        return value
    return "EXPORT_UPSTREAM_FAILED"
