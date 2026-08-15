"""Structured, value-free observations of additive response contract drift."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "gravity.response-drift.v1"
_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_FIELDS = frozenset({"path", "observed_type"})


class ResponseDriftRecorder:
    """Collect deterministic JSON Pointer/type pairs without retaining values."""

    def __init__(self) -> None:
        self._fields: set[tuple[str, str]] = set()

    def add_unknown_fields(
        self,
        parent: Sequence[str],
        value: Mapping[Any, Any],
        unknown: set[str],
    ) -> None:
        if not unknown:
            return
        for key, item in value.items():
            name = str(key)
            if name in unknown:
                self._fields.add((_pointer((*parent, name)), _observed_type(item)))

    def to_contract(self) -> dict[str, Any] | None:
        if not self._fields:
            return None
        return _contract(self._fields)


def normalize_response_drift(value: object) -> dict[str, Any]:
    """Validate and normalize the independently versioned drift sub-contract."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "direction", "classification", "fields"
    }:
        raise ValueError("response drift fields changed")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("direction") != "response"
        or value.get("classification") != "additive"
    ):
        raise ValueError("response drift contract changed")
    raw_fields = value.get("fields")
    if not isinstance(raw_fields, Sequence) or isinstance(
        raw_fields, (str, bytes, bytearray)
    ) or not raw_fields:
        raise ValueError("response drift fields must be a non-empty array")
    fields: set[tuple[str, str]] = set()
    for field in raw_fields:
        fields.add(_normalize_field(field))
    return _contract(fields)


def _normalize_field(field: object) -> tuple[str, str]:
    if not isinstance(field, Mapping) or set(field) != _FIELDS:
        raise ValueError("response drift observation fields changed")
    path, observed_type = field.get("path"), field.get("observed_type")
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 4_096:
        raise ValueError("response drift path is invalid")
    if observed_type not in _TYPES:
        raise ValueError("response drift observed_type is invalid")
    return path, str(observed_type)


def merge_response_drifts(values: Sequence[object]) -> dict[str, Any] | None:
    fields: set[tuple[str, str]] = set()
    for value in values:
        if value is None:
            continue
        normalized = normalize_response_drift(value)
        fields.update(
            (str(item["path"]), str(item["observed_type"]))
            for item in normalized["fields"]
        )
    return _contract(fields) if fields else None


def _contract(fields: set[tuple[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "direction": "response",
        "classification": "additive",
        "fields": [
            {"path": path, "observed_type": observed_type}
            for path, observed_type in sorted(fields)
        ],
    }


def _pointer(path: Sequence[str]) -> str:
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in path
    )


def _observed_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    raise ValueError("response drift value is not JSON-compatible")


__all__ = [
    "SCHEMA_VERSION",
    "ResponseDriftRecorder",
    "merge_response_drifts",
    "normalize_response_drift",
]
