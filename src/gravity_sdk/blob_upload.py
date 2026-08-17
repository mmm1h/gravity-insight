"""Upload authorization and receipt helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .blob_models import (
    AuthorizedUploadTarget,
    BlobTransferError,
    BlobTransport,
    UploadReceipt,
)
from .blob_policy import (
    BlobPolicy,
    _header,
    _normalize_expected_digest,
    _runtime_mime,
    _select_extension,
    _validate_declared_size,
    _validate_expiry,
    _validate_remote_url,
)
from .blob_storage import _hash_regular_file, _prepare_local_source
from .blob_verify import _inspect_type_and_archive

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _prepare_upload(
    source_relative_path: str | Path,
    target: AuthorizedUploadTarget,
    policy: BlobPolicy,
    now: datetime,
) -> tuple[Path, str, str]:
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
    source_path = _prepare_local_source(source_relative_path, policy.upload_root)
    extension = _select_extension(source_path.name, policy.allowed_extensions)
    content_type = _runtime_mime(target.content_type, stage="upload_policy")
    _validate_remote_url(
        target.url,
        policy,
        allowed_hosts=policy.allowed_hosts,
        declared_path=target.declared_path,
    )
    _validate_expiry(target.expires_at, now)
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
    return source_path, extension, content_type


def _hash_and_inspect_upload(
    source_path: Path,
    extension: str,
    content_type: str,
    policy: BlobPolicy,
) -> tuple[int, str]:
    size_bytes, sha256 = _hash_regular_file(
        source_path,
        policy.max_stream_size_bytes,
        policy.chunk_size,
    )
    _validate_declared_size(size_bytes, policy)
    _inspect_type_and_archive(source_path, extension, content_type, policy)
    return size_bytes, sha256


def _send_upload(
    transport: BlobTransport,
    target: AuthorizedUploadTarget,
    source_path: Path,
    content_type: str,
    policy: BlobPolicy,
) -> Any:
    try:
        return transport.upload(
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


def _read_upload_receipt(
    response: Any,
    target: AuthorizedUploadTarget,
    source_path: Path,
    size_bytes: int,
    sha256: str,
    content_type: str,
) -> UploadReceipt:
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
