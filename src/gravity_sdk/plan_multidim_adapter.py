"""Dedicated Plan adapter for App-bound and legacy Multidim requests."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import PaginationError
from .multidim_service import MULTIDIM_QUERY_OPERATION
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    mapping,
    nested_mapping,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .plan_binding import set_pointer
from .plan_multidim_result import (
    is_multidim_result,
    multidim_result_item_count,
    project_multidim_result,
    sanitize_multidim_result,
)


MULTIDIM_NAME = "multidim"
MULTIDIM_REQUEST_FIELDS = frozenset(
    {"name", "app", "inputs", "include_total", "read_all", "metadata_inputs"}
)
MULTIDIM_OUTPUT_FIELDS = frozenset(
    {
        "app_id",
        "error",
        "exit_code",
        "input_schema_version",
        "network_called",
        "next_action",
        "ok",
        "operation_id",
        "query",
        "query_executed",
        "schema_version",
        "status",
        "total",
        "validation",
    }
)


def validate_multidim_plan(
    insight: Any,
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> None:
    """Validate one request, touching the Insight facade only for legacy fields."""

    request_object(request, MULTIDIM_REQUEST_FIELDS, "multidim")
    if request.get("name") != MULTIDIM_NAME:
        raise input_error("multidim request has the wrong composite name", "name")
    _switches(request)
    nested_mapping(request.get("metadata_inputs", {}), "metadata_inputs")
    _validate_output_fields(context)

    raw_inputs = mapping(request.get("inputs", {}), "inputs")
    product_schema = _product_schema()
    product_fields = product_schema["properties"]
    legacy_fields: Mapping[str, Any] | None = None
    dynamic_names = _dynamic_input_names(context.dynamic_targets)
    if not dynamic_names <= set(product_fields):
        legacy_fields = _legacy_fields(insight)
    allowed_names = set(product_fields) | set(legacy_fields or {})
    validate_exact_targets(
        context,
        frozenset({"/app", *(f"/inputs/{name}" for name in allowed_names)}),
    )
    dynamic_inputs = copy.deepcopy(dict(raw_inputs))
    for name in dynamic_names:
        spec = product_fields.get(name)
        if spec is None:
            assert legacy_fields is not None
            spec = legacy_fields[name]
        set_pointer(dynamic_inputs, f"/{name}", _field_sentinel(spec))

    app_id = 1 if "/app" in context.dynamic_targets else _resolve_app(
        workspace, request.get("app")
    )
    product_mode = _is_product_inputs(dynamic_inputs, product_schema) and not request.get(
        "metadata_inputs"
    )
    if product_mode:
        _validate_product_inputs(dynamic_inputs, app_id)
        return
    if legacy_fields is None:
        legacy_fields = _legacy_fields(insight)
    if (set(dynamic_inputs) | dynamic_names) - set(legacy_fields):
        raise input_error("multidim inputs contain an unknown operation field", "inputs")
    supplied = _bind_legacy_app(dynamic_inputs, app_id)
    validation = insight.validate(MULTIDIM_QUERY_OPERATION, supplied)
    if not isinstance(validation, Mapping) or validation.get("ok") is not True:
        raise input_error("multidim request failed offline validation", "inputs")


def execute_multidim_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute through the product core or the compatible legacy service."""

    app_id = _resolve_app(context.workspace, request.get("app"))
    inputs = dict(mapping(request.get("inputs", {}), "inputs"))
    include_total = bool(request.get("include_total", False))
    read_all = bool(request.get("read_all", False))
    product_mode = _is_product_inputs(inputs, _product_schema()) and not request.get(
        "metadata_inputs"
    )
    if product_mode:
        from .multidim_product import run_multidim_query

        native = run_multidim_query(
            sdk.insight,
            inputs,
            app_id=app_id,
            include_total=include_total,
            read_all=read_all,
            max_pages=context.max_pages,
            max_items=context.max_items,
            max_workers=1,
        )
    else:
        from .composite import CompositeService

        native = CompositeService(sdk.insight).multidim_query(
            _bind_legacy_app(inputs, app_id),
            include_total=include_total,
            read_all=read_all,
            metadata_inputs=request.get("metadata_inputs"),
            max_pages=context.max_pages,
            max_items=context.max_items,
            max_workers=1,
        )
        native = {
            **dict(native),
            "app_id": str(app_id),
            "network_called": True,
            "query_executed": True,
        }
    safe = sanitize_multidim_result(native, str(app_id))
    if multidim_result_item_count(safe) > context.max_items:
        raise PaginationError("multidimensional query exceeded its Plan item budget")
    return safe


def _product_schema() -> dict[str, Any]:
    from .multidim_product import multidim_input_schema

    schema = multidim_input_schema()
    if not isinstance(schema.get("properties"), Mapping):
        raise input_error("multidim product schema is invalid", "name")
    return schema


def _validate_product_inputs(inputs: Mapping[str, Any], app_id: int) -> None:
    from .multidim_product import (
        bind_multidim_app,
        normalize_multidim_inputs,
        prepare_multidim_query,
    )

    normalized = normalize_multidim_inputs(inputs)
    bound = bind_multidim_app(normalized, app_id)
    preview = prepare_multidim_query(None, bound, app_id=app_id)
    if preview.get("ok") is not True or preview.get("network_called") is not False:
        raise input_error("multidim product preflight failed", "inputs")


def _is_product_inputs(inputs: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    properties = schema.get("properties", {})
    return isinstance(properties, Mapping) and set(inputs) <= set(properties)


def _legacy_fields(insight: Any) -> Mapping[str, Any]:
    schema = insight.schema(MULTIDIM_QUERY_OPERATION)
    fields = schema.get("input_fields", {}) if isinstance(schema, Mapping) else {}
    if not isinstance(fields, Mapping):
        raise input_error("multidim operation input contract is invalid", "name")
    return fields


def _bind_legacy_app(inputs: Mapping[str, Any], app_id: int) -> dict[str, Any]:
    selected = copy.deepcopy(dict(inputs))
    filters = selected.get("filters", [])
    if not isinstance(filters, list):
        raise input_error("multidim filters must be an array", "inputs.filters")
    selected["filters"] = [
        item
        for item in filters
        if not isinstance(item, Mapping) or item.get("field") != "app_id"
    ] + [{"field": "app_id", "operator": "EQUALS", "values": [str(app_id)]}]
    return selected


def _resolve_app(workspace: Any, value: Any) -> int:
    try:
        app_id = workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise input_error("multidim App is not configured", "app") from None
    if type(app_id) is not int or app_id <= 0:
        raise input_error("multidim App is invalid", "app")
    return app_id


def _switches(request: Mapping[str, Any]) -> None:
    for field in ("include_total", "read_all"):
        if field in request and not isinstance(request[field], bool):
            raise input_error("multidim switches must be booleans", field)


def _validate_output_fields(context: AdapterContext) -> None:
    validate_selected_fields(
        context.output_fields, MULTIDIM_OUTPUT_FIELDS, "output_fields"
    )


def _dynamic_input_names(targets: tuple[str, ...]) -> set[str]:
    return {
        target.removeprefix("/inputs/")
        for target in targets
        if target.startswith("/inputs/") and target.count("/") == 2
    }


def _field_sentinel(value: Any) -> Any:
    spec = value if isinstance(value, Mapping) else {}
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    kind = _field_kind(spec.get("type", "string"))
    if kind == "array":
        return _array_sentinel(spec)
    if kind == "object":
        return _object_sentinel(spec)
    if kind == "integer":
        return max(1, int(spec.get("minimum", 1)))
    if kind == "number":
        return max(1, spec.get("minimum", 1))
    if kind == "boolean":
        return False
    if spec.get("format") == "date" or kind == "date":
        return "2026-01-01"
    return "plan-preflight"


def _field_kind(value: Any) -> str:
    if isinstance(value, list):
        return next((item for item in value if item != "null"), "string")
    return str(value)


def _array_sentinel(spec: Mapping[str, Any]) -> list[Any]:
    count = max(int(spec.get("minItems", spec.get("min_items", 0))), 1)
    item = spec.get("items", {"type": spec.get("item_type", "string")})
    return [_field_sentinel(item) for _ in range(count)]


def _object_sentinel(spec: Mapping[str, Any]) -> dict[str, Any]:
    required, properties = spec.get("required"), spec.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        return {}
    return {name: _field_sentinel(properties.get(name, {})) for name in required}


__all__ = [
    "MULTIDIM_NAME",
    "execute_multidim_plan",
    "is_multidim_result",
    "multidim_result_item_count",
    "project_multidim_result",
    "validate_multidim_plan",
]
