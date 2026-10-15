"""Shared JSON-schema builders for compact Analysis specs."""

from __future__ import annotations

from typing import Any, Mapping

from ._field_policy_shared import ANALYSIS_QUERY_ID_RE, ANALYSIS_TIME_GROUPS
from .analysis_spec_validation import dated_spec_notes


ANALYSIS_TIME_GROUPS_BY_KIND = {
    "event": ANALYSIS_TIME_GROUPS - {"hour", "minute"},
    "funnel": ANALYSIS_TIME_GROUPS,
    "retention": ANALYSIS_TIME_GROUPS,
    "scatter": ANALYSIS_TIME_GROUPS,
}


def base_spec(*, required: tuple[str, ...], properties: dict[str, Any]) -> dict[str, Any]:
    common = {
        "app": {"type": ["string", "integer"]},
        "query_id": {
            "type": "string",
            "pattern": ANALYSIS_QUERY_ID_RE.pattern,
        },
        "group_by": array_ref("group_by", 0, 20),
    }
    return {
        "type": "object",
        "required": list(required),
        "additionalProperties": False,
        "properties": {**common, **properties},
    }


def dated_spec(
    kind: str,
    *,
    required: tuple[str, ...],
    properties: dict[str, Any],
    notes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = base_spec(
        required=required,
        properties={
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
            "time_grain": {
                "type": "string",
                "enum": sorted(ANALYSIS_TIME_GROUPS_BY_KIND[kind]),
            },
            **properties,
        },
    )
    spec["notes"] = {**dated_spec_notes(), **dict(notes or {})}
    return spec


def array_ref(name: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {"$ref": f"#/definitions/{name}"},
    }


def integer(minimum: int, maximum: int) -> dict[str, Any]:
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


__all__ = [
    "ANALYSIS_TIME_GROUPS_BY_KIND",
    "array_ref",
    "base_spec",
    "dated_spec",
    "enum",
    "integer",
]
