"""Default controlled adapters for the dependency-injected Plan v1 engine."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from .output_projection import validate_output_fields
from .plan import AdapterContext, PlanAdapter, PlanAdapters
from . import plan_analysis_adapter as analysis_plan
from . import plan_segment_composites as segment_plan
from . import plan_user_journey_adapter as user_journey_plan
from . import plan_dashboard_adapter as dashboard_plan
from . import plan_order_adapter as order_plan
from .plan_binding import set_pointer
from .plan_pulse_adapter import execute_business_pulse, validate_business_pulse
from .plan_saved_analysis_adapter import (
    execute_saved_analysis_plan,
    is_saved_analysis_result,
    project_saved_analysis_result,
    validate_saved_analysis,
)
from .plan_multidim_adapter import (
    MULTIDIM_NAME,
    execute_multidim_plan,
    is_multidim_result,
    project_multidim_result,
    validate_multidim_plan,
)
from .plan_material_performance_adapter import (
    MATERIAL_PERFORMANCE_NAME,
    execute_material_performance_plan,
    is_material_performance_result,
    project_material_performance_result,
    validate_material_performance_plan,
)
from .plan_promotion_performance_adapter import (
    PROMOTION_PERFORMANCE_NAME,
    execute_promotion_performance_plan,
    is_promotion_performance_result,
    project_promotion_performance_result,
    validate_promotion_performance_plan,
)
from .plan_metadata_adapter import execute_metadata_plan, validate_metadata_plan
from .resolver_support import build_inputs
from .plan_adapter_support import (
    alias_mapping as _alias_mapping,
    array as _array,
    bounded_optional as _bounded_optional,
    composite_projection as _composite_projection,
    has_dynamic as _has_dynamic,
    identity_projection as _identity_projection,
    input_error as _input,
    mapping as _mapping,
    metadata_projection as _metadata_projection,
    request_object as _request_object,
    sql_projection as _sql_projection,
    validate_exact_targets as _validate_exact_targets,
    validate_input_names as _validate_input_names,
    validate_selected_fields as _validate_selected_fields,
)
from .sql.products import normalize_app_ids
from .sql.time_window import normalize_window


_RUN_FIELDS = frozenset(
    {"selector", "input", "inputs", "parameters", "app", "start", "end", "all_pages"}
)
_SQL_FIELDS = frozenset({"product", "start", "end", "app_id", "app_ids"})
_COMPOSITE_FIELDS = frozenset(
    {
        "name", "app", "apps", "ref", "mode", "start", "end", "platforms", "include_hourly",
        "inputs", "include_total", "read_all", "metadata_inputs", "metrics",
        "input_schema_version",
    }
)
_COMPOSITES = frozenset(
    {
        "analysis_context", "app_snapshot", "attribution_snapshot",
        "business_pulse", "saved_analysis", MULTIDIM_NAME,
        MATERIAL_PERFORMANCE_NAME,
        PROMOTION_PERFORMANCE_NAME,
        analysis_plan.ANALYSIS_QUERY_NAME,
        *segment_plan.COMPOSITE_NAMES,
        user_journey_plan.USER_JOURNEY_NAME,
        *dashboard_plan.COMPOSITE_NAMES,
    }
)
_COMPOSITE_OUTPUT_FIELDS = frozenset(
    {
        "app_count", "app_id", "components", "coverage", "date_range",
        "include_hourly", "operation_count", "platforms",
        "paginated_operation_count", "query", "results", "scopes", "source_count",
        "total", "validation", "items", "saved_analysis", "source", "kind",
        "operation_id", "definition_network_called", "query_executed", "result",
    }
)


def build_plan_adapters(
    sdk: Any,
    *,
    workspace: Any | None = None,
    metadata_database: str | Path | None = None,
) -> PlanAdapters:
    """Bind the four Plan v1 kinds to one existing SDK facade and workspace."""

    workspace = sdk.workspace if workspace is None else workspace
    insight = sdk.insight
    stable_operations = frozenset(
        str(item["operation_id"])
        for item in insight.operations(stability="stable")
        if isinstance(item, Mapping) and item.get("operation_id")
    )
    database = Path(metadata_database) if metadata_database is not None else None

    def validate_run(request: Mapping[str, Any], context: AdapterContext) -> None:
        _validate_run(request, context, insight, workspace, stable_operations)

    def execute_run(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_run(request, replace(context, dynamic_targets=()))
        inputs = request.get("inputs", request.get("input", {}))
        result = sdk.run(
            str(request["selector"]),
            inputs,
            parameters=request.get("parameters"),
            workspace=context.workspace,
            app=request.get("app"),
            start=request.get("start"),
            end=request.get("end"),
            all_pages=bool(request.get("all_pages", False)),
            max_pages=context.max_pages,
            max_items=context.max_items,
            max_workers=1,
            metadata_database=database,
            output_fields=context.output_fields or None,
        )
        if isinstance(result, Mapping) and result.get("ok") is not False:
            native = result.get("result")
            return dict(native) if isinstance(native, Mapping) else result
        return result

    def validate_sql(request: Mapping[str, Any], context: AdapterContext) -> None:
        _validate_sql(request, context, workspace)

    def execute_sql(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_sql(request, replace(context, dynamic_targets=()))
        return sdk.query_sql_products(
            request, max_workers=1, workspace=context.workspace
        )

    def validate_metadata(request: Mapping[str, Any], context: AdapterContext) -> None:
        validate_metadata_plan(request, context)

    def execute_metadata(request: Mapping[str, Any], _context: AdapterContext) -> Any:
        return execute_metadata_plan(request, _context, database=database)

    def validate_composite(request: Mapping[str, Any], context: AdapterContext) -> None:
        _validate_composite(request, context, insight, workspace)

    def execute_composite(request: Mapping[str, Any], context: AdapterContext) -> Any:
        validate_composite(request, replace(context, dynamic_targets=()))
        return _execute_composite(sdk, request, context)

    return PlanAdapters(
        run=PlanAdapter(execute_run, validate_run, _identity_projection),
        sql_product=PlanAdapter(execute_sql, validate_sql, _sql_projection),
        metadata_search=PlanAdapter(
            execute_metadata, validate_metadata, _metadata_projection
        ),
        composite=PlanAdapter(
            execute_composite, validate_composite, _project_composite
        ),
    )


def _validate_run(
    request: Mapping[str, Any],
    context: AdapterContext,
    insight: Any,
    workspace: Any,
    stable_operations: frozenset[str],
) -> None:
    _request_object(request, _RUN_FIELDS, "run")
    selector = request.get("selector")
    if not isinstance(selector, str) or not selector.strip():
        raise _input("run request requires selector", "selector")
    operation_id, recipe = _resolve_selector(selector, workspace, stable_operations)
    description = insight.describe(operation_id)
    fields = description.get("input_schema", {})
    if not isinstance(fields, Mapping):
        raise _input("operation input contract is invalid", "selector")
    dynamic_request = _run_dynamic_request(request, context, fields, recipe)
    inputs = _alias_mapping(dynamic_request, "input", "inputs")
    parameters = _mapping(dynamic_request.get("parameters", {}), "parameters")
    _validate_input_names(inputs, description, ())
    _validate_run_options(dynamic_request, parameters, recipe, workspace, context)
    bound = build_inputs(
        recipe,
        workspace,
        description,
        inputs,
        parameters,
        app=dynamic_request.get("app"),
        start=dynamic_request.get("start"),
        end=dynamic_request.get("end"),
    )
    validation = insight.validate(operation_id, bound)
    if validation.get("ok") is not True:
        raise _input("run request failed offline operation validation", "inputs")
    if context.output_fields:
        validate_output_fields(description, context.output_fields, request_inputs=bound)


def _run_dynamic_request(
    request: Mapping[str, Any],
    context: AdapterContext,
    fields: Mapping[str, Any],
    recipe: Any | None,
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(request))
    supplied = _alias_mapping(selected, "input", "inputs")
    selected.pop("input", None)
    selected["inputs"] = copy.deepcopy(dict(supplied))
    allowed = {"/app", "/start", "/end", "/all_pages"}
    input_aliases = ("/input/", "/inputs/")
    for target in context.dynamic_targets:
        if target in allowed:
            set_pointer(selected, target, _shortcut_sentinel(target))
            continue
        name = _target_name(target, input_aliases)
        if name is not None and name in fields:
            set_pointer(selected, f"/inputs/{name}", _field_sentinel(fields[name]))
            continue
        parameter = _target_name(target, ("/parameters/",))
        if parameter is not None and recipe is not None and parameter in recipe.parameters:
            path = str(recipe.parameters[parameter]).split(".", 1)[0]
            set_pointer(selected, target, _field_sentinel(fields.get(path, {})))
            continue
        raise _input("run binding target is outside the adapter contract", "bindings")
    return selected


def _shortcut_sentinel(target: str) -> Any:
    return {
        "/app": 1,
        "/start": "2026-01-01",
        "/end": "2026-01-02",
        "/all_pages": False,
    }[target]


def _field_sentinel(specification: Any) -> Any:
    spec = specification if isinstance(specification, Mapping) else {}
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    kind = str(spec.get("type", "string"))
    if kind == "integer":
        return max(1, int(spec.get("minimum", 1)))
    if kind == "number":
        return max(1, spec.get("minimum", 1))
    if kind == "boolean":
        return False
    if kind == "array":
        count = max(0, int(spec.get("min_items", 0)))
        item = _field_sentinel({"type": spec.get("item_type", "string")})
        return [copy.deepcopy(item) for _ in range(count)]
    if kind == "object":
        return {}
    if kind == "date":
        return "2026-01-01"
    if kind == "datetime":
        return "2026-01-01T00:00:00+08:00"
    return "plan-preflight"


def _target_name(target: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if target.startswith(prefix) and target.count("/") == 2:
            return target.removeprefix(prefix)
    return None


def _resolve_selector(
    selector: str, workspace: Any, stable_operations: frozenset[str]
) -> tuple[str, Any | None]:
    if selector.startswith("@"):
        try:
            recipe = workspace.recipe(selector[1:])
        except (KeyError, ValueError) as exc:
            raise _input("run recipe is not configured", "selector") from exc
        operation_id = str(recipe.operation)
    else:
        recipe = None
        operation_id = selector
    if operation_id not in stable_operations:
        raise _input("run selector is not a stable operation or recipe", "selector")
    return operation_id, recipe


def _validate_run_options(
    request: Mapping[str, Any],
    parameters: Mapping[str, Any],
    recipe: Any | None,
    workspace: Any,
    context: AdapterContext,
) -> None:
    if recipe is None and parameters:
        raise _input("parameters require a workspace recipe", "parameters")
    if recipe is not None:
        _validate_recipe_parameters(recipe, parameters, context)
    if "app" in request and not _has_dynamic(context, "/app"):
        workspace.resolve_app(request.get("app"))
    for field in ("start", "end"):
        if field in request and not isinstance(request[field], str):
            raise _input("run time bounds must be strings", field)
    if "all_pages" in request and not isinstance(request["all_pages"], bool):
        raise _input("run all_pages must be a boolean", "all_pages")


def _validate_recipe_parameters(
    recipe: Any, parameters: Mapping[str, Any], context: AdapterContext
) -> None:
    allowed_parameters = set(recipe.parameters) | set(recipe.required_parameters)
    if set(parameters) - allowed_parameters:
        raise _input("run request contains an undeclared recipe parameter", "parameters")
    missing = set(recipe.required_parameters) - set(parameters)
    dynamic_parameters = {
        target.split("/", 2)[2]
        for target in context.dynamic_targets
        if target.startswith("/parameters/") and target.count("/") == 2
    }
    if missing - dynamic_parameters:
        raise _input("run request is missing a required recipe parameter", "parameters")


def _validate_sql(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    _request_object(request, _SQL_FIELDS, "sql_product")
    _validate_exact_targets(context, frozenset({"/start", "/end", "/app_id"}))
    product = request.get("product")
    if not isinstance(product, str) or not product.strip():
        raise _input("SQL product request requires product", "product")
    try:
        definition = workspace.product(product)
    except (KeyError, ValueError) as exc:
        raise _input("SQL product is not configured", "product") from exc
    max_rows = definition.get("max_rows", 1_000)
    if type(max_rows) is not int or max_rows > context.max_items:
        raise _input("SQL product max_rows exceeds this node max_items", "limits.max_items")
    dynamic = set(context.dynamic_targets)
    start, end = request.get("start"), request.get("end")
    for field, value in (("start", start), ("end", end)):
        if f"/{field}" not in dynamic and not isinstance(value, str):
            raise _input("SQL product requires start and end", "start/end")
    if not ({"/start", "/end"} & dynamic):
        normalize_window(start, end)
    _validate_sql_apps(request, product, workspace, dynamic)
    allowed = frozenset(str(item) for item in definition.get("output_fields", []))
    _validate_selected_fields(context.output_fields, allowed, "output_fields")


def _validate_sql_apps(
    request: Mapping[str, Any],
    product: str,
    workspace: Any,
    dynamic: set[str],
) -> None:
    if "app_id" in request and "app_ids" in request:
        raise _input("SQL product app_id and app_ids cannot be combined", "app_ids")
    if {"/app_id", "/app_ids"} & dynamic:
        return
    raw = request.get("app_ids", request.get("app_id"))
    if raw is None:
        normalize_app_ids(product, None, workspace)
        return
    values = [raw] if type(raw) is int else list(raw) if _array(raw) else None
    if values is None:
        raise _input("SQL product app ids are invalid", "app_ids")
    normalize_app_ids(product, values, workspace)


def _validate_composite(
    request: Mapping[str, Any],
    context: AdapterContext,
    insight: Any,
    workspace: Any,
) -> None:
    name = request.get("name")
    if name == analysis_plan.ANALYSIS_QUERY_NAME:
        analysis_plan.validate_analysis_query_plan(
            insight, workspace, request, context
        )
        return
    if segment_plan.is_segment_composite(name):
        segment_plan.validate_segment_composite(
            insight, workspace, request, context
        )
        return
    if name == user_journey_plan.USER_JOURNEY_NAME:
        user_journey_plan.validate_user_journey_plan(request, context, workspace)
        return
    if dashboard_plan.is_dashboard_composite(name):
        dashboard_plan.validate_dashboard_plan(request, context, workspace)
        return
    if order_plan.is_order_composite(name):
        order_plan.validate_order_plan(request, context, workspace)
        return
    _request_object(request, _COMPOSITE_FIELDS, "composite")
    if name not in _COMPOSITES:
        raise _input("composite name is not allowlisted", "name")
    if name == "business_pulse":
        validate_business_pulse(
            request, context, workspace, _COMPOSITE_OUTPUT_FIELDS
        )
        return
    if name == "saved_analysis":
        validate_saved_analysis(
            request, context, workspace, _COMPOSITE_OUTPUT_FIELDS
        )
        return
    if name == MULTIDIM_NAME:
        validate_multidim_plan(insight, workspace, request, context)
        return
    if name == MATERIAL_PERFORMANCE_NAME:
        validate_material_performance_plan(request, context, workspace)
        return
    if name == PROMOTION_PERFORMANCE_NAME:
        validate_promotion_performance_plan(request, context, workspace)
        return
    allowed_targets = {"/app"}
    _validate_exact_targets(context, frozenset(allowed_targets))
    dynamic_app = _has_dynamic(context, "/app")
    app_id = None if dynamic_app else workspace.resolve_app(request.get("app"))
    _validate_selected_fields(
        context.output_fields, _COMPOSITE_OUTPUT_FIELDS, "output_fields"
    )
    _validate_fixed_composite(request, context, str(name))


def _validate_fixed_composite(
    request: Mapping[str, Any], context: AdapterContext, name: str
) -> None:
    if set(request) - {"name", "app"}:
        raise _input("composite request contains fields unavailable for this name", "request")
    required_items = {
        "analysis_context": 13,
        "app_snapshot": 6,
        "attribution_snapshot": 8,
    }[name]
    if context.max_items < required_items:
        raise _input(
            "composite fixed sources exceed this node max_items", "limits.max_items"
        )


def _execute_composite(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> Any:
    name = str(request["name"])
    app = request.get("app")
    if name == "analysis_context":
        return sdk.analysis_context(
            app,
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
            workspace=context.workspace,
        )
    if name == "app_snapshot":
        return sdk.app_snapshot(
            app,
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
            workspace=context.workspace,
        )
    if name == "attribution_snapshot":
        return sdk.attribution_snapshot(
            app,
            max_workers=1,
            max_pages=context.max_pages,
            max_items=context.max_items,
            workspace=context.workspace,
        )
    if name == "business_pulse":
        return execute_business_pulse(sdk, request, context)
    if name == "saved_analysis":
        return execute_saved_analysis_plan(sdk, request, context)
    if name == MULTIDIM_NAME:
        return execute_multidim_plan(sdk, request, context)
    if name == MATERIAL_PERFORMANCE_NAME:
        return execute_material_performance_plan(sdk, request, context)
    if name == PROMOTION_PERFORMANCE_NAME:
        return execute_promotion_performance_plan(sdk, request, context)
    if name == analysis_plan.ANALYSIS_QUERY_NAME:
        return analysis_plan.execute_analysis_query_plan(sdk, request, context)
    if segment_plan.is_segment_composite(name):
        return segment_plan.execute_segment_composite(sdk, request, context)
    if name == user_journey_plan.USER_JOURNEY_NAME:
        return user_journey_plan.execute_user_journey_plan(sdk, request, context)
    if dashboard_plan.is_dashboard_composite(name):
        return dashboard_plan.execute_dashboard_plan(sdk, request, context)
    if order_plan.is_order_composite(name):
        return order_plan.execute_order_plan(sdk, request, context)
    raise RuntimeError("validated composite routing omitted an executor")


def _project_composite(
    result: Any, fields: tuple[str, ...], context: AdapterContext
) -> Any:
    if analysis_plan.is_analysis_query_result(result):
        return analysis_plan.project_analysis_query_result(result, fields, context)
    if segment_plan.is_segment_result(result):
        return segment_plan.project_segment_result(result, fields, context)
    if user_journey_plan.is_user_journey_result(result):
        return user_journey_plan.project_user_journey_result(result, fields, context)
    if dashboard_plan.is_dashboard_result(result):
        return dashboard_plan.project_dashboard_result(result, fields, context)
    if order_plan.is_order_result(result):
        return order_plan.project_order_result(result, fields, context)
    if is_saved_analysis_result(result):
        return project_saved_analysis_result(result, fields, context)
    if is_multidim_result(result):
        return project_multidim_result(result, fields, context)
    if is_material_performance_result(result):
        return project_material_performance_result(result, fields, context)
    if is_promotion_performance_result(result):
        return project_promotion_performance_result(result, fields, context)
    return _composite_projection(result, fields, context)


__all__ = ["build_plan_adapters"]
