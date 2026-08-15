"""Streaming transfer for URLs obtained from a fresh registered response."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import requests

from .blob_policy import BlobPolicy, _header
from .blob_storage import _new_staging_path
from .blob_verify import _commit_staging
from .errors import (
    ContractChangedError,
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    LocalIOError,
    UpstreamUnavailableError,
)
from .paths import STATE_ROOT
from .receipt import perform_http_request, request_receipt_context


class _AssetTransport(Protocol):
    def open_download(self, url: str, *, timeout: float) -> Any: ...


class _RequestsAssetTransport:
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def open_download(self, url: str, *, timeout: float) -> requests.Response:
        return perform_http_request(
            self._session.get,
            url,
            headers={"Accept-Encoding": "identity"},
            timeout=timeout,
            stream=True,
            allow_redirects=True,
            http_receipt=request_receipt_context(
                operation_id="material.asset.fetch",
                method="GET",
                path="/<response-bound-material-binary>",
            ),
            receipt_root=STATE_ROOT,
        )


class MaterialAssetHttpError(GravityInsightError):
    """An actual terminal asset HTTP status, always owned by upstream."""

    category = ErrorCategory.UPSTREAM

    def __init__(self, status: int) -> None:
        if status in {401, 403}:
            code = ErrorCode.PERMISSION_UNAVAILABLE
            action = "Refresh the source operation once and confirm upstream asset access."
        elif status == 429:
            code = ErrorCode.RATE_LIMITED
            action = "Wait for the upstream limit to clear, then repeat the same fetch once."
        else:
            code = ErrorCode.UPSTREAM_UNAVAILABLE
            action = "Refresh the source operation once; do not construct or edit the asset URL."
        super().__init__(
            f"response-bound material asset returned HTTP {status}",
            code=code,
            next_action=action,
        )
        self.status = status
        self.retryable = status in {408, 425, 429} or status >= 500

    def to_error_detail(
        self, *, operation_id: str | None = None, next_action: str | None = None
    ) -> ErrorDetail:
        return ErrorDetail.create(
            self.code,
            self,
            operation_id=operation_id,
            category=self.category,
            retryable=self.retryable,
            next_action=next_action or self.next_action,
        )


def _download_response_bound_asset(
    url: str,
    item: Mapping[str, Any],
    role: str,
    role_contract: Mapping[str, Any],
    source_contract: Mapping[str, Any],
    destination: str | Path,
    *,
    transport: _AssetTransport | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    destination_path = _destination_path(destination)
    staging = _new_staging_path(destination_path.parent)
    response: Any | None = None
    committed = False
    try:
        response = _open_response(url, transport, timeout_seconds)
        verified = _verify_response(
            response, staging, item, role, role_contract, source_contract
        )
        _commit_staging(
            staging,
            destination_path,
            BlobPolicy(destination_root=destination_path.parent),
        )
        committed = True
        facts = _redirect_facts(url, response)
        return {
            "destination": str(destination_path),
            "complete": True,
            **verified,
            **facts,
        }
    finally:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if not committed:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass


def _open_response(
    url: str, transport: _AssetTransport | None, timeout_seconds: float
) -> Any:
    try:
        response = (transport or _RequestsAssetTransport()).open_download(
            url, timeout=timeout_seconds
        )
    except Exception as exc:
        raise UpstreamUnavailableError(
            "response-bound material asset request failed",
            next_action=(
                "Refresh the source operation once; do not construct or edit the asset URL."
            ),
        ) from exc
    status = int(getattr(response, "status_code", 0))
    if status != 200:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise MaterialAssetHttpError(status)
    return response


def _verify_response(
    response: Any,
    staging: Path,
    item: Mapping[str, Any],
    role: str,
    role_contract: Mapping[str, Any],
    source_contract: Mapping[str, Any],
) -> dict[str, Any]:
    content_type = _content_type(response)
    content_length = _content_length(response)
    size, sha256, md5, prefix = _stream_to_staging(response, staging)
    if content_length is not None and size != content_length:
        raise ContractChangedError(
            "material asset byte count differs from Content-Length"
        )
    declared_size = _declared_size(item, source_contract, role)
    if declared_size is not None and size != declared_size:
        raise ContractChangedError(
            "material asset byte count differs from its source response"
        )
    declared_md5 = _declared_md5(item, source_contract, role)
    if declared_md5 is not None and md5 != declared_md5:
        raise ContractChangedError("material asset MD5 differs from its source response")
    magic_type = _magic_type(prefix)
    observed_type = role_contract.get("observed_content_type")
    observed_magic = role_contract.get("observed_magic_type")
    if content_type != observed_type or magic_type != observed_magic:
        raise ContractChangedError(
            "material asset MIME or magic bytes changed from the verified contract"
        )
    return {
        "size_bytes": size,
        "sha256": sha256,
        "content_type": content_type,
        "magic_type": magic_type,
        "source_size_verified": declared_size is not None,
        "source_md5_verified": declared_md5 is not None,
    }


def _destination_path(destination: str | Path) -> Path:
    try:
        path = Path(destination)
    except (TypeError, ValueError) as exc:
        raise LocalIOError("material asset output path is invalid") from exc
    parent = Path(os.path.abspath(path.parent))
    if not parent.is_dir():
        raise LocalIOError("material asset output parent directory does not exist")
    return parent / path.name


def _content_type(response: Any) -> str:
    raw = _header(getattr(response, "headers", {}), "Content-Type")
    if not raw or "/" not in raw:
        raise ContractChangedError("material asset response omitted Content-Type")
    return raw.split(";", 1)[0].strip().casefold()


def _content_length(response: Any) -> int | None:
    raw = _header(getattr(response, "headers", {}), "Content-Length")
    if raw is None:
        return None
    if not raw.isdigit():
        raise ContractChangedError("material asset Content-Length is malformed")
    return int(raw)


def _stream_to_staging(
    response: Any, staging: Path
) -> tuple[int, str, str, bytes]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    prefix = bytearray()
    iterator = getattr(response, "iter_content", None)
    if not callable(iterator):
        raise ContractChangedError("material asset response is not streamable")
    try:
        with staging.open("wb") as output:
            try:
                for value in iterator(chunk_size=64 * 1024):
                    if not isinstance(value, (bytes, bytearray)):
                        raise ContractChangedError(
                            "material asset stream yielded a non-byte chunk"
                        )
                    chunk = bytes(value)
                    if not chunk:
                        continue
                    if len(prefix) < 32:
                        prefix.extend(chunk[: 32 - len(prefix)])
                    output.write(chunk)
                    size += len(chunk)
                    sha256.update(chunk)
                    md5.update(chunk)
            except ContractChangedError:
                raise
            except requests.RequestException as exc:
                raise UpstreamUnavailableError(
                    "material asset stream ended before completion"
                ) from exc
            output.flush()
            os.fsync(output.fileno())
    except GravityInsightError:
        raise
    except OSError as exc:
        raise LocalIOError("could not write the material asset staging file") from exc
    return size, sha256.hexdigest(), md5.hexdigest(), bytes(prefix)


def _declared_size(
    item: Mapping[str, Any], source: Mapping[str, Any], role: str
) -> int | None:
    field = source.get("declared_size_field") if role == "file" else None
    value = item.get(field) if isinstance(field, str) else None
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractChangedError("material asset declared size is malformed") from exc
    if parsed < 0:
        raise ContractChangedError("material asset declared size is negative")
    return parsed


def _declared_md5(
    item: Mapping[str, Any], source: Mapping[str, Any], role: str
) -> str | None:
    field = source.get("declared_md5_field") if role == "file" else None
    value = item.get(field) if isinstance(field, str) else None
    if value in (None, ""):
        return None
    normalized = str(value).strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{32}", normalized):
        raise ContractChangedError("material asset declared MD5 is malformed")
    return normalized


def _magic_type(value: bytes) -> str:
    if value.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(value) >= 12 and value[4:8] == b"ftyp":
        return "iso-bmff"
    return "unknown"


def _redirect_facts(source_url: str, response: Any) -> dict[str, Any]:
    final_url = str(getattr(response, "url", source_url) or source_url)
    initial_host = (urlsplit(source_url).hostname or "").casefold()
    final_host = (urlsplit(final_url).hostname or "").casefold()
    return {
        "initial_host_family": _host_family(initial_host),
        "final_host_family": _host_family(final_host),
        "redirect_count": len(getattr(response, "history", ()) or ()),
        "cross_host_redirect": initial_host != final_host,
    }


def _host_family(host: str) -> str:
    return re.sub(r"^([vp])\d+-", r"\1{shard}-", host)


__all__ = ["MaterialAssetHttpError"]
