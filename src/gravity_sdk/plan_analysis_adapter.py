"""Controlled Plan adapter for literal compact Analysis query specs."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .analysis_spec import (
    ANALYSIS_QUERY_OPERATIONS,
    compile_query_spec,
    validate_query_spec,
)
from .output_projection import validate_output_fields
from .plan import AdapterContext
from .plan_adapter_support import (
    has_dynamic,
    input_error,
    mapping,
    request_object,
    validate_exact_targets,
)
from . import plan_monetization_adapter as monetization_plan
from . import plan_derived_metrics_adapter as derived_plan


ANALYSIS_QUERY_NAME = "analysis_query"
COMPOSITE_NAMES = frozenset(
    {
        ANALYSIS_QUERY_NAME,
        derived_plan.DERIVED_METRICS_NAME,
        monetization_plan.MONETIZATION_DETAIL_NAME,
    }
)
ANALYSIS_QUERY_REQUEST_FIELDS = frozenset(
    {"name", "kind", "app", "spec", "start", "end", "compare_start", "compare_end"}
)
_ANALYSIS_OPERATIONS = frozenset(ANALYSIS_QUERY_OPERATIONS.values())
_SAFE_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "operation_id",
        "contract_version",
        "source",
        "fetched_at",
        "schema_fingerprint",
        "page",
        "data",
        "warnings",
        "error",
        "output_fields",
        "kind",
        "network_called",
        "windows",
        "delta",
        "next_action",
    }
)
_SAFE_ERROR_FIELDS = frozenset(
    {
        "category",
        "code",
        "field",
        "retryable",
        "retry_after_ms",
    }
)
_BREAKING_STATUSES = frozenset(
    {"contract_changed", "upstream_changed", "error", "failed", "unavailable"}
)


def validate_analysis_query_plan(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> str:
    """Compile and FieldPolicy-validate a literal spec without network access."""

    request_object(request, ANALYSIS_QUERY_REQUEST_FIELDS, "analysis_query")
    if request.get("name") != ANALYSIS_QUERY_NAME:
        raise input_error("analysis query composite name is invalid", "name")
    validate_exact_targets(context, frozenset({"/app"}))
    if "spec" not in request:
        raise input_error("analysis query composite requires spec", "spec")
    spec = mapping(request.get("spec"), "spec")
    if "app" not in request and not has_dynamic(context, "/app"):
        raise input_error("analysis query composite requires app", "app")
    selected_app = 1 if has_dynamic(context, "/app") else request.get("app")
    compiled, _validation = validate_query_spec(
        insight,
        request.get("kind"),
        spec,
        workspace=workspace,
        app=selected_app,
        start=request.get("start"),
        end=request.get("end"),
    )
    compare_start, compare_end = request.get("compare_start"), request.get("compare_end")
    if (compare_start is None) != (compare_end is None):
        raise input_error(
            "analysis query compare_start and compare_end must be provided together",
            "compare_start/compare_end",
        )
    if compare_start is not None:
        if context.output_fields:
            raise input_error(
                "analysis period compare does not accept single-window output_fields",
                "output_fields",
            )
        if compiled.kind == "property":
            raise input_error(
                "property Analysis has no governed date-window input",
                "compare_start/compare_end",
            )
        compile_query_spec(
            compiled.kind,
            spec,
            workspace=workspace,
            app=selected_app,
            start=compare_start,
            end=compare_end,
        )
    if context.output_fields:
        validate_output_fields(
            insight.schema(compiled.operation_id),
            context.output_fields,
            request_inputs=compiled.inputs,
        )
    return compiled.operation_id


def is_analysis_composite(value: Any) -> bool:
    return value in COMPOSITE_NAMES


def validate_analysis_plan(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> None:
    if request.get("name") == derived_plan.DERIVED_METRICS_NAME:
        derived_plan.validate_derived_metrics_plan(request, context)
        return
    if request.get("name") == monetization_plan.MONETIZATION_DETAIL_NAME:
        monetization_plan.validate_monetization_detail_plan(
            request, context, workspace
        )
        return
    validate_analysis_query_plan(insight, workspace, request, context)


def execute_analysis_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == derived_plan.DERIVED_METRICS_NAME:
        return derived_plan.execute_derived_metrics_plan(sdk, request, context)
    if request.get("name") == monetization_plan.MONETIZATION_DETAIL_NAME:
        return monetization_plan.execute_monetization_detail_plan(
            sdk, request, context
        )
    return execute_analysis_query_plan(sdk, request, context)


def is_analysis_result(value: Any) -> bool:
    return derived_plan.is_derived_metrics_result(value) or is_analysis_query_result(value) or (
        monetization_plan.is_monetization_detail_result(value)
    )


def project_analysis_result(
    value: Any, fields: tuple[str, ...], context: AdapterContext
) -> dict[str, Any]:
    if derived_plan.is_derived_metrics_result(value):
        return derived_plan.project_derived_metrics_result(value, fields, context)
    if monetization_plan.is_monetization_detail_result(value):
        return monetization_plan.project_monetization_detail_result(
            value, fields, context
        )
    return project_analysis_query_result(value, fields, context)


def execute_analysis_query_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Revalidate the bound request, execute once, and remove request values."""

    expected_operation = validate_analysis_query_plan(
        sdk.insight,
        context.workspace,
        request,
        replace(context, dynamic_targets=()),
    )
    result = sdk.analysis_query(
        request.get("kind"),
        request.get("spec"),
        app=request.get("app"),
        start=request.get("start"),
        end=request.get("end"),
        compare_start=request.get("compare_start"),
        compare_end=request.get("compare_end"),
        max_workers=1,
        workspace=context.workspace,
        output_fields=context.output_fields or None,
    )
    return safe_analysis_envelope(
        result,
        expected_operation=expected_operation,
    )


def is_analysis_query_result(result: Any) -> bool:
    return (
        isinstance(result, Mapping)
        and result.get("operation_id") in _ANALYSIS_OPERATIONS
    )


def safe_analysis_envelope(
    result: Any, *, expected_operation: str | None = None
) -> dict[str, Any]:
    """Retain governed result data while never returning compiled/request input."""

    if not isinstance(result, Mapping):
        raise input_error("analysis query result is invalid", "result")
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _SAFE_ENVELOPE_FIELDS and key != "error"
    }
    status = str(result.get("status", "")).casefold()
    if expected_operation is not None and result.get("operation_id") != expected_operation:
        selected["ok"] = False
        selected["status"] = "contract_changed"
        selected["data"] = {}
        selected["operation_id"] = expected_operation
        selected["error"] = _safe_drift_error(selected, "contract_changed")
        return selected
    if status in _BREAKING_STATUSES:
        selected["ok"] = False
        selected["status"] = status
        selected["data"] = {}
        selected["error"] = _safe_drift_error(result, status)
        return selected
    error = result.get("error")
    if isinstance(error, Mapping):
        selected["error"] = {
            key: copy.deepcopy(value)
            for key, value in error.items()
            if key in _SAFE_ERROR_FIELDS
        }
    return selected


def _safe_drift_error(result: Mapping[str, Any], status: str) -> dict[str, Any]:
    error = result.get("error")
    if isinstance(error, Mapping):
        selected = {
            key: copy.deepcopy(value)
            for key, value in error.items()
            if key in _SAFE_ERROR_FIELDS
        }
        if selected:
            selected["message"] = "The Analysis response no longer matches its governed contract."
            selected["next_action"] = (
                "Inspect the operation drift evidence before retrying this Plan node."
            )
            return selected
    return {
        "category": "upstream",
        "code": "CONTRACT_CHANGED",
        "message": "The Analysis response no longer matches its governed contract.",
        "next_action": "Inspect the operation drift evidence before retrying this Plan node.",
        "operation_id": result.get("operation_id"),
        "retryable": status == "upstream_changed",
    }


def project_analysis_query_result(
    result: Any,
    _fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    """The SDK already applied data-relative fields; only enforce safety again."""

    return safe_analysis_envelope(result)


__all__ = [
    "ANALYSIS_QUERY_NAME",
    "ANALYSIS_QUERY_REQUEST_FIELDS",
    "COMPOSITE_NAMES",
    "execute_analysis_plan",
    "execute_analysis_query_plan",
    "is_analysis_composite",
    "is_analysis_result",
    "is_analysis_query_result",
    "project_analysis_result",
    "project_analysis_query_result",
    "safe_analysis_envelope",
    "validate_analysis_plan",
    "validate_analysis_query_plan",
]
