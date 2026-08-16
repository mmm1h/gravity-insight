"""Narrow deterministic compiler for registered Multidim semantic members."""

from __future__ import annotations

import copy
import json
import math
from datetime import date
from typing import Any, Mapping, NoReturn, Sequence

from .errors import InputValidationError
from .multidim_product import (
    FRONTEND_ADREPORT_DATA_CONF,
    MULTIDIM_INPUT_SCHEMA_VERSION,
    run_multidim_query,
)
from .multidim_service import MULTIDIM_QUERY_OPERATION
from .plan_multidim_result import sanitize_multidim_result
from .result_source import GOVERNED_PRODUCT, result_source
from .semantic_compose_catalog import (
    available_definition_refs,
    definition_by_id,
    definition_fingerprint,
    semantic_definitions,
)


SEMANTIC_COMPOSE_NAME = "semantic_compose"
SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION = "gravity.semantic-compose-input.v1"
SEMANTIC_COMPOSE_COMPILED_SCHEMA_VERSION = "gravity.semantic-compose-compiled.v1"
SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION = "gravity.semantic-compose-result.v1"
SEMANTIC_COMPOSE_RESOLUTION_TIER = "tier_b_governed_semantic"
_INPUT_FIELDS = frozenset(
    {"definition", "window", "metric", "dimensions", "filters", "grain", "joins"}
)
_MAX_TEXT = 4_096
_MAX_FILTER_VALUES = 32


def semantic_compose_input_schema() -> dict[str, Any]:
    """Return the closed request schema plus exact currently registered references."""

    definitions = semantic_definitions()
    definition_refs = [
        {"definition_id": item["definition_id"], "version": item["version"]}
        for item in definitions
    ]
    members, filter_operators, limits = _schema_inventory(definitions)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
        "schema_version": SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_INPUT_FIELDS),
        "properties": {
            "definition": _ref_schema(definition_refs),
            "window": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end"],
                "properties": {
                    "start": {"type": "string", "format": "date"},
                    "end": {"type": "string", "format": "date"},
                },
            },
            "metric": _ref_schema(members["metrics"]),
            "dimensions": {
                "type": "array",
                "maxItems": limits["dimensions"],
                "uniqueItems": True,
                "items": _ref_schema(members["dimensions"]),
            },
            "filters": {
                "type": "array",
                "maxItems": limits["filters"],
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["member", "operator", "values"],
                    "properties": {
                        "member": _ref_schema(members["filters"]),
                        "operator": (
                            {"enum": filter_operators} if filter_operators else {"not": {}}
                        ),
                        "values": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": _MAX_FILTER_VALUES,
                            "items": {"type": ["string", "number", "integer", "boolean"]},
                        },
                    },
                },
            },
            "grain": _ref_schema(members["grains"]),
            "joins": {
                "type": "array",
                "maxItems": limits["joins"],
                "uniqueItems": True,
                "items": _ref_schema(members["joins"]),
            },
        },
        "x-registered-definitions": available_definition_refs(),
    }


def _schema_inventory(
    definitions: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, int]]:
    members = {
        kind: _unique_refs(
            [
                {
                    "definition_id": member["definition_id"],
                    "version": member["version"],
                }
                for definition in definitions
                for member in definition[kind]
            ]
        )
        for kind in ("metrics", "dimensions", "filters", "grains", "joins")
    }
    operators = sorted(
        {
            str(operator)
            for definition in definitions
            for member in definition["filters"]
            for operator in member["operators"]
        }
    )
    limits = {
        kind: max(int(definition["limits"][kind]) for definition in definitions)
        for kind in ("dimensions", "filters", "joins")
    }
    return members, operators, limits


def _unique_refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique = {
        (str(item["definition_id"]), int(item["version"])): {
            "definition_id": str(item["definition_id"]),
            "version": int(item["version"]),
        }
        for item in values
    }
    return [unique[key] for key in sorted(unique)]


def compile_semantic_compose(inputs: Mapping[str, Any], *, app_id: int) -> dict[str, Any]:
    """Compile registered member references into one canonical Multidim request."""

    request = _object(inputs, "inputs", "the semantic compose object schema")
    if set(request) != _INPUT_FIELDS:
        _fail("semantic compose fields do not match the closed schema", "inputs", sorted(request), sorted(_INPUT_FIELDS))
    app = _positive_app(app_id)
    definition_ref = _reference(request.get("definition"), "definition")
    try:
        definition = definition_by_id(*definition_ref)
    except KeyError:
        _fail("semantic definition is unknown", "definition", definition_ref, available_definition_refs())
    window = _window(request.get("window"))
    metric = _member(definition, "metrics", request.get("metric"), "metric")
    dimensions = _member_array(definition, "dimensions", request.get("dimensions"), "dimensions")
    filters = _filters(definition, request.get("filters"))
    grain = _member(definition, "grains", request.get("grain"), "grain")
    joins = _member_array(definition, "joins", request.get("joins"), "joins")
    _validate_grain(metric, grain)
    _validate_joins(dimensions, joins)
    _validate_filter_dimensions(filters, dimensions)
    return _compiled_output(
        definition, app, window, metric, dimensions, filters, grain, joins
    )


def _compiled_output(
    definition: Mapping[str, Any],
    app: int,
    window: Mapping[str, str],
    metric: Mapping[str, Any],
    dimensions: Sequence[Mapping[str, Any]],
    filters: Sequence[Mapping[str, Any]],
    grain: Mapping[str, Any],
    joins: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_filters = [
        {
            "field": item["member"]["physical_name"],
            "operator": item["operator"],
            "values": copy.deepcopy(item["values"]),
        }
        for item in filters
    ]
    physical_filters.append(
        {"field": definition["access_scope"]["physical_filter"], "operator": "EQUALS", "values": [app]}
    )
    generated_inputs = {
        "date_list": [window["start"], window["end"]],
        "time_dims": grain["physical_name"],
        "metrics_list": [metric["physical_name"]],
        "custom_metrics_list": [],
        "data_dims": [item["physical_name"] for item in dimensions],
        "relate_dims": [],
        "filters": physical_filters,
    }
    if definition["source"].get("request_profile") == "frontend_adreport_current":
        generated_inputs["multi_keys"] = list(range(2, 31))
        generated_inputs["data_conf"] = copy.deepcopy(FRONTEND_ADREPORT_DATA_CONF)
    generated_query = {
        "name": "multidim",
        "input_schema_version": MULTIDIM_INPUT_SCHEMA_VERSION,
        "app": app,
        "inputs": generated_inputs,
        "include_total": False,
        "read_all": False,
    }
    members = {
        "metric": _public_member("metric", metric),
        "dimensions": [_public_member("dimension", item) for item in dimensions],
        "filters": [_public_filter(item) for item in filters],
        "grain": _public_member("grain", grain),
        "joins": [_public_join(item) for item in joins],
    }
    scope = {
        "app_id": app,
        "window": window,
        "metric": metric["definition_id"],
        "dimensions": [item["definition_id"] for item in dimensions],
        "filters": [item["member"]["definition_id"] for item in filters],
        "grain": grain["definition_id"],
    }
    return {
        "schema_version": SEMANTIC_COMPOSE_COMPILED_SCHEMA_VERSION,
        "resolution_tier": SEMANTIC_COMPOSE_RESOLUTION_TIER,
        "definition": {
            "definition_id": definition["definition_id"],
            "version": definition["version"],
            "fingerprint": definition_fingerprint(definition),
        },
        "semantic_members": members,
        "generated_query": generated_query,
        "validation": {
            "status": "validated",
            "network_called": False,
            "members": "registered_version_exact",
            "grain_compatibility": "validated",
            "join_cardinality": "validated",
            "access_scope": "app_bound_validated",
            "operation_contract_version": definition["source"]["operation_contract_version"],
        },
        "allowed_claims": [
            {**copy.deepcopy(claim), "scope": copy.deepcopy(scope)}
            for claim in definition["allowed_claims"]
        ],
    }


def compiled_semantic_bytes(inputs: Mapping[str, Any], *, app_id: int) -> bytes:
    """Expose the byte-level determinism acceptance surface."""

    return json.dumps(
        compile_semantic_compose(inputs, app_id=app_id),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def run_semantic_compose(
    client: Any,
    inputs: Mapping[str, Any],
    *,
    app_id: int,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Execute only the generated registered Multidim query."""

    compiled = compile_semantic_compose(inputs, app_id=app_id)
    query = compiled["generated_query"]
    native = run_multidim_query(
        client,
        query["inputs"],
        app_id=app_id,
        include_total=False,
        read_all=False,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=1,
    )
    safe = sanitize_multidim_result(native, str(app_id))
    ok = safe.get("ok") is True and safe.get("status") in {"success", "empty"}
    validation = {
        **compiled["validation"],
        "network_called": True,
        "live_metadata": copy.deepcopy(safe.get("validation")),
        "result_eligible": ok,
    }
    return {
        "schema_version": SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "resolution_tier": compiled["resolution_tier"],
        "definition": compiled["definition"],
        "semantic_members": compiled["semantic_members"],
        "generated_query": compiled["generated_query"],
        "validation": validation,
        "allowed_claims": compiled["allowed_claims"] if ok else [],
        "operation_id": safe.get("operation_id", MULTIDIM_QUERY_OPERATION),
        "network_called": True,
        "query_executed": True,
        "ok": safe.get("ok") is True,
        "status": safe.get("status"),
        "exit_code": safe.get("exit_code"),
        "error": copy.deepcopy(safe.get("error")),
        "next_action": safe.get("next_action"),
        "result": safe,
    }


def is_semantic_compose_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION


def _ref_schema(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not values:
        return {"not": {}}
    return {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["definition_id", "version"],
                "properties": {
                    "definition_id": {"const": str(item["definition_id"])},
                    "version": {"const": int(item["version"])},
                },
            }
            for item in sorted(
                values,
                key=lambda item: (str(item["definition_id"]), int(item["version"])),
            )
        ]
    }


def _reference(value: Any, field: str) -> tuple[str, int]:
    selected = _object(value, field, "an exact {definition_id, version} reference")
    if set(selected) != {"definition_id", "version"}:
        _fail("semantic member reference fields are invalid", field, sorted(selected), ["definition_id", "version"])
    identifier, version = selected.get("definition_id"), selected.get("version")
    if not isinstance(identifier, str) or not identifier or type(version) is not int or version < 1:
        _fail("semantic member reference identity is invalid", field, selected, "registered definition_id and positive integer version")
    return identifier, version


def _member(definition: Mapping[str, Any], kind: str, value: Any, field: str) -> Mapping[str, Any]:
    reference = _reference(value, field)
    matches = [item for item in definition[kind] if (item["definition_id"], item["version"]) == reference]
    if len(matches) != 1:
        allowed = [{"definition_id": item["definition_id"], "version": item["version"]} for item in definition[kind]]
        _fail("semantic member is unknown for this definition", field, reference, allowed)
    return matches[0]


def _member_array(definition: Mapping[str, Any], kind: str, value: Any, field: str) -> list[Mapping[str, Any]]:
    limit = int(definition["limits"][kind])
    if not isinstance(value, list) or len(value) > limit:
        _fail("semantic member array exceeds the definition bound", field, value, f"array with at most {limit} registered references")
    selected = [_member(definition, kind, item, f"{field}.{index}") for index, item in enumerate(value)]
    identities = [(item["definition_id"], item["version"]) for item in selected]
    if len(identities) != len(set(identities)):
        _fail("semantic member array contains duplicates", field, identities, "unique registered references")
    return selected


def _filters(definition: Mapping[str, Any], value: Any) -> list[dict[str, Any]]:
    limit = int(definition["limits"]["filters"])
    if not isinstance(value, list) or len(value) > limit:
        _fail("semantic filters exceed the definition bound", "filters", value, f"array with at most {limit} registered filters")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        field = f"filters.{index}"
        item = _object(raw, field, "the registered filter shape")
        if set(item) != {"member", "operator", "values"}:
            _fail("semantic filter fields are invalid", field, sorted(item), ["member", "operator", "values"])
        member = _member(definition, "filters", item.get("member"), f"{field}.member")
        operator = item.get("operator")
        if operator not in member["operators"]:
            _fail("semantic filter operator is not registered", f"{field}.operator", operator, member["operators"])
        values = item.get("values")
        if not isinstance(values, list) or not 1 <= len(values) <= _MAX_FILTER_VALUES or any(not _scalar(value) for value in values):
            _fail("semantic filter values are invalid", f"{field}.values", values, f"1..{_MAX_FILTER_VALUES} bounded JSON scalars")
        result.append({"member": member, "operator": operator, "values": copy.deepcopy(values)})
    identities = [(item["member"]["definition_id"], item["member"]["version"]) for item in result]
    if len(identities) != len(set(identities)):
        _fail("semantic filters contain duplicate members", "filters", identities, "unique registered filter members")
    return sorted(result, key=lambda item: (item["member"]["definition_id"], item["member"]["version"]))


def _validate_grain(metric: Mapping[str, Any], grain: Mapping[str, Any]) -> None:
    if grain["definition_id"] not in metric["allowed_grains"]:
        _fail("semantic grain conflicts with the selected metric", "grain", grain["definition_id"], metric["allowed_grains"])


def _validate_joins(dimensions: Sequence[Mapping[str, Any]], joins: Sequence[Mapping[str, Any]]) -> None:
    required = {str(item["required_join"]) for item in dimensions}
    selected = {str(item["definition_id"]) for item in joins}
    if selected - required:
        _fail("semantic join is registered but forbidden for the selected dimensions", "joins", sorted(selected), sorted(required))
    if required - selected:
        _fail("semantic dimensions require an allowed join", "joins", sorted(selected), sorted(required))


def _validate_filter_dimensions(
    filters: Sequence[Mapping[str, Any]], dimensions: Sequence[Mapping[str, Any]]
) -> None:
    selected = {str(item["definition_id"]) for item in dimensions}
    required = {str(item["member"]["required_dimension"]) for item in filters}
    missing = sorted(item for item in required if item not in selected)
    if missing:
        _fail(
            "semantic filters require their grouped dimensions",
            "filters",
            sorted(selected),
            sorted(required),
        )


def _window(value: Any) -> dict[str, str]:
    selected = _object(value, "window", "the {start, end} ISO-date shape")
    if set(selected) != {"start", "end"}:
        _fail("semantic window fields are invalid", "window", sorted(selected), ["start", "end"])
    parsed: list[date] = []
    result: dict[str, str] = {}
    for field in ("start", "end"):
        raw = selected.get(field)
        try:
            day = date.fromisoformat(raw) if isinstance(raw, str) else None
        except ValueError:
            day = None
        if day is None or day.isoformat() != raw:
            _fail("semantic window date is invalid", f"window.{field}", raw, "canonical YYYY-MM-DD")
        parsed.append(day)
        result[field] = raw
    if parsed[0] > parsed[1]:
        _fail("semantic window start is after end", "window", result, "start <= end")
    return result


def _positive_app(value: Any) -> int:
    if type(value) is not int or value < 1:
        _fail("semantic access scope App is invalid", "app", value, "positive configured App id")
    return value


def _public_member(kind: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "definition_id": value["definition_id"], "version": value["version"], "physical_name": value["physical_name"]}


def _public_filter(value: Mapping[str, Any]) -> dict[str, Any]:
    return {**_public_member("filter", value["member"]), "operator": value["operator"], "values": copy.deepcopy(value["values"])}


def _public_join(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "join", "definition_id": value["definition_id"], "version": value["version"], "cardinality": value["cardinality"], "realization": value["realization"]}


def _object(value: Any, field: str, allowed: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("semantic compose value must be an object", field, value, allowed)
    return value


def _scalar(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, str):
        return bool(value) and len(value) <= _MAX_TEXT
    return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))


def actual_value(value: Any) -> str:
    rendered = repr(value).replace("\n", " ")
    return rendered[:160] + ("..." if len(rendered) > 160 else "")


def _fail(message: str, field: str, value: Any, allowed: Any) -> NoReturn:
    raise InputValidationError(
        f"{message}; actual value {actual_value(value)}",
        field=field,
        next_action=(
            "Run `gravity semantic compose --input-schema`, replace this field with "
            f"an allowed registered value, then retry. Allowed: {actual_value(allowed)}"
        ),
    )


__all__ = [
    "SEMANTIC_COMPOSE_COMPILED_SCHEMA_VERSION",
    "SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION",
    "SEMANTIC_COMPOSE_NAME",
    "SEMANTIC_COMPOSE_RESULT_SCHEMA_VERSION",
    "compiled_semantic_bytes",
    "compile_semantic_compose",
    "is_semantic_compose_result",
    "run_semantic_compose",
    "semantic_compose_input_schema",
]
