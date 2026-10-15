"""Finite Journey input adaptation to existing read and product owners."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .composite_catalog import stable_operation
from .models import load_operation_manifest
from .plan import AdapterContext
from .workspace_app import resolve_workspace_app


def _read_owner(domain: str, resource: str, action: str) -> str:
    return stable_operation(domain, resource, action=action).operation_id


READ_JOURNEYS = {
    "analysis.readable-app-catalog": _read_owner("app", "app", "list"),
    "analysis.app-configuration": _read_owner("app", "detail", "get"),
    "analysis.attribution-backtrack-configuration": _read_owner("attribution", "attr_backtrack", "list"),
    "analysis.attribution-click-interval": _read_owner("attribution", "attr_click_interval", "get"),
    "analysis.postback-mode": _read_owner("attribution", "postback_mode", "list"),
    "analysis.postback-window": _read_owner("attribution", "post_backtrack", "list"),
    "analysis.reattribution-configuration": _read_owner("attribution", "reattribution", "list"),
    "analysis.event-metadata": _read_owner("analysis", "event", "list"),
    "analysis.event-properties": _read_owner("analysis", "event_property", "list"),
    "analysis.user-properties": _read_owner("analysis", "user_property", "list"),
    "analysis.user-report": _read_owner("analysis", "user_detail", "list"),
}
PRODUCT_JOURNEYS = {
    "analysis.ad-report": ("multidim_query", "composite:multidim", "gravity-insight.composite.multidim.v1"),
    "analysis.material-report": ("material_performance", "composite:material_performance", "gravity-insight.material-performance.v1"),
    "analysis.order-report": ("order_directory", "composite:order_directory", "gravity-insight.order-directory.v1"),
    "analysis.monetization-report": ("monetization_detail", "composite:monetization_detail", "gravity-insight.monetization-detail.v1"),
}
VOCABULARY_JOURNEYS = {
    "analysis.ad-metric-catalog": "metric",
    "analysis.material-metric-catalog": "material_metric",
    "analysis.user-report-fields": "user_report_field",
}
_APP = {"type": "string|integer", "required": True, "nullable": False}


@lru_cache(maxsize=1)
def _operations() -> dict[str, Any]:
    root = Path(__file__).resolve().parent / "manifests"
    return {op.operation_id: op for p in sorted(root.glob("*.json")) for op in load_operation_manifest(p)}


def task_binding(identity: str) -> dict[str, Any] | None:
    """Only exact built-in identities can select these existing owners."""
    if identity in READ_JOURNEYS:
        return {"sdk_method": "read", "owner": READ_JOURNEYS[identity], "mode": "operation",
                "result_schema_version": "gravity-insight.read.v1"}
    if identity in PRODUCT_JOURNEYS:
        method, owner, schema = PRODUCT_JOURNEYS[identity]
        return {"sdk_method": method, "owner": owner, "mode": "composite", "result_schema_version": schema}
    if identity in VOCABULARY_JOURNEYS:
        return {"sdk_method": "analysis_vocabulary", "owner": "metadata:search",
                "mode": "product", "result_schema_version": "gravity.metadata-search.v1"}
    if identity == "analysis.event-trend":
        return {"sdk_method": "analysis_query", "owner": "analysis_query", "mode": "plan",
                "result_schema_version": "gravity-insight.read.v1"}
    return None


def task_input_contract(identity: str) -> dict[str, Any] | None:
    """Expose the original owner descriptors, including nested machine schemas."""
    if identity == "analysis.realtime-event-catalog":
        from .agents.realtime_event_catalog import REALTIME_EVENT_CATALOG_CAPABILITY

        fields = REALTIME_EVENT_CATALOG_CAPABILITY["input_schema"]
    elif identity == "analysis.default-value-dictionary":
        fields = {"app": copy.deepcopy(_APP)}
    elif task_binding(identity) is None:
        return None
    elif identity in READ_JOURNEYS:
        fields = _operations()[READ_JOURNEYS[identity]].schema()["input_fields"]
        if "app_id" in fields:
            fields.pop("app_id")
            fields["app"] = copy.deepcopy(_APP)
    elif identity in PRODUCT_JOURNEYS:
        from .agents.product_inventory import canonical_capability_cards

        selector = PRODUCT_JOURNEYS[identity][1]
        fields = next(c["input_schema"] for c in canonical_capability_cards(None) if c["selector"] == selector)
    elif identity in VOCABULARY_JOURNEYS:
        fields = _vocabulary_fields(identity)
    else:
        fields = {"app": copy.deepcopy(_APP), "spec": {"type": "object", "required": True},
                  **{k: {"type": "string", "required": False} for k in ("start", "end")}}
    description = {"schema_version": "gravity.journey-input-description.v1", "fields": copy.deepcopy(fields),
                   "required_inputs": sorted(k for k, v in fields.items() if v.get("required")),
                   "additional_fields": "rejected"}
    if identity in PRODUCT_JOURNEYS:
        context = _context(None)
        description["execution_limits"] = {"max_pages": context.max_pages, "max_items": context.max_items,
                                           "max_workers": context.max_workers}
    return description


def _vocabulary_fields(identity: str) -> dict[str, Any]:
    fields = {"query": {"type": "string", "default": ""},
              "limit": {"type": "integer", "default": 20}, "offset": {"type": "integer", "default": 0}}
    if identity == "analysis.ad-metric-catalog":
        fields["source"] = {"type": "string", "enum": ["preset", "custom"], "default": "preset"}
    elif identity == "analysis.material-metric-catalog":
        from .material_metrics import CATALOG_PLATFORMS

        fields["platform"] = {"type": "string", "enum": list(CATALOG_PLATFORMS)}
    else:
        from .user_report_fields import GROUPS

        fields["group"] = {"type": "string", "enum": list(GROUPS)}
    return fields


def normalize_task_inputs(identity: str, inputs: Mapping[str, Any], workspace: Any) -> dict[str, Any]:
    description = task_input_contract(identity)
    if description is None or set(inputs) - set(description["fields"]):
        raise InputValidationError("Journey inputs contain unavailable fields", field="inputs",
                                   next_action="Inspect this exact Journey's input_contract and remove unsupported fields.")
    missing = set(description["required_inputs"]) - set(inputs)
    if missing:
        raise InputValidationError("Journey inputs are missing required fields: " + ", ".join(sorted(missing)), field="inputs",
                                   next_action="Inspect this Journey's input_contract and provide the required inputs.")
    result = copy.deepcopy(dict(inputs))
    if identity in READ_JOURNEYS:
        operation = _operations()[READ_JOURNEYS[identity]]
        if "app_id" in operation.fields:
            result["app_id"] = str(resolve_workspace_app(workspace, result.pop("app", None)))
        return operation.validate_inputs(result)
    if identity in VOCABULARY_JOURNEYS:
        return _vocabulary_inputs(identity, result, workspace)
    if identity in PRODUCT_JOURNEYS:
        return _product_inputs(identity, result, workspace)
    return _event_inputs(result, workspace)


def _context(workspace: Any) -> AdapterContext:
    return AdapterContext(node_id="journey", execution_id="readiness", kind="composite", workspace=workspace,
                          output_fields=(), dynamic_targets=(), max_pages=1, max_items=1000, max_workers=1)


def _vocabulary_inputs(identity: str, result: dict[str, Any], workspace: Any) -> dict[str, Any]:
    from .plan_metadata_adapter import validate_metadata_plan

    kind = VOCABULARY_JOURNEYS[identity]
    if identity == "analysis.ad-metric-catalog":
        source = result.pop("source", "preset")
        kinds = {"preset": "metric", "custom": "custom_metric"}
        if not isinstance(source, str) or source not in kinds:
            raise InputValidationError("Metric source must be preset or custom", field="source")
        kind = kinds[source]
    result["kind"] = kind
    validate_metadata_plan(result, _context(workspace))
    return result


def _product_inputs(identity: str, result: dict[str, Any], workspace: Any) -> dict[str, Any]:
    from .plan_material_performance_adapter import validate_material_performance_plan
    from .plan_monetization_adapter import validate_monetization_detail_plan
    from .plan_multidim_adapter import validate_multidim_plan
    from .plan_order_directory_adapter import validate_order_directory_plan
    from .multidim_product import MULTIDIM_INPUT_SCHEMA_VERSION

    method, owner, _schema = PRODUCT_JOURNEYS[identity]
    name = owner.removeprefix("composite:")
    request = {"name": name, **result}
    context = _context(workspace)
    if method == "multidim_query":
        request["input_schema_version"] = MULTIDIM_INPUT_SCHEMA_VERSION
        validate_multidim_plan(None, workspace, request, context)
    elif method == "material_performance":
        validate_material_performance_plan(request, context, workspace)
    elif method == "order_directory":
        validate_order_directory_plan(request, context, workspace)
    else:
        validate_monetization_detail_plan(request, context, workspace)
    if "app" in result:
        result["app"] = resolve_workspace_app(workspace, result["app"])
    if "apps" in result:
        result["apps"] = [resolve_workspace_app(workspace, app) for app in result["apps"]]
    return result


def _event_inputs(result: dict[str, Any], workspace: Any) -> dict[str, Any]:
    from .analysis_spec import compile_query_spec

    app = resolve_workspace_app(workspace, result.get("app"))
    compile_query_spec("event", result.get("spec"), workspace=workspace, app=app,
                       start=result.get("start"), end=result.get("end"))
    return {**result, "app": app, "kind": "event"}


def invoke_task(sdk: Any, identity: str, method: str, inputs: Mapping[str, Any], workspace: Any) -> Any:
    """Delegate once; fixed operation and offline catalog have no workspace keyword."""
    if identity in READ_JOURNEYS:
        return sdk.read(READ_JOURNEYS[identity], inputs)
    if identity in VOCABULARY_JOURNEYS:
        return sdk.analysis_vocabulary(**inputs)
    limits = {"max_pages": 1, "max_items": 1000, "max_workers": 1} if identity in PRODUCT_JOURNEYS else {}
    return getattr(sdk, method)(**inputs, workspace=workspace, **limits)
