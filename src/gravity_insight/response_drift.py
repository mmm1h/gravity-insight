"""Structured, value-free observations of response contract drift."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


V1_SCHEMA_VERSION = "gravity.response-drift.v1"
V2_SCHEMA_VERSION = "gravity.response-drift.v2"
SCHEMA_VERSION = V2_SCHEMA_VERSION
_JSON_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_BREAKING_OBSERVED_TYPES = _JSON_TYPES | {"missing", "non_json"}
_EXPECTED_TYPES = _JSON_TYPES | {"json", "json_scalar", "object_or_array"}
_V1_FIELDS = frozenset({"path", "observed_type"})
_V2_ADDITIVE_FIELDS = frozenset({"classification", "path", "observed_type"})
_V2_BREAKING_FIELDS = frozenset(
    {"classification", "path", "expected_type", "observed_type"}
)
_MISSING = object()
_DYNAMIC_KEY_PATH_SEGMENT = re.compile(r"^(?:\[\]|\*|[A-Za-z_][A-Za-z0-9_-]*)$")
_DYNAMIC_KEY_SHAPES = frozenset({"decimal_19", "iso_date"})
_ISO_DATE_KEY = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DECIMAL_19_KEY = re.compile(r"^[0-9]{19}$")


def normalize_dynamic_key_patterns(value: object) -> dict[str, str]:
    """Validate exact response-container paths and their closed key shapes."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("response_projection.dynamic_key_patterns must be an object")
    result: dict[str, str] = {}
    for raw_path, raw_shape in value.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError(
                "response_projection.dynamic_key_patterns contains an invalid path"
            )
        parts = raw_path.split(".")
        if any(not _DYNAMIC_KEY_PATH_SEGMENT.fullmatch(part) for part in parts):
            raise ValueError(
                "response_projection.dynamic_key_patterns contains an invalid path"
            )
        if raw_shape not in _DYNAMIC_KEY_SHAPES:
            raise ValueError(
                "response_projection.dynamic_key_patterns contains an invalid key shape"
            )
        result[raw_path] = str(raw_shape)
    return dict(sorted(result.items()))


def dynamic_key_shape(
    patterns: Mapping[str, str], path: Sequence[str], key: str
) -> str | None:
    """Return the matching declared shape for one key at one container path."""

    for raw_path, shape in patterns.items():
        expected = raw_path.split(".")
        if len(expected) != len(path) or any(
            wanted != "*" and wanted != actual
            for wanted, actual in zip(expected, path)
        ):
            continue
        if _dynamic_key_matches_shape(key, shape):
            return shape
    return None


def dynamic_key_path_shape(
    patterns: Mapping[str, str], path: Sequence[str]
) -> str | None:
    """Return the declared shape at a path even when a candidate key is invalid."""

    for raw_path, shape in patterns.items():
        expected = raw_path.split(".")
        if len(expected) == len(path) and all(
            wanted == "*" or wanted == actual
            for wanted, actual in zip(expected, path)
        ):
            return shape
    return None


def _dynamic_key_matches_shape(key: str, shape: str) -> bool:
    if shape == "iso_date":
        if not _ISO_DATE_KEY.fullmatch(key):
            return False
        try:
            return date.fromisoformat(key).isoformat() == key
        except ValueError:
            return False
    if shape == "decimal_19":
        return bool(_DECIMAL_19_KEY.fullmatch(key))
    return False


class ResponseDriftRecorder:
    """Collect deterministic JSON Pointer/type observations without values."""

    def __init__(self) -> None:
        self._additive_fields: set[tuple[str, str]] = set()
        self._breaking_fields: set[tuple[str, str, str]] = set()

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
                self._additive_fields.add(
                    (_pointer((*parent, name)), _observed_type(item))
                )

    def add_breaking_field(
        self,
        path: Sequence[str],
        expected_type: str,
        value: object = _MISSING,
    ) -> None:
        if expected_type not in _EXPECTED_TYPES:
            raise ValueError("response drift expected_type is invalid")
        observed_type = (
            "missing" if value is _MISSING else _breaking_observed_type(value)
        )
        self._breaking_fields.add(
            (_pointer(path), expected_type, observed_type)
        )

    def to_contract(self) -> dict[str, Any] | None:
        if self._breaking_fields:
            return _v2_contract(self._additive_fields, self._breaking_fields)
        if self._additive_fields:
            return _v1_contract(self._additive_fields)
        return None


def normalize_response_drift(value: object) -> dict[str, Any]:
    """Validate and normalize either version of the drift sub-contract."""

    if not isinstance(value, Mapping):
        raise ValueError("response drift fields changed")
    if value.get("schema_version") == V1_SCHEMA_VERSION:
        return _normalize_v1(value)
    if value.get("schema_version") == V2_SCHEMA_VERSION:
        return _normalize_v2(value)
    raise ValueError("response drift contract changed")


def _normalize_v1(value: Mapping[Any, Any]) -> dict[str, Any]:
    if set(value) != {"schema_version", "direction", "classification", "fields"}:
        raise ValueError("response drift fields changed")
    if (
        value.get("direction") != "response"
        or value.get("classification") != "additive"
    ):
        raise ValueError("response drift contract changed")
    fields = {
        _normalize_v1_field(field) for field in _raw_fields(value.get("fields"))
    }
    return _v1_contract(fields)


def _normalize_v2(value: Mapping[Any, Any]) -> dict[str, Any]:
    if set(value) != {"schema_version", "direction", "classification", "fields"}:
        raise ValueError("response drift fields changed")
    if (
        value.get("direction") != "response"
        or value.get("classification") != "breaking"
    ):
        raise ValueError("response drift contract changed")
    additive: set[tuple[str, str]] = set()
    breaking: set[tuple[str, str, str]] = set()
    for field in _raw_fields(value.get("fields")):
        if not isinstance(field, Mapping):
            raise ValueError("response drift observation fields changed")
        if field.get("classification") == "additive":
            if set(field) != _V2_ADDITIVE_FIELDS:
                raise ValueError("response drift observation fields changed")
            additive.add(_normalize_path_observed(field))
        elif field.get("classification") == "breaking":
            if set(field) != _V2_BREAKING_FIELDS:
                raise ValueError("response drift observation fields changed")
            path, observed_type = _normalize_path_observed(
                field, observed_types=_BREAKING_OBSERVED_TYPES
            )
            expected_type = field.get("expected_type")
            if expected_type not in _EXPECTED_TYPES:
                raise ValueError("response drift expected_type is invalid")
            breaking.add((path, str(expected_type), observed_type))
        else:
            raise ValueError("response drift observation classification is invalid")
    if not breaking:
        raise ValueError("breaking response drift requires a breaking observation")
    return _v2_contract(additive, breaking)


def _raw_fields(value: object) -> Sequence[object]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
    ):
        raise ValueError("response drift fields must be a non-empty array")
    return value


def _normalize_v1_field(field: object) -> tuple[str, str]:
    if not isinstance(field, Mapping) or set(field) != _V1_FIELDS:
        raise ValueError("response drift observation fields changed")
    return _normalize_path_observed(field)


def _normalize_path_observed(
    field: Mapping[Any, Any],
    *,
    observed_types: frozenset[str] = _JSON_TYPES,
) -> tuple[str, str]:
    path, observed_type = field.get("path"), field.get("observed_type")
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 4_096:
        raise ValueError("response drift path is invalid")
    if observed_type not in observed_types:
        raise ValueError("response drift observed_type is invalid")
    return path, str(observed_type)


def merge_response_drifts(values: Sequence[object]) -> dict[str, Any] | None:
    additive: set[tuple[str, str]] = set()
    breaking: set[tuple[str, str, str]] = set()
    for value in values:
        if value is None:
            continue
        normalized = normalize_response_drift(value)
        if normalized["schema_version"] == V1_SCHEMA_VERSION:
            additive.update(
                (str(item["path"]), str(item["observed_type"]))
                for item in normalized["fields"]
            )
            continue
        for item in normalized["fields"]:
            if item["classification"] == "additive":
                additive.add((str(item["path"]), str(item["observed_type"])))
            else:
                breaking.add(
                    (
                        str(item["path"]),
                        str(item["expected_type"]),
                        str(item["observed_type"]),
                    )
                )
    if breaking:
        return _v2_contract(additive, breaking)
    return _v1_contract(additive) if additive else None


def _v1_contract(fields: set[tuple[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": V1_SCHEMA_VERSION,
        "direction": "response",
        "classification": "additive",
        "fields": [
            {"path": path, "observed_type": observed_type}
            for path, observed_type in sorted(fields)
        ],
    }


def _v2_contract(
    additive: set[tuple[str, str]],
    breaking: set[tuple[str, str, str]],
) -> dict[str, Any]:
    fields = [
        {
            "classification": "additive",
            "path": path,
            "observed_type": observed_type,
        }
        for path, observed_type in additive
    ]
    fields.extend(
        {
            "classification": "breaking",
            "path": path,
            "expected_type": expected_type,
            "observed_type": observed_type,
        }
        for path, expected_type, observed_type in breaking
    )
    fields.sort(
        key=lambda item: (
            item["path"],
            item["classification"],
            item.get("expected_type", ""),
            item["observed_type"],
        )
    )
    return {
        "schema_version": V2_SCHEMA_VERSION,
        "direction": "response",
        "classification": "breaking",
        "fields": fields,
    }


def _pointer(path: Sequence[str]) -> str:
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in path
    )


def _breaking_observed_type(value: object) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        return "non_json"
    try:
        return _observed_type(value)
    except ValueError:
        return "non_json"


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
    "V1_SCHEMA_VERSION",
    "V2_SCHEMA_VERSION",
    "ResponseDriftRecorder",
    "dynamic_key_path_shape",
    "dynamic_key_shape",
    "merge_response_drifts",
    "normalize_dynamic_key_patterns",
    "normalize_response_drift",
]
