"""Governed local transfer for binary sources resolved by trusted adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from .agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from .artifact_transfer_errors import (
    ArtifactTransferError,
    ArtifactTransferHttpError,
    translate_blob_error,
)
from .blob_models import (
    AuthorizedBlobSource,
    BlobMetadata,
    BlobTransferError,
    BlobTransport,
    MagicSignature,
)
from .blob_policy import BlobPolicy
from .blob_storage import _prepare_destination
from .blob_transfer import SafeBlobTransfer
from .errors import ErrorCategory
from .paths import STATE_ROOT
from .receipt import (
    PRODUCTION_HTTP_KIND,
    capture_http_receipt_references,
    perform_http_request,
    request_receipt_context,
)
from .result_audit import bind_error_receipts


SCHEMA_VERSION = "gravity.artifact-transfer.v1"
_LIMITATIONS = (
    "local_file_reference_only",
    "same_host_redirects_only",
    "source_url_redacted",
)
_HOST_SHARD = re.compile(r"^([pv])\d+-")


@dataclass(frozen=True)
class _ArtifactTypeContract:
    media_type: str
    extensions: tuple[str, ...]
    magic_signatures: Mapping[str, tuple[MagicSignature, ...]]
    max_bytes: int
    allowed_sources: Mapping[str, tuple[str, ...]]
    max_redirects: int = 3
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class _PreparedArtifactTransfer:
    destination: str
    local_ref: str
    policy: BlobPolicy
    type_contract: _ArtifactTypeContract


@dataclass(frozen=True)
class _ResolvedArtifactSource:
    url: str
    source_capability: str
    source_operation_id: str
    reference_field: str
    reference_value: str | int
    role: str
    declared_size: int | None = None
    expected_md5: str | None = None


@dataclass(frozen=True)
class _ArtifactTransferOutcome:
    artifact: dict[str, Any]
    receipt_references: tuple[Mapping[str, str], ...]


class ArtifactTransferService:
    """Internal owner used only after a trusted adapter resolves a private URL."""

    def __init__(
        self,
        transport: BlobTransport | None = None,
        *,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def prepare(
        self,
        destination: str | Path,
        type_contract: _ArtifactTypeContract,
        *,
        output_root: str | Path | None = None,
    ) -> _PreparedArtifactTransfer:
        """Bind and validate the local output before any source read may run."""

        _validate_type_contract(type_contract)
        root, relative = _output_binding(destination, output_root)
        policy = BlobPolicy(
            allowed_extensions=frozenset(type_contract.extensions),
            allowed_mime_types=frozenset({type_contract.media_type}),
            magic_signatures=type_contract.magic_signatures,
            mime_types_by_extension={
                extension: (type_contract.media_type,)
                for extension in type_contract.extensions
            },
            max_declared_size_bytes=type_contract.max_bytes,
            max_stream_size_bytes=type_contract.max_bytes,
            destination_root=root,
            temporary_root=root,
            overwrite_policy="deny",
            max_redirects=type_contract.max_redirects,
            request_timeout_seconds=type_contract.timeout_seconds,
        )
        try:
            destination_path, _extension = _prepare_destination(relative, policy)
        except BlobTransferError as exc:
            raise translate_blob_error(exc, network_started=False) from exc
        local_ref = destination_path.relative_to(root).as_posix()
        if len(local_ref) > 1024:
            raise ArtifactTransferError(
                "Artifact local reference exceeds its contract limit",
                code="ARTIFACT_OUTPUT_DENIED",
                category=ErrorCategory.CALLER,
                stage="destination_policy",
                reason_category="output_policy",
                field="output",
                next_action="Choose a shorter relative output beneath the same root.",
            )
        return _PreparedArtifactTransfer(relative, local_ref, policy, type_contract)

    def transfer(
        self,
        prepared: _PreparedArtifactTransfer,
        source: _ResolvedArtifactSource,
    ) -> _ArtifactTransferOutcome:
        """Stream, verify and publish one already-resolved private Artifact URL."""

        _validate_resolved_source(source)
        host, declared_path = _private_url_identity(source.url)
        policy = replace(
            prepared.policy,
            allowed_hosts=frozenset(prepared.type_contract.allowed_sources),
            allowed_redirect_hosts=frozenset({host}),
            allowed_path_prefixes={},
            allowed_path_patterns=prepared.type_contract.allowed_sources,
        )
        now = self._wall_clock()
        authorized = AuthorizedBlobSource(
            url=source.url,
            declared_path=declared_path,
            expires_at=now + timedelta(seconds=policy.request_timeout_seconds + 1),
            authorization_scope=source.source_capability,
            declared_size=source.declared_size,
            declared_mime_type=prepared.type_contract.media_type,
            expected_md5=source.expected_md5,
        )
        transport = _TrackingTransport(
            self._transport
            or _RequestsArtifactTransport(source.source_capability)
        )
        artifact: dict[str, Any] | None = None

        def validate_before_commit(_stage: str, metadata: BlobMetadata) -> None:
            nonlocal artifact
            artifact = _artifact_result(
                prepared,
                source,
                size_bytes=metadata.size_bytes,
                content_type=metadata.content_type,
                extension=metadata.extension,
                digest=metadata.sha256,
                urls=transport.urls,
            )
            try:
                validate_artifact_transfer(artifact)
            except AgentRuntimeContractError as exc:
                raise BlobTransferError(
                    "Artifact metadata failed its pre-commit contract",
                    code="BLOB_POLICY_INVALID",
                    stage="integrity",
                ) from exc

        with capture_http_receipt_references() as references:
            try:
                SafeBlobTransfer(
                    transport,
                    wall_clock=lambda: now,
                ).download(
                    authorized,
                    prepared.destination,
                    policy,
                    observer=validate_before_commit,
                )
            except BlobTransferError as exc:
                translated = translate_blob_error(
                    exc, network_started=bool(transport.urls)
                )
                bind_error_receipts(translated, references)
                raise translated from exc
            if artifact is None:
                raise ArtifactTransferError(
                    "Artifact transfer completed without pre-commit metadata",
                    code="ARTIFACT_CONTRACT_CHANGED",
                    category=ErrorCategory.LOCAL,
                    stage="commit",
                    reason_category="contract",
                    next_action="Stop automation and verify the installed Artifact Transfer contract.",
                )
        return _ArtifactTransferOutcome(artifact, tuple(references))


class _RequestsArtifactTransport:
    def __init__(
        self,
        operation_id: str,
        session: requests.Session | None = None,
    ) -> None:
        self._operation_id = operation_id
        self._session = session or requests.Session()

    def open_download(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        return perform_http_request(
            self._session.get,
            url,
            kind=PRODUCTION_HTTP_KIND,
            headers=dict(headers),
            timeout=timeout,
            stream=True,
            allow_redirects=False,
            http_receipt=request_receipt_context(
                operation_id=self._operation_id,
                method="GET",
                path="/<response-bound-artifact-binary>",
                effect="stream",
            ),
            receipt_root=STATE_ROOT,
        )


class _TrackingTransport:
    def __init__(self, delegate: BlobTransport) -> None:
        self._delegate = delegate
        self.urls: list[str] = []

    def open_download(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        self.urls.append(url)
        return self._delegate.open_download(url, headers=headers, timeout=timeout)


def validate_artifact_transfer(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one complete public Artifact metadata object."""

    selected = dict(value)
    validate_schema(selected, "artifact-transfer-v1.schema.json", "Artifact Transfer")
    local_ref = str(selected["local_ref"])
    path = PurePosixPath(local_ref)
    if (
        path.is_absolute()
        or "\\" in local_ref
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise AgentRuntimeContractError("Artifact local_ref must stay relative")
    digest = str(selected["sha256"])
    if selected["artifact_id"] != f"sha256:{digest}":
        raise AgentRuntimeContractError("Artifact identity and digest disagree")
    if (selected["extension"], selected["media_type"]) not in {
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".mp4", "video/mp4"),
    }:
        raise AgentRuntimeContractError("Artifact extension and MIME disagree")
    transfer = selected["transfer"]
    if transfer["initial_host_family"] != transfer["final_host_family"]:
        raise AgentRuntimeContractError("Artifact same-host redirect facts disagree")
    if tuple(selected["limitations"]) != _LIMITATIONS:
        raise AgentRuntimeContractError("Artifact limitations changed")
    return selected


def _output_binding(
    destination: str | Path, output_root: str | Path | None
) -> tuple[Path, str]:
    try:
        selected = Path(destination)
        if output_root is None and selected.is_absolute():
            root = selected.parent
            relative = selected.name
        else:
            root = Path.cwd() if output_root is None else Path(output_root)
            relative = os.fspath(selected)
        return Path(os.path.abspath(root)), relative
    except (TypeError, ValueError, OSError) as exc:
        raise ArtifactTransferError(
            "Artifact output path is invalid",
            code="ARTIFACT_OUTPUT_DENIED",
            category=ErrorCategory.CALLER,
            stage="destination_policy",
            reason_category="output_policy",
            field="output",
            next_action="Choose a relative output under an existing plain output root.",
        ) from exc


def _validate_type_contract(contract: _ArtifactTypeContract) -> None:
    bindings = {
        "image/jpeg": frozenset({".jpg", ".jpeg"}),
        "video/mp4": frozenset({".mp4"}),
    }
    extensions = frozenset(contract.extensions)
    valid = (
        bool(extensions)
        and len(extensions) == len(contract.extensions)
        and extensions <= bindings.get(contract.media_type, frozenset())
        and set(contract.magic_signatures) == set(extensions)
        and all(contract.magic_signatures[value] for value in extensions)
        and 0 < contract.max_bytes <= 1024 * 1024 * 1024
        and 0 <= contract.max_redirects <= 3
        and 0 < contract.timeout_seconds <= 300
        and _valid_allowed_sources(contract.allowed_sources)
    )
    if not valid:
        raise ArtifactTransferError(
            "Artifact type policy is invalid",
            code="ARTIFACT_CONTRACT_CHANGED",
            category=ErrorCategory.LOCAL,
            stage="destination_policy",
            reason_category="contract",
            next_action="Stop automation and verify the installed Artifact Transfer contract.",
        )


def _valid_path_pattern(value: str) -> bool:
    try:
        re.compile(value)
    except re.error:
        return False
    return True


def _valid_allowed_sources(value: Mapping[str, tuple[str, ...]]) -> bool:
    if not value:
        return False
    for host, patterns in value.items():
        if (
            not isinstance(host, str)
            or host != host.casefold()
            or any(character in host for character in "/*:@[]\\\r\n")
            or not patterns
        ):
            return False
        if any(
            not isinstance(pattern, str)
            or not pattern
            or len(pattern) > 512
            or not _valid_path_pattern(pattern)
            for pattern in patterns
        ):
            return False
    return True


def _validate_resolved_source(source: _ResolvedArtifactSource) -> None:
    reference = source.reference_value
    if (
        isinstance(reference, bool)
        or not isinstance(reference, (str, int))
        or reference == ""
        or isinstance(reference, str)
        and len(reference) > 256
    ):
        raise ArtifactTransferError(
            "Artifact source reference is invalid",
            code="ARTIFACT_REFERENCE_INVALID",
            category=ErrorCategory.CALLER,
            stage="source_policy",
            reason_category="reference",
            field="ref",
            next_action="Choose one exact documented reference from the fresh source response.",
        )


def _private_url_identity(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
    except (TypeError, ValueError) as exc:
        raise ArtifactTransferError(
            "fresh source response contains a malformed Artifact URL",
            code="ARTIFACT_SOURCE_DENIED",
            category=ErrorCategory.UPSTREAM,
            stage="source_policy",
            reason_category="source_policy",
            next_action="Refresh the registered source operation once and retry the same reference.",
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        raise ArtifactTransferError(
            "fresh source response contains a denied Artifact URL",
            code="ARTIFACT_SOURCE_DENIED",
            category=ErrorCategory.UPSTREAM,
            stage="source_policy",
            reason_category="source_policy",
            next_action="Refresh the registered source operation once; do not construct or edit its URL.",
        )
    return host, parsed.path


def _artifact_result(
    prepared: _PreparedArtifactTransfer,
    source: _ResolvedArtifactSource,
    *,
    size_bytes: int,
    content_type: str,
    extension: str,
    digest: str,
    urls: Sequence[str],
) -> dict[str, Any]:
    initial_host = (urlsplit(urls[0]).hostname or "").casefold()
    final_host = (urlsplit(urls[-1]).hostname or "").casefold()
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": f"sha256:{digest}",
        "status": "complete",
        "local_ref": prepared.local_ref,
        "size_bytes": size_bytes,
        "media_type": content_type,
        "extension": extension,
        "sha256": digest,
        "source": {
            "capability": source.source_capability,
            "operation_id": source.source_operation_id,
            "response_fresh": True,
            "reference_field": source.reference_field,
            "reference_value": source.reference_value,
            "role": source.role,
            "caller_url_accepted": False,
        },
        "transfer": {
            "streaming": True,
            "max_bytes": prepared.type_contract.max_bytes,
            "redirect_policy": "same_host_only",
            "redirect_count": max(0, len(urls) - 1),
            "initial_host_family": _host_family(initial_host),
            "final_host_family": _host_family(final_host),
            "cross_host_redirect": initial_host != final_host,
            "output_root_bound": True,
        },
        "integrity": {
            "source_size_verified": source.declared_size is not None,
            "source_md5_verified": source.expected_md5 is not None,
            "magic_verified": True,
            "sha256_computed": True,
            "atomic_commit": True,
            "overwrite": "denied",
        },
        "limitations": list(_LIMITATIONS),
    }


def _host_family(host: str) -> str:
    return _HOST_SHARD.sub(r"\1{shard}-", host)


__all__ = [
    "ArtifactTransferError",
    "ArtifactTransferHttpError",
    "SCHEMA_VERSION",
    "validate_artifact_transfer",
]
