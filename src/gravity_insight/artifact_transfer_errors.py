"""Stable public error mapping for governed Artifact transfers."""

from __future__ import annotations

from .blob_models import BlobTransferError
from .errors import ErrorCategory, ErrorCode, GravityInsightError


_MISMATCH_CODES = {
    "BLOB_EXTENSION_MISMATCH": "ARTIFACT_EXTENSION_MISMATCH",
    "BLOB_MIME_MISMATCH": "ARTIFACT_MIME_MISMATCH",
    "BLOB_TYPE_MISMATCH": "ARTIFACT_MIME_MISMATCH",
    "BLOB_MAGIC_MISMATCH": "ARTIFACT_MAGIC_MISMATCH",
    "BLOB_SIZE_LIMIT": "ARTIFACT_SIZE_LIMIT",
    "BLOB_SIZE_INVALID": "ARTIFACT_SIZE_MISMATCH",
    "BLOB_SIZE_MISMATCH": "ARTIFACT_SIZE_MISMATCH",
    "BLOB_HASH_MISMATCH": "ARTIFACT_DIGEST_MISMATCH",
    "BLOB_MD5_MISMATCH": "ARTIFACT_DIGEST_MISMATCH",
    "BLOB_DIGEST_INVALID": "ARTIFACT_DIGEST_MISMATCH",
}


class ArtifactTransferError(GravityInsightError):
    """Stable, caller-safe failure from one governed Artifact transfer."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | str,
        category: ErrorCategory,
        stage: str,
        reason_category: str,
        retryable: bool = False,
        field: str | None = None,
        next_action: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message, code=code, field=field, next_action=next_action)
        self.category = category
        self.retryable = retryable
        self.stage = stage
        self.reason_category = reason_category
        self.http_status = http_status


class ArtifactTransferHttpError(ArtifactTransferError):
    """An actual terminal HTTP status from the private Artifact URL."""

    def __init__(self, status: int) -> None:
        if status in {401, 403}:
            code: ErrorCode | str = ErrorCode.PERMISSION_UNAVAILABLE
            action = "Refresh the source operation once and confirm upstream asset access."
        elif status == 429:
            code = ErrorCode.RATE_LIMITED
            action = "Wait for the upstream limit to clear, then repeat the same fetch once."
        else:
            code = ErrorCode.UPSTREAM_UNAVAILABLE
            action = "Refresh the source operation once; do not construct or edit its URL."
        super().__init__(
            f"response-bound Artifact returned HTTP {status}",
            code=code,
            category=ErrorCategory.UPSTREAM,
            stage="headers",
            reason_category="http_status",
            retryable=status in {408, 425, 429} or status >= 500,
            next_action=action,
            http_status=status,
        )


def translate_blob_error(
    error: BlobTransferError, *, network_started: bool
) -> ArtifactTransferError:
    translators = (
        _transport_error,
        lambda selected: _source_error(selected, network_started=network_started),
        _output_error,
        _integrity_error,
        _local_error,
    )
    for translator in translators:
        if translated := translator(error):
            return translated
    return ArtifactTransferError(
        "Artifact transfer policy failed closed",
        code="ARTIFACT_CONTRACT_CHANGED",
        category=ErrorCategory.LOCAL,
        stage=error.stage,
        reason_category="contract",
        next_action="Stop automation and verify the installed Artifact Transfer contract.",
    )


def _transport_error(error: BlobTransferError) -> ArtifactTransferError | None:
    code = str(error.code)
    if code == "BLOB_HTTP_STATUS":
        return ArtifactTransferHttpError(int(error.details.get("status", 0)))
    if code == "BLOB_TRANSPORT_ERROR":
        return ArtifactTransferError(
            "Artifact transfer failed before completion",
            code="ARTIFACT_TRANSPORT_FAILED",
            category=ErrorCategory.UPSTREAM,
            stage=error.stage,
            reason_category="transport",
            retryable=error.retryable,
            next_action="Refresh the source operation once, then retry the same transfer once.",
        )
    return None


def _source_error(
    error: BlobTransferError, *, network_started: bool
) -> ArtifactTransferError | None:
    code = str(error.code)
    if code == "BLOB_URL_DENIED":
        reason = "redirect_policy" if network_started else "source_policy"
        return ArtifactTransferError(
            "Artifact redirect escaped its authorized host"
            if network_started
            else "fresh source response contains a denied Artifact URL",
            code="ARTIFACT_REDIRECT_DENIED"
            if network_started
            else "ARTIFACT_SOURCE_DENIED",
            category=ErrorCategory.UPSTREAM,
            stage=error.stage,
            reason_category=reason,
            next_action="Refresh the registered source operation once; do not construct or edit its URL.",
        )
    if code in {"BLOB_REDIRECT_INVALID", "BLOB_REDIRECT_LIMIT"}:
        return ArtifactTransferError(
            "Artifact redirect policy could not be satisfied",
            code="ARTIFACT_REDIRECT_INVALID"
            if code.endswith("INVALID")
            else "ARTIFACT_REDIRECT_LIMIT",
            category=ErrorCategory.UPSTREAM,
            stage=error.stage,
            reason_category="redirect_policy",
            next_action="Refresh the registered source operation once and retry the same reference.",
        )
    return None


def _output_error(error: BlobTransferError) -> ArtifactTransferError | None:
    code = str(error.code)
    if error.stage == "destination_policy" or code in {
        "BLOB_OVERWRITE_DENIED",
        "BLOB_PATH_ESCAPE",
        "BLOB_PATH_REPARSE",
        "BLOB_PATH_UNSAFE",
    }:
        return ArtifactTransferError(
            "Artifact output violates the configured root or file policy",
            code="ARTIFACT_OUTPUT_DENIED",
            category=ErrorCategory.CALLER,
            stage=error.stage,
            reason_category="output_policy",
            field="output",
            next_action="Choose a new relative file with the documented extension under a plain output root.",
        )
    return None


def _integrity_error(error: BlobTransferError) -> ArtifactTransferError | None:
    code = str(error.code)
    if code not in _MISMATCH_CODES:
        return None
    reason = (
        "type_validation"
        if "MIME" in code or "MAGIC" in code or "TYPE" in code or "EXTENSION" in code
        else "size_validation"
        if "SIZE" in code
        else "digest_validation"
    )
    return ArtifactTransferError(
        "Artifact bytes contradict the governed transfer contract",
        code=_MISMATCH_CODES[code],
        category=ErrorCategory.UPSTREAM,
        stage=error.stage,
        reason_category=reason,
        next_action="Refresh the source operation once and stop if the same contract mismatch repeats.",
    )


def _local_error(error: BlobTransferError) -> ArtifactTransferError | None:
    if str(error.code) == "LOCAL_IO_ERROR" or error.stage in {"staging", "commit"}:
        return ArtifactTransferError(
            "Artifact could not be committed to local storage",
            code="ARTIFACT_LOCAL_IO",
            category=ErrorCategory.LOCAL,
            stage=error.stage,
            reason_category="local_io",
            next_action="Check output-root permissions and free space, then retry once.",
        )
    return None


__all__ = ["ArtifactTransferError", "ArtifactTransferHttpError"]
