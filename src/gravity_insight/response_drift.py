"""Structured, value-free observations of response contract drift."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
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
_EXPECTATION_PROVENANCE_FIELD = "expectation_provenance"
_EXPECTATION_PROVENANCE_FIELDS = frozenset(
    {
        "operation_contract",
        "runtime_version",
        "request_shape_fingerprint",
        "accepted_upstream_baseline",
        "current_observation",
    }
)
_OPERATION_CONTRACT_FIELDS = frozenset({"digest", "version"})
_BASELINE_FIELDS = frozenset(
    {
        "observed_type",
        "response_shape_fingerprint",
        "observed_at",
        "app_environment_fingerprint",
    }
)
_CURRENT_OBSERVATION_FIELDS = frozenset(
    {
        "response_shape_fingerprint",
        "observed_at",
        "app_environment_fingerprint",
    }
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
        self._breaking_fields: dict[
            tuple[str, str, str], dict[str, Any] | None
        ] = {}

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
        *,
        expectation_provenance: Mapping[str, Any] | None = None,
    ) -> None:
        if expected_type not in _EXPECTED_TYPES:
            raise ValueError("response drift expected_type is invalid")
        observed_type = (
            "missing" if value is _MISSING else _breaking_observed_type(value)
        )
        _merge_breaking_observation(
            self._breaking_fields,
            (_pointer(path), expected_type, observed_type),
            _normalize_expectation_provenance(expectation_provenance)
            if expectation_provenance is not None
            else None,
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
    breaking: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for field in _raw_fields(value.get("fields")):
        if not isinstance(field, Mapping):
            raise ValueError("response drift observation fields changed")
        if field.get("classification") == "additive":
            if set(field) != _V2_ADDITIVE_FIELDS:
                raise ValueError("response drift observation fields changed")
            additive.add(_normalize_path_observed(field))
        elif field.get("classification") == "breaking":
            if set(field) not in {
                _V2_BREAKING_FIELDS,
                _V2_BREAKING_FIELDS | {_EXPECTATION_PROVENANCE_FIELD},
            }:
                raise ValueError("response drift observation fields changed")
            path, observed_type = _normalize_path_observed(
                field, observed_types=_BREAKING_OBSERVED_TYPES
            )
            expected_type = field.get("expected_type")
            if expected_type not in _EXPECTED_TYPES:
                raise ValueError("response drift expected_type is invalid")
            provenance = (
                _normalize_expectation_provenance(
                    field[_EXPECTATION_PROVENANCE_FIELD]
                )
                if _EXPECTATION_PROVENANCE_FIELD in field
                else None
            )
            _merge_breaking_observation(
                breaking,
                (path, str(expected_type), observed_type),
                provenance,
            )
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
    breaking: dict[tuple[str, str, str], dict[str, Any] | None] = {}
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
                _merge_breaking_observation(
                    breaking,
                    (
                        str(item["path"]),
                        str(item["expected_type"]),
                        str(item["observed_type"]),
                    ),
                    dict(item[_EXPECTATION_PROVENANCE_FIELD])
                    if _EXPECTATION_PROVENANCE_FIELD in item
                    else None,
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
    breaking: Mapping[tuple[str, str, str], Mapping[str, Any] | None],
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
            **(
                {_EXPECTATION_PROVENANCE_FIELD: dict(provenance)}
                if provenance is not None
                else {}
            ),
        }
        for (path, expected_type, observed_type), provenance in breaking.items()
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


def _merge_breaking_observation(
    target: dict[tuple[str, str, str], dict[str, Any] | None],
    key: tuple[str, str, str],
    provenance: dict[str, Any] | None,
) -> None:
    if key not in target:
        target[key] = provenance
    elif target[key] != provenance:
        # One merged field can carry provenance only when every identical
        # observation agrees.  Omission is safer than a false attribution.
        target[key] = None


def _normalize_expectation_provenance(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _EXPECTATION_PROVENANCE_FIELDS
    ):
        raise ValueError("response drift expectation provenance fields changed")
    operation_contract = _normalize_operation_contract(
        value.get("operation_contract")
    )
    runtime_version = _identifier(value.get("runtime_version"), "runtime version")
    request_shape = _digest(value.get("request_shape_fingerprint"), "request shape")
    baseline = _normalize_baseline(value.get("accepted_upstream_baseline"))
    current = _normalize_current_observation(value.get("current_observation"))
    if _parsed_timestamp(baseline["observed_at"]) >= _parsed_timestamp(
        current["observed_at"]
    ):
        raise ValueError("response drift baseline must predate current observation")
    return {
        "operation_contract": operation_contract,
        "runtime_version": runtime_version,
        "request_shape_fingerprint": request_shape,
        "accepted_upstream_baseline": baseline,
        "current_observation": current,
    }


def _normalize_operation_contract(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _OPERATION_CONTRACT_FIELDS:
        raise ValueError("response drift operation contract provenance changed")
    return {
        "digest": _digest(value.get("digest"), "operation contract"),
        "version": _identifier(value.get("version"), "operation contract version"),
    }


def _normalize_baseline(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _BASELINE_FIELDS:
        raise ValueError("response drift accepted baseline fields changed")
    observed_type = value.get("observed_type")
    if observed_type not in _BREAKING_OBSERVED_TYPES:
        raise ValueError("response drift baseline observed_type is invalid")
    return {
        "observed_type": str(observed_type),
        "response_shape_fingerprint": _digest(
            value.get("response_shape_fingerprint"), "baseline response shape"
        ),
        "observed_at": _timestamp(value.get("observed_at"), "baseline"),
        "app_environment_fingerprint": _digest(
            value.get("app_environment_fingerprint"), "baseline App/environment"
        ),
    }


def _normalize_current_observation(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _CURRENT_OBSERVATION_FIELDS:
        raise ValueError("response drift current observation fields changed")
    return {
        "response_shape_fingerprint": _digest(
            value.get("response_shape_fingerprint"), "current response shape"
        ),
        "observed_at": _timestamp(value.get("observed_at"), "current observation"),
        "app_environment_fingerprint": _digest(
            value.get("app_environment_fingerprint"), "current App/environment"
        ),
    }


def _identifier(value: object, field: str) -> str:
    initial = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+:/-"
    )
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value[0] not in initial
        or any(character not in allowed for character in value)
    ):
        raise ValueError(f"response drift {field} is invalid")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"response drift {field} fingerprint is invalid")
    return value


def _timestamp(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) not in {20, 27}
        or not value.endswith("Z")
    ):
        raise ValueError(f"response drift {field} timestamp is invalid")
    try:
        parsed = _parsed_timestamp(value)
    except ValueError:
        raise ValueError(f"response drift {field} timestamp is invalid") from None
    timespec = "seconds" if len(value) == 20 else "microseconds"
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec=timespec).replace(
        "+00:00", "Z"
    )
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
        or canonical != value
    ):
        raise ValueError(f"response drift {field} timestamp is invalid")
    return value


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
