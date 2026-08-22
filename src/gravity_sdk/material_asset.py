"""Response-bound material file effect shared by CLI and SDK."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ContractChangedError, ErrorDetail, GravityInsightError
from .material_asset_contract import actual_value, source_contract
from .blob_models import BlobTransport
from .material_asset_transfer import (
    _download_response_bound_asset,
    _prepare_response_bound_asset,
)
from .result_audit import (
    add_result_audit,
    bind_error_receipts,
    result_receipt_references,
)
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity.material-asset.v2"


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
    result = client.read(operation_id, dict(source_input))
    receipts = result_receipt_references(result)
    try:
        _raise_source_failure(result, operation_id)
        rows = _response_rows(result, contract)
        matched = [item for item in rows if _same_reference(item.get(ref_field), ref)]
        if len(matched) != 1:
            raise actual_value(
                field="ref",
                actual=ref,
                allowed=("exactly one reference in the fresh source response",),
                next_action=(
                    f"Run `gravity run {operation_id}` with the same input, then copy one "
                    "exact documented reference field and value."
                ),
            )
        url_field = str(role_contract["url_field"])
        url = matched[0].get(url_field)
        if not isinstance(url, str) or not url.strip():
            raise actual_value(
                field="role",
                actual=role,
                allowed=("a role populated on the selected source row",),
                next_action=(
                    f"Refresh `{operation_id}` and select a row whose `{url_field}` is populated."
                ),
            )
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


def _response_rows(
    result: Any, contract: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    if not isinstance(result, Mapping):
        return []
    value: Any = result
    for part in contract.get("list_path", ()):
        value = value.get(part) if isinstance(value, Mapping) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _same_reference(observed: Any, selected: str | int) -> bool:
    return (
        not isinstance(observed, bool)
        and not isinstance(selected, bool)
        and observed not in (None, "")
        and str(observed) == str(selected)
    )


__all__ = ["SCHEMA_VERSION", "fetch_material_asset"]
