"""Public envelopes and completion classification for governed exports."""
from __future__ import annotations

from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail
from .export_contracts import export_error_field
from .export_models import ExportCompletionStatus, ExportState
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
        return {
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
        }
    return {
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
    }


def snapshot_completion_status(snapshot: Any) -> str:
    code = str(getattr(snapshot, "failure_code", "") or "")
    if code == "EXPORT_UPSTREAM_EXPIRED":
        return ExportCompletionStatus.EXPIRED.value
    return ExportCompletionStatus.PARTIAL.value


def result_completion_status(result: Any) -> str:
    receipt = getattr(result, "receipt", None)
    if result.error is None and receipt is not None:
        rows = int(receipt.finalization.rows_processed)
        return (
            ExportCompletionStatus.EMPTY.value
            if rows == 0
            else ExportCompletionStatus.COMPLETE.value
        )
    code = str(getattr(result.error, "code", "") or "")
    if code in {"EXPORT_UPSTREAM_EXPIRED", "BLOB_URL_EXPIRED"}:
        return ExportCompletionStatus.EXPIRED.value
    if code == "BLOB_SIZE_LIMIT":
        return ExportCompletionStatus.TRUNCATED.value
    return ExportCompletionStatus.PARTIAL.value


def _export_result_error_detail(operation_id: str, result: Any) -> ErrorDetail:
    code = str(getattr(result.error, "code", "UPSTREAM_UNAVAILABLE"))
    public_code, next_action = _public_export_error(code, operation_id, result.job_id)
    return ErrorDetail.create(
        public_code,
        result.error,
        operation_id=operation_id,
        category=(ErrorCategory.LOCAL if code == "EXPORT_PRIVACY_DENIED" else None),
        field=export_error_field(code),
        retryable=bool(getattr(result.error, "retryable", False)),
        next_action=next_action,
    )


def _public_export_error(
    code: str,
    operation_id: str,
    job_id: str | None,
) -> tuple[ErrorCode, str]:
    input_codes = {
        "EXPORT_COLUMNS_INVALID", "EXPORT_JOB_INVALID",
        "EXPORT_IDEMPOTENCY_KEY_INVALID", "EXPORT_TIMEOUT_INVALID",
    }
    local_codes = {"LOCAL_IO_ERROR", "BLOB_PATH_UNSAFE", "BLOB_PATH_REPARSE"}
    contract_codes = {
        "EXPORT_PRIVACY_DENIED", "EXPORT_SCHEMA_MISMATCH",
        "EXPORT_FORMAT_INVALID", "EXPORT_FORMAT_UNSUPPORTED",
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
            "<writable-file.xlsx> --timeout 300`."
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
    }


__all__ = [
    "export_failed_snapshot_envelope", "export_result_envelope",
    "export_snapshot_envelope", "result_completion_status",
    "snapshot_completion_status",
]
