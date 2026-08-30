"""Offline validation for Plan run and governed SQL-product nodes."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .output_projection import validate_output_fields
from .plan import AdapterContext
from .plan_adapter_support import (
    alias_mapping,
    array,
    has_dynamic,
    input_error,
    mapping,
    request_object,
    validate_exact_targets,
    validate_input_names,
    validate_selected_fields,
)
from .plan_binding import set_pointer
from .resolver_support import build_inputs
from .sql.products import normalize_app_ids
from .sql.time_window import normalize_window


RUN_FIELDS = frozenset(
    {"selector", "input", "inputs", "parameters", "app", "start", "end", "all_pages"}
)
SQL_FIELDS = frozenset({"product", "start", "end", "app_id", "app_ids"})


def validate_run_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    insight: Any,
    workspace: Any,
    stable_operations: frozenset[str],
) -> None:
    request_object(request, RUN_FIELDS, "run")
    selector = request.get("selector")
    if not isinstance(selector, str) or not selector.strip():
        raise input_error(
            f"actual value: {actual_value(selector)}; run request requires selector",
            "selector",
        )
    operation_id, recipe = _resolve_selector(selector, workspace, stable_operations)
    description = insight.describe(operation_id)
    fields = description.get("input_schema", {})
    if not isinstance(fields, Mapping):
        raise input_error(
            f"actual value: {actual_value(type(fields).__name__)}; "
            "operation input contract must be a mapping of field names",
            "selector",
        )
    dynamic_request = _run_dynamic_request(request, context, fields, recipe)
    inputs = alias_mapping(dynamic_request, "input", "inputs")
    parameters = mapping(dynamic_request.get("parameters", {}), "parameters")
    validate_input_names(inputs, description, ())
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
        raise input_error(
            f"actual value: {actual_value(validation.get('ok'))}; "
            "run request must pass offline operation validation; run `gravity insight "
            "operations describe` and correct inputs",
            "inputs",
        )
    if context.output_fields:
        validate_output_fields(description, context.output_fields, request_inputs=bound)


def _run_dynamic_request(
    request: Mapping[str, Any],
    context: AdapterContext,
    fields: Mapping[str, Any],
    recipe: Any | None,
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(request))
    supplied = alias_mapping(selected, "input", "inputs")
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
        raise input_error(
            f"actual value: {actual_value(target)}; "
            "run binding target must stay inside the adapter contract; remove the extra binding",
            "bindings",
        )
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
            raise input_error(
                f"actual value: {actual_value({'kind': 'recipe', 'configured': False})}; "
                "run recipe must be configured in gravity.toml; inspect [plan_recipes]",
                "selector",
            ) from exc
        operation_id = str(recipe.operation)
    else:
        recipe = None
        operation_id = selector
    if operation_id not in stable_operations:
        raise input_error(
            f"actual value: {actual_value(operation_id)}; run selector must be a stable "
            "operation_id or @recipe; run `gravity insight operations search`",
            "selector",
        )
    return operation_id, recipe


def _validate_run_options(
    request: Mapping[str, Any],
    parameters: Mapping[str, Any],
    recipe: Any | None,
    workspace: Any,
    context: AdapterContext,
) -> None:
    if recipe is None and parameters:
        raise input_error(
            f"actual value: {actual_value(sorted(parameters))}; "
            "parameters requires a workspace recipe; use an @recipe selector",
            "parameters",
        )
    if recipe is not None:
        _validate_recipe_parameters(recipe, parameters, context)
    if "app" in request and not has_dynamic(context, "/app"):
        workspace.resolve_app(request.get("app"))
    for field in ("start", "end"):
        if field in request and not isinstance(request[field], str):
            raise input_error(
                f"actual value: {actual_value(request.get(field))}; run time bounds must be strings",
                field,
            )
    if "all_pages" in request and not isinstance(request["all_pages"], bool):
        raise input_error(
            f"actual value: {actual_value(request.get('all_pages'))}; run all_pages must be a boolean",
            "all_pages",
        )


def _validate_recipe_parameters(
    recipe: Any, parameters: Mapping[str, Any], context: AdapterContext
) -> None:
    allowed_parameters = set(recipe.parameters) | set(recipe.required_parameters)
    extra = set(parameters) - allowed_parameters
    if extra:
        raise input_error(
            f"actual value: {actual_value(sorted(extra))}; "
            "run request must use only declared recipe parameters; remove the extra keys",
            "parameters",
        )
    missing = set(recipe.required_parameters) - set(parameters)
    dynamic_parameters = {
        target.split("/", 2)[2]
        for target in context.dynamic_targets
        if target.startswith("/parameters/") and target.count("/") == 2
    }
    unbound = missing - dynamic_parameters
    if unbound:
        raise input_error(
            f"actual value: {actual_value(sorted(unbound))}; "
            "run request must include every required recipe parameter",
            "parameters",
        )


def validate_sql_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    request_object(request, SQL_FIELDS, "sql_product")
    validate_exact_targets(context, frozenset({"/start", "/end", "/app_id"}))
    product = request.get("product")
    if not isinstance(product, str) or not product.strip():
        raise input_error(
            f"actual value: {actual_value(product)}; SQL product request requires product",
            "product",
        )
    try:
        definition = workspace.product(product)
    except (KeyError, ValueError) as exc:
        raise input_error(
            f"actual value: {actual_value({'configured': False})}; "
            "SQL product must be configured in gravity.toml; inspect [sql_products]",
            "product",
        ) from exc
    max_rows = definition.get("max_rows", 1_000)
    if type(max_rows) is not int or max_rows > context.max_items:
        raise input_error(
            f"actual value: {actual_value((max_rows, context.max_items))}; "
            "SQL product max_rows must stay at or below this node max_items; raise limits.max_items",
            "limits.max_items",
        )
    dynamic = set(context.dynamic_targets)
    start, end = request.get("start"), request.get("end")
    for field, value in (("start", start), ("end", end)):
        if f"/{field}" not in dynamic and not isinstance(value, str):
            raise input_error(
                f"actual value: {actual_value((start, end))}; SQL product requires start and end",
                "start/end",
            )
    if not ({"/start", "/end"} & dynamic):
        normalize_window(start, end)
    _validate_sql_apps(request, product, workspace, dynamic)
    allowed = frozenset(str(item) for item in definition.get("output_fields", []))
    validate_selected_fields(context.output_fields, allowed, "output_fields")


def _validate_sql_apps(
    request: Mapping[str, Any],
    product: str,
    workspace: Any,
    dynamic: set[str],
) -> None:
    if "app_id" in request and "app_ids" in request:
        raise input_error(
            f"actual value: {actual_value(['app_id', 'app_ids'])}; "
            "SQL product must use only one of app_id or app_ids; remove the other",
            "app_ids",
        )
    if {"/app_id", "/app_ids"} & dynamic:
        return
    raw = request.get("app_ids", request.get("app_id"))
    if raw is None:
        normalize_app_ids(product, None, workspace)
        return
    values = [raw] if type(raw) is int else list(raw) if array(raw) else None
    if values is None:
        raise input_error(
            f"actual value: {actual_value(type(raw).__name__)}; "
            "SQL product app ids must be positive integers or a workspace App list",
            "app_ids",
        )
    normalize_app_ids(product, values, workspace)


__all__ = ["RUN_FIELDS", "SQL_FIELDS", "validate_run_plan", "validate_sql_plan"]
