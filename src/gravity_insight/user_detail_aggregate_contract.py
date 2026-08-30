"""Closed input and error contract for governed user-detail aggregation."""

from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any, Mapping, Sequence

from .errors import (
    ContractChangedError,
    ErrorCategory,
    InputValidationError,
    PaginationError,
)
from .pagination_cli import DEFAULT_STDOUT_MAX_ITEMS
from .domains import ANALYSIS_DETAIL_OPERATIONS, ANALYSIS_METADATA_OPERATIONS
from .actionable_error_values import actual_value


INPUT_SCHEMA_VERSION = "gravity-insight.user-detail-aggregate-input.v1"
RESULT_SCHEMA_VERSION = "gravity-insight.user-detail-aggregate.v1"
PRODUCT_OPERATION_ID = "analysis.user_detail.aggregate"
SOURCE_OPERATION_ID = ANALYSIS_DETAIL_OPERATIONS["user"]
METADATA_OPERATION_ID = ANALYSIS_METADATA_OPERATIONS[1]
MAX_AGGREGATE_CELLS = DEFAULT_STDOUT_MAX_ITEMS

FIELD_UNSUPPORTED = "USER_DETAIL_AGGREGATE_FIELD_UNSUPPORTED"
MIXED_TYPE = "USER_DETAIL_AGGREGATE_MIXED_TYPE"
CARDINALITY_LIMIT = "USER_DETAIL_AGGREGATE_CARDINALITY_LIMIT"
BOUNDS_REQUIRED = "USER_DETAIL_AGGREGATE_BOUNDS_REQUIRED"

_INPUT_FIELDS = frozenset({"source", "filters", "group_by", "measures", "bounds"})
_OPERATORS = frozenset(
    {
        "EQUALS",
        "NOT_EQUALS",
        "IN",
        "NOT_IN",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "WITH_VAL",
        "WITHOUT_VAL",
    }
)
_COMPARISON_OPERATORS = frozenset({"GT", "GTE", "LT", "LTE"})
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class AggregateFieldUnsupportedError(InputValidationError):
    code = FIELD_UNSUPPORTED
    category = ErrorCategory.CALLER


class AggregateMixedTypeError(ContractChangedError):
    code = MIXED_TYPE
    category = ErrorCategory.UPSTREAM


class AggregateCardinalityError(PaginationError):
    code = CARDINALITY_LIMIT
    category = ErrorCategory.CALLER


class AggregateBoundsError(InputValidationError):
    code = BOUNDS_REQUIRED
    category = ErrorCategory.CALLER


def user_detail_aggregate_input_schema() -> dict[str, Any]:
    """Return a fresh machine-readable schema for the local product."""

    condition = _condition_schema()
    return copy.deepcopy(
        {
            "schema_version": INPUT_SCHEMA_VERSION,
            "type": "object",
            "additionalProperties": False,
            "required": sorted(_INPUT_FIELDS),
            "properties": {
                "source": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["app_id", "date"],
                    "properties": {
                        "app_id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "date": {"type": "string", "format": "date"},
                    },
                },
                "filters": {
                    "type": "array",
                    "maxItems": 20,
                    "items": condition,
                },
                "group_by": {
                    "type": "array",
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 256},
                },
                "measures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"oneOf": _measure_schemas(condition)},
                },
                "bounds": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["max_pages", "max_items", "max_cells"],
                    "properties": {
                        "max_pages": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "max_items": {"type": "integer", "minimum": 1, "maximum": 100000},
                        "max_cells": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_AGGREGATE_CELLS,
                        },
                    },
                },
            },
        }
    )


def _condition_schema() -> dict[str, Any]:
    scalar = {"type": ["string", "number", "integer", "boolean", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["field", "operator", "values"],
        "properties": {
            "field": {"type": "string", "minLength": 1, "maxLength": 256},
            "operator": {"type": "string", "enum": sorted(_OPERATORS)},
            "values": {"type": "array", "maxItems": 50, "items": scalar},
        },
    }


def _measure_schemas(condition: Mapping[str, Any]) -> list[dict[str, Any]]:
    name = {"type": "string", "pattern": _NAME.pattern}
    common = {"type": "object", "additionalProperties": False}
    return [
        {
            **common,
            "required": ["name", "op"],
            "properties": {"name": name, "op": {"const": "count"}},
        },
        {
            **common,
            "required": ["name", "op", "condition"],
            "properties": {
                "name": name,
                "op": {"const": "count_if"},
                "condition": condition,
            },
        },
        {
            **common,
            "required": ["name", "op", "field"],
            "properties": {
                "name": name,
                "op": {"const": "sum"},
                "field": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        },
    ]


def normalize_user_detail_aggregate_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a complete product request without reading metadata or rows."""

    if isinstance(value, Mapping) and "bounds" not in value:
        raise AggregateBoundsError(
            "aggregate requests require explicit max_pages, max_items, and max_cells",
            field="bounds",
        )
    _exact_mapping(value, _INPUT_FIELDS, "inputs")
    source = _source(value.get("source"))
    filters = _conditions(value.get("filters"), "filters", maximum=20)
    group_by = _fields(value.get("group_by"), "group_by", maximum=3)
    measures = _measures(value.get("measures"))
    bounds = _bounds(value.get("bounds"))
    return {
        "source": source,
        "filters": filters,
        "group_by": group_by,
        "measures": measures,
        "bounds": bounds,
    }


def referenced_fields(value: Mapping[str, Any]) -> frozenset[str]:
    """Return every row field whose membership and type affect the query."""

    fields = set(value["group_by"])
    fields.update(item["field"] for item in value["filters"])
    for measure in value["measures"]:
        if measure["op"] == "sum":
            fields.add(measure["field"])
        elif measure["op"] == "count_if":
            fields.add(measure["condition"]["field"])
    return frozenset(fields)


def numeric_measure_fields(value: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        item["field"] for item in value["measures"] if item["op"] == "sum"
    )


def metric_definitions(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Render explicit, executable definitions without referencing source rows."""

    definitions: list[dict[str, Any]] = []
    for measure in value["measures"]:
        item = copy.deepcopy(measure)
        if measure["op"] == "count":
            item["definition"] = "Count rows that pass every query filter."
        elif measure["op"] == "count_if":
            item["definition"] = (
                "Count rows that pass every query filter and the measure condition."
            )
        else:
            item["definition"] = (
                "Sum finite registered numeric values after query filters; null or "
                "missing values contribute zero."
            )
        definitions.append(item)
    return definitions


def _source(value: Any) -> dict[str, str]:
    _exact_mapping(value, {"app_id", "date"}, "source")
    app_id = value.get("app_id")
    if not isinstance(app_id, str) or not app_id or len(app_id) > 64:
        raise InputValidationError(
            "source.app_id must be a non-empty string of at most 64 characters",
            field="source.app_id",
        )
    day = value.get("date")
    try:
        parsed = date.fromisoformat(day) if isinstance(day, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != day:
        raise InputValidationError(
            "source.date must be one canonical ISO calendar date",
            field="source.date",
        )
    return {"app_id": app_id, "date": day}


def _conditions(value: Any, field: str, *, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise InputValidationError(
            f"{field} must be an array with at most {maximum} conditions",
            field=field,
        )
    return [_condition(item, f"{field}[]") for item in value]


def _condition(value: Any, field: str) -> dict[str, Any]:
    _exact_mapping(value, {"field", "operator", "values"}, field)
    selected_field = _field(value.get("field"), f"{field}.field")
    operator = value.get("operator")
    if not isinstance(operator, str) or operator not in _OPERATORS:
        raise InputValidationError(
            f"actual value: {actual_value(operator)}; aggregate condition operator "
            "must be one of the supported operators",
            field=f"{field}.operator",
        )
    values = value.get("values")
    if not isinstance(values, (list, tuple)) or len(values) > 50:
        raise InputValidationError(
            "aggregate condition values must be a bounded scalar array",
            field=f"{field}.values",
        )
    selected = list(values)
    if any(not _scalar(item) for item in selected):
        raise InputValidationError(
            "aggregate condition values must contain finite JSON scalars",
            field=f"{field}.values",
        )
    _condition_arity(operator, selected, field)
    return {"field": selected_field, "operator": operator, "values": selected}


def _condition_arity(operator: str, values: Sequence[Any], field: str) -> None:
    expected = (
        "zero" if operator in {"WITH_VAL", "WITHOUT_VAL"}
        else "one" if operator in _COMPARISON_OPERATORS | {"EQUALS", "NOT_EQUALS"}
        else "one or more"
    )
    valid = (
        not values if expected == "zero"
        else len(values) == 1 if expected == "one"
        else bool(values)
    )
    if not valid:
        raise InputValidationError(
            f"aggregate operator {operator} requires {expected} values",
            field=f"{field}.values",
        )


def _fields(value: Any, field: str, *, maximum: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise InputValidationError(
            f"{field} must be an array with at most {maximum} fields",
            field=field,
        )
    result = [_field(item, f"{field}[]") for item in value]
    if len(result) != len(set(result)):
        raise InputValidationError(f"{field} fields must be unique", field=field)
    return result


def _field(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or "\x00" in value
    ):
        raise InputValidationError(
            "aggregate fields must be bounded non-empty strings",
            field=field,
        )
    return value


def _measures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 10:
        raise InputValidationError(
            "measures must contain between 1 and 10 definitions",
            field="measures",
        )
    result = [_measure(item) for item in value]
    names = [item["name"] for item in result]
    if len(names) != len(set(names)):
        raise InputValidationError("measure names must be unique", field="measures[].name")
    return result


def _measure(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError("measure definitions must be objects", field="measures[]")
    name = value.get("name")
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise InputValidationError(
            "measure names must be stable ASCII identifiers of at most 64 characters",
            field="measures[].name",
        )
    operation = value.get("op")
    allowed = {
        "count": {"name", "op"},
        "count_if": {"name", "op", "condition"},
        "sum": {"name", "op", "field"},
    }
    if operation not in allowed or set(value) != allowed[operation]:
        raise InputValidationError(
            f"actual value: {actual_value(sorted(str(key) for key in value))}; "
            "measure definition must match count, count_if, or sum",
            field="measures[]",
        )
    if operation == "count_if":
        return {
            "name": name,
            "op": operation,
            "condition": _condition(value.get("condition"), "measures[].condition"),
        }
    if operation == "sum":
        return {
            "name": name,
            "op": operation,
            "field": _field(value.get("field"), "measures[].field"),
        }
    return {"name": name, "op": operation}


def _bounds(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {
        "max_pages",
        "max_items",
        "max_cells",
    }:
        raise AggregateBoundsError(
            "aggregate requests require explicit max_pages, max_items, and max_cells",
            field="bounds",
        )
    result: dict[str, int] = {}
    for field, maximum in (
        ("max_pages", 1_000),
        ("max_items", 100_000),
        ("max_cells", MAX_AGGREGATE_CELLS),
    ):
        item = value.get(field)
        if type(item) is not int or not 1 <= item <= maximum:
            raise AggregateBoundsError(
                f"aggregate {field} must be between 1 and {maximum}",
                field=f"bounds.{field}",
            )
        result[field] = item
    return result


def _exact_mapping(value: Any, fields: set[str] | frozenset[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise InputValidationError(
            f"{label} must use exactly the registered aggregate fields",
            field=label,
        )


def _scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return value.bit_length() <= 13_607
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str) and len(value) <= 4_096


__all__ = [
    "AggregateBoundsError",
    "AggregateCardinalityError",
    "AggregateFieldUnsupportedError",
    "AggregateMixedTypeError",
    "BOUNDS_REQUIRED",
    "CARDINALITY_LIMIT",
    "FIELD_UNSUPPORTED",
    "INPUT_SCHEMA_VERSION",
    "MAX_AGGREGATE_CELLS",
    "METADATA_OPERATION_ID",
    "MIXED_TYPE",
    "PRODUCT_OPERATION_ID",
    "RESULT_SCHEMA_VERSION",
    "SOURCE_OPERATION_ID",
    "metric_definitions",
    "normalize_user_detail_aggregate_inputs",
    "numeric_measure_fields",
    "referenced_fields",
    "user_detail_aggregate_input_schema",
]
