"""Closed, Agent-friendly product boundary for Multidim queries."""

from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any, Mapping

from .composite_batch import validate_composite_bounds
from .errors import InputValidationError
from .multidim_service import (
    MAX_MULTIDIM_WORKERS,
    MULTIDIM_QUERY_OPERATION,
    MultidimService,
)


MULTIDIM_INPUT_SCHEMA_VERSION = "gravity-insight.multidim-input.v1"
MULTIDIM_PREVIEW_SCHEMA_VERSION = "gravity-insight.multidim-preview.v1"

_FIELDS = (
    "date_list",
    "time_dims",
    "metrics_list",
    "custom_metrics_list",
    "data_dims",
    "relate_dims",
    "filters",
    "multi_keys",
)
_REQUIRED = frozenset({"date_list", "time_dims", "metrics_list"})
_TIME_DIMS = ("hour", "day", "week", "month", "total")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_NAME_LIMITS = {
    "metrics_list": 500,
    "custom_metrics_list": 500,
    "data_dims": 100,
    "relate_dims": 100,
}
_MAX_FILTERS = 100
_MAX_FILTER_VALUES = 100


def multidim_input_schema() -> dict[str, Any]:
    """Return a fresh machine schema for the closed product input."""

    def name_array(field: str, *, default: bool = False) -> dict[str, Any]:
        result = {
            "type": "array",
            "maxItems": _NAME_LIMITS[field],
            "items": {"type": "string", "maxLength": 4_096},
        }
        if default:
            result["default"] = []
        return result
    schema = {
        "schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["date_list", "time_dims", "metrics_list"],
        "properties": {
            "date_list": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {"type": "string", "format": "date"},
            },
            "time_dims": {"type": "string", "enum": list(_TIME_DIMS)},
            "metrics_list": name_array("metrics_list"),
            "custom_metrics_list": name_array("custom_metrics_list", default=True),
            "data_dims": name_array("data_dims", default=True),
            "relate_dims": name_array("relate_dims", default=True),
            "filters": {
                "type": "array",
                "maxItems": _MAX_FILTERS,
                "default": [],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "operator"],
                    "properties": {
                        "field": {"type": "string", "minLength": 1, "maxLength": 128},
                        "operator": {
                            "oneOf": [
                                {"type": "string", "maxLength": 4_096},
                                {"type": "integer"},
                            ]
                        },
                        "values": {
                            "type": "array",
                            "maxItems": _MAX_FILTER_VALUES,
                            "items": {"type": ["string", "number", "integer", "boolean", "null"]},
                        },
                        "value": {
                            "type": "array",
                            "maxItems": _MAX_FILTER_VALUES,
                            "items": {"type": ["string", "number", "integer", "boolean", "null"]},
                        },
                    },
                },
            },
            "multi_keys": {
                "type": "array",
                "minItems": 1,
                "maxItems": 29,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 2, "maximum": 30},
            },
        },
    }
    return copy.deepcopy(schema)


def normalize_multidim_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the product fields without invoking a client or adding a DSL."""

    if not isinstance(inputs, Mapping):
        raise _input_error("multidimensional inputs must be an object", "inputs")
    unknown = set(inputs) - set(_FIELDS)
    missing = _REQUIRED - set(inputs)
    if unknown:
        raise _input_error("multidimensional inputs contain unsupported fields", "inputs")
    if missing:
        raise _input_error("multidimensional inputs are missing required fields", "inputs")

    normalized = {
        "date_list": _dates(inputs.get("date_list")),
        "time_dims": _time_dim(inputs.get("time_dims")),
        "metrics_list": _names(inputs.get("metrics_list"), "metrics_list"),
        "custom_metrics_list": _names(
            inputs.get("custom_metrics_list", []), "custom_metrics_list"
        ),
        "data_dims": _names(inputs.get("data_dims", []), "data_dims"),
        "relate_dims": _names(inputs.get("relate_dims", []), "relate_dims"),
        "filters": _filters(inputs.get("filters", [])),
    }
    if "multi_keys" in inputs:
        normalized["multi_keys"] = _multi_keys(inputs.get("multi_keys"))
    return normalized


def bind_multidim_app(inputs: Mapping[str, Any], app_id: str | int) -> dict[str, Any]:
    """Return normalized inputs with exactly one canonical ``app_id`` filter."""

    normalized = normalize_multidim_inputs(inputs)
    selected_app = _positive_app_id(app_id)
    retained = [item for item in normalized["filters"] if item["field"] != "app_id"]
    if len(retained) >= _MAX_FILTERS:
        raise _input_error(
            "filters leave no bounded slot for the required app_id binding",
            "filters",
        )
    retained.append(
        {"field": "app_id", "operator": "EQUALS", "values": [selected_app]}
    )
    normalized["filters"] = retained
    return normalized


def prepare_multidim_query(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    app_id: str | int,
) -> dict[str, Any]:
    """Perform a value-safe, zero-network product preflight."""

    del client  # The parameter keeps prepare/run call sites symmetric by design.
    bound = bind_multidim_app(inputs, app_id)
    canonical_app = _positive_app_id(app_id)
    needs_metadata = bool(bound["metrics_list"] or bound["custom_metrics_list"])
    status = "needs_live_metadata" if needs_metadata else "validated"
    return {
        "schema_version": MULTIDIM_PREVIEW_SCHEMA_VERSION,
        "ok": True,
        "status": status,
        "exit_code": 0,
        "app_id": canonical_app,
        "network_called": False,
        "query_executed": False,
        "operation_id": MULTIDIM_QUERY_OPERATION,
        "validation": {
            "shape": "validated_offline",
            "live_metadata": "required" if needs_metadata else "not_required",
            "metric_count": len(bound["metrics_list"]),
            "custom_metric_count": len(bound["custom_metrics_list"]),
            "data_dim_count": len(bound["data_dims"]),
            "relate_dim_count": len(bound["relate_dims"]),
            "filter_count": len(bound["filters"]),
            "multi_key_count": len(bound.get("multi_keys", [])),
        },
        "input_schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "next_action": (
            "Execute the same explicit Multidim request to validate live metric metadata."
            if needs_metadata
            else "Execute the same explicit Multidim request."
        ),
    }


def run_multidim_query(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    app_id: str | int,
    include_total: bool = False,
    read_all: bool = False,
    max_pages: int = 1_000,
    max_items: int = 100_000,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Validate and execute one explicit, App-bound Multidim query."""

    _boolean(include_total, "include_total")
    _boolean(read_all, "read_all")
    pages, items = validate_composite_bounds(max_pages, max_items, minimum_items=1)
    workers = _workers(max_workers)
    canonical_app = _positive_app_id(app_id)
    bound = bind_multidim_app(inputs, canonical_app)
    result = MultidimService(client).query(
        bound,
        include_total=include_total,
        read_all=read_all,
        max_pages=pages,
        max_items=items,
        max_workers=workers,
    )
    return {
        **result,
        "app_id": canonical_app,
        "network_called": True,
        "query_executed": True,
    }


def _dates(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _input_error("date_list must contain exactly two ISO dates", "date_list")
    parsed: list[date] = []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _input_error("date_list must contain canonical ISO dates", "date_list")
        try:
            day = date.fromisoformat(item)
        except ValueError:
            raise _input_error("date_list must contain valid ISO dates", "date_list") from None
        if day.isoformat() != item:
            raise _input_error("date_list must contain canonical ISO dates", "date_list")
        parsed.append(day)
        result.append(item)
    if parsed[0] > parsed[1]:
        raise _input_error("date_list start must not be after end", "date_list")
    return result


def _time_dim(value: Any) -> str:
    if not isinstance(value, str) or value not in _TIME_DIMS:
        raise _input_error("time_dims is not a supported grain", "time_dims")
    return value


def _names(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > _NAME_LIMITS[field]:
        raise _input_error(f"{field} must be a bounded string array", field)
    selected = list(value)
    if any(
        not isinstance(item, str)
        or len(item) > 4_096
        for item in selected
    ):
        raise _input_error(f"{field} must contain bounded strings", field)
    return selected


def _filters(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_FILTERS:
        raise _input_error("filters must be a bounded array", "filters")
    return [_filter_item(item) for item in value]


def _filter_item(value: Any) -> dict[str, Any]:
    allowed = {"field", "operator", "values", "value"}
    if (
        not isinstance(value, Mapping)
        or set(value) - allowed
        or "field" not in value
        or "operator" not in value
    ):
        raise _input_error("filter items must match the closed product shape", "filters")
    field = _filter_field(value.get("field"))
    operator = _filter_operator(value.get("operator"))
    value_key = "values" if "values" in value else "value"
    normalized = {"field": field, "operator": operator}
    if value_key in value:
        normalized[value_key] = _filter_values(value.get(value_key))
    return normalized


def _filter_field(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 128 or not _FIELD_RE.fullmatch(value):
        raise _input_error("filter field must be a bounded field name", "filters")
    return value


def _filter_operator(value: Any) -> str | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int))
        or isinstance(value, str)
        and len(value) > 4_096
    ):
        raise _input_error("filter operator must be a bounded string or integer", "filters")
    return value


def _filter_values(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_FILTER_VALUES:
        raise _input_error("filter values must be a bounded array", "filters")
    if any(not _is_bounded_scalar(scalar) for scalar in value):
        raise _input_error("filter values must contain bounded JSON scalars", "filters")
    return list(value)


def _is_bounded_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str) and len(value) <= 4_096


def _multi_keys(value: Any) -> list[int]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or len(value) > 29
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 2 <= item <= 30
            for item in value
        )
        or len(set(value)) != len(value)
        or list(value) != sorted(value)
    ):
        raise _input_error(
            "multi_keys must be unique ascending integers from 2 to 30",
            "multi_keys",
        )
    return list(value)


def _positive_app_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _input_error("app_id must be a positive integer", "app_id")
    rendered = str(value).strip()
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise _input_error("app_id must be a positive integer", "app_id")
    return str(int(rendered))


def _workers(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_MULTIDIM_WORKERS
    ):
        raise _input_error(
            f"max_workers must be between 1 and {MAX_MULTIDIM_WORKERS}",
            "max_workers",
        )
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise _input_error(f"{field} must be boolean", field)
    return value


def _input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(message, field=field)


__all__ = [
    "MULTIDIM_INPUT_SCHEMA_VERSION",
    "MULTIDIM_PREVIEW_SCHEMA_VERSION",
    "bind_multidim_app",
    "multidim_input_schema",
    "normalize_multidim_inputs",
    "prepare_multidim_query",
    "run_multidim_query",
]
