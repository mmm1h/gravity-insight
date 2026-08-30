"""Operator implementations for caller-bound, meaning-free derived metrics."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any


def calculate_operator(
    specification: Mapping[str, Any],
    rows: list[Any],
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    operator = str(specification["operator"])
    if operator == "ratio":
        return _ratio(specification, rows, places, partial, warnings)
    if operator == "share":
        return _share(specification, rows, places, partial, warnings)
    if operator == "change":
        return _change(specification, rows, places, partial, warnings)
    return _reconcile(specification, rows, partial, warnings)


def _ratio(
    spec: Mapping[str, Any],
    rows: list[Any],
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    output = []
    for index, row in enumerate(rows):
        numerator = _operand(row, str(spec["numerator"]), warnings)
        denominator = _operand(row, str(spec["denominator"]), warnings)
        state = _first_failure(numerator, denominator)
        if state is None and denominator["number"] == 0:
            warnings["DENOMINATOR_ZERO"] += 1
            state = _not_calculable("denominator_zero")
        if state is None:
            state = _division(
                numerator["number"], denominator["number"], places, partial, warnings
            )
        output.append({"row_index": index, "result": state})
    return _row_calculation(spec, output, partial)


def _share(
    spec: Mapping[str, Any],
    rows: list[Any],
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    operands = [_operand(row, str(spec["value"]), warnings) for row in rows]
    invalid = any(item["status"] != "valid" for item in operands)
    if partial or invalid:
        warnings["INCOMPLETE_TOTAL"] += 1
        reason = "upstream_partial_total" if partial else "incomplete_total"
        output = [
            {
                "row_index": index,
                "result": item if item["status"] != "valid" else _not_calculable(reason),
            }
            for index, item in enumerate(operands)
        ]
        return _row_calculation(spec, output, True)
    total = sum((item["number"] for item in operands), Decimal(0))
    if total == 0:
        warnings["DENOMINATOR_ZERO"] += len(rows)
        output = [
            {"row_index": index, "result": _not_calculable("denominator_zero")}
            for index in range(len(rows))
        ]
    else:
        output = [
            {
                "row_index": index,
                "result": _division(item["number"], total, places, False, warnings),
            }
            for index, item in enumerate(operands)
        ]
    return _row_calculation(spec, output, False)


def _change(
    spec: Mapping[str, Any],
    rows: list[Any],
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    sides: dict[str, dict[str, list[tuple[int, Mapping[str, Any]]]]] = {
        "baseline": {},
        "current": {},
    }
    identities: dict[str, dict[str, Any]] = {}
    unaligned: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        aligned = _aligned_row(raw, index, spec, warnings)
        if aligned is None:
            unaligned.append({"row_index": index, "reason": "invalid_alignment_columns"})
            continue
        side, identity, key_values = aligned
        if side is None:
            warnings["ROW_OUTSIDE_CHANGE_PAIR"] += 1
            unaligned.append({"row_index": index, "reason": "outside_declared_pair"})
            continue
        identities[identity] = key_values
        sides[side].setdefault(identity, []).append((index, raw))
    items = [
        _change_item(identity, identities[identity], sides, spec, places, partial, warnings)
        for identity in sorted(identities)
    ]
    status = "partial" if partial or unaligned or any(not item["ok"] for item in items) else "success"
    return {
        "operator": "change",
        "result_name": spec["result_name"],
        "ok": status == "success",
        "status": status,
        "alignment": {
            "keys": list(spec["keys"]),
            "mode": "exact_key_identity",
            "baseline": spec["baseline"],
            "current": spec["current"],
        },
        "rows": items,
        "unaligned_rows": unaligned,
    }


def _aligned_row(
    row: Any,
    index: int,
    spec: Mapping[str, Any],
    warnings: Counter[str],
) -> tuple[str | None, str, dict[str, Any]] | None:
    if not isinstance(row, Mapping):
        warnings["ROW_NOT_OBJECT"] += 1
        return None
    columns = [str(spec["period"]), *(str(item) for item in spec["keys"])]
    missing = [column for column in columns if column not in row]
    if missing:
        warnings["MISSING_COLUMN"] += 1
        return None
    key_values = {column: row[column] for column in spec["keys"]}
    try:
        identity = json.dumps(
            list(key_values.values()), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError):
        warnings["INVALID_NUMBER"] += 1
        return None
    period = row[spec["period"]]
    side = "baseline" if period == spec["baseline"] else (
        "current" if period == spec["current"] else None
    )
    return side, identity, key_values


def _change_item(
    identity: str,
    keys: Mapping[str, Any],
    sides: Mapping[str, Mapping[str, list[tuple[int, Mapping[str, Any]]]]],
    spec: Mapping[str, Any],
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    baseline = sides["baseline"].get(identity, [])
    current = sides["current"].get(identity, [])
    if not baseline or not current:
        warnings["ALIGNMENT_SIDE_MISSING"] += 1
        missing = "baseline" if not baseline else "current"
        return {
            "keys": dict(keys), "ok": False, "status": "not_calculable",
            "reason": f"{missing}_missing", "baseline_rows": [item[0] for item in baseline],
            "current_rows": [item[0] for item in current],
        }
    if len(baseline) != 1 or len(current) != 1:
        warnings["DUPLICATE_ALIGNMENT_KEY"] += 1
        return {
            "keys": dict(keys), "ok": False, "status": "not_calculable",
            "reason": "duplicate_alignment_key",
            "baseline_rows": [item[0] for item in baseline],
            "current_rows": [item[0] for item in current],
        }
    before = _operand(baseline[0][1], str(spec["value"]), warnings)
    after = _operand(current[0][1], str(spec["value"]), warnings)
    failure = _first_failure(before, after)
    if failure is not None:
        return {"keys": dict(keys), "ok": False, "status": "not_calculable", "reason": failure["reason"]}
    difference = after["number"] - before["number"]
    absolute = _calculated(difference, partial)
    if before["number"] == 0:
        warnings["DENOMINATOR_ZERO"] += 1
        relative = _not_calculable("baseline_zero")
    else:
        relative = _division(difference, before["number"], places, partial, warnings)
    ok = relative["status"] != "not_calculable"
    return {
        "keys": dict(keys), "ok": ok,
        "status": "partial" if partial or not ok else "success",
        "baseline_value": _decimal_text(before["number"]),
        "current_value": _decimal_text(after["number"]),
        "absolute_change": absolute,
        "relative_change": relative,
    }


def _reconcile(
    spec: Mapping[str, Any],
    rows: list[Any],
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    observed: list[str] = []
    unclassified: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warnings["ROW_NOT_OBJECT"] += 1
            unclassified.append({"row_index": index, "reason": "row_not_object"})
        elif spec["observed"] not in row:
            warnings["MISSING_COLUMN"] += 1
            warnings["UNCLASSIFIED_OBSERVED"] += 1
            unclassified.append({"row_index": index, "reason": "missing_column"})
        elif not isinstance(row[spec["observed"]], str):
            warnings["UNCLASSIFIED_OBSERVED"] += 1
            unclassified.append({"row_index": index, "reason": "invalid_observed_value"})
        else:
            observed.append(row[spec["observed"]])
    unique_observed = list(dict.fromkeys(observed))
    warnings["DUPLICATE_OBSERVED"] += len(observed) - len(unique_observed)
    expected = list(spec["expected"])
    expected_set, observed_set = set(expected), set(unique_observed)
    status = "partial" if partial or unclassified else "success"
    return {
        "operator": "reconcile",
        "result_name": spec["result_name"],
        "ok": status == "success",
        "status": status,
        "present": [item for item in expected if item in observed_set],
        "missing": [item for item in expected if item not in observed_set],
        "unexpected": [item for item in unique_observed if item not in expected_set],
        "missing_is_definitive": not partial and not unclassified,
        "unclassified_rows": unclassified,
    }


def _operand(row: Any, column: str, warnings: Counter[str]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        warnings["ROW_NOT_OBJECT"] += 1
        return _not_calculable("row_not_object")
    if column not in row:
        warnings["MISSING_COLUMN"] += 1
        return {**_not_calculable("missing_column"), "missing_columns": [column]}
    value = row[column]
    if value is None:
        warnings["NULL_OPERAND"] += 1
        return _not_calculable("null_operand")
    if isinstance(value, bool):
        warnings["INVALID_NUMBER"] += 1
        return _not_calculable("invalid_number")
    try:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidOperation
            warnings["BINARY_FLOAT_INPUT"] += 1
            number = Decimal(str(value))
        elif isinstance(value, (int, str)):
            number = Decimal(value)
        else:
            raise InvalidOperation
        if not number.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        warnings["INVALID_NUMBER"] += 1
        return _not_calculable("invalid_number")
    return {"status": "valid", "number": number}


def _division(
    numerator: Decimal,
    denominator: Decimal,
    places: int,
    partial: bool,
    warnings: Counter[str],
) -> dict[str, Any]:
    quantum = Decimal(1).scaleb(-places)
    digits = len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(34, digits + places + 10)
        raw = numerator / denominator
        rounded = raw.quantize(quantum, rounding=ROUND_HALF_EVEN)
    if rounded * denominator != numerator:
        warnings["PRECISION_ROUNDED"] += 1
    return {
        "status": "calculated_from_partial" if partial else "calculated",
        "value": format(rounded, "f"),
        "numeric_type": "decimal",
        "decimal_places": places,
    }


def _calculated(value: Decimal, partial: bool) -> dict[str, Any]:
    return {
        "status": "calculated_from_partial" if partial else "calculated",
        "value": _decimal_text(value),
        "numeric_type": "decimal",
    }


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _first_failure(*values: Mapping[str, Any]) -> dict[str, Any] | None:
    return next((dict(value) for value in values if value["status"] != "valid"), None)


def _not_calculable(reason: str) -> dict[str, Any]:
    return {"status": "not_calculable", "reason": reason}


def _row_calculation(
    spec: Mapping[str, Any], rows: list[dict[str, Any]], partial: bool
) -> dict[str, Any]:
    unavailable = any(item["result"]["status"] == "not_calculable" for item in rows)
    status = "partial" if partial or unavailable else "success"
    return {
        "operator": spec["operator"],
        "result_name": spec["result_name"],
        "ok": status == "success",
        "status": status,
        "rows": rows,
    }


__all__ = ["calculate_operator"]
