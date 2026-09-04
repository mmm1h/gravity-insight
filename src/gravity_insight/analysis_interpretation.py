"""Declare how to read Analysis numbers without inventing a metrics engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .analysis_spec_schema import FUNNEL_RESULT_NOTES, RETENTION_RESULT_NOTES


SCHEMA_VERSION = "gravity.analysis-interpretation.v1"
_NON_ADDITIVE = frozenset(
    {
        "PresetUserCount",
        "DistinctCount",
        "UserAvg",
        "ListDistinctCount",
        "ListSetDistinctCount",
        "ListElementDistinctCount",
    }
)
_ADDITIVE = frozenset({"PresetAllCount", "Count", "SumCount"})


def analysis_interpretation(kind: str, spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return machine-readable rate and additivity facts for one result."""

    selected_kind = str(kind or "").strip().casefold()
    notes: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": selected_kind,
        "metrics": _metrics(selected_kind, spec if isinstance(spec, Mapping) else {}),
    }
    if selected_kind == "funnel":
        notes.update(FUNNEL_RESULT_NOTES)
    elif selected_kind == "retention":
        notes.update(RETENTION_RESULT_NOTES)
    return notes


def attach_analysis_interpretation(
    result: Any, kind: str, spec: Mapping[str, Any] | None
) -> Any:
    """Copy a result and add interpretation without replacing existing facts."""

    if not isinstance(result, dict):
        return result
    if isinstance(result.get("interpretation"), Mapping):
        return result
    selected = dict(result)
    selected["interpretation"] = analysis_interpretation(kind, spec)
    return selected


def _metrics(kind: str, spec: Mapping[str, Any]) -> list[dict[str, str]]:
    if kind == "property":
        item = _metric(spec.get("property"))
        return [item] if item is not None else []
    items: list[dict[str, str]] = []
    steps = spec.get("steps")
    if not isinstance(steps, list):
        return items
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        item = _metric(step.get("metric"))
        if item is not None:
            items.append(item)
    return items


def _metric(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    aggregation = value.get("aggregation")
    field = value.get("field")
    if not isinstance(aggregation, str) or not aggregation:
        return None
    if aggregation in _NON_ADDITIVE:
        additivity = "non_additive"
    elif aggregation in _ADDITIVE:
        additivity = "additive"
    else:
        additivity = "unknown"
    return {
        "field": field if isinstance(field, str) else "",
        "aggregation": aggregation,
        "additivity": additivity,
    }


__all__ = [
    "SCHEMA_VERSION",
    "analysis_interpretation",
    "attach_analysis_interpretation",
]
