"""Detect additive-metric row sums that do not match the upstream total."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any


_ADDITIVE = frozenset({
    "AppRealRegisterCnt",
    "reporting_ad_cnt",
    "reporting_ad_revenue",
})


def dimension_sum_diagnostics(
    result: Mapping[str, Any], inputs: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    data = result.get("data")
    if not isinstance(data, Mapping):
        return []
    rows = data.get("list")
    total = data.get("total")
    if not isinstance(rows, list) or not isinstance(total, Mapping):
        return []
    requested = (inputs or {}).get("metrics_list")
    names = [
        str(name)
        for name in (requested if isinstance(requested, list) else total)
        if str(name) in _ADDITIVE
    ]
    diagnostics: list[dict[str, Any]] = []
    for name in names:
        row_sum = _sum_metric(rows, name)
        total_value = _number(total.get(name))
        if row_sum is None or total_value is None or row_sum == total_value:
            continue
        diagnostics.append({
            "code": "dimension_sum_mismatch",
            "priority": 20,
            "message": (
                f"Additive metric {name} row sum {row_sum} does not equal "
                f"total {total_value}; delta {total_value - row_sum}."
            ),
            "metric": name,
            "list_sum": _plain(row_sum),
            "total": _plain(total_value),
            "delta": _plain(total_value - row_sum),
        })
    return diagnostics


def dimension_sum_warnings(
    result: Mapping[str, Any], inputs: Mapping[str, Any] | None = None
) -> tuple[str, ...]:
    return tuple(item["message"] for item in dimension_sum_diagnostics(result, inputs))


def _sum_metric(rows: list[Any], name: str) -> Decimal | None:
    values: list[Decimal] = []
    for row in rows:
        if not isinstance(row, Mapping) or name not in row:
            continue
        value = _number(row.get(name))
        if value is None:
            return None
        values.append(value)
    return sum(values, Decimal("0")) if values else None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def _plain(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)
