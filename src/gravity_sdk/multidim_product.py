"""Closed, Agent-friendly product boundary for Multidim queries."""

from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any, Mapping

from .actionable_error_values import actual_value
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
    "data_conf",
)
_REQUIRED = frozenset({"date_list", "time_dims", "metrics_list"})
_TIME_DIMS = ("hour", "day", "week", "month", "total")
_MAX_SCALAR_TEXT = 4_096
_MAX_SCALAR_INT_BITS = 13_607
_FILTER_OPERATORS = frozenset(
    {
        "EQUALS",
        "IN",
        "NOT_EQUALS",
        "NOT_IN",
        "CONTAINS",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "RANGE_IN",
    }
)
_STATIC_FILTER_FIELDS = frozenset(
    {
        "advertiser_id",
        "app_id",
        "click_company",
        "day",
        "gid",
        "hour",
        "week",
        "month",
        "date",
        "stat_time",
    }
)
_DYNAMIC_FILTER_SOURCES = (
    "data_dims",
    "relate_dims",
    "metrics_list",
    "custom_metrics_list",
)
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_NAME_LIMITS = {
    "metrics_list": 500,
    "custom_metrics_list": 500,
    "data_dims": 100,
    "relate_dims": 100,
}
_MAX_FILTERS = 100
_MAX_FILTER_VALUES = 100
FRONTEND_ADREPORT_DATA_CONF = {
    "accumulate": False,
    "asa_time_zone": "UTC",
    "decimal_point": 2,
    "minigame_pay_shared_ratio": 100,
    "minigame_pay_shared_ratio_ios": 100,
    "return_all_metrics": False,
}


def multidim_input_schema() -> dict[str, Any]:
    """Return a fresh machine schema for the closed product input."""

    def name_array(field: str, *, default: bool = False) -> dict[str, Any]:
        result = {
            "type": "array",
            "maxItems": _NAME_LIMITS[field],
            "items": {"type": "string", "minLength": 1, "maxLength": 4_096},
        }
        if default:
            result["default"] = []
        return result
    schema = {
        "schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["date_list", "time_dims", "metrics_list"],
        "x-cli-shortcuts": _cli_shortcut_schema(),
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
                "x-allowed-field-sources": {
                    "static": sorted(_STATIC_FILTER_FIELDS),
                    "input_fields": list(_DYNAMIC_FILTER_SOURCES),
                },
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "operator"],
                    "properties": {
                        "field": {"type": "string", "minLength": 1, "maxLength": 128},
                        "operator": {
                            "type": "string",
                            "enum": sorted(_FILTER_OPERATORS),
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
            "data_conf": {"const": copy.deepcopy(FRONTEND_ADREPORT_DATA_CONF)},
        },
    }
    return copy.deepcopy(schema)


def _cli_shortcut_schema() -> dict[str, Any]:
    return {
        "precedence": ["shortcut", "--set", "--input", "contract_default"],
        "filter": {
            "argv": ["FIELD", "OPERATOR", "VALUE[,VALUE...]"],
            "maps_to": "filters",
            "max_occurrences": 1,
            "operator_enum": sorted(_FILTER_OPERATORS),
            "value_items": "JSON scalar",
            "combination_logic": "unproven_single_condition_only",
            "conflicts_with": ["--media"],
        },
        "custom-metric": {
            "argv": ["NAME[,NAME...]"],
            "maps_to": "custom_metrics_list",
        },
        "relate-dim": {
            "argv": ["NAME[,NAME...]"],
            "maps_to": "relate_dims",
        },
    }


def normalize_multidim_inputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the product fields without invoking a client or adding a DSL."""

    if not isinstance(inputs, Mapping):
        raise _input_error(f"actual value: {actual_value(inputs)}; " + ("multidimensional inputs must be an object"), "inputs")
    unknown = set(inputs) - set(_FIELDS)
    missing = _REQUIRED - set(inputs)
    if unknown:
        raise _input_error("multidimensional inputs contain unsupported fields; must use only declared fields; remove extras", "inputs")
    if missing:
        raise _input_error("multidimensional inputs are missing required fields; must include every required field", "inputs")

    normalized: dict[str, Any] = {
        "date_list": _dates(inputs.get("date_list")),
        "time_dims": _time_dim(inputs.get("time_dims")),
        "metrics_list": _names(inputs.get("metrics_list"), "metrics_list"),
        "custom_metrics_list": _names(
            inputs.get("custom_metrics_list", []), "custom_metrics_list"
        ),
        "data_dims": _names(inputs.get("data_dims", []), "data_dims"),
        "relate_dims": _names(inputs.get("relate_dims", []), "relate_dims"),
    }
    _require_metric_for_dimensions(normalized)
    allowed_fields = _STATIC_FILTER_FIELDS | {
        item
        for source in _DYNAMIC_FILTER_SOURCES
        for item in normalized[source]
    }
    normalized["filters"] = _filters(
        inputs.get("filters", []), allowed_fields=allowed_fields
    )
    if "multi_keys" in inputs:
        normalized["multi_keys"] = _multi_keys(inputs.get("multi_keys"))
    if "data_conf" in inputs:
        normalized["data_conf"] = _data_conf(inputs.get("data_conf"))
    return normalized


def _data_conf(value: Any) -> dict[str, Any]:
    if value != FRONTEND_ADREPORT_DATA_CONF:
        raise InputValidationError(
            "data_conf does not match the frontend-proven adreport profile; "
            f"actual value: {actual_value(value)}",
            field="data_conf",
            next_action=(
                "Use the exact data_conf object published by the current input schema "
                f"and retry: {actual_value(FRONTEND_ADREPORT_DATA_CONF)}"
            ),
        )
    return copy.deepcopy(FRONTEND_ADREPORT_DATA_CONF)


def bind_multidim_app(inputs: Mapping[str, Any], app_id: str | int) -> dict[str, Any]:
    """Return normalized inputs with exactly one canonical ``app_id`` filter."""

    normalized = normalize_multidim_inputs(inputs)
    selected_app = _positive_app_id(app_id)
    retained = [item for item in normalized["filters"] if item["field"] != "app_id"]
    if len(retained) >= _MAX_FILTERS:
        raise _input_error(
            "filters leave no bounded slot for the required app_id binding; must leave a slot for app_id; remove one filter",
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
        "input_schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "network_called": True,
        "query_executed": True,
    }


def _dates(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _input_error(f"actual value: {actual_value(value)}; " + ("date_list must contain exactly two ISO dates"), "date_list")
    parsed: list[date] = []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise _input_error(f"actual value: {actual_value(item)}; " + ("date_list must contain canonical ISO dates"), "date_list")
        try:
            day = date.fromisoformat(item)
        except ValueError:
            raise _input_error(f"actual value: {actual_value(value)}; " + ("date_list must contain valid ISO dates"), "date_list") from None
        if day.isoformat() != item:
            raise _input_error(f"actual value: {actual_value(value)}; " + ("date_list must contain canonical ISO dates"), "date_list")
        parsed.append(day)
        result.append(item)
    if parsed[0] > parsed[1]:
        raise _input_error(f"actual value: {actual_value(parsed[0])}; " + ("date_list start must not be after end"), "date_list")
    return result


def _time_dim(value: Any) -> str:
    if not isinstance(value, str) or value not in _TIME_DIMS:
        raise _input_error("time_dims is not a supported grain; must be one of the documented Multidim grains", "time_dims")
    return value


def _names(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > _NAME_LIMITS[field]:
        raise _input_error(f"actual value: {actual_value(value)}; " + (f"{field} must be a bounded string array"), field)
    selected = list(value)
    if any(not isinstance(item, str) or not item or len(item) > 4_096 for item in selected):
        raise _input_error(f"actual value: {actual_value(selected)}; " + (f"{field} must contain bounded non-empty strings"), field)
    return selected


def _require_metric_for_dimensions(inputs: Mapping[str, Any]) -> None:
    if (
        not inputs["metrics_list"]
        and not inputs["custom_metrics_list"]
        and (inputs["data_dims"] or inputs["relate_dims"])
    ):
        raise _input_error(
            "data_dims/relate_dims require at least one selected metric; must add metrics_list",
            "data_dims/relate_dims",
        )


def _filters(
    value: Any, *, allowed_fields: frozenset[str] | set[str]
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_FILTERS:
        raise _input_error(f"actual value: {actual_value(value)}; " + ("filters must be a bounded array"), "filters")
    return [_filter_item(item, allowed_fields=allowed_fields) for item in value]


def _filter_item(
    value: Any, *, allowed_fields: frozenset[str] | set[str]
) -> dict[str, Any]:
    allowed = {"field", "operator", "values", "value"}
    if (
        not isinstance(value, Mapping)
        or set(value) - allowed
        or "field" not in value
        or "operator" not in value
    ):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("filter items must match the closed product shape"), "filters")
    field = _filter_field(value.get("field"))
    if field not in allowed_fields:
        raise _input_error(
            "filter field is absent from the explicit Multidim controls; must use an explicit Multidim control field",
            "filters[].field",
        )
    operator = _filter_operator(value.get("operator"))
    value_key = "values" if "values" in value else "value"
    normalized = {"field": field, "operator": operator}
    if value_key in value:
        normalized[value_key] = _filter_values(value.get(value_key))
    return normalized


def _filter_field(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 128 or not _FIELD_RE.fullmatch(value):
        raise _input_error(
            f"actual value: {actual_value(value)}; " + ("filter field must be a bounded field name"), "filters[].field"
        )
    return value


def _filter_operator(value: Any) -> str:
    if not isinstance(value, str) or value not in _FILTER_OPERATORS:
        raise _input_error("filter operator is not supported; must be one of the documented Multidim operators", "filters[].operator")
    return value


def _filter_values(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_FILTER_VALUES:
        raise _input_error("filter values must be a bounded array", "filters[].values")
    if any(not _is_bounded_scalar(scalar) for scalar in value):
        raise _input_error(
            "filter values must contain bounded JSON scalars", "filters[].values"
        )
    return list(value)


def _is_bounded_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value.bit_length() <= _MAX_SCALAR_INT_BITS
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str) and len(value) <= _MAX_SCALAR_TEXT


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
            f"actual value: {actual_value(value)}; " + ("multi_keys must be unique ascending integers from 2 to 30"),
            "multi_keys",
        )
    return list(value)


def _positive_app_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("app_id must be a positive integer"), "app_id")
    if isinstance(value, int):
        if value <= 0 or value.bit_length() > 426:
            raise _input_error(f"actual value: {actual_value(value)}; " + ("app_id must be a bounded positive integer"), "app_id")
        rendered = str(value)
    else:
        rendered = value.strip()
    if (
        not rendered
        or len(rendered) > 128
        or not rendered.isascii()
        or not rendered.isdigit()
        or not any(character != "0" for character in rendered)
    ):
        raise _input_error(f"actual value: {actual_value(rendered)}; " + ("app_id must be a positive integer"), "app_id")
    return rendered.lstrip("0")


def _workers(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_MULTIDIM_WORKERS
    ):
        raise _input_error(
            f"actual value: {actual_value(value)}; " + (f"max_workers must be between 1 and {MAX_MULTIDIM_WORKERS}"),
            "max_workers",
        )
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise _input_error(f"actual value: {actual_value(value)}; " + (f"{field} must be boolean"), field)
    return value


def _input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(message, field=field)


__all__ = [
    "FRONTEND_ADREPORT_DATA_CONF",
    "MULTIDIM_INPUT_SCHEMA_VERSION",
    "MULTIDIM_PREVIEW_SCHEMA_VERSION",
    "bind_multidim_app",
    "multidim_input_schema",
    "normalize_multidim_inputs",
    "prepare_multidim_query",
    "run_multidim_query",
]
