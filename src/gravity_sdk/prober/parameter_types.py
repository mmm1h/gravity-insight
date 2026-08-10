"""Normalize ambiguous frontend parameter observations into probe-safe fields."""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping


MISSING = object()
_DESCRIPTION_MARKER = "Frontend-observed candidate"
_PARAMETER_GROUPS = (
    ("path", "path_parameters", "path_fields"),
    ("query", "query_parameters", "query_fields"),
    ("body", "body_parameters", "body_fields"),
)
_VALID_PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTEGER_PAGINATION_FIELDS = {
    "current_page",
    "limit",
    "page",
    "page_no",
    "page_num",
    "page_number",
    "page_size",
    "pagesize",
    "size",
}


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "any"


def top_level_parameters(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for location, source_key, request_key in _PARAMETER_GROUPS:
        parameters = route.get(source_key, [])
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, Mapping):
                continue
            name = str(parameter.get("name", ""))
            if (
                str(parameter.get("path", "")) != f"$.{name}"
                or not _VALID_PARAMETER_NAME.fullmatch(name)
            ):
                continue
            result.append(
                {
                    **copy.deepcopy(dict(parameter)),
                    "location": location,
                    "request_key": request_key,
                }
            )
    return result


def field_type(parameter: Mapping[str, Any]) -> str:
    observed = {
        str(item) for item in parameter.get("types", []) if isinstance(item, str)
    }
    name = str(parameter.get("name", "")).casefold()
    if name in _INTEGER_PAGINATION_FIELDS:
        return "integer"
    if "default" in parameter:
        default_type = value_type(parameter["default"])
        if (
            default_type == "number"
            and isinstance(parameter["default"], float)
            and parameter["default"].is_integer()
            and "integer" in observed
        ):
            default_type = "integer"
        if default_type in observed:
            return default_type
    for candidate in (
        "array",
        "object",
        "boolean",
        "integer",
        "number",
        "string",
    ):
        if candidate in observed:
            return candidate
    return "any"


def _item_type(parameter: Mapping[str, Any]) -> str | None:
    items = parameter.get("items")
    if not isinstance(items, Mapping):
        return None
    selected = field_type(items)
    allowed = {"string", "integer", "number", "boolean", "object"}
    return selected if selected in allowed else None


def candidate_value(parameter: Mapping[str, Any]) -> Any:
    if "default" in parameter:
        value = copy.deepcopy(parameter["default"])
        if (
            field_type(parameter) == "integer"
            and isinstance(value, float)
            and value.is_integer()
        ):
            return int(value)
        return value
    if parameter.get("required") != "observed_always":
        return MISSING
    name = str(parameter.get("name", "")).casefold()
    inferred_type = field_type(parameter)
    if name in {"page", "page_no", "page_num", "page_number", "current_page"}:
        return 1
    if name in {"page_size", "pagesize", "limit", "size"}:
        return 20
    if name in {"start_date", "begin_date", "date_start"}:
        return "$yesterday"
    if name in {"end_date", "date_end", "date"}:
        return "$today"
    if inferred_type == "array":
        return []
    if inferred_type == "object":
        return {}
    if inferred_type == "boolean":
        return False
    if inferred_type in {"integer", "number", "any"}:
        return 0
    return ""


def reconcile_field(
    existing: Any, parameter: Mapping[str, Any]
) -> tuple[dict[str, Any], Any]:
    """Repair inferred type/default conflicts without overriding valid manual types."""

    field = dict(existing) if isinstance(existing, Mapping) else {}
    inferred_type = field_type(parameter)
    candidate = candidate_value(parameter)
    current_type = str(field.get("type", "any"))
    candidate_type = value_type(candidate) if candidate is not MISSING else None
    compatible = (
        candidate_type is None
        or current_type == "any"
        or candidate_type == current_type
        or (current_type == "number" and candidate_type == "integer")
    )
    if not field.get("type") or field.get("type") == "any" or not compatible:
        field["type"] = inferred_type
    if field.get("type") != "array":
        for key in ("item_type", "item_enum", "min_items", "max_items"):
            field.pop(key, None)
    elif not field.get("item_type"):
        item_type = _item_type(parameter)
        if item_type:
            field["item_type"] = item_type
    return field, candidate


def merge_description(existing: Any, observed: str) -> str:
    current = str(existing or "").strip()
    if _DESCRIPTION_MARKER in current:
        current = current.split(_DESCRIPTION_MARKER, 1)[0].rstrip(" ;")
    return f"{current}; {observed}" if current else observed


def parameter_metadata(parameter: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": str(parameter["name"]),
        "location": str(parameter["location"]),
        "path": str(parameter.get("path", "")),
        "types": [str(item) for item in parameter.get("types", [])],
        "confidence": str(parameter.get("confidence", "unknown")),
        "presence": str(parameter.get("required", "unknown")),
        "default_observed": "default" in parameter,
    }


def apply_parameter(operation: dict[str, Any], parameter: Mapping[str, Any]) -> str:
    name = str(parameter["name"])
    field, candidate = reconcile_field(operation["input_fields"].get(name), parameter)
    if "default" in parameter:
        field["default"] = copy.deepcopy(candidate)
        operation["request"]["defaults"][name] = copy.deepcopy(candidate)
    confidence = str(parameter.get("confidence", "unknown"))
    presence = str(parameter.get("required", "unknown"))
    description = (
        f"{_DESCRIPTION_MARKER} from route-params.json "
        f"(confidence={confidence}, presence={presence}); "
        "presence describes frontend calls and is not a server-required declaration."
    )
    field["description"] = merge_description(field.get("description"), description)
    operation["input_fields"][name] = field

    request = operation["request"]
    binding = str(parameter["request_key"])
    for other in ("path_fields", "query_fields", "body_fields"):
        if other != binding:
            request[other] = [item for item in request.get(other, []) if item != name]
    request[binding] = sorted(set(request.get(binding, [])) | {name})
    probe_inputs = operation["live_probe"]["inputs"]
    if candidate is not MISSING and (
        "default" in parameter or name not in probe_inputs
    ):
        probe_inputs[name] = candidate
    return confidence
