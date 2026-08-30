"""Material binding for the shared governed Artifact Transfer service."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from .artifact_transfer import (
    ArtifactTransferHttpError,
    ArtifactTransferService,
    _ArtifactTransferOutcome,
    _ArtifactTypeContract,
    _PreparedArtifactTransfer,
    _ResolvedArtifactSource,
)
from .blob_models import BlobTransport, MagicSignature
from .errors import ContractChangedError


MaterialAssetHttpError = ArtifactTransferHttpError


def _prepare_response_bound_asset(
    role_contract: Mapping[str, Any],
    destination: str | Path,
    *,
    output_root: str | Path | None,
    transport: BlobTransport | None,
) -> tuple[ArtifactTransferService, _PreparedArtifactTransfer]:
    signatures = tuple(
        MagicSignature(int(item["offset"]), bytes.fromhex(str(item["hex"])))
        for item in role_contract["magic_signatures"]
    )
    extensions = tuple(str(value) for value in role_contract["extensions"])
    allowed_sources = {
        str(item["host"]): (str(item["path_pattern"]),)
        for item in role_contract["allowed_sources"]
    }
    contract = _ArtifactTypeContract(
        media_type=str(role_contract["observed_content_type"]),
        extensions=extensions,
        magic_signatures={extension: signatures for extension in extensions},
        max_bytes=int(role_contract["max_bytes"]),
        allowed_sources=allowed_sources,
        max_redirects=int(role_contract["max_redirects"]),
        timeout_seconds=float(role_contract["timeout_seconds"]),
    )
    service = ArtifactTransferService(transport)
    return service, service.prepare(
        destination,
        contract,
        output_root=output_root,
    )


def _download_response_bound_asset(
    service: ArtifactTransferService,
    prepared: _PreparedArtifactTransfer,
    url: str,
    item: Mapping[str, Any],
    operation_id: str,
    ref_field: str,
    ref: str | int,
    role: str,
    source_contract: Mapping[str, Any],
) -> _ArtifactTransferOutcome:
    return service.transfer(
        prepared,
        _ResolvedArtifactSource(
            url=url,
            source_capability="material.asset.fetch",
            source_operation_id=operation_id,
            reference_field=ref_field,
            reference_value=ref,
            role=role,
            declared_size=_declared_size(item, source_contract, role),
            expected_md5=_declared_md5(item, source_contract, role),
        ),
    )


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


__all__ = ["MaterialAssetHttpError"]
