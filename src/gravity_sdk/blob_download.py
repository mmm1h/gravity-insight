"""Download streaming, integrity, and publication helpers."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Iterable

from .blob_headers import _HeaderInfo, _validate_received_sizes
from .blob_models import (
    AuthorizedBlobSource,
    BlobFinalizationResult,
    BlobFinalizer,
    BlobMetadata,
    BlobReceipt,
    BlobResumeState,
    BlobTransferError,
)
from .blob_policy import BlobPolicy, _header
from .blob_storage import _copy_prefix, _hash_regular_file, _new_staging_path
from .blob_verify import _commit_staging, _inspect_type_and_archive


def _download_request_headers(
    resume: BlobResumeState | None,
) -> dict[str, str]:
    request_headers = {"Accept-Encoding": "identity"}
    if resume is not None:
        request_headers["Range"] = f"bytes={resume.bytes_received}-"
        validator = resume.etag or resume.last_modified
        if validator:
            request_headers["If-Range"] = validator
    return request_headers


def _write_download_stream(
    response: Any,
    output: Any,
    digest: Any,
    *,
    resume_path: Path | None,
    staging_path: Path,
    policy: BlobPolicy,
) -> tuple[int, int]:
    bytes_written = 0
    if resume_path is not None:
        bytes_written = _copy_prefix(
            resume_path,
            output,
            digest,
            policy.max_stream_size_bytes,
            policy.chunk_size,
        )
    try:
        response_bytes = 0
        for chunk in _iter_response_bytes(response, policy.chunk_size):
            if not chunk:
                continue
            response_bytes += len(chunk)
            bytes_written += len(chunk)
            if bytes_written > policy.max_stream_size_bytes:
                raise BlobTransferError(
                    "download exceeded the streaming size cap",
                    code="BLOB_SIZE_LIMIT",
                    stage="stream",
                    details={"limit": policy.max_stream_size_bytes},
                )
            output.write(chunk)
            digest.update(chunk)
    except BlobTransferError:
        raise
    except Exception as exc:
        output.flush()
        os.fsync(output.fileno())
        validator_etag = _header(response.headers, "ETag")
        validator_modified = _header(response.headers, "Last-Modified")
        can_resume = (
            policy.allow_range_resume
            and bytes_written > 0
            and bool(validator_etag or validator_modified)
        )
        resume_state = (
            BlobResumeState(
                partial_path=staging_path,
                bytes_received=bytes_written,
                etag=validator_etag,
                last_modified=validator_modified,
            )
            if can_resume
            else None
        )
        raise BlobTransferError(
            "download stream failed",
            code="BLOB_TRANSPORT_ERROR",
            stage="stream",
            retryable=can_resume,
            details={"bytes_received": bytes_written},
            resume_state=resume_state,
        ) from exc
    output.flush()
    os.fsync(output.fileno())
    return response_bytes, bytes_written


def _materialize_download(
    response: Any,
    source: AuthorizedBlobSource,
    policy: BlobPolicy,
    header_info: _HeaderInfo,
    *,
    resume_path: Path | None,
    staging_path: Path,
    extension: str,
    expected_digest: str | None,
) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    with staging_path.open("wb") as output:
        response_bytes, bytes_written = _write_download_stream(
            response,
            output,
            digest,
            resume_path=resume_path,
            staging_path=staging_path,
            policy=policy,
        )
    source_sha256 = digest.hexdigest()
    _verify_download_integrity(
        source,
        header_info,
        response_bytes=response_bytes,
        total_bytes=bytes_written,
        source_sha256=source_sha256,
        expected_digest=expected_digest,
        staging_path=staging_path,
        extension=extension,
        content_type=header_info.content_type,
        policy=policy,
    )
    return response_bytes, bytes_written, source_sha256


def _finish_download(
    response: Any,
    source: AuthorizedBlobSource,
    policy: BlobPolicy,
    header_info: _HeaderInfo,
    *,
    destination_path: Path,
    extension: str,
    expected_digest: str | None,
    resume: BlobResumeState | None,
    resume_path: Path | None,
    staging_path: Path,
    finalizer: BlobFinalizer | None,
    observer: Callable[[str, BlobMetadata], None] | None,
) -> tuple[BlobReceipt, bool]:
    _response_bytes, bytes_written, source_sha256 = _materialize_download(
        response,
        source,
        policy,
        header_info,
        resume_path=resume_path,
        staging_path=staging_path,
        extension=extension,
        expected_digest=expected_digest,
    )
    content_type = header_info.content_type
    source_metadata = BlobMetadata(
        size_bytes=bytes_written,
        sha256=source_sha256,
        content_type=content_type,
        extension=extension,
        etag=header_info.etag,
        last_modified=header_info.last_modified,
        resumed=resume is not None,
    )
    finalized_path: Path | None = None
    try:
        finalization, commit_path, committed_size, committed_sha256 = (
            _apply_download_finalizer(
                staging_path,
                destination_path,
                source_metadata,
                extension=extension,
                content_type=content_type,
                policy=policy,
                finalizer=finalizer,
            )
        )
        if commit_path != staging_path:
            finalized_path = commit_path
        receipt = _publish_download(
            commit_path,
            destination_path,
            policy,
            committed_size=committed_size,
            committed_sha256=committed_sha256,
            bytes_written=bytes_written,
            source_sha256=source_sha256,
            content_type=content_type,
            extension=extension,
            header_info=header_info,
            resume=resume,
            finalization=finalization,
            observer=observer,
        )
        finalized_path = None
        return receipt, commit_path != staging_path
    finally:
        if finalized_path is not None:
            _unlink_quietly(finalized_path)


def _verify_download_integrity(
    source: AuthorizedBlobSource,
    header_info: _HeaderInfo,
    *,
    response_bytes: int,
    total_bytes: int,
    source_sha256: str,
    expected_digest: str | None,
    staging_path: Path,
    extension: str,
    content_type: str,
    policy: BlobPolicy,
) -> None:
    _validate_received_sizes(
        source,
        header_info,
        response_bytes=response_bytes,
        total_bytes=total_bytes,
    )
    if expected_digest is not None and source_sha256 != expected_digest:
        raise BlobTransferError(
            "download SHA-256 does not match the authorized digest",
            code="BLOB_HASH_MISMATCH",
            stage="integrity",
            details={"expected": expected_digest, "actual": source_sha256},
        )
    _inspect_type_and_archive(staging_path, extension, content_type, policy)


def _apply_download_finalizer(
    staging_path: Path,
    destination_path: Path,
    source_metadata: BlobMetadata,
    *,
    extension: str,
    content_type: str,
    policy: BlobPolicy,
    finalizer: BlobFinalizer | None,
) -> tuple[BlobFinalizationResult, Path, int, str]:
    finalization = BlobFinalizationResult()
    commit_path = staging_path
    committed_size = source_metadata.size_bytes
    committed_sha256 = source_metadata.sha256
    if finalizer is None:
        return finalization, commit_path, committed_size, committed_sha256
    finalized_path = _new_staging_path(destination_path.parent, suffix=".final")
    keep_finalized = False
    try:
        try:
            finalization = finalizer.finalize(
                staging_path,
                finalized_path,
                source_metadata,
            )
        except BlobTransferError:
            raise
        except Exception as exc:
            raise BlobTransferError(
                "blob finalizer failed",
                code="BLOB_FINALIZER_FAILED",
                stage="finalizer",
            ) from exc
        if not isinstance(finalization, BlobFinalizationResult):
            raise BlobTransferError(
                "blob finalizer returned an invalid result",
                code="BLOB_FINALIZER_FAILED",
                stage="finalizer",
            )
        committed_size, committed_sha256 = _hash_regular_file(
            finalized_path,
            policy.max_stream_size_bytes,
            policy.chunk_size,
        )
        _inspect_type_and_archive(finalized_path, extension, content_type, policy)
        keep_finalized = True
        return finalization, finalized_path, committed_size, committed_sha256
    finally:
        if not keep_finalized:
            _unlink_quietly(finalized_path)


def _publish_download(
    commit_path: Path,
    destination_path: Path,
    policy: BlobPolicy,
    *,
    committed_size: int,
    committed_sha256: str,
    bytes_written: int,
    source_sha256: str,
    content_type: str,
    extension: str,
    header_info: _HeaderInfo,
    resume: BlobResumeState | None,
    finalization: BlobFinalizationResult,
    observer: Callable[[str, BlobMetadata], None] | None,
) -> BlobReceipt:
    committed_metadata = BlobMetadata(
        size_bytes=committed_size,
        sha256=committed_sha256,
        content_type=content_type,
        extension=extension,
        etag=header_info.etag,
        last_modified=header_info.last_modified,
        resumed=resume is not None,
    )
    if observer is not None:
        observer("verified", committed_metadata)
    _commit_staging(commit_path, destination_path, policy)
    return BlobReceipt(
        destination=destination_path,
        size_bytes=committed_size,
        source_size_bytes=bytes_written,
        source_sha256=source_sha256,
        committed_sha256=committed_sha256,
        content_type=content_type,
        extension=extension,
        etag=header_info.etag,
        last_modified=header_info.last_modified,
        resumed=resume is not None,
        finalization=finalization,
    )


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _iter_response_bytes(response: Any, chunk_size: int) -> Iterable[bytes]:
    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        raise BlobTransferError(
            "download response does not expose a streaming body",
            code="BLOB_TRANSPORT_ERROR",
            stage="stream",
        )
    for chunk in iterator(chunk_size=chunk_size):
        if not isinstance(chunk, (bytes, bytearray)):
            raise BlobTransferError(
                "download stream yielded a non-byte chunk",
                code="BLOB_TRANSPORT_ERROR",
                stage="stream",
            )
        yield bytes(chunk)
