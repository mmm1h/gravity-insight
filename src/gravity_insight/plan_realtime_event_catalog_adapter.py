"""Plan v1 boundary for the realtime-event catalog."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ErrorCode, ErrorDetail, exit_code_for_error
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .contracts.envelope_obligations import CompletenessState, EnvelopeObligations, serialize_envelope
from .realtime_event_catalog import SCHEMA_VERSION, _diagnostic_obligations, _diagnostic_scope, _safe_items
from .realtime_event_diagnostics import FILTER_FIELDS, PUBLIC_FILTER_FIELDS, realtime_event_inputs
from .result_source import GOVERNED_PRODUCT, result_source
from .workspace_app import resolve_workspace_app


REALTIME_EVENT_CATALOG_NAME = "realtime_event_catalog"
REQUEST_FIELDS = frozenset({"name", "app", "start", "end", "event_type", "property_fields", *FILTER_FIELDS})
OUTPUT_FIELDS = frozenset(
    {
        "operation_id",
        "app_id",
        "start",
        "end",
        "event_type",
        "item_count",
        "data",
    }
)
_STRUCTURAL_FIELDS = frozenset(
    {
        "schema_version",
        "result_source",
        "ok",
        "status",
        "exit_code",
        "error",
        "result_audit",
        "obligations",
        "completeness",
        "allowed_claims",
        "forbidden_claims",
        "diagnostic_scope",
    }
)
_SAFE_FIELDS = _STRUCTURAL_FIELDS | OUTPUT_FIELDS


def validate_realtime_event_catalog_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    request_object(request, REQUEST_FIELDS, REALTIME_EVENT_CATALOG_NAME)
    validate_exact_targets(context, frozenset({"/app"}))
    if not has_dynamic(context, "/app"):
        resolve_workspace_app(workspace, request.get("app"))
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")
    realtime_event_inputs(1, request.get("start"), request.get("end"), request.get("event_type", "profile"), {key: request[key] for key in (*FILTER_FIELDS, "property_fields") if key in request})


def execute_realtime_event_catalog_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    return safe_realtime_event_catalog_envelope(
        sdk.realtime_event_catalog(
            request.get("app"),
            start=request.get("start"),
            end=request.get("end"),
            event_type=request.get("event_type", "profile"),
            **{key: request[key] for key in (*FILTER_FIELDS, "property_fields") if key in request},
            workspace=context.workspace,
        )
    )


def project_realtime_event_catalog_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    validate_selected_fields(fields, OUTPUT_FIELDS, "output_fields")
    selected = safe_realtime_event_catalog_envelope(result)
    return {
        key: copy.deepcopy(value)
        for key, value in selected.items()
        if key in _STRUCTURAL_FIELDS or key in fields
    }


def safe_realtime_event_catalog_envelope(result: Any) -> dict[str, Any]:
    normalized = _validated_product(result)
    if normalized is None:
        detail = ErrorDetail.create(
            ErrorCode.CONTRACT_CHANGED,
            "Realtime-event catalog result contract changed.",
        )
        return serialize_envelope({
            "schema_version": SCHEMA_VERSION,
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": False,
            "status": "contract_changed",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
        }, _diagnostic_obligations(False, 0, detail))
    return serialize_envelope(*normalized)


def _validated_product(result: Any) -> tuple[dict[str, Any], EnvelopeObligations] | None:
    if not isinstance(result, Mapping) or result.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        obligations = EnvelopeObligations.from_dict(result["obligations"])
        scope = result.get("diagnostic_scope", {})
        if not isinstance(scope, Mapping):
            return None
        properties = scope.get("property_fields", ())
        items = _safe_items(result.get("data"), properties)
        if obligations.data_completeness.state is not CompletenessState.UNKNOWN or items is None:
            return None
        if result.get("ok") is True:
            valid = _valid_success(result, scope, properties, items, obligations)
        elif result.get("ok") is False:
            valid = _valid_failure(result, items, obligations)
        else:
            valid = False
        if not valid:
            return None
        selected = {key: copy.deepcopy(value) for key, value in result.items() if key in _SAFE_FIELDS and key != "obligations"}
        selected["data"] = {"list": items}
        return selected, obligations
    except (KeyError, TypeError, ValueError):
        return None


def _valid_success(result: Mapping[str, Any], scope: Mapping[str, Any], properties: Any, items: list[dict[str, Any]], obligations: EnvelopeObligations) -> bool:
    filters = scope.get("filter_fields")
    public_filters = scope.get("public_filters")
    if not _valid_public_filters(public_filters):
        return False
    return (
        isinstance(filters, list) and all(isinstance(name, str) and name in {*FILTER_FIELDS, "event_type"} for name in filters)
        and len(filters) == len(set(filters)) and set(public_filters) == set(filters) & PUBLIC_FILTER_FIELDS
        and scope == _diagnostic_scope(filters, properties, len(items), public_filters)
        and _matches_public_scope(items, public_filters)
        and result.get("item_count") == len(items) and obligations == _diagnostic_obligations(True, len(items))
        and result.get("allowed_claims") == ["returned-realtime-event-observation"]
        and result.get("forbidden_claims") == ["complete-event-history", "ingestion-completeness", "empty-proves-no-delivery"]
    )


def _valid_public_filters(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) - PUBLIC_FILTER_FIELDS:
        return False
    return all(isinstance(item, str) and 1 <= len(item) <= 128 for item in value.values())


def _matches_public_scope(items: list[dict[str, Any]], filters: Mapping[str, str]) -> bool:
    return all(all(row.get(key) == value for key, value in filters.items()) for row in items)


def _valid_failure(result: Mapping[str, Any], items: list[dict[str, Any]], obligations: EnvelopeObligations) -> bool:
    error = result.get("error")
    return items == [] and result.get("item_count") == 0 and isinstance(error, Mapping) and obligations == _diagnostic_obligations(False, 0, error) and not result.get("allowed_claims")


def is_realtime_event_catalog_result(result: Any) -> bool:
    return isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION


__all__ = [
    "OUTPUT_FIELDS",
    "REALTIME_EVENT_CATALOG_NAME",
    "execute_realtime_event_catalog_plan",
    "is_realtime_event_catalog_result",
    "project_realtime_event_catalog_result",
    "safe_realtime_event_catalog_envelope",
    "validate_realtime_event_catalog_plan",
]
