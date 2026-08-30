"""Purely local derived arithmetic over an existing result envelope."""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .plan_binding import resolve_pointer, validate_pointer
from .result_source import CALLER_DEFINED, result_source


SCHEMA_VERSION = "gravity.derived-metrics.v1"
SPEC_SCHEMA_VERSION = "gravity.derived-metrics-spec.v1"
OPERATORS = ("ratio", "share", "change", "reconcile")
_RESULT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_ROOT_FIELDS = frozenset(
    {"schema_version", "rows_path", "decimal_places", "calculations"}
)
_FIELDS = {
    "ratio": frozenset({"operator", "result_name", "numerator", "denominator"}),
    "share": frozenset({"operator", "result_name", "value"}),
    "change": frozenset(
        {
            "operator", "result_name", "value", "period", "baseline", "current",
            "keys",
        }
    ),
    "reconcile": frozenset({"operator", "result_name", "observed", "expected"}),
}
_WARNING_MESSAGES = {
    "UPSTREAM_PARTIAL": "The upstream envelope is partial; derived conclusions are not complete.",
    "UPSTREAM_UNAVAILABLE": "The upstream envelope is not consumable for derivation.",
    "ROWS_PATH_MISSING": "The declared rows_path does not resolve to an array.",
    "ROW_NOT_OBJECT": "A source row is not an object and could not supply columns.",
    "MISSING_COLUMN": "A declared source column is absent from one or more rows.",
    "NULL_OPERAND": "A declared operand is null in one or more rows.",
    "INVALID_NUMBER": "A declared numeric operand is not a finite decimal value.",
    "DENOMINATOR_ZERO": "A denominator is zero; the corresponding result is not calculable.",
    "INCOMPLETE_TOTAL": "A share total is incomplete, so no visible-row total was substituted.",
    "ALIGNMENT_SIDE_MISSING": "A change key is absent from one side of the comparison.",
    "DUPLICATE_ALIGNMENT_KEY": "A change key occurs more than once on one comparison side.",
    "ROW_OUTSIDE_CHANGE_PAIR": "A change row does not belong to either declared side.",
    "UNCLASSIFIED_OBSERVED": "A reconciliation row has no usable observed value.",
    "DUPLICATE_OBSERVED": "A reconciliation value occurs more than once in observed rows.",
    "BINARY_FLOAT_INPUT": "A binary float was consumed through its decimal text representation.",
    "PRECISION_ROUNDED": "A division result was rounded to the declared decimal places.",
}


def derive_metrics(
    source: Mapping[str, Any], specification: Mapping[str, Any]
) -> dict[str, Any]:
    """Copy one envelope and add a versioned, caller-bound derivation contract."""

    if not isinstance(source, Mapping):
        _invalid("source must be an object", "source", source)
    if "derived_metrics" in source:
        _invalid(
            "source must not already contain derived_metrics",
            "source.derived_metrics",
            source.get("derived_metrics"),
        )
    path, places, calculations = validate_derived_spec(specification)
    selected = copy.deepcopy(dict(source))
    upstream_status = str(source.get("status", "")).strip().casefold()
    partial = upstream_status == "partial"
    warnings: Counter[str] = Counter()
    if partial:
        warnings["UPSTREAM_PARTIAL"] += 1
    upstream = _upstream_statement(source, upstream_status)
    if upstream_status not in {"success", "partial", "empty"}:
        warnings["UPSTREAM_UNAVAILABLE"] += 1
        derived = _unavailable(calculations, places, upstream, warnings)
    else:
        rows = _rows(source, path, warnings)
        derived = _calculate(
            rows, calculations, places, partial, upstream, warnings
        )
    selected["derived_metrics"] = derived
    return selected


def derive_metrics_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the shared CLI/Plan request shape without any I/O."""

    if not isinstance(request, Mapping):
        _invalid("derive request must be an object", "request", request)
    unknown = sorted(set(request) - {"source", "spec"})
    if unknown:
        _invalid("derive request contains unknown fields", "request", unknown)
    if "source" not in request or "spec" not in request:
        missing = [name for name in ("source", "spec") if name not in request]
        _invalid("derive request must include source and spec", "request", missing)
    return derive_metrics(request["source"], request["spec"])


def validate_derived_request(request: Mapping[str, Any]) -> None:
    """Validate a request for Plan preflight without calculating source values."""

    if not isinstance(request, Mapping):
        _invalid("derive request must be an object", "request", request)
    unknown = sorted(set(request) - {"name", "source", "spec"})
    if unknown:
        _invalid("derive request contains unknown fields", "request", unknown)
    if request.get("name") not in {None, "derived_metrics"}:
        _invalid("derive request name must be derived_metrics", "name", request.get("name"))
    for field in ("source", "spec"):
        if field not in request:
            _invalid(f"derive request must include {field}", field, None)
    if not isinstance(request["source"], Mapping):
        _invalid("source must be an object", "source", request["source"])
    validate_derived_spec(request["spec"])


def validate_derived_spec(
    value: Mapping[str, Any],
) -> tuple[str, int, tuple[dict[str, Any], ...]]:
    """Return a normalized, strict arithmetic specification."""

    if not isinstance(value, Mapping):
        _invalid("derived spec must be an object", "spec", value)
    unknown = sorted(set(value) - _ROOT_FIELDS)
    if unknown:
        _invalid("derived spec contains unknown fields", "spec", unknown)
    if value.get("schema_version") != SPEC_SCHEMA_VERSION:
        _invalid(
            f"derived spec schema_version must be {SPEC_SCHEMA_VERSION}",
            "spec.schema_version",
            value.get("schema_version"),
        )
    path = value.get("rows_path")
    try:
        path = validate_pointer(path, "spec.rows_path", allow_root=False)
    except InputValidationError:
        _invalid("rows_path must be a non-root JSON Pointer", "spec.rows_path", path)
    places = value.get("decimal_places", 12)
    if type(places) is not int or not 0 <= places <= 28:
        _invalid("decimal_places must be an integer from 0 through 28", "spec.decimal_places", places)
    raw = value.get("calculations")
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes, bytearray))
        or not 1 <= len(raw) <= 32
    ):
        _invalid("calculations must contain between 1 and 32 objects", "spec.calculations", raw)
    calculations = tuple(_calculation(item, index) for index, item in enumerate(raw))
    names = [item["result_name"] for item in calculations]
    if len(names) != len(set(names)):
        _invalid("calculation result_name values must be unique", "spec.calculations", names)
    return str(path), places, calculations


def _calculation(value: Any, index: int) -> dict[str, Any]:
    field = f"spec.calculations[{index}]"
    if not isinstance(value, Mapping):
        _invalid("calculation must be an object", field, value)
    operator = value.get("operator")
    if operator not in OPERATORS:
        _invalid(f"operator must be one of {', '.join(OPERATORS)}", f"{field}.operator", operator)
    required = _FIELDS[str(operator)]
    if set(value) != required:
        shape = {"missing": sorted(required - set(value)), "unknown": sorted(set(value) - required)}
        _invalid("calculation fields must exactly match its operator contract", field, shape)
    name = value.get("result_name")
    if not isinstance(name, str) or not _RESULT_NAME.fullmatch(name):
        _invalid("result_name must be a stable ASCII identifier", f"{field}.result_name", name)
    selected = copy.deepcopy(dict(value))
    for column in _column_fields(str(operator)):
        if not isinstance(selected[column], str) or not selected[column]:
            _invalid("column bindings must be non-empty strings", f"{field}.{column}", selected[column])
    if operator == "change":
        _validate_change(selected, field)
    if operator == "reconcile":
        _validate_expected(selected, field)
    return selected


def _column_fields(operator: str) -> tuple[str, ...]:
    return {
        "ratio": ("numerator", "denominator"),
        "share": ("value",),
        "change": ("value", "period"),
        "reconcile": ("observed",),
    }[operator]


def _validate_change(value: Mapping[str, Any], field: str) -> None:
    if value["baseline"] == value["current"]:
        _invalid("baseline and current labels must differ", f"{field}.current", value["current"])
    keys = value["keys"]
    if not isinstance(keys, list) or not all(isinstance(item, str) and item for item in keys):
        _invalid("keys must be an array of non-empty column names", f"{field}.keys", keys)
    if len(keys) != len(set(keys)) or len(keys) > 8:
        _invalid("keys must be unique and contain at most 8 columns", f"{field}.keys", keys)


def _validate_expected(value: Mapping[str, Any], field: str) -> None:
    expected = value["expected"]
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        _invalid("expected must be an array of strings", f"{field}.expected", expected)
    if len(expected) != len(set(expected)) or len(expected) > 10_000:
        _invalid("expected must be unique and contain at most 10000 strings", f"{field}.expected", expected)


def _rows(
    source: Mapping[str, Any], path: str, warnings: Counter[str]
) -> list[Any] | None:
    try:
        value = resolve_pointer(source, path)
    except (KeyError, IndexError, TypeError, ValueError):
        value = None
    if not isinstance(value, list):
        warnings["ROWS_PATH_MISSING"] += 1
        return None
    return value


def _calculate(
    rows: list[Any] | None,
    calculations: tuple[dict[str, Any], ...],
    places: int,
    partial: bool,
    upstream: Mapping[str, Any],
    warnings: Counter[str],
) -> dict[str, Any]:
    from .derived_metric_operators import calculate_operator

    if rows is None:
        results = [
            {"operator": item["operator"], "result_name": item["result_name"],
             "ok": False, "status": "not_calculated", "reason": "rows_path_missing"}
            for item in calculations
        ]
    else:
        results = [
            calculate_operator(item, rows, places, partial, warnings)
            for item in calculations
        ]
    if rows == []:
        status = "empty"
    elif partial or any(item["status"] != "success" for item in results):
        status = "partial"
    else:
        status = "success"
    return _contract(status, results, places, upstream, warnings)


def _unavailable(
    calculations: tuple[dict[str, Any], ...],
    places: int,
    upstream: Mapping[str, Any],
    warnings: Counter[str],
) -> dict[str, Any]:
    results = [
        {"operator": item["operator"], "result_name": item["result_name"],
         "ok": False, "status": "not_calculated", "reason": "upstream_unavailable"}
        for item in calculations
    ]
    return _contract("not_calculated", results, places, upstream, warnings)


def _contract(
    status: str,
    calculations: list[dict[str, Any]],
    places: int,
    upstream: Mapping[str, Any],
    warnings: Counter[str],
) -> dict[str, Any]:
    rendered = [
        {"code": code, "count": count, "message": _WARNING_MESSAGES[code]}
        for code, count in sorted(warnings.items())
        if count
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(CALLER_DEFINED),
        "ok": status in {"success", "empty"},
        "status": status,
        "upstream": dict(upstream),
        "numeric_contract": {
            "type": "decimal_string",
            "division_decimal_places": places,
            "rounding": "half_even",
            "integer_conversion": "exact",
        },
        "calculations": calculations,
        "warnings": rendered,
        "notes": [f"{item['message']} Count: {item['count']}." for item in rendered],
    }


def _upstream_statement(
    source: Mapping[str, Any], status: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": source.get("schema_version"),
        "status": status or "unknown",
    }
    if isinstance(source.get("result_source"), Mapping):
        result["result_source"] = copy.deepcopy(dict(source["result_source"]))
    return result


def _invalid(message: str, field: str, value: Any) -> NoReturn:
    raise InputValidationError(
        f"{message}; actual value: {actual_value(value)}",
        field=field,
        next_action=(
            "Correct the request using `gravity derive --help` and the "
            f"{SPEC_SCHEMA_VERSION} contract, then retry."
        ),
    )


__all__ = [
    "OPERATORS",
    "SCHEMA_VERSION",
    "SPEC_SCHEMA_VERSION",
    "derive_metrics",
    "derive_metrics_request",
    "validate_derived_request",
    "validate_derived_spec",
]
