"""Business Semantic Definition, Binding, and Source contract primitives."""

from __future__ import annotations

import copy
import json
import re
import tomllib
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


DEFINITION_SCHEMA_VERSION = "gravity.semantic-definition.v1"
BINDING_SCHEMA_VERSION = "gravity.semantic-binding.v1"
SOURCE_SCHEMA_VERSION = "gravity.semantic-source.v1"
_DEFINITION_SCHEMA = "semantic-definition-v1.schema.json"
_BINDING_SCHEMA = "semantic-binding-v1.schema.json"
_SOURCE_SCHEMA = "semantic-source-v1.schema.json"
_BUILTIN_ROOT = Path(__file__).resolve().parent / "contracts" / "semantics"
_URI = re.compile(
    r"^(?P<kind>metric|dimension|entity|cohort|event|sku|activity|release|schema)://"
    r"[a-z0-9.-]+/[a-z0-9./-]+@(?P<version>[1-9][0-9]*)$"
)
_MEMBER_KINDS = {
    "metric": "metrics",
    "dimension": "dimensions",
    "filter": "filters",
    "grain": "grains",
    "join": "joins",
}


class SemanticContractError(AgentRuntimeContractError):
    """A Semantic artifact is structurally invalid."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def validate_semantic_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _object(value, "Semantic Definition")
    try:
        validate_schema(selected, _DEFINITION_SCHEMA, "Semantic Definition")
    except AgentRuntimeContractError as exc:
        raise SemanticContractError("SEMANTIC_DEFINITION_INVALID", str(exc)) from exc
    match = _URI.fullmatch(str(selected["uri"]))
    if match is None or match.group("kind") != selected["kind"] or int(
        match.group("version")
    ) != selected["version"]:
        raise SemanticContractError(
            "SEMANTIC_IDENTITY_INVALID", "URI scheme/kind/version disagree"
        )
    _effective_range(selected["effective_range"])
    if set(selected["claim_policy"]["allowed"]) & set(
        selected["claim_policy"]["forbidden"]
    ):
        raise SemanticContractError(
            "SEMANTIC_CLAIM_CONFLICT",
            "allowed and forbidden claims must be disjoint",
        )
    if selected["kind"] == "metric":
        if any(
            selected[name] is None
            for name in ("unit", "aggregation", "time", "entity_uri", "formula")
        ):
            raise SemanticContractError(
                "SEMANTIC_DEFINITION_INVALID",
                "Metric requires unit, aggregation, time, entity and formula",
            )
        _validate_unit(selected["unit"])
        _validate_formula_shape(selected)
        if selected["formula"]["parameters"] and not selected["binding_required"]:
            raise SemanticContractError(
                "SEMANTIC_PARAMETER_BINDING_INVALID",
                "Formula parameters require an explicit project Binding",
            )
    elif any(
        selected[name] is not None
        for name in ("unit", "aggregation", "time", "entity_uri", "formula")
    ):
        raise SemanticContractError(
            "SEMANTIC_DEFINITION_INVALID",
            "only Metric definitions carry metric formula, unit, aggregation, time, and entity fields",
        )
    return _normalize_definition(selected)


def validate_semantic_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _object(value, "Semantic Binding")
    try:
        validate_schema(selected, _BINDING_SCHEMA, "Semantic Binding")
    except AgentRuntimeContractError as exc:
        raise SemanticContractError("SEMANTIC_BINDING_INVALID", str(exc)) from exc
    _effective_range(selected["effective_range"])
    match = re.fullmatch(
        r"binding://(?P<authority>[a-z0-9.-]+)/[a-z0-9./-]+@(?P<version>[1-9][0-9]*)",
        str(selected["binding_uri"]),
    )
    if match is None:
        raise SemanticContractError(
            "SEMANTIC_BINDING_INVALID", "Binding URI is invalid"
        )
    members = selected["provider"]["members"]
    if set(members) - set(_MEMBER_KINDS):
        raise SemanticContractError(
            "SEMANTIC_BINDING_INVALID", "physical member kind is unsupported"
        )
    _validate_physical_provider(selected["provider"])
    return _normalize_binding(selected)


def compile_semantic_source(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _object(value, "Semantic Source")
    try:
        validate_schema(selected, _SOURCE_SCHEMA, "Semantic Source")
    except AgentRuntimeContractError as exc:
        raise SemanticContractError("SEMANTIC_SOURCE_INVALID", str(exc)) from exc
    definitions = [
        validate_semantic_definition(item) for item in selected["definitions"]
    ]
    bindings = [validate_semantic_binding(item) for item in selected["bindings"]]
    _validate_source_policy(selected, definitions, bindings)
    normalized = _normalize_source(selected, definitions, bindings)
    return _compiled_source(normalized)


def _validate_source_policy(
    source: Mapping[str, Any],
    definitions: Sequence[Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
) -> None:
    if source["source_kind"] == "runtime_builtin":
        if source["project_id"] is not None or bindings:
            raise SemanticContractError(
                "SEMANTIC_SOURCE_INVALID",
                "Runtime Built-in source cannot carry project identity or bindings",
            )
        if any(item["authority"] != "runtime" for item in definitions):
            raise SemanticContractError(
                "SEMANTIC_SOURCE_INVALID", "Built-in definitions require Runtime authority"
            )
    elif not source["project_id"]:
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID", "project/provider source requires project_id"
        )
    if any(item["owner"] != source["owner"] for item in definitions):
        raise SemanticContractError(
            "SEMANTIC_OWNER_CONFLICT", "Definition owner disagrees with source"
        )
    if source["source_kind"] in {"project_json", "project_toml"} and any(
        item["authority"] != "project" for item in definitions
    ):
        raise SemanticContractError(
            "SEMANTIC_AUTHORITY_CONFLICT",
            "Project sources require project Definition authority",
        )
    if any(
        item["project_id"] != source["project_id"]
        or item["owner"] != source["owner"]
        for item in bindings
    ):
        raise SemanticContractError(
            "SEMANTIC_BINDING_INVALID", "Binding project/owner disagrees with source"
        )


def _normalize_source(
    source: Mapping[str, Any],
    definitions: Sequence[Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_kind": source["artifact_kind"],
        "schema_version": source["schema_version"],
        "source_id": source["source_id"],
        "source_kind": source["source_kind"],
        "project_id": source["project_id"],
        "owner": source["owner"],
        "definitions": sorted(
            definitions,
            key=lambda item: (
                item["uri"],
                _range_sort_key(item["effective_range"]),
                canonical_digest(item),
            ),
        ),
        "bindings": sorted(
            bindings,
            key=lambda item: (
                item["binding_uri"],
                _range_sort_key(item["effective_range"]),
                canonical_digest(item),
            ),
        ),
    }


def _compiled_source(normalized: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": copy.deepcopy(dict(normalized)),
        "digest": canonical_digest(normalized),
        "definitions": [
            {"contract": item, "digest": canonical_digest(item)}
            for item in normalized["definitions"]
        ],
        "bindings": [
            {"contract": item, "digest": canonical_digest(item)}
            for item in normalized["bindings"]
        ],
    }


def load_semantic_source(path: str | Path) -> dict[str, Any]:
    """Load one local JSON or TOML Semantic Source and compile it canonically."""

    selected = Path(path)
    try:
        if selected.suffix.casefold() == ".json":
            value = json.loads(selected.read_text(encoding="utf-8"))
            expected_kind = "project_json"
        elif selected.suffix.casefold() == ".toml":
            with selected.open("rb") as stream:
                value = _normalize_toml_source(tomllib.load(stream))
            expected_kind = "project_toml"
        else:
            raise SemanticContractError(
                "SEMANTIC_SOURCE_INVALID", "Semantic source must be JSON or TOML"
            )
    except SemanticContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID", "Semantic source cannot be read"
        ) from exc
    if not isinstance(value, Mapping):
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID", "Semantic source must be an object"
        )
    if value.get("source_kind") != expected_kind:
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID",
            "Semantic source kind disagrees with its local file format",
        )
    return compile_semantic_source(value)


@lru_cache(maxsize=1)
def builtin_semantic_source() -> dict[str, Any]:
    definitions = [
        load_json_object(path, f"Built-in Semantic {path.name}")
        for path in sorted(_BUILTIN_ROOT.glob("*.json"))
    ]
    if not definitions:
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID", "Built-in Semantic source is empty"
        )
    return compile_semantic_source(
        {
            "artifact_kind": "semantic_source",
            "schema_version": SOURCE_SCHEMA_VERSION,
            "source_id": "gravity-runtime/builtins",
            "source_kind": "runtime_builtin",
            "project_id": None,
            "owner": "gravity-runtime/semantic",
            "definitions": definitions,
            "bindings": [],
        }
    )


def effective_range(value: Mapping[str, Any]) -> tuple[date | None, date | None]:
    return _effective_range(value)


def ranges_overlap(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    left_start, left_end = _effective_range(left)
    right_start, right_end = _effective_range(right)
    return (left_end is None or right_start is None or right_start <= left_end) and (
        right_end is None or left_start is None or left_start <= right_end
    )


def range_contains(
    value: Mapping[str, Any], start: date, end: date
) -> bool:
    selected_start, selected_end = _effective_range(value)
    return (selected_start is None or selected_start <= start) and (
        selected_end is None or end <= selected_end
    )


def _validate_formula_shape(definition: Mapping[str, Any]) -> None:
    formula = definition["formula"]
    operator = formula["operator"]
    dependencies = formula["dependencies"]
    required = {"source": 0, "difference": 2, "ratio": 2}
    if operator in required and len(dependencies) != required[operator]:
        raise SemanticContractError(
            "SEMANTIC_FORMULA_INVALID",
            f"{operator} formula has the wrong dependency count",
        )
    if operator == "sum" and not dependencies:
        raise SemanticContractError(
            "SEMANTIC_FORMULA_INVALID", "sum formula requires dependencies"
        )
    if operator == "ratio" and (
        definition["unit"]["kind"] != "ratio"
        or definition["aggregation"]["method"] != "ratio"
        or definition["aggregation"]["additivity"] != "non_additive"
    ):
        raise SemanticContractError(
            "SEMANTIC_UNIT_CONFLICT", "ratio formula requires ratio/non-additive output"
        )


def _validate_unit(unit: Mapping[str, Any]) -> None:
    currency = unit["currency"]
    if unit["kind"] != "currency" and currency is not None:
        raise SemanticContractError(
            "SEMANTIC_UNIT_CONFLICT", "only currency units may declare currency"
        )
    if currency is not None and (
        not isinstance(currency, str)
        or re.fullmatch(r"[A-Z]{3,8}", currency) is None
    ):
        raise SemanticContractError(
            "SEMANTIC_UNIT_CONFLICT", "currency must be a canonical uppercase code"
        )


def _validate_physical_provider(provider: Mapping[str, Any]) -> None:
    from .semantic_compose_catalog import definition_by_id

    reference = provider["definition"]
    try:
        definition = definition_by_id(
            str(reference["definition_id"]), int(reference["version"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticContractError(
            "SEMANTIC_BINDING_INVALID", "semantic-compose definition is missing"
        ) from exc
    for kind, member in provider["members"].items():
        if member is None:
            continue
        candidates = definition[_MEMBER_KINDS[kind]]
        identity = (member["definition_id"], member["version"])
        if not any(
            (item["definition_id"], item["version"]) == identity
            for item in candidates
        ):
            raise SemanticContractError(
                "SEMANTIC_BINDING_INVALID",
                f"semantic-compose {kind} member is not registered",
            )


def _normalize_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    if result["time"] is not None:
        result["time"]["grains"] = sorted(result["time"]["grains"])
    if result["formula"] is not None:
        result["formula"]["parameters"] = sorted(result["formula"]["parameters"])
    result["claim_policy"]["allowed"] = sorted(result["claim_policy"]["allowed"])
    result["claim_policy"]["forbidden"] = sorted(
        result["claim_policy"]["forbidden"]
    )
    return result


def _normalize_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result["provider"]["members"] = {
        key: result["provider"]["members"][key]
        for key in sorted(result["provider"]["members"])
    }
    result["parameters"] = {
        key: result["parameters"][key] for key in sorted(result["parameters"])
    }
    return result


def _effective_range(value: Mapping[str, Any]) -> tuple[date | None, date | None]:
    try:
        start = date.fromisoformat(value["start"]) if value["start"] is not None else None
        end = date.fromisoformat(value["end"]) if value["end"] is not None else None
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticContractError(
            "SEMANTIC_EFFECTIVE_RANGE_INVALID", "effective range date is invalid"
        ) from exc
    if start is not None and end is not None and start > end:
        raise SemanticContractError(
            "SEMANTIC_EFFECTIVE_RANGE_INVALID", "effective range start follows end"
        )
    if start is not None and start.isoformat() != value["start"]:
        raise SemanticContractError(
            "SEMANTIC_EFFECTIVE_RANGE_INVALID", "effective range start is not canonical"
        )
    if end is not None and end.isoformat() != value["end"]:
        raise SemanticContractError(
            "SEMANTIC_EFFECTIVE_RANGE_INVALID", "effective range end is not canonical"
        )
    return start, end


def _range_sort_key(value: Mapping[str, Any]) -> tuple[str, str]:
    return (value["start"] or "", value["end"] or "9999-12-31")


def _normalize_toml_source(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.setdefault("project_id", None)
    for definition in result.get("definitions", []):
        if not isinstance(definition, dict):
            continue
        for field in ("unit", "aggregation", "time", "entity_uri", "formula"):
            definition.setdefault(field, None)
        definition.setdefault("effective_range", {})
        definition["effective_range"].setdefault("start", None)
        definition["effective_range"].setdefault("end", None)
        if isinstance(definition.get("unit"), dict):
            definition["unit"].setdefault("currency", None)
        if isinstance(definition.get("time"), dict):
            definition["time"].setdefault("attribution_window", None)
    for binding in result.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        binding.setdefault("app_alias", None)
        binding.setdefault("parameters", {})
        binding.setdefault("effective_range", {})
        binding["effective_range"].setdefault("start", None)
        binding["effective_range"].setdefault("end", None)
    return result


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticContractError(
            "SEMANTIC_SOURCE_INVALID", f"{label} must be an object"
        )
    return copy.deepcopy(dict(value))


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "DEFINITION_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "SemanticContractError",
    "builtin_semantic_source",
    "compile_semantic_source",
    "effective_range",
    "load_semantic_source",
    "range_contains",
    "ranges_overlap",
    "validate_semantic_binding",
    "validate_semantic_definition",
]
