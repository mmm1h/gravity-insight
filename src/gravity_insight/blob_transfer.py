"""Download and upload orchestration for authorized blobs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urljoin

from .blob_download import (
    _download_request_headers,
    _finish_download,
)
from .blob_headers import _preflight_headers
from .blob_models import (
    AuthorizedBlobSource, AuthorizedUploadTarget, BlobFinalizer, BlobMetadata,
    BlobReceipt, BlobResumeState, BlobTransferError, BlobTransport,
    RequestsBlobTransport, SafeLocalSource, UploadReceipt,
)
from .blob_policy import (
    BlobPolicy, _header, _normalize_expected_digest, _normalize_expected_md5,
    _validate_authorized_source, _validate_declared_size, _validate_remote_url,
)
from .blob_storage import _new_staging_path, _prepare_destination, _validate_resume_state
from .blob_upload import (
    _hash_and_inspect_upload,
    _prepare_upload,
    _read_upload_receipt,
    _send_upload,
)

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
        expected_md5 = _normalize_expected_md5(source.expected_md5)
        resume_path = _validate_resume_state(resume, policy)
        response, _ = self._open_download(
            source.url,
            policy,
            request_headers=_download_request_headers(resume),
        )
        staging_path: Path | None = None
        preserve_staging = False
        try:
            header_info = _preflight_headers(
                response,
                source,
                policy,
                resume=resume,
            )
            staging_path = _new_staging_path(destination_path.parent)
            try:
                receipt, unlink_staging = _finish_download(
                    response,
                    source,
                    policy,
                    header_info,
                    destination_path=destination_path,
                    extension=extension,
                    expected_digest=expected_digest,
                    expected_md5=expected_md5,
                    resume=resume,
                    resume_path=resume_path,
                    staging_path=staging_path,
                    finalizer=finalizer,
                    observer=observer,
                )
            except BlobTransferError as exc:
                if exc.resume_state is not None:
                    preserve_staging = True
                raise
            if not unlink_staging:
                staging_path = None
            return receipt
        finally:
            _close_response(response)
            if staging_path is not None and not preserve_staging:
                _unlink_quietly(staging_path)

    def upload(
        self,
        source: SafeLocalSource,
        target: AuthorizedUploadTarget,
        policy: BlobPolicy,
    ) -> UploadReceipt:
        source_path, extension, content_type = _prepare_upload(
            source.relative_path,
            target,
            policy,
            self._wall_clock(),
        )
        size_bytes, sha256 = _hash_and_inspect_upload(
            source_path,
            extension,
            content_type,
            policy,
        )
        response = _send_upload(
            self._transport,
            target,
            source_path,
            content_type,
            policy,
        )
        try:
            return _read_upload_receipt(
                response,
                target,
                source_path,
                size_bytes,
                sha256,
                content_type,
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
