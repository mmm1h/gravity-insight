"""Download and upload orchestration for authorized blobs."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin

from .blob_headers import _preflight_headers, _validate_received_sizes
from .blob_models import (
    AuthorizedBlobSource, AuthorizedUploadTarget, BlobFinalizationResult,
    BlobFinalizer, BlobMetadata, BlobReceipt, BlobResumeState, BlobTransferError,
    BlobTransport, RequestsBlobTransport, SafeLocalSource, UploadReceipt,
)
from .blob_policy import (
    BlobPolicy, _header, _normalize_expected_digest, _runtime_mime, _select_extension,
    _validate_authorized_source, _validate_declared_size, _validate_expiry,
    _validate_remote_url,
)
from .blob_storage import (
    _copy_prefix, _hash_regular_file, _new_staging_path, _prepare_destination,
    _prepare_local_source, _validate_resume_state,
)
from .blob_verify import _commit_staging, _inspect_type_and_archive

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

class SafeBlobTransfer:
    def __init__(
        self,
        transport: BlobTransport | None = None,
        *,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or RequestsBlobTransport()
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def download(
        self,
        source: AuthorizedBlobSource,
        destination: str | Path,
        policy: BlobPolicy,
        *,
        finalizer: BlobFinalizer | None = None,
        resume: BlobResumeState | None = None,
        observer: Callable[[str, BlobMetadata], None] | None = None,
    ) -> BlobReceipt:
        destination_path, extension = _prepare_destination(destination, policy)
        _validate_download_authorization(source, policy, self._wall_clock())
        _validate_declared_size(source.declared_size, policy)
        expected_digest = _normalize_expected_digest(source.expected_sha256)
        resume_path = _validate_resume_state(resume, policy)

        request_headers = {"Accept-Encoding": "identity"}
        initial_size = 0
        if resume is not None:
            initial_size = resume.bytes_received
            request_headers["Range"] = f"bytes={initial_size}-"
            request_headers["If-Range"] = resume.etag or resume.last_modified or ""

        response, _ = self._open_download(
            source.url,
            policy,
            request_headers=request_headers,
        )
        staging_path: Path | None = None
        finalized_path: Path | None = None
        preserve_staging = False
        try:
            header_info = _preflight_headers(
                response,
                source,
                policy,
                resume=resume,
            )
            content_type = header_info.content_type
            staging_path = _new_staging_path(destination_path.parent)
            digest = hashlib.sha256()
            bytes_written = 0
            with staging_path.open("wb") as output:
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
                    preserve_staging = can_resume
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

            _validate_received_sizes(
                source,
                header_info,
                response_bytes=response_bytes,
                total_bytes=bytes_written,
            )
            source_sha256 = digest.hexdigest()
            if expected_digest is not None and source_sha256 != expected_digest:
                raise BlobTransferError(
                    "download SHA-256 does not match the authorized digest",
                    code="BLOB_HASH_MISMATCH",
                    stage="integrity",
                    details={"expected": expected_digest, "actual": source_sha256},
                )
            _inspect_type_and_archive(staging_path, extension, content_type, policy)

            source_metadata = BlobMetadata(
                size_bytes=bytes_written,
                sha256=source_sha256,
                content_type=content_type,
                extension=extension,
                etag=header_info.etag,
                last_modified=header_info.last_modified,
                resumed=resume is not None,
            )
            finalization = BlobFinalizationResult()
            commit_path = staging_path
            committed_size = bytes_written
            committed_sha256 = source_sha256
            if finalizer is not None:
                finalized_path = _new_staging_path(destination_path.parent, suffix=".final")
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
                commit_path = finalized_path

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
            if commit_path == staging_path:
                staging_path = None
            else:
                finalized_path = None
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
        finally:
            _close_response(response)
            if staging_path is not None and not preserve_staging:
                _unlink_quietly(staging_path)
            if finalized_path is not None:
                _unlink_quietly(finalized_path)

    def upload(
        self,
        source: SafeLocalSource,
        target: AuthorizedUploadTarget,
        policy: BlobPolicy,
    ) -> UploadReceipt:
        if not policy.allow_upload:
            raise BlobTransferError(
                "blob upload is disabled by policy",
                code="UPLOAD_DISABLED",
                stage="upload_policy",
            )
        if policy.upload_root is None:
            raise BlobTransferError(
                "upload policy has no local source root",
                code="BLOB_POLICY_INVALID",
                stage="upload_policy",
            )
        source_path = _prepare_local_source(source.relative_path, policy.upload_root)
        extension = _select_extension(source_path.name, policy.allowed_extensions)
        content_type = _runtime_mime(target.content_type, stage="upload_policy")
        _validate_remote_url(
            target.url,
            policy,
            allowed_hosts=policy.allowed_hosts,
            declared_path=target.declared_path,
        )
        _validate_expiry(target.expires_at, self._wall_clock())
        if (
            not isinstance(target.authorization_scope, str)
            or not target.authorization_scope.strip()
            or not isinstance(target.file_field, str)
            or not target.file_field.strip()
        ):
            raise BlobTransferError(
                "upload target lacks an authorization scope or file field",
                code="BLOB_AUTHORIZATION_INVALID",
                stage="upload_policy",
            )
        size_bytes, sha256 = _hash_regular_file(
            source_path,
            policy.max_stream_size_bytes,
            policy.chunk_size,
        )
        _validate_declared_size(size_bytes, policy)
        _inspect_type_and_archive(source_path, extension, content_type, policy)
        try:
            response = self._transport.upload(
                target.url,
                file_path=source_path,
                file_field=target.file_field,
                content_type=content_type,
                form_fields=MappingProxyType(dict(target.form_fields)),
                timeout=policy.request_timeout_seconds,
            )
        except Exception as exc:
            raise BlobTransferError(
                "upload transport failed",
                code="BLOB_TRANSPORT_ERROR",
                stage="upload",
                retryable=False,
                details={"write_may_have_occurred": True},
            ) from exc
        try:
            status = int(getattr(response, "status_code", 0))
            if status in _REDIRECT_STATUSES or not 200 <= status < 300:
                raise BlobTransferError(
                    "upload did not return an accepted terminal response",
                    code="BLOB_UPLOAD_REJECTED",
                    stage="upload_receipt",
                    details={"status": status, "write_may_have_occurred": True},
                )
            server_receipt = (
                _header(response.headers, target.receipt_header)
                if target.receipt_header
                else None
            )
            if target.receipt_header and server_receipt is None:
                raise BlobTransferError(
                    "upload response omitted its contracted receipt",
                    code="BLOB_UPLOAD_RECEIPT_INVALID",
                    stage="upload_receipt",
                    details={"write_may_have_occurred": True},
                )
            server_sha256 = (
                _normalize_expected_digest(
                    _header(response.headers, target.server_digest_header)
                )
                if target.server_digest_header
                else None
            )
            if target.server_digest_header and server_sha256 is None:
                raise BlobTransferError(
                    "upload response omitted its contracted digest",
                    code="BLOB_UPLOAD_RECEIPT_INVALID",
                    stage="upload_receipt",
                    details={"write_may_have_occurred": True},
                )
            if server_sha256 is not None and server_sha256 != sha256:
                raise BlobTransferError(
                    "upload response digest does not match the local source",
                    code="BLOB_UPLOAD_RECEIPT_INVALID",
                    stage="upload_receipt",
                    details={"write_may_have_occurred": True},
                )
            return UploadReceipt(
                source=source_path,
                size_bytes=size_bytes,
                sha256=sha256,
                content_type=content_type,
                server_receipt=server_receipt,
                server_sha256=server_sha256,
            )
        finally:
            _close_response(response)

    def _open_download(
        self,
        url: str,
        policy: BlobPolicy,
        *,
        request_headers: Mapping[str, str],
    ) -> tuple[Any, str]:
        current = url
        redirects = 0
        while True:
            try:
                response = self._transport.open_download(
                    current,
                    headers=request_headers,
                    timeout=policy.request_timeout_seconds,
                )
            except Exception as exc:
                raise BlobTransferError(
                    "download request failed",
                    code="BLOB_TRANSPORT_ERROR",
                    stage="request",
                    retryable=True,
                ) from exc
            status = int(getattr(response, "status_code", 0))
            if status not in _REDIRECT_STATUSES:
                return response, current
            location = _header(response.headers, "Location")
            _close_response(response)
            if not location:
                raise BlobTransferError(
                    "redirect response omitted Location",
                    code="BLOB_REDIRECT_INVALID",
                    stage="headers",
                )
            redirects += 1
            if redirects > policy.max_redirects:
                raise BlobTransferError(
                    "download exceeded the redirect limit",
                    code="BLOB_REDIRECT_LIMIT",
                    stage="headers",
                )
            current = urljoin(current, location)
            _validate_remote_url(
                current,
                policy,
                allowed_hosts=policy.allowed_redirect_hosts,
                declared_path=None,
            )
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


def _validate_download_authorization(
    source: AuthorizedBlobSource,
    policy: BlobPolicy,
    now: datetime,
) -> None:
    _validate_authorized_source(source, policy, now)
    if not policy.require_effect_receipt:
        return
    # Keep the standalone blob core independent from the Insight registry.
    from .registry import _consume_authorized_blob_download

    _consume_authorized_blob_download(source.effect_receipt, source=source)

def _close_response(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
