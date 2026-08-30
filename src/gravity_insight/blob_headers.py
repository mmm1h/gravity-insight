"""HTTP response preflight checks for blob downloads."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .blob_models import AuthorizedBlobSource, BlobResumeState, BlobTransferError
from .blob_policy import (
    BlobPolicy,
    _header,
    _parse_content_length,
    _runtime_mime,
    _validate_declared_size,
)

_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")

@dataclass(frozen=True)
class _HeaderInfo:
    content_type: str
    response_length: int | None
    expected_total: int | None
    etag: str | None
    last_modified: str | None


def _preflight_headers(
    response: Any,
    source: AuthorizedBlobSource,
    policy: BlobPolicy,
    *,
    resume: BlobResumeState | None,
) -> _HeaderInfo:
    _require_download_status(response, resume)
    content_type = _require_identity_content_type(response, source)
    response_length = _parse_content_length(_header(response.headers, "Content-Length"))
    expected_total, etag, last_modified = _preflight_resume_or_full(
        response,
        resume,
        response_length,
    )
    _validate_declared_size(expected_total, policy)
    _reject_size_declaration_mismatch(source, expected_total)
    return _HeaderInfo(
        content_type=content_type,
        response_length=response_length,
        expected_total=expected_total,
        etag=etag,
        last_modified=last_modified,
    )


def _require_download_status(response: Any, resume: BlobResumeState | None) -> None:
    status = int(getattr(response, "status_code", 0))
    expected_status = 206 if resume is not None else 200
    if status != expected_status:
        raise BlobTransferError(
            "download returned an unexpected HTTP status",
            code="BLOB_HTTP_STATUS",
            stage="headers",
            retryable=status >= 500,
            details={"status": status, "expected_status": expected_status},
        )


def _require_identity_content_type(
    response: Any,
    source: AuthorizedBlobSource,
) -> str:
    content_encoding = (_header(response.headers, "Content-Encoding") or "identity").lower()
    if content_encoding != "identity":
        raise BlobTransferError(
            "encoded transfer bodies are not accepted",
            code="BLOB_CONTENT_ENCODING_UNSUPPORTED",
            stage="headers",
        )
    content_type_header = _header(response.headers, "Content-Type")
    if not content_type_header:
        raise BlobTransferError(
            "download response omitted Content-Type",
            code="BLOB_MIME_MISMATCH",
            stage="headers",
        )
    content_type = _runtime_mime(
        content_type_header.split(";", 1)[0],
        stage="headers",
    )
    declared_mime = _runtime_mime(source.declared_mime_type, stage="source_policy")
    if content_type != declared_mime:
        raise BlobTransferError(
            "response MIME does not match the authorized source declaration",
            code="BLOB_MIME_MISMATCH",
            stage="headers",
            details={"declared": declared_mime, "actual": content_type},
        )
    return content_type


def _preflight_resume_or_full(
    response: Any,
    resume: BlobResumeState | None,
    response_length: int | None,
) -> tuple[int | None, str | None, str | None]:
    if resume is not None:
        return _preflight_resume_headers(response, resume, response_length)
    return (
        response_length,
        _header(response.headers, "ETag"),
        _header(response.headers, "Last-Modified"),
    )


def _preflight_resume_headers(
    response: Any,
    resume: BlobResumeState,
    response_length: int | None,
) -> tuple[int, str | None, str | None]:
    etag = _header(response.headers, "ETag")
    last_modified = _header(response.headers, "Last-Modified")
    if resume.etag is not None and etag != resume.etag:
        raise BlobTransferError(
            "resume ETag changed",
            code="BLOB_RESUME_VALIDATOR_CHANGED",
            stage="headers",
        )
    if resume.last_modified is not None and last_modified != resume.last_modified:
        raise BlobTransferError(
            "resume Last-Modified changed",
            code="BLOB_RESUME_VALIDATOR_CHANGED",
            stage="headers",
        )
    content_range = _header(response.headers, "Content-Range")
    match = _CONTENT_RANGE.fullmatch(content_range or "")
    if match is None:
        raise BlobTransferError(
            "resume response omitted a valid Content-Range",
            code="BLOB_RESUME_RANGE_INVALID",
            stage="headers",
        )
    start, end, total = (int(value) for value in match.groups())
    if start != resume.bytes_received or end < start or end >= total:
        raise BlobTransferError(
            "resume Content-Range does not continue the partial file",
            code="BLOB_RESUME_RANGE_INVALID",
            stage="headers",
        )
    if response_length is not None and response_length != end - start + 1:
        raise BlobTransferError(
            "resume Content-Length conflicts with Content-Range",
            code="BLOB_SIZE_MISMATCH",
            stage="headers",
        )
    return total, etag, last_modified


def _reject_size_declaration_mismatch(
    source: AuthorizedBlobSource,
    expected_total: int | None,
) -> None:
    if (
        source.declared_size is not None
        and expected_total is not None
        and source.declared_size != expected_total
    ):
        raise BlobTransferError(
            "response size does not match the authorized declaration",
            code="BLOB_SIZE_MISMATCH",
            stage="headers",
            details={"declared": source.declared_size, "header_total": expected_total},
        )


def _validate_received_sizes(
    source: AuthorizedBlobSource,
    headers: _HeaderInfo,
    *,
    response_bytes: int,
    total_bytes: int,
) -> None:
    if headers.response_length is not None and response_bytes != headers.response_length:
        raise BlobTransferError(
            "received byte count does not match Content-Length",
            code="BLOB_SIZE_MISMATCH",
            stage="integrity",
            details={"header": headers.response_length, "actual": response_bytes},
        )
    if headers.expected_total is not None and total_bytes != headers.expected_total:
        raise BlobTransferError(
            "received byte count does not match the declared total",
            code="BLOB_SIZE_MISMATCH",
            stage="integrity",
            details={"declared": headers.expected_total, "actual": total_bytes},
        )
    if source.declared_size is not None and total_bytes != source.declared_size:
        raise BlobTransferError(
            "received byte count does not match the authorized source size",
            code="BLOB_SIZE_MISMATCH",
            stage="integrity",
            details={"declared": source.declared_size, "actual": total_bytes},
        )
