"""Blob transfer value objects and transport protocols."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import requests

from .errors import GravityInsightError

class BlobTransferError(GravityInsightError):
    """A structured, caller-safe transfer failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        stage: str,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
        resume_state: BlobResumeState | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable
        self.details = MappingProxyType(dict(details or {}))
        self.resume_state = resume_state

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "stage": self.stage,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class MagicSignature:
    offset: int
    value: bytes

    def __post_init__(self) -> None:
        if self.offset < 0 or not self.value:
            raise ValueError("magic signatures require a non-negative offset and bytes")


@dataclass(frozen=True)
class ArchivePolicy:
    enabled: bool = False
    max_uncompressed_size_bytes: int = 256 * 1024 * 1024
    max_entries: int = 1_000
    max_nested_depth: int = 0
    max_compression_ratio: float = 100.0

    def __post_init__(self) -> None:
        if self.max_uncompressed_size_bytes <= 0:
            raise ValueError("archive uncompressed size cap must be positive")
        if self.max_entries <= 0:
            raise ValueError("archive entry cap must be positive")
        if self.max_nested_depth < 0:
            raise ValueError("archive nested depth cannot be negative")
        if self.max_compression_ratio <= 0:
            raise ValueError("archive compression ratio cap must be positive")
@dataclass(frozen=True)
class AuthorizedBlobSource:
    url: str
    declared_path: str
    expires_at: datetime
    authorization_scope: str
    job_id: str | None = None
    declared_size: int | None = None
    declared_mime_type: str = ""
    expected_sha256: str | None = None
    effect_receipt: object | None = None


@dataclass(frozen=True)
class AuthorizedUploadTarget:
    url: str
    declared_path: str
    expires_at: datetime
    authorization_scope: str
    file_field: str
    content_type: str
    form_fields: Mapping[str, str] = field(default_factory=dict)
    receipt_header: str | None = "X-Upload-Receipt"
    server_digest_header: str | None = None


@dataclass(frozen=True)
class SafeLocalSource:
    relative_path: str | Path


@dataclass(frozen=True)
class BlobResumeState:
    partial_path: Path
    bytes_received: int
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class BlobMetadata:
    size_bytes: int
    sha256: str
    content_type: str
    extension: str
    etag: str | None
    last_modified: str | None
    resumed: bool


@dataclass(frozen=True)
class BlobFinalizationResult:
    schema: tuple[str, ...] = ()
    rows_processed: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)


class BlobFinalizer(Protocol):
    def finalize(
        self,
        source_path: Path,
        output_path: Path,
        metadata: BlobMetadata,
    ) -> BlobFinalizationResult: ...


@dataclass(frozen=True)
class BlobReceipt:
    destination: Path
    size_bytes: int
    source_size_bytes: int
    source_sha256: str
    committed_sha256: str
    content_type: str
    extension: str
    etag: str | None
    last_modified: str | None
    resumed: bool
    finalization: BlobFinalizationResult


@dataclass(frozen=True)
class UploadReceipt:
    source: Path
    size_bytes: int
    sha256: str
    content_type: str
    server_receipt: str | None
    server_sha256: str | None


class BlobTransport(Protocol):
    def open_download(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any: ...

    def upload(
        self,
        url: str,
        *,
        file_path: Path,
        file_field: str,
        content_type: str,
        form_fields: Mapping[str, str],
        timeout: float,
    ) -> Any: ...


class RequestsBlobTransport:
    """The requests-backed transport; tests inject a transport instead."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def open_download(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> requests.Response:
        return self._session.get(
            url,
            headers=dict(headers),
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )

    def upload(
        self,
        url: str,
        *,
        file_path: Path,
        file_field: str,
        content_type: str,
        form_fields: Mapping[str, str],
        timeout: float,
    ) -> requests.Response:
        with file_path.open("rb") as handle:
            return self._session.post(
                url,
                data=dict(form_fields),
                files={file_field: (file_path.name, handle, content_type)},
                timeout=timeout,
                allow_redirects=False,
            )
