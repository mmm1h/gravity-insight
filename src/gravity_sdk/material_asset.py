"""Response-bound material file effect shared by CLI and SDK."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifact_transfer import ArtifactTransferError
from .artifact_transfer_errors import ArtifactTransferHttpError
from .errors import (
    ContractChangedError,
    ErrorCategory,
    ErrorDetail,
    GravityInsightError,
)
from .material_asset_contract import actual_value, source_contract
from .material_asset_source import _read_bound_material_asset_source
from .blob_models import BlobTransport
from .material_asset_transfer import (
    _download_response_bound_asset,
    _prepare_response_bound_asset,
)
from .result_audit import (
    add_result_audit,
    bind_error_receipts,
    error_receipt_references,
    result_receipt_references,
)
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity.material-asset.v2"


class MaterialAssetUnavailableError(ArtifactTransferError):
    """The fresh source cannot distinguish why the requested bytes are absent."""

    def __init__(self, *, stage: str = "source_resolution") -> None:
        super().__init__(
            "material binary is unavailable; the upstream reason is indistinguishable",
            code="MATERIAL_ASSET_BINARY_UNAVAILABLE",
            category=ErrorCategory.UPSTREAM,
            stage=stage,
            reason_category="indistinguishable_binary_unavailable",
            next_action=(
                "Refresh the same registered source scope once; if the reference or role "
                "is still absent, report the binary as unavailable without guessing why."
            ),
        )


class MaterialAssetSourceUnsupportedError(ArtifactTransferError):
    """The private response URL is outside the evidence-backed source subset."""

    def __init__(self, *, stage: str) -> None:
        super().__init__(
            "material binary source is outside the installed contract allowlist",
            code="MATERIAL_ASSET_SOURCE_UNSUPPORTED",
            category=ErrorCategory.UPSTREAM,
            stage=stage,
            reason_category="source_contract",
            next_action=(
                "Do not fetch the URL directly; report this source as unsupported by the "
                "installed material asset contract."
            ),
        )


class _SourceOperationError(GravityInsightError):
    def __init__(self, operation_id: str, value: Mapping[str, Any]) -> None:
        super().__init__(
            str(value.get("message") or "material source operation failed"),
            field=str(value["field"]) if value.get("field") else None,
            retry_after_ms=value.get("retry_after_ms"),
            next_action=str(value.get("next_action") or ""),
            code=str(value.get("code") or "UPSTREAM_UNAVAILABLE"),
        )
        self.operation_id = operation_id
        self.category = str(value.get("category") or "upstream")
        self.retryable = bool(value.get("retryable", False))

    def to_error_detail(
        self, *, operation_id: str | None = None, next_action: str | None = None
    ) -> ErrorDetail:
        return ErrorDetail.create(
            self.code,
            self,
            operation_id=operation_id or self.operation_id,
            category=self.category,
            field=self.field,
            retryable=self.retryable,
            retry_after_ms=self.retry_after_ms,
            next_action=next_action or self.next_action,
        )


def fetch_material_asset(
    client: Any,
    source: str,
    source_input: Mapping[str, Any],
    ref_field: str,
    ref: str | int,
    role: str,
    destination: str | Path,
    *,
    output_root: str | Path | None = None,
    _transport: BlobTransport | None = None,
) -> dict[str, Any]:
    """Read a registered source, resolve one row, then download its URL."""

    contract, role_contract = _validate_source_request(
        source, source_input, ref_field, role
    )
    service, prepared = _prepare_response_bound_asset(
        role_contract,
        destination,
        output_root=output_root,
        transport=_transport,
    )
    operation_id, item, url, source_result = _resolve_response_asset(
        client, contract, source_input, ref_field, ref, role, role_contract
    )
    source_receipts = result_receipt_references(source_result)
    try:
        transfer = _download_response_bound_asset(
            service,
            prepared,
            url,
            item,
            operation_id,
            ref_field,
            ref,
            role,
            contract,
        )
    except ArtifactTransferError as exc:
        translated = _translate_material_transfer_error(exc)
        bind_error_receipts(
            translated,
            [*source_receipts, *error_receipt_references(exc)],
        )
        if translated is exc:
            raise
        raise translated from exc
    except BaseException as exc:
        bind_error_receipts(exc, source_receipts)
        raise
    return add_result_audit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "result_source": result_source(GOVERNED_PRODUCT),
        "effect": "material_file_download",
        "artifact": transfer.artifact,
    }, [*source_receipts, *transfer.receipt_references])


def _validate_source_request(
    source: str,
    source_input: Mapping[str, Any],
    ref_field: str,
    role: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    contract = source_contract(source)
    if not isinstance(source_input, Mapping):
        raise actual_value(
            field="input",
            actual=type(source_input).__name__,
            allowed=("JSON object",),
            next_action="Pass the documented source operation input as a JSON object.",
        )
    references = tuple(contract.get("reference_fields", ()))
    if ref_field not in references:
        raise actual_value(
            field="ref_field",
            actual=ref_field,
            allowed=references,
            next_action="Choose a reference field returned by the selected source operation.",
        )
    roles = contract.get("roles")
    role_contract = roles.get(role) if isinstance(roles, Mapping) else None
    if not isinstance(role_contract, Mapping):
        raise actual_value(
            field="role",
            actual=role,
            allowed=tuple(roles or ()),
            next_action="Choose `file` or `thumbnail` and retry the same material reference.",
        )
    return contract, role_contract


def _resolve_response_asset(
    client: Any,
    contract: Mapping[str, Any],
    source_input: Mapping[str, Any],
    ref_field: str,
    ref: str | int,
    role: str,
    role_contract: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], str, Mapping[str, Any]]:
    operation_id = str(contract["operation_id"])
    selected = _read_bound_material_asset_source(
        client, operation_id, dict(source_input)
    )
    if (
        not isinstance(selected, tuple)
        or len(selected) != 2
        or not isinstance(selected[0], Mapping)
        or not isinstance(selected[1], (list, tuple))
    ):
        raise ContractChangedError("material asset private source result changed")
    result, rows = selected
    receipts = result_receipt_references(result)
    try:
        _raise_source_failure(result, operation_id)
        matched = [
            item
            for item in rows
            if isinstance(item, Mapping)
            and _same_reference(item.get(ref_field), ref)
        ]
        if len(matched) != 1:
            raise MaterialAssetUnavailableError()
        url_field = str(role_contract["url_field"])
        url = matched[0].get(url_field)
        if not isinstance(url, str) or not url.strip():
            raise MaterialAssetUnavailableError()
    except BaseException as exc:
        bind_error_receipts(exc, receipts)
        raise
    return operation_id, matched[0], url, result


def _raise_source_failure(result: Any, operation_id: str) -> None:
    if (
        isinstance(result, Mapping)
        and result.get("ok") is not False
        and result.get("status") in {"success", "empty"}
    ):
        return
    error = result.get("error") if isinstance(result, Mapping) else None
    if isinstance(error, Mapping):
        raise _SourceOperationError(operation_id, error)
    raise ContractChangedError("material source operation returned an invalid envelope")


def _translate_material_transfer_error(
    error: ArtifactTransferError,
) -> ArtifactTransferError:
    if error.code in {"ARTIFACT_SOURCE_DENIED", "ARTIFACT_REDIRECT_DENIED"}:
        return MaterialAssetSourceUnsupportedError(stage=error.stage)
    if isinstance(error, ArtifactTransferHttpError):
        status = int(error.http_status or 0)
        if 400 <= status < 500 and status not in {408, 425, 429}:
            return MaterialAssetUnavailableError(stage="binary_response")
    return error


def _same_reference(observed: Any, selected: str | int) -> bool:
    return (
        not isinstance(observed, bool)
        and not isinstance(selected, bool)
        and observed not in (None, "")
        and str(observed) == str(selected)
    )


__all__ = [
    "MaterialAssetSourceUnsupportedError",
    "MaterialAssetUnavailableError",
    "SCHEMA_VERSION",
    "fetch_material_asset",
]
