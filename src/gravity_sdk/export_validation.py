"""Offline validation for governed export create inputs."""
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
            "Run `gravity export start "
            f"{operation_id} --input <request.json> --columns <column-codes> "
            "--idempotency-key <key>` after matching --columns to the "
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
