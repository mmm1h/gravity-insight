"""Export protocol values, state vocabulary, and policy predicates."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
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

    def __init__(self, message: str, *, field: str | None = None,
                 category: str | None = None, next_action: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.field = field
        self.category = category
        self.next_action = next_action


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
    column_order: tuple[str, ...] = ()
    column_types: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    temporal_semantics: str | None = None

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
        if self.column_order and (
            len(set(self.column_order)) != len(self.column_order)
            or set(self.column_order) != set(self.allowed_columns)
        ):
            raise ValueError("export column order must cover exactly the allowed columns")
        if set(self.column_types) - set(self.allowed_columns):
            raise ValueError("export column types must refer to allowed columns")

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
    completeness: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if self.completeness is not None:
            object.__setattr__(
                self, "completeness", MappingProxyType(dict(self.completeness))
            )


@dataclass(frozen=True)
class ExportJobSnapshot:
    job_id: str
    state: ExportState | str
    download_source: AuthorizedBlobSource | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    failure_retryable: bool = False
    completeness: Mapping[str, Any] | None = None


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
    completeness: Mapping[str, Any] | None = None
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
    field: str | None = None,
    category: str | None = None,
    next_action: str | None = None,
) -> ExportRuntimeError:
    return ExportRuntimeError(
        message,
        code=code,
        stage=stage,
        retryable=retryable,
        details=details,
        field=field,
        category=category,
        next_action=next_action,
    )


def validate_origin_conditions(value: Any, schema: Mapping[str, Any]) -> None:
    if not isinstance(value, list):
        _reject("conditions", "Expected an array.")
    # Bound draft diagnostics independently of the executable max_items=0 contract.
    if len(value) > 100:
        _reject("conditions", "Submit at most 100 condition draft items for validation.")
    item_schema = schema["items"]
    for index, item in enumerate(value):
        _validate_item(item, item_schema, f"conditions[{index}]")
    if value:
        _reject("conditions[0]", "Nonempty raw-export conditions are not supported.",
                unsupported=True)


def _validate_item(item: Any, schema: Mapping[str, Any], path: str) -> None:
    if not isinstance(item, Mapping):
        _reject(path, "Expected a condition object.")
    properties = schema["properties"]
    for key in schema["required"]:
        if key not in item:
            _reject(f"{path}.{key}", "Required condition key is missing.")
    if set(item) - set(properties):
        # Unknown keys may themselves contain user values; never echo them.
        _reject(path, "Unexpected condition key; only type, field, operator and value are allowed.")
    _validate_condition_strings(item, properties, path)
    _validate_condition_values(item, schema, path)


def _validate_condition_strings(item: Mapping[str, Any], properties: Mapping[str, Any], path: str) -> None:
    for key in ("type", "field", "operator"):
        value = item[key]
        spec = properties[key]
        if not isinstance(value, str):
            _reject(f"{path}.{key}", "Expected a string.")
        if "enum" in spec and value not in spec["enum"]:
            _reject(f"{path}.{key}", "Value is outside the client-draft enum.")
        if not spec.get("min_length", 0) <= len(value) <= spec.get("max_length", 256):
            _reject(f"{path}.{key}", "String length is outside the client-draft bounds.")


def _validate_condition_values(item: Mapping[str, Any], schema: Mapping[str, Any], path: str) -> None:
    properties = schema["properties"]
    values = item["value"]
    if not isinstance(values, list):
        _reject(f"{path}.value", "Expected an array of scalar values.")
    rule = schema["operator_constraints"][item["operator"]]
    if not rule["min_items"] <= len(values) <= rule["max_items"]:
        _reject(f"{path}.value", "Value count is outside the client-draft operator bounds.")
    for index, value in enumerate(values):
        _validate_condition_scalar(value, properties["value"]["items"], f"{path}.value[{index}]")
    if rule.get("ordered_numeric"):
        for index, value in enumerate(values):
            if type(value) not in (int, float):
                _reject(f"{path}.value[{index}]", "RANGE_IN requires numeric bounds.")
        if values[0] > values[1]:
            _reject(f"{path}.value", "RANGE_IN lower bound must not exceed upper bound.")


def _validate_condition_scalar(value: Any, schema: Mapping[str, Any], path: str) -> None:
    scalar = type(value) in (str, int, float, bool)
    if not scalar or (type(value) is float and not math.isfinite(value)):
        _reject(path, "Expected a finite JSON scalar, excluding null.")
    if isinstance(value, str) and len(value) > schema["max_length"]:
        _reject(path, "Scalar text exceeds the client-draft bound.")


def _reject(field: str, reason: str, *, unsupported: bool = False) -> None:
    raise _export_error(
        reason + " No request was sent; the item schema is an unverified client draft.",
        code="EXPORT_CONDITIONS_UNSUPPORTED" if unsupported else "INPUT_INVALID",
        stage="conditions", field=field,
        category="local" if unsupported else "caller",
        next_action=(
            reason + " "
            "Inspect conditions in gravity export describe export.analysis.origin_event.start. "
            "Correct the draft shape if needed, but do not retry nonempty conditions: "
            "filtered export requires maintainer validation and a future contract. "
            "Preserve required business filters; an unfiltered export is not equivalent."
        ),
    )


def _safe_failure_code(value: str | None) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value):
        return value
    return "EXPORT_UPSTREAM_FAILED"
