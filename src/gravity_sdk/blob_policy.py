"""Authorization and size policy validation for blob transfers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from .blob_models import ArchivePolicy, BlobTransferError, MagicSignature

_DEFAULT_MAX_BYTES = 100 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

@dataclass(frozen=True)
class BlobPolicy:
    allowed_extensions: frozenset[str] = frozenset()
    allowed_mime_types: frozenset[str] = frozenset()
    magic_signatures: Mapping[str, tuple[MagicSignature, ...]] = field(default_factory=dict)
    mime_types_by_extension: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    max_declared_size_bytes: int = _DEFAULT_MAX_BYTES
    max_stream_size_bytes: int = _DEFAULT_MAX_BYTES
    allowed_hosts: frozenset[str] = frozenset()
    allowed_redirect_hosts: frozenset[str] = frozenset()
    allowed_path_prefixes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    allowed_https_ports: frozenset[int] = frozenset({443})
    archive_policy: ArchivePolicy = field(default_factory=ArchivePolicy)
    overwrite_policy: str = "deny"
    destination_root: Path | None = None
    temporary_root: Path | None = None
    allow_range_resume: bool = False
    max_redirects: int = 3
    chunk_size: int = 64 * 1024
    request_timeout_seconds: float = 60.0
    allow_upload: bool = False
    upload_root: Path | None = None
    require_effect_receipt: bool = False

    def __post_init__(self) -> None:
        normalized = _normalize_policy_fields(self)
        _validate_policy_numeric_limits(self)
        _validate_policy_type_bindings(
            normalized[0],
            normalized[1],
            normalized[4],
            normalized[5],
        )
        _commit_normalized_policy(self, normalized)


def _normalize_policy_fields(
    policy: BlobPolicy,
) -> tuple[
    frozenset[str],
    frozenset[str],
    frozenset[str],
    frozenset[str],
    dict[str, tuple[MagicSignature, ...]],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    extensions = frozenset(_normalize_extension(value) for value in policy.allowed_extensions)
    mime_types = frozenset(_normalize_mime(value) for value in policy.allowed_mime_types)
    hosts = frozenset(_normalize_host(value) for value in policy.allowed_hosts)
    redirect_hosts = frozenset(
        _normalize_host(value) for value in policy.allowed_redirect_hosts
    )
    magic = {
        _normalize_extension(extension): tuple(signatures)
        for extension, signatures in policy.magic_signatures.items()
    }
    mime_by_extension = {
        _normalize_extension(extension): tuple(
            _normalize_mime(mime) for mime in extension_mimes
        )
        for extension, extension_mimes in policy.mime_types_by_extension.items()
    }
    prefixes: dict[str, tuple[str, ...]] = {}
    for host, values in policy.allowed_path_prefixes.items():
        normalized_host = _normalize_host(host)
        normalized_values = tuple(_normalize_path_prefix(value) for value in values)
        prefixes[normalized_host] = normalized_values
    return (
        extensions,
        mime_types,
        hosts,
        redirect_hosts,
        magic,
        mime_by_extension,
        prefixes,
    )


def _validate_policy_numeric_limits(policy: BlobPolicy) -> None:
    if policy.max_declared_size_bytes <= 0 or policy.max_stream_size_bytes <= 0:
        raise ValueError("blob size caps must be positive")
    if policy.max_redirects < 0:
        raise ValueError("max_redirects cannot be negative")
    if policy.chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if policy.request_timeout_seconds <= 0:
        raise ValueError("request timeout must be positive")
    if policy.overwrite_policy not in {"deny", "replace"}:
        raise ValueError("overwrite_policy must be 'deny' or 'replace'")
    if not policy.allowed_https_ports or any(
        port < 1 or port > 65535 for port in policy.allowed_https_ports
    ):
        raise ValueError("allowed HTTPS ports must be between 1 and 65535")


def _validate_policy_type_bindings(
    extensions: frozenset[str],
    mime_types: frozenset[str],
    magic: Mapping[str, tuple[MagicSignature, ...]],
    mime_by_extension: Mapping[str, tuple[str, ...]],
) -> None:
    if not set(magic).issubset(extensions):
        raise ValueError("magic signatures must be keyed by an allowed extension")
    if not set(mime_by_extension).issubset(extensions):
        raise ValueError("MIME bindings must be keyed by an allowed extension")
    if any(not signatures for signatures in magic.values()):
        raise ValueError("each magic binding must contain at least one signature")
    if any(
        not isinstance(signature, MagicSignature)
        for signatures in magic.values()
        for signature in signatures
    ):
        raise ValueError("magic bindings must contain MagicSignature values")
    if any(not values for values in mime_by_extension.values()):
        raise ValueError("each extension MIME binding must be non-empty")
    if any(
        mime not in mime_types
        for values in mime_by_extension.values()
        for mime in values
    ):
        raise ValueError("extension MIME bindings must use allowed MIME types")


def _commit_normalized_policy(
    policy: BlobPolicy,
    normalized: tuple[
        frozenset[str],
        frozenset[str],
        frozenset[str],
        frozenset[str],
        dict[str, tuple[MagicSignature, ...]],
        dict[str, tuple[str, ...]],
        dict[str, tuple[str, ...]],
    ],
) -> None:
    (
        extensions,
        mime_types,
        hosts,
        redirect_hosts,
        magic,
        mime_by_extension,
        prefixes,
    ) = normalized
    object.__setattr__(policy, "allowed_extensions", extensions)
    object.__setattr__(policy, "allowed_mime_types", mime_types)
    object.__setattr__(policy, "allowed_hosts", hosts)
    object.__setattr__(policy, "allowed_redirect_hosts", redirect_hosts)
    object.__setattr__(policy, "allowed_https_ports", frozenset(policy.allowed_https_ports))
    object.__setattr__(policy, "magic_signatures", MappingProxyType(magic))
    object.__setattr__(
        policy,
        "mime_types_by_extension",
        MappingProxyType(mime_by_extension),
    )
    object.__setattr__(policy, "allowed_path_prefixes", MappingProxyType(prefixes))
    object.__setattr__(
        policy,
        "destination_root",
        Path(policy.destination_root) if policy.destination_root is not None else None,
    )
    object.__setattr__(
        policy,
        "temporary_root",
        Path(policy.temporary_root) if policy.temporary_root is not None else None,
    )
    object.__setattr__(
        policy,
        "upload_root",
        Path(policy.upload_root) if policy.upload_root is not None else None,
    )


def _validate_authorized_source(
    source: AuthorizedBlobSource,
    policy: BlobPolicy,
    now: datetime,
) -> None:
    if not isinstance(source.authorization_scope, str) or not source.authorization_scope.strip():
        raise BlobTransferError(
            "blob source lacks an authorization scope",
            code="BLOB_AUTHORIZATION_INVALID",
            stage="source_policy",
        )
    if not isinstance(source.declared_mime_type, str) or not source.declared_mime_type.strip():
        raise BlobTransferError(
            "blob source lacks a declared MIME type",
            code="BLOB_AUTHORIZATION_INVALID",
            stage="source_policy",
        )
    _validate_expiry(source.expires_at, now)
    _validate_remote_url(
        source.url,
        policy,
        allowed_hosts=policy.allowed_hosts,
        declared_path=source.declared_path,
    )


def _validate_expiry(expires_at: datetime, now: datetime) -> None:
    if (
        not isinstance(expires_at, datetime)
        or not isinstance(now, datetime)
        or expires_at.tzinfo is None
        or now.tzinfo is None
    ):
        raise BlobTransferError(
            "authorized URL expiry must be timezone-aware",
            code="BLOB_AUTHORIZATION_INVALID",
            stage="source_policy",
        )
    if expires_at <= now:
        raise BlobTransferError(
            "authorized URL has expired",
            code="BLOB_URL_EXPIRED",
            stage="source_policy",
        )


def _validate_remote_url(
    url: str,
    policy: BlobPolicy,
    *,
    allowed_hosts: frozenset[str],
    declared_path: str | None,
) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise BlobTransferError(
            "authorized blob URL is malformed",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        ) from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise BlobTransferError(
            "blob URLs must use HTTPS with an explicit host",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        )
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise BlobTransferError(
            "blob URL contains forbidden authority or fragment data",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        )
    try:
        host = _normalize_host(parsed.hostname)
    except ValueError as exc:
        raise BlobTransferError(
            "blob URL host is malformed",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        ) from exc
    if host not in allowed_hosts or port not in policy.allowed_https_ports:
        raise BlobTransferError(
            "blob URL host or port is outside the allowlist",
            code="BLOB_URL_DENIED",
            stage="source_policy",
            details={"host": host, "port": port},
        )
    raw_path = parsed.path
    if declared_path is not None and raw_path != declared_path:
        raise BlobTransferError(
            "blob URL path does not match the authorized status declaration",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        )
    safe_path = _decode_and_validate_url_path(raw_path)
    prefixes = policy.allowed_path_prefixes.get(host, ())
    if not any(_path_has_prefix(safe_path, prefix) for prefix in prefixes):
        raise BlobTransferError(
            "blob URL path is outside the allowlist",
            code="BLOB_URL_DENIED",
            stage="source_policy",
            details={"host": host},
        )


def _decode_and_validate_url_path(path: str) -> str:
    decoded = path
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "//" in decoded
        or "\x00" in decoded
        or "\\" in decoded
    ):
        raise BlobTransferError(
            "blob URL path is unsafe",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        )
    if any(part in {".", ".."} for part in PurePosixPath(decoded).parts):
        raise BlobTransferError(
            "blob URL path contains traversal",
            code="BLOB_URL_DENIED",
            stage="source_policy",
        )
    return decoded


def _path_has_prefix(path: str, prefix: str) -> bool:
    if prefix == "/":
        return True
    boundary = prefix.rstrip("/")
    return path == boundary or path.startswith(boundary + "/")


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isdigit():
        raise BlobTransferError(
            "Content-Length is malformed",
            code="BLOB_SIZE_INVALID",
            stage="headers",
        )
    return int(value)
def _validate_declared_size(size: int | None, policy: BlobPolicy) -> None:
    if size is None:
        return
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise BlobTransferError(
            "declared blob size is invalid",
            code="BLOB_SIZE_INVALID",
            stage="headers",
        )
    if size > policy.max_declared_size_bytes or size > policy.max_stream_size_bytes:
        raise BlobTransferError(
            "declared blob size exceeds policy",
            code="BLOB_SIZE_LIMIT",
            stage="headers",
            details={
                "declared": size,
                "declared_limit": policy.max_declared_size_bytes,
                "stream_limit": policy.max_stream_size_bytes,
            },
        )


def _normalize_expected_digest(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized[7:]
    if not _SHA256.fullmatch(normalized):
        raise BlobTransferError(
            "authorized SHA-256 digest is malformed",
            code="BLOB_DIGEST_INVALID",
            stage="source_policy",
        )
    return normalized


def _select_extension(filename: str, allowed: frozenset[str]) -> str:
    lower_name = filename.casefold()
    for extension in sorted(allowed, key=len, reverse=True):
        if lower_name.endswith(extension):
            return extension
    raise BlobTransferError(
        "destination extension is outside the allowlist",
        code="BLOB_EXTENSION_MISMATCH",
        stage="destination_policy",
    )


def _normalize_extension(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized.startswith(".") or len(normalized) < 2:
        raise ValueError("extensions must begin with '.'")
    if any(character in normalized for character in "/\\\x00"):
        raise ValueError("extension contains a path separator")
    return normalized


def _normalize_mime(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or "/" not in normalized or any(
        character in normalized for character in "\r\n"
    ):
        raise ValueError("MIME type is invalid")
    return normalized


def _runtime_mime(value: Any, *, stage: str) -> str:
    if not isinstance(value, str):
        raise BlobTransferError(
            "blob MIME declaration is invalid",
            code="BLOB_MIME_MISMATCH",
            stage=stage,
        )
    try:
        return _normalize_mime(value)
    except ValueError as exc:
        raise BlobTransferError(
            "blob MIME declaration is invalid",
            code="BLOB_MIME_MISMATCH",
            stage=stage,
        ) from exc


def _normalize_host(value: str) -> str:
    normalized = value.strip().casefold().rstrip(".")
    if not normalized or any(character in normalized for character in "/:@[]\r\n"):
        raise ValueError("host allowlist entry is invalid")
    return normalized


def _normalize_path_prefix(value: str) -> str:
    if "?" in value or "#" in value:
        raise ValueError("path prefixes cannot contain query or fragment data")
    try:
        normalized = _decode_and_validate_url_path(value)
    except BlobTransferError as exc:
        raise ValueError("path prefix is unsafe") from exc
    return normalized


def _header(headers: Mapping[str, Any], name: str | None) -> str | None:
    if not name:
        return None
    target = name.casefold()
    items = getattr(headers, "items", None)
    if not callable(items):
        raise BlobTransferError(
            "transport response headers are invalid",
            code="BLOB_TRANSPORT_ERROR",
            stage="headers",
        )
    for key, value in items():
        if str(key).casefold() == target:
            return str(value).strip()
    return None
