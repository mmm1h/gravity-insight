"""Offline input checks and live projection binding for governed exports."""
from __future__ import annotations

from typing import Any, Mapping

from .errors import (
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    PolicyViolation,
    error_detail_from_exception,
)
from .export_contracts import validate_export_payload
from .export_models import _export_error
from ._field_policy_metadata import rows
from ._field_policy_operations import ANALYSIS_USER_PROPERTY


def validate_export_live_fields(client: Any, contract: Any, payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    bindings = contract.privacy.get("metadata_fields")
    if not isinstance(bindings, Mapping):
        return
    field_map = payload["field_map"]
    labels = dict(zip(contract.privacy["request_columns"], contract.privacy["allowed_columns"], strict=True))
    if any(labels.get(code) != label for code, label in field_map.items()):
        raise _export_error("field labels must match the verified projection", code="EXPORT_COLUMNS_INVALID", stage="creating")
    selected = {code: bindings[code] for code in field_map if code in bindings}
    if not selected:
        return
    envelope = _live_user_properties(client, str(payload["app_id"]))
    observed: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows(envelope):
        name = row.get("name")
        if isinstance(name, str):
            observed.setdefault(name, []).append(row)
    for code, binding in selected.items():
        candidates = observed.get(binding["name"], [])
        if not _matches_metadata(candidates, binding, labels[code], str(payload["app_id"])):
            raise _export_error(
                "requested field is absent, ambiguous or changed in live metadata",
                code="EXPORT_COLUMNS_INVALID", stage="metadata",
                details={"column": contract.privacy["request_columns"].index(code) + 1},
            )
    return envelope


def _matches_metadata(candidates: list[Mapping[str, Any]], binding: Mapping[str, Any], label: str, app_id: str) -> bool:
    if len(candidates) != 1:
        return False
    row = candidates[0]
    return (
        row.get("cname") == label and row.get("data_type") == binding["data_type"]
        and row.get("visible") is not False
        and (row.get("app_id") is None or str(row["app_id"]) == app_id)
    )


def _live_user_properties(client: Any, app_id: str) -> Mapping[str, Any]:
    # The executor still owns auth, policy, projection and retries. Bypass only
    # the persisted metadata cache; do not toggle a shared client's cache mode.
    all_rows: list[Mapping[str, Any]] = []
    try:
        client._operation_catalog.guard(ANALYSIS_USER_PROPERTY)
        for page_number in range(1, 51):
            envelope = client._executor.execute(ANALYSIS_USER_PROPERTY, {
                "app_id": app_id, "page": page_number, "page_size": 2000,
            }).to_dict()
            page = envelope.get("page")
            if not isinstance(page, Mapping):
                raise ValueError("metadata pagination unavailable")
            if envelope.get("ok") is not True or envelope.get("status") not in {"success", "empty"}:
                raise ValueError("metadata unavailable")
            all_rows.extend(rows(envelope))
            if page.get("has_more") is False:
                break
            if page.get("has_more") is not True:
                raise ValueError("metadata completeness unknown")
        else:
            raise ValueError("metadata page budget exhausted")
    except (GravityInsightError, ValueError):
        raise _export_error(
            "complete live user-property metadata is required before create",
            code="EXPORT_METADATA_UNAVAILABLE", stage="metadata",
        ) from None
    return {**envelope, "data": {"list": all_rows}}


def validate_export_input(
    client: Any,
    operation_id: str,
    payload: Mapping[str, Any] | None,
    *,
    render_wire: bool = False,
) -> dict[str, Any]:
    values = dict(payload or {})
    try:
        contracts, policy, _ = client._export_components()
        contract = contracts.get(operation_id)
        policy.authorize_effect_operation(
            operation_id, expected_effect="export_job_create"
        )
        validate_export_payload(contract, values)
    except GravityInsightError as exc:
        return _validation_error(operation_id, exc)
    result = _validation_envelope(operation_id, values)
    if render_wire:
        authorization = policy._prepare_effect_request(
            operation_id, "export_job_create", values
        )
        query, body = policy._consume_effect_request(
            authorization,
            method=authorization.method,
            path=authorization.path,
            query=authorization.query,
            body=authorization.body,
        )
        result["wire"] = {
            "method": authorization.method,
            "path": authorization.path,
            "query": query,
            "body": body,
        }
    return result


def _validation_envelope(operation_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.validation.v1",
        "ok": True,
        "status": "valid_offline",
        "operation_id": operation_id,
        "network_called": False,
        "normalized_input": dict(values),
        "live_metadata_dependencies": [],
        "validation_scope": {
            "input_schema": "complete",
            "columns": "validated_by_export_start",
            "idempotency_key": "validated_by_export_start",
        },
        "error": None,
        "next_action": (
            "Run `gravity export run "
            f"{operation_id} --input <request.json> --columns <column-codes> "
            "--idempotency-key <key> --output <file.xlsx>` after matching "
            "--columns to the "
            "export_col_list described by `export describe`."
        ),
    }


def _validation_error(operation_id: str, error: GravityInsightError) -> dict[str, Any]:
    detail: ErrorDetail
    if isinstance(error, PolicyViolation) and "catalog-only" in str(error):
        detail = ErrorDetail.create(
            ErrorCode.NOT_IMPLEMENTED, error, operation_id=operation_id
        )
    else:
        detail = error_detail_from_exception(error, operation_id=operation_id)
    return {
        "schema_version": "gravity-insight.validation.v1",
        "ok": False,
        "status": "invalid",
        "operation_id": operation_id,
        "network_called": False,
        "normalized_input": None,
        "live_metadata_dependencies": [],
        "error": detail.to_dict(),
    }


__all__ = ["validate_export_input"]
