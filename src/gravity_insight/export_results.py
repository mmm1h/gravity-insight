"""Public envelopes and completion classification for governed exports."""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from .contracts.envelope_obligations import serialize_envelope
from .errors import ErrorCategory, ErrorCode, ErrorDetail
from .export_completion import (
    completeness_audit,
    export_result_obligations,
    result_completion_status,
    snapshot_completion_status,
)
from .export_contracts import export_error_field
from .export_describe_actions import download_receipt_argument
from .export_models import ExportState
from .result_source import GOVERNED_PRODUCT, result_source


def export_snapshot_envelope(operation_id: str, snapshot: Any) -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.export.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "success",
        "operation_id": operation_id,
        "job_id": snapshot.job_id,
        "state": (
            snapshot.state.value
            if isinstance(snapshot.state, ExportState)
            else str(snapshot.state)
        ),
        "completion_status": snapshot_completion_status(snapshot),
        "download_ready": snapshot.download_source is not None,
        "failure_code": snapshot.failure_code,
        "retryable": bool(snapshot.failure_retryable),
        **_snapshot_completeness(snapshot),
    }


def export_failed_snapshot_envelope(
    operation_id: str,
    snapshot: Any,
    polls: int,
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "export job reached terminal FAILED state; no file is available",
        operation_id=operation_id,
        retryable=False,
        next_action=(
            "Run `gravity export list --page 1 "
            "--page-size 100` to record the terminal job, then run "
            f"`gravity export describe {operation_id}` "
            "before requesting authorization for a new input."
        ),
    )
    return {
        "schema_version": "gravity-insight.error.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "error",
        "operation_id": operation_id,
        "job_id": snapshot.job_id,
        "state": ExportState.FAILED.value,
        "completion_status": snapshot_completion_status(snapshot),
        "polls": polls,
        "failure_code": snapshot.failure_code,
        "error": detail.to_dict(),
    }


def export_result_envelope(operation_id: str, result: Any) -> dict[str, Any]:
    if result.error is not None:
        detail = _export_result_error_detail(operation_id, result)
        obligations = export_result_obligations(result, detail.to_dict())
        return serialize_envelope({
            "schema_version": "gravity-insight.error.v1",
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": False,
            "status": "error",
            "operation_id": operation_id,
            "job_id": result.job_id,
            "state": result.state.value,
            "completion_status": result_completion_status(result),
            "history": [state.value for state in result.history],
            "resumable": result.resumable,
            "error": detail.to_dict(),
            **_failure_diagnostics(result.error),
            **_completeness_fields(result),
        }, obligations)
    obligations = export_result_obligations(result)
    return serialize_envelope({
        "schema_version": "gravity-insight.export.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "success",
        "operation_id": operation_id,
        "job_id": result.job_id,
        "state": result.state.value,
        "completion_status": result_completion_status(result),
        "history": [state.value for state in result.history],
        "resumable": result.resumable,
        "file": _file_receipt(result.receipt),
        **_completeness_fields(result),
    }, obligations)


def _export_result_error_detail(operation_id: str, result: Any) -> ErrorDetail:
    code = str(getattr(result.error, "code", "UPSTREAM_UNAVAILABLE"))
    public_code, next_action = _public_export_error(code, operation_id, result.job_id)
    return ErrorDetail.create(
        public_code,
        result.error,
        operation_id=operation_id,
        category=(ErrorCategory.LOCAL if code == "EXPORT_PRIVACY_DENIED"
                  else getattr(result.error, "category", None)),
        field=getattr(result.error, "field", None) or export_error_field(code),
        retryable=bool(getattr(result.error, "retryable", False)),
        next_action=getattr(result.error, "next_action", None) or next_action,
    )


def _failure_diagnostics(error: Any) -> dict[str, Any]:
    """Expose only fixed phases/reasons and numeric positions, never exception values."""

    stage = getattr(error, "stage", None)
    code = str(getattr(error, "code", ""))
    reasons = {
        ("conditions", "INPUT_INVALID"): "condition_shape_invalid",
        ("conditions", "EXPORT_CONDITIONS_UNSUPPORTED"): "nonempty_conditions_unsupported",
        ("compression", "EXPORT_FORMAT_INVALID"): "invalid_gzip",
        ("compression", "BLOB_SIZE_LIMIT"): "gzip_expansion_limit",
        ("encoding", "EXPORT_FORMAT_INVALID"): "invalid_text_encoding",
        ("headers", "EXPORT_SCHEMA_MISMATCH"): "schema_mismatch",
        ("csv_framing", "EXPORT_SCHEMA_MISMATCH"): "row_width_mismatch",
        ("csv_framing", "EXPORT_FORMAT_INVALID"): "invalid_csv",
        ("local_io", "LOCAL_IO_ERROR"): "local_io_failed",
        ("cell_types", "EXPORT_TYPE_MISMATCH"): "cell_type_mismatch",
        ("xlsx_framing", "EXPORT_FORMAT_INVALID"): "invalid_xlsx",
        ("projection", "EXPORT_COLUMNS_INVALID"): "unverified_fields",
        ("metadata", "EXPORT_COLUMNS_INVALID"): "metadata_field_mismatch",
        ("metadata", "EXPORT_METADATA_UNAVAILABLE"): "metadata_unavailable",
    }
    reason = reasons.get((stage, code))
    semantic_reasons = {
        "EXPORT_SEMANTIC_REJECTED": "unclassified_semantic_rejection",
        "EXPORT_RESPONSE_CONTRADICTED": "success_with_error_indicator",
    }
    if code in semantic_reasons:
        stage, reason = "semantic_response", semantic_reasons[code]
    if code in {"BLOB_SIZE_MISMATCH", "BLOB_HASH_MISMATCH", "BLOB_MD5_MISMATCH"}:
        stage, reason = "completeness", "source_integrity_mismatch"
    if reason is None:
        return {}
    diagnostic: dict[str, Any] = {"stage": stage, "reason": reason}
    details = getattr(error, "details", {})
    if code in semantic_reasons:
        diagnostic["responsibility"] = "unclassified"
        value = details.get("semantic_code") if isinstance(details, Mapping) else None
        diagnostic["semantic_code"] = (
            value if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,6}", value)
            else "redacted"
        )
    for key in ("line", "rows_processed", "column", "missing_column_count", "unknown_column_count"):
        value = details.get(key) if isinstance(details, Mapping) else None
        if type(value) is int and value >= 0:
            diagnostic[key] = value
    return {"diagnostics": diagnostic}


def _public_export_error(
    code: str,
    operation_id: str,
    job_id: str | None,
) -> tuple[ErrorCode | str, str]:
    if code in {"EXPORT_CONDITIONS_UNSUPPORTED", "EXPORT_SEMANTIC_REJECTED",
                "EXPORT_RESPONSE_CONTRADICTED", "INPUT_INVALID"}:
        return code, (
            f"Inspect gravity export describe {operation_id} and the error field; "
            "preserve business filters and stop until the reported limitation is resolved."
        )
    input_codes = {
        "EXPORT_COLUMNS_INVALID", "EXPORT_JOB_INVALID",
        "EXPORT_IDEMPOTENCY_KEY_INVALID", "EXPORT_TIMEOUT_INVALID",
    }
    local_codes = {"LOCAL_IO_ERROR", "BLOB_PATH_UNSAFE", "BLOB_PATH_REPARSE"}
    contract_codes = {
        "EXPORT_PRIVACY_DENIED", "EXPORT_SCHEMA_MISMATCH",
        "EXPORT_FORMAT_INVALID", "EXPORT_FORMAT_UNSUPPORTED",
        "EXPORT_TYPE_MISMATCH",
        "EXPORT_PROTOCOL_ERROR",
        "BLOB_MIME_MISMATCH", "BLOB_TYPE_MISMATCH", "BLOB_MAGIC_MISMATCH",
    }
    if code == "EXPORT_TIMEOUT":
        return ErrorCode.EXPORT_TIMEOUT, (
            "Run `gravity export status "
            f"{job_id} --operation-id {operation_id}`, then resume with "
            "`export download` when READY."
        )
    if code == "BLOB_SIZE_LIMIT":
        return ErrorCode.PAGINATION_LIMIT, (
            "Run `gravity export describe "
            f"{operation_id}` and retry once with a narrower documented date, "
            "segment, or condition scope; do not treat the staged file as complete."
        )
    if code in input_codes:
        return ErrorCode.INPUT_INVALID, (
            "Run `gravity export describe "
            f"{operation_id}` and retry `gravity export run` with the documented "
            "input and an explicit output file."
        )
    if code in local_codes:
        return ErrorCode.LOCAL_IO_ERROR, (
            "Run `gravity export download "
            f"{job_id or '<job-id>'} --operation-id {operation_id} --output "
            "<writable-file.xlsx> --timeout 300"
            f"{download_receipt_argument(operation_id)}`."
        )
    if code in contract_codes:
        return ErrorCode.CONTRACT_CHANGED, (
            "Run `gravity export describe "
            f"{operation_id}` and stop automation until the maintainer republishes "
            "a verified contract."
        )
    return ErrorCode.UPSTREAM_UNAVAILABLE, (
        "Run `gravity export list --page 1 --page-size "
        "100` to determine whether a job was created; do not create a duplicate."
    )


def _file_receipt(receipt: Any) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "path": str(receipt.destination),
        "size_bytes": receipt.size_bytes,
        "source_size_bytes": receipt.source_size_bytes,
        "source_sha256": receipt.source_sha256,
        "committed_sha256": receipt.committed_sha256,
        "content_type": receipt.content_type,
        "extension": receipt.extension,
        "etag_present": receipt.etag is not None,
        "last_modified_present": receipt.last_modified is not None,
        "schema": list(receipt.finalization.schema),
        "rows": receipt.finalization.rows_processed,
        **({"empty_values_by_column": dict(receipt.finalization.details["empty_values_by_column"]),
            "temporal_semantics": receipt.finalization.details.get("temporal_semantics")}
           if "empty_values_by_column" in getattr(receipt.finalization, "details", {}) else {}),
    }


def _completeness_fields(result: Any) -> dict[str, Any]:
    audit = completeness_audit(result)
    return {} if audit is None else {"completeness": audit}


def _snapshot_completeness(snapshot: Any) -> dict[str, Any]:
    value = getattr(snapshot, "completeness", None)
    return {} if not isinstance(value, Mapping) else {"completeness": dict(value)}


__all__ = [
    "export_failed_snapshot_envelope", "export_result_envelope",
    "export_snapshot_envelope", "result_completion_status",
    "snapshot_completion_status",
]
