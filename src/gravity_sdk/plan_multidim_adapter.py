"""Dedicated Plan adapter for versioned, App-bound Multidim requests."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ContractChangedError, PaginationError
from .multidim_product import MULTIDIM_INPUT_SCHEMA_VERSION
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    mapping,
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
    {
        "name", "app", "inputs", "include_total", "read_all",
        "input_schema_version",
    }
)
_PRODUCT_SCALAR_INPUTS = frozenset({"time_dims"})
_SWITCH_TARGETS = frozenset({"/include_total", "/read_all"})
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
    """Validate one explicitly versioned product request without network access."""

    del insight
    request_object(request, MULTIDIM_REQUEST_FIELDS, "multidim")
    if request.get("name") != MULTIDIM_NAME:
        raise input_error("multidim request has the wrong composite name", "name")
    _require_product_version(request)
    _switches(request)
    _validate_output_fields(context)

    raw_inputs = mapping(request.get("inputs", {}), "inputs")
    if request.get("app") is None and "/app" not in context.dynamic_targets:
        raise input_error("Multidim requests require an explicit App", "app")
    dynamic_names = _dynamic_input_names(context.dynamic_targets)
    fields = _product_schema()["properties"]
    validate_exact_targets(
        context,
        frozenset(
            {
                "/app",
                *_SWITCH_TARGETS,
                *(f"/inputs/{name}" for name in _PRODUCT_SCALAR_INPUTS),
            }
        ),
    )
    dynamic_inputs = copy.deepcopy(dict(raw_inputs))
    for name in dynamic_names:
        set_pointer(dynamic_inputs, f"/{name}", _scalar_sentinel(fields[name]))

    app_id = 1 if "/app" in context.dynamic_targets else _resolve_app(
        workspace, request.get("app")
    )
    _validate_product_inputs(dynamic_inputs, app_id)


def execute_multidim_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    """Execute through the single versioned product core."""

    _require_product_version(request)
    app_id = _resolve_app(context.workspace, request.get("app"))
    inputs = dict(mapping(request.get("inputs", {}), "inputs"))
    _switches(request)
    include_total = bool(request.get("include_total", False))
    read_all = bool(request.get("read_all", False))
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
    safe = sanitize_multidim_result(native, str(app_id))
    if safe.get("input_schema_version") != MULTIDIM_INPUT_SCHEMA_VERSION:
        raise ContractChangedError("multidim input schema identity changed")
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


def _require_product_version(request: Mapping[str, Any]) -> None:
    if request.get("input_schema_version") != MULTIDIM_INPUT_SCHEMA_VERSION:
        raise input_error(
            "multidim requests require the current input schema version",
            "input_schema_version",
        )


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


def _scalar_sentinel(value: Any) -> Any:
    spec = value if isinstance(value, Mapping) else {}
    enum = spec.get("enum")
    if isinstance(enum, list) and enum:
        return copy.deepcopy(enum[0])
    kind = _field_kind(spec.get("type", "string"))
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


__all__ = [
    "MULTIDIM_NAME",
    "execute_multidim_plan",
    "is_multidim_result",
    "multidim_result_item_count",
    "project_multidim_result",
    "validate_multidim_plan",
]
