"""Machine-decidable completeness for one governed export file."""

from __future__ import annotations

from typing import Any, Mapping

from .export_models import ExportCompletionStatus


UPSTREAM_FILE_ROW_LIMIT = 1_000_000
MONETIZATION_EXPORT_OPERATION = ".".join(
    ("export", "analysis", "monetization_detail", "start")
)
_EXPIRED_CODES = frozenset({"EXPORT_UPSTREAM_EXPIRED", "BLOB_URL_EXPIRED"})


def snapshot_completion_status(snapshot: Any) -> str:
    code = str(getattr(snapshot, "failure_code", "") or "")
    if code == "EXPORT_UPSTREAM_EXPIRED":
        return ExportCompletionStatus.EXPIRED.value
    return ExportCompletionStatus.PARTIAL.value


def result_completion_status(result: Any) -> str:
    receipt = getattr(result, "receipt", None)
    if result.error is None and receipt is not None:
        return _committed_status(result, receipt)
    code = str(getattr(result.error, "code", "") or "")
    if code in _EXPIRED_CODES:
        return ExportCompletionStatus.EXPIRED.value
    if code == "BLOB_SIZE_LIMIT":
        return ExportCompletionStatus.TRUNCATED.value
    return ExportCompletionStatus.PARTIAL.value


def completeness_audit(result: Any) -> dict[str, Any] | None:
    snapshot = getattr(result, "completeness", None)
    if not isinstance(snapshot, Mapping):
        return None
    return dict(snapshot)


def _committed_status(result: Any, receipt: Any) -> str:
    rows = int(receipt.finalization.rows_processed)
    if rows == 0:
        return ExportCompletionStatus.EMPTY.value
    snapshot = getattr(result, "completeness", None)
    if isinstance(snapshot, Mapping) and snapshot.get("truncated") is True:
        return ExportCompletionStatus.TRUNCATED.value
    if isinstance(snapshot, Mapping) and snapshot.get("complete") is True:
        return ExportCompletionStatus.COMPLETE.value
    if isinstance(snapshot, Mapping) or rows >= UPSTREAM_FILE_ROW_LIMIT:
        return ExportCompletionStatus.PARTIAL.value
    return ExportCompletionStatus.COMPLETE.value


__all__ = [
    "MONETIZATION_EXPORT_OPERATION",
    "UPSTREAM_FILE_ROW_LIMIT",
    "completeness_audit",
    "result_completion_status",
    "snapshot_completion_status",
]
