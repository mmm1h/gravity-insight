"""Plan adapter for the single governed semantic composition family."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .errors import ContractChangedError, InputValidationError, PaginationError
from .plan import AdapterContext
from .plan_adapter_support import (
    mapping,
    request_object,
    validate_exact_targets,
    validate_selected_fields,
)
from .semantic_compose import (
    SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
    SEMANTIC_COMPOSE_NAME,
    actual_value,
    compile_semantic_compose,
    is_semantic_compose_result,
    run_semantic_compose,
)


REQUEST_FIELDS = frozenset({"name", "app", "inputs", "input_schema_version"})
OUTPUT_FIELDS = frozenset(
    {
        "allowed_claims",
        "definition",
        "error",
        "exit_code",
        "generated_query",
        "network_called",
        "next_action",
        "ok",
        "operation_id",
        "query_executed",
        "resolution_tier",
        "result",
        "result_source",
        "schema_version",
        "semantic_members",
        "status",
        "validation",
    }
)
_STRUCTURAL = frozenset(
    {
        "schema_version",
        "result_source",
        "resolution_tier",
        "definition",
        "ok",
        "status",
        "exit_code",
        "error",
        "next_action",
        "operation_id",
        "network_called",
        "query_executed",
    }
)


def validate_semantic_compose_plan(
    workspace: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> None:
    """Compile every semantic guard without touching the client."""

    request_object(request, REQUEST_FIELDS, "semantic compose")
    if request.get("name") != SEMANTIC_COMPOSE_NAME:
        raise _plan_error(
            "semantic compose request has the wrong name",
            "name",
            actual_value(request.get("name")),
            next_action="Use name='semantic_compose' and retry the same Plan.",
        )
    if request.get("input_schema_version") != SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION:
        raise _plan_error(
            "semantic compose request requires the current input schema version",
            "input_schema_version",
            actual_value(request.get("input_schema_version")),
            next_action=(
                "Run `gravity semantic compose --input-schema`, use its schema_version, "
                "and retry the same Plan."
            ),
        )
    validate_exact_targets(context, frozenset())
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")
    app_id = _resolve_app(workspace, request.get("app"))
    compiled = compile_semantic_compose(mapping(request.get("inputs"), "inputs"), app_id=app_id)
    if compiled["validation"].get("network_called") is not False:
        raise ContractChangedError("semantic compiler crossed its zero-network boundary")


def execute_semantic_compose_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    app_id = _resolve_app(context.workspace, request.get("app"))
    result = run_semantic_compose(
        sdk.insight,
        mapping(request.get("inputs"), "inputs"),
        app_id=app_id,
        max_pages=context.max_pages,
        max_items=context.max_items,
    )
    safe = _sanitize_result(result)
    if semantic_compose_result_item_count(safe) > context.max_items:
        raise PaginationError("semantic compose result exceeded its Plan item budget")
    return safe


def execute_multidim_or_semantic(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    if request.get("name") == SEMANTIC_COMPOSE_NAME:
        return execute_semantic_compose_plan(sdk, request, context)
    from .plan_multidim_adapter import execute_multidim_plan

    return execute_multidim_plan(sdk, request, context)


def project_semantic_compose_result(
    result: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    safe = _sanitize_result(result)
    if not fields:
        return safe
    return {
        key: copy.deepcopy(value)
        for key, value in safe.items()
        if key in _STRUCTURAL or key in fields
    }


def semantic_compose_result_item_count(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    result = value.get("result")
    query = result.get("query") if isinstance(result, Mapping) else None
    data = query.get("data") if isinstance(query, Mapping) else None
    rows = data.get("list") if isinstance(data, Mapping) else None
    return len(rows) if isinstance(rows, list) else 0


def _sanitize_result(value: Any) -> dict[str, Any]:
    if not is_semantic_compose_result(value):
        raise ContractChangedError("semantic compose result has the wrong schema")
    assert isinstance(value, Mapping)
    if not _valid_provenance(value):
        raise ContractChangedError("semantic compose result provenance changed")
    if not _valid_definition_identity(value["definition"]):
        raise ContractChangedError("semantic compose definition identity changed")
    return copy.deepcopy(dict(value))


def _valid_provenance(value: Mapping[str, Any]) -> bool:
    return value.get("resolution_tier") == "tier_b_governed_semantic" and all(
        (
            isinstance(value.get("definition"), Mapping),
            isinstance(value.get("semantic_members"), Mapping),
            isinstance(value.get("generated_query"), Mapping),
            isinstance(value.get("validation"), Mapping),
            isinstance(value.get("allowed_claims"), list),
            isinstance(value.get("result"), Mapping),
            value.get("network_called") is True,
            value.get("query_executed") is True,
        )
    )


def _valid_definition_identity(definition: Mapping[str, Any]) -> bool:
    fingerprint = definition.get("fingerprint")
    return (
        isinstance(definition.get("definition_id"), str)
        and type(definition.get("version")) is int
        and isinstance(fingerprint, str)
        and len(fingerprint) == 64
    )


def _resolve_app(workspace: Any, value: Any) -> int:
    try:
        app_id = workspace.resolve_app(value)
    except (KeyError, TypeError, ValueError):
        raise _plan_error(
            "semantic compose App is not configured",
            "app",
            actual_value(value),
            next_action="Use a configured workspace App alias or positive App id, then retry.",
        ) from None
    if type(app_id) is not int or app_id <= 0:
        raise _plan_error(
            "semantic compose App is invalid",
            "app",
            actual_value(app_id),
            next_action="Use a configured workspace App alias or positive App id, then retry.",
        )
    return app_id


def _plan_error(
    message: str, field: str, actual: str, *, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"{message}; actual value {actual}",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "SEMANTIC_COMPOSE_NAME",
    "execute_semantic_compose_plan",
    "execute_multidim_or_semantic",
    "is_semantic_compose_result",
    "project_semantic_compose_result",
    "semantic_compose_result_item_count",
    "validate_semantic_compose_plan",
]
