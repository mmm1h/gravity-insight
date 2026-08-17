"""Projection and structural helpers shared by controlled Plan adapters."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import InputValidationError
from .plan import AdapterContext
from .actionable_error_values import actual_value


ENVELOPE_FIELDS = frozenset(
    {
        "schema_version", "ok", "status", "exit_code", "count", "total", "limit",
        "offset", "offline", "catalog", "kind", "requested_count",
        "network_called",
        "succeeded_count", "failed_count", "question_count", "source_count",
        "operation_count", "paginated_operation_count", "app_id", "coverage", "scopes",
        "scope", "observed",
        "result_audit",
    }
)
METADATA_FAILURE_FIELDS = frozenset(
    {"source", "operation_id", "status", "category", "code"}
)


def identity_projection(
    result: Any, _fields: tuple[str, ...], _context: AdapterContext
) -> Any:
    return copy.deepcopy(result)


def sql_projection(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> Any:
    if not isinstance(result, Mapping):
        raise input_error("SQL product result is invalid", "result")
    selected = envelope(result)
    items = result.get("results")
    selected["results"] = [
        project_sql_item(item, fields) for item in items
    ] if isinstance(items, list) else []
    return selected


def project_sql_item(item: Any, fields: tuple[str, ...]) -> Any:
    if not isinstance(item, Mapping):
        raise input_error("SQL product item is invalid", "result")
    selected = {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key in {
            "request_id", "product", "ok", "status", "exit_code", "error",
            "result_audit",
        }
    }
    if item.get("ok") is False:
        return selected
    for key in ("window", "app_ids", "warnings", "forbidden_claims", "hashes", "notes"):
        if key in item:
            selected[key] = copy.deepcopy(item[key])
    selected["summary"] = recursive_fields(item.get("summary"), fields)
    return selected


def metadata_projection(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> Any:
    if not isinstance(result, Mapping):
        raise input_error("metadata result is invalid", "result")
    selected = envelope(result)
    rows = result.get("results")
    selected["results"] = [
        {field: copy.deepcopy(item[field]) for field in fields if field in item}
        for item in rows
        if isinstance(item, Mapping)
    ] if isinstance(rows, list) else []
    failures = result.get("failures")
    if isinstance(failures, list):
        selected["failures"] = [
            {
                field: copy.deepcopy(item[field])
                for field in METADATA_FAILURE_FIELDS
                if field in item and isinstance(item[field], str)
            }
            for item in failures[:9]
            if isinstance(item, Mapping)
        ]
    return selected


def composite_projection(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> Any:
    if not isinstance(result, Mapping):
        raise input_error("composite result is invalid", "result")
    selected = envelope(result)
    selected.update(
        {field: copy.deepcopy(result[field]) for field in fields if field in result}
    )
    return selected


def recursive_fields(value: Any, fields: tuple[str, ...]) -> Any:
    if isinstance(value, list):
        return [recursive_fields(item, fields) for item in value]
    if not isinstance(value, Mapping):
        return copy.deepcopy(value)
    structural = {"rows", "row_count", "app_ids", "measurement"}
    return {
        key: (
            recursive_fields(item, fields)
            if isinstance(item, (Mapping, list))
            else copy.deepcopy(item)
        )
        for key, item in value.items()
        if key in fields or key in structural or isinstance(item, (Mapping, list))
    }


def envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key in ENVELOPE_FIELDS
    }


def validate_input_names(
    inputs: Mapping[str, Any], schema: Mapping[str, Any], targets: tuple[str, ...]
) -> None:
    fields = schema.get("input_fields", schema.get("input_schema", {}))
    if not isinstance(fields, Mapping):
        raise input_error("operation input contract is invalid", "selector")
    dynamic_names = {
        target.split("/", 2)[2]
        for target in targets
        if target.startswith(("/input/", "/inputs/")) and target.count("/") == 2
    }
    if (set(inputs) | dynamic_names) - set(fields):
        raise input_error("run inputs contain an unknown operation field", "inputs")


def request_object(
    request: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    if not isinstance(request, Mapping):
        raise input_error(f"actual value: {actual_value(request)}; " + (f"{label} request must be an object"), "request")
    if set(request) - allowed:
        raise input_error(f"{label} request contains an unknown field", "request")


def alias_mapping(
    request: Mapping[str, Any], first: str, second: str
) -> Mapping[str, Any]:
    if first in request and second in request:
        raise input_error("run input aliases cannot be combined", second)
    return mapping(request.get(second, request.get(first, {})), second)


def mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise input_error(f"actual value: {actual_value(value)}; " + (f"{field} must be an object"), field)
    return value


def nested_mapping(value: Any, field: str) -> None:
    selected = mapping(value, field)
    if any(not isinstance(item, Mapping) for item in selected.values()):
        raise input_error(f"actual value: {actual_value(value)}; " + (f"{field} values must be objects"), field)


def validate_selected_fields(
    fields: tuple[str, ...], allowed: frozenset[str], field: str
) -> None:
    if set(fields) - allowed:
        raise input_error("output_fields contains a field outside the adapter contract", field)


def validate_exact_targets(context: AdapterContext, allowed: frozenset[str]) -> None:
    if set(context.dynamic_targets) - allowed:
        raise input_error("binding target is outside the adapter contract", "bindings")


def has_dynamic(context: AdapterContext, target: str) -> bool:
    return target in context.dynamic_targets


def bounded_optional(
    value: Any,
    minimum: int,
    maximum: int,
    field: str,
    *,
    allow_none: bool = False,
) -> None:
    if allow_none and value is None:
        return
    if type(value) is not int or not minimum <= value <= maximum:
        raise input_error(f"actual value: {actual_value(value)}; " + (f"{field} is outside its allowed bound"), field)


def array(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(message, field=field)


__all__ = [
    "alias_mapping", "array", "bounded_optional", "composite_projection",
    "has_dynamic", "identity_projection", "input_error", "mapping",
    "metadata_projection", "nested_mapping", "request_object", "sql_projection",
    "validate_exact_targets", "validate_input_names", "validate_selected_fields",
]
