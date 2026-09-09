"""Immutable semantic definitions layered on the existing product catalog."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractChangedError
from .multidim_service import STANDARD_METRIC_OPERATION
from .workspace_semantic_context import compiled_operation


DEFINITION_SCHEMA_VERSION = "gravity.semantic-definition.v1"
AP_COST_DATE_SEMANTICS_GAP_CODE = "AP_COST_DATE_SEMANTICS_UNDECLARED"
POST_REGISTRATION_USER_GROUP_COST_GAP_CODE = (
    "POST_REGISTRATION_USER_GROUP_EXACT_COST_UNAVAILABLE"
)
_ID_RE = re.compile(r"^[a-z][a-z0-9.-]+$")
_COLLECTIONS = ("metrics", "dimensions", "filters", "grains", "joins")
_ROOT_FIELDS = frozenset(
    {
        "$schema",
        "schema_version",
        "definition_id",
        "version",
        "description",
        "source",
        "access_scope",
        "limits",
        *_COLLECTIONS,
        "allowed_claims",
    }
)
_COST_BOUNDARY_FIELDS = frozenset(
    {"cost_granularity_and_provenance", "forbidden_claims"}
)
_SOURCE_FIELDS = frozenset(
    {"product", "operation_id", "operation_contract_version", "fact_path"}
)
_REQUEST_PROFILES = frozenset({"frontend_adreport_current"})


def semantic_definitions() -> tuple[dict[str, Any], ...]:
    """Return fresh copies of every validated built-in semantic definition."""

    return tuple(copy.deepcopy(value) for value in _semantic_definitions())


def definition_by_id(definition_id: str, version: int) -> dict[str, Any]:
    """Resolve one exact definition version; callers decide error classification."""

    matches = [
        value
        for value in _semantic_definitions()
        if value["definition_id"] == definition_id and value["version"] == version
    ]
    if len(matches) != 1:
        raise KeyError((definition_id, version))
    return copy.deepcopy(matches[0])


def definition_fingerprint(value: Mapping[str, Any]) -> str:
    """Hash the complete versioned definition, excluding no interpretation fields."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def available_definition_refs() -> list[dict[str, Any]]:
    return [
        {"definition_id": value["definition_id"], "version": value["version"]}
        for value in _semantic_definitions()
    ]


@lru_cache(maxsize=1)
def _semantic_definitions() -> tuple[dict[str, Any], ...]:
    root = Path(__file__).resolve().parent / "contracts" / "semantic"
    values = tuple(
        _read_definition(path) for path in sorted(root.glob("*.json"))
    )
    identities = [(value["definition_id"], value["version"]) for value in values]
    if not values or len(identities) != len(set(identities)):
        raise ContractChangedError("semantic definition identities are empty or duplicated")
    return values


def _read_definition(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractChangedError(f"cannot read semantic definition {path.name}") from exc
    if not isinstance(value, dict):
        raise ContractChangedError("semantic definition root must be an object")
    _validate_definition(value)
    return value


def _validate_definition(value: Mapping[str, Any]) -> None:
    version = _validate_header(value)
    limits = _validate_limits(value.get("limits"))
    collections = {
        name: _members(value.get(name), name) for name in _COLLECTIONS
    }
    if limits["metrics"] != 1 or len(collections["metrics"]) < 1:
        raise ContractChangedError("semantic definitions require exactly one selected metric")
    for name in ("dimensions", "filters", "joins"):
        if len(collections[name]) > limits[name]:
            raise ContractChangedError(f"semantic definition {name} exceed their limit")
    _validate_relationships(collections)
    allowed_claims = _validate_claims(value.get("allowed_claims"), "allowed_claims")
    if version >= 5:
        forbidden_claims = _validate_claims(
            value.get("forbidden_claims"), "forbidden_claims"
        )
        if allowed_claims & forbidden_claims:
            raise ContractChangedError(
                "semantic allowed and forbidden claims must be disjoint"
            )
        _validate_cost_boundaries(
            value.get("cost_granularity_and_provenance"), collections["dimensions"]
        )


def _validate_header(value: Mapping[str, Any]) -> int:
    identity = _identity(value, "definition")
    expected = _ROOT_FIELDS | _COST_BOUNDARY_FIELDS if identity[1] >= 5 else _ROOT_FIELDS
    if set(value) != expected:
        raise ContractChangedError("semantic definition root fields changed")
    if value.get("schema_version") != DEFINITION_SCHEMA_VERSION:
        raise ContractChangedError("semantic definition schema version changed")
    if not isinstance(value.get("description"), str) or not value["description"].strip():
        raise ContractChangedError("semantic definition description is invalid")
    _validate_source(value.get("source"))
    if value.get("access_scope") != {"kind": "app_bound", "physical_filter": "app_id"}:
        raise ContractChangedError("semantic definition access scope changed")
    return identity[1]


def _validate_limits(value: Any) -> Mapping[str, Any]:
    limits = _object(value, "limits")
    if set(limits) != {"metrics", "dimensions", "filters", "joins"} or any(
        type(limits[name]) is not int or limits[name] < 0 for name in limits
    ):
        raise ContractChangedError("semantic definition limits are invalid")
    return limits


def _validate_claims(claims: Any, field: str) -> set[str]:
    if not isinstance(claims, list) or not claims:
        raise ContractChangedError(f"semantic definition {field} are empty")
    identifiers: set[str] = set()
    for claim in claims:
        selected = _object(claim, field)
        if set(selected) != {"claim_id", "statement"}:
            raise ContractChangedError(f"semantic {field} fields changed")
        identifier = _stable_id(selected.get("claim_id"), "claim_id")
        if identifier in identifiers:
            raise ContractChangedError(f"semantic {field} identities are duplicated")
        identifiers.add(identifier)
        if not isinstance(selected.get("statement"), str) or not selected["statement"].strip():
            raise ContractChangedError(f"semantic {field} statement is invalid")
    return identifiers


def _validate_cost_boundaries(
    value: Any, dimensions: list[Mapping[str, Any]]
) -> None:
    boundaries = _object(value, "cost_granularity_and_provenance")
    if set(boundaries) != {"native_cost", "revenue", "join_evidence"}:
        raise ContractChangedError("semantic cost boundary fields changed")

    native = _object(boundaries.get("native_cost"), "native_cost")
    if set(native) != {
        "metric",
        "non_time_dimensions",
        "date_semantics",
        "post_registration_user_grouping",
        "estimation",
    }:
        raise ContractChangedError("semantic native cost boundary fields changed")
    dimension_names = [str(item["physical_name"]) for item in dimensions]
    if native.get("metric") != "ap_cost" or native.get("non_time_dimensions") != dimension_names:
        raise ContractChangedError("semantic native cost dimensions differ from registered dimensions")
    _validate_cost_date_semantics(native.get("date_semantics"))
    grouping = _object(
        native.get("post_registration_user_grouping"),
        "post_registration_user_grouping",
    )
    if grouping != {
        "status": "unavailable",
        "gap_code": POST_REGISTRATION_USER_GROUP_COST_GAP_CODE,
    }:
        raise ContractChangedError("semantic post-registration cost boundary changed")
    estimation = _object(native.get("estimation"), "estimation")
    if estimation != {
        "native_or_exact_allowed": False,
        "required_label": "estimated",
        "required_disclosures": [
            "method",
            "covered_population",
            "excluded_label_treatment",
            "assumptions",
        ],
    }:
        raise ContractChangedError("semantic cost estimation policy changed")

    _validate_revenue_boundaries(boundaries.get("revenue"))
    join_evidence = _object(boundaries.get("join_evidence"), "join_evidence")
    if join_evidence != {
        "artifact_path": "../join-keys/registry.v1.json",
        "registry_id": "join-key://gravity/acquisition-user@1",
        "right_side_semantics": "acquisition_attribution_fields",
        "post_registration_user_property_mapping": False,
    }:
        raise ContractChangedError("semantic cost join evidence changed")


def _validate_cost_date_semantics(value: Any) -> None:
    semantics = _object(value, "date_semantics")
    if semantics != {
        "status": "undeclared",
        "basis": None,
        "gap_code": AP_COST_DATE_SEMANTICS_GAP_CODE,
        "evidence": {
            "operation_id": STANDARD_METRIC_OPERATION,
            "field": "data.list[].tip",
            "declared_meaning": "total_spend_only",
        },
    }:
        raise ContractChangedError("semantic ap_cost date boundary changed")


def _validate_revenue_boundaries(value: Any) -> None:
    revenue = _object(value, "revenue")
    if revenue != {
        "cohort_basis": "activation",
        "evidence": {
            "operation_id": STANDARD_METRIC_OPERATION,
            "field": "data.list[].tip",
            "declared_meaning": "activation_cohort",
        },
        "metrics": [
            {
                "physical_name": "standard_1day_pay_amount",
                "metric_type": 0,
                "event_timing": "within_activation_day",
            },
            {
                "physical_name": "multi_day_pay_amount",
                "metric_type": 2,
                "event_timing": "post_activation_day_n",
            },
        ],
    }:
        raise ContractChangedError("semantic revenue date boundary changed")


def _validate_source(value: Any) -> None:
    source = _object(value, "source")
    source_fields = frozenset(source)
    if (
        source_fields
        not in (_SOURCE_FIELDS, _SOURCE_FIELDS | {"request_profile"})
        or source.get("product") != "multidim"
        or (
            "request_profile" in source
            and source.get("request_profile") not in _REQUEST_PROFILES
        )
    ):
        raise ContractChangedError("semantic definition source changed")
    operation = compiled_operation(str(source.get("operation_id", "")))
    if (
        operation is None
        or str(operation.contract_version) != str(source.get("operation_contract_version"))
        or operation.stability != "stable"
        or not operation.executable
        or operation.effect != "read"
    ):
        raise ContractChangedError("semantic definition source operation is stale")
    if source.get("fact_path") != "/result/query/data/list":
        raise ContractChangedError("semantic definition fact path changed")


def _members(value: Any, field: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ContractChangedError(f"semantic definition {field} must be an object array")
    identities = [_identity(item, field) for item in value]
    if len(identities) != len(set(identities)):
        raise ContractChangedError(f"semantic definition {field} identities are duplicated")
    return value


def _validate_relationships(values: Mapping[str, list[Mapping[str, Any]]]) -> None:
    ids = {
        kind: {str(item["definition_id"]) for item in members}
        for kind, members in values.items()
    }
    _validate_metric_relationships(values["metrics"], ids["grains"])
    _validate_dimension_relationships(values, ids)
    _validate_filter_relationships(values, ids)
    _validate_physical_names(values)


def _validate_metric_relationships(
    metrics: list[Mapping[str, Any]], grain_ids: set[str]
) -> None:
    for metric in metrics:
        grains = metric.get("allowed_grains")
        if not isinstance(grains, list) or not grains or not set(grains) <= grain_ids:
            raise ContractChangedError("semantic metric grains are invalid")
        if metric.get("metadata_operation") != STANDARD_METRIC_OPERATION:
            raise ContractChangedError("semantic metric metadata source changed")


def _validate_dimension_relationships(
    values: Mapping[str, list[Mapping[str, Any]]], ids: Mapping[str, set[str]]
) -> None:
    for dimension in values["dimensions"]:
        if dimension.get("required_join") not in ids["joins"]:
            raise ContractChangedError("semantic dimension join is invalid")
    for join in values["joins"]:
        if (
            join.get("right_member") not in ids["dimensions"]
            or join.get("cardinality") not in {"one_to_one", "many_to_one"}
            or join.get("realization") != "embedded_dimension"
        ):
            raise ContractChangedError("semantic join relationship is invalid")


def _validate_filter_relationships(
    values: Mapping[str, list[Mapping[str, Any]]], ids: Mapping[str, set[str]]
) -> None:
    dimensions = {
        str(item["definition_id"]): item for item in values["dimensions"]
    }
    for item in values["filters"]:
        operators = item.get("operators")
        required = item.get("required_dimension")
        if (
            not isinstance(operators, list)
            or not operators
            or any(not isinstance(operator, str) or not operator for operator in operators)
            or len(operators) != len(set(operators))
            or required not in ids["dimensions"]
            or item.get("physical_name") != dimensions[str(required)].get("physical_name")
        ):
            raise ContractChangedError("semantic filter relationship is invalid")


def _validate_physical_names(
    values: Mapping[str, list[Mapping[str, Any]]]
) -> None:
    for item in (*values["metrics"], *values["dimensions"], *values["filters"], *values["grains"]):
        if not isinstance(item.get("physical_name"), str) or not item["physical_name"]:
            raise ContractChangedError("semantic member physical name is invalid")


def _identity(value: Mapping[str, Any], field: str) -> tuple[str, int]:
    return (
        _stable_id(value.get("definition_id"), f"{field}.definition_id"),
        _version(value.get("version"), f"{field}.version"),
    )


def _stable_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ContractChangedError(f"semantic definition {field} is invalid")
    return value


def _version(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ContractChangedError(f"semantic definition {field} is invalid")
    return value


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractChangedError(f"semantic definition {field} must be an object")
    return value


__all__ = [
    "AP_COST_DATE_SEMANTICS_GAP_CODE",
    "DEFINITION_SCHEMA_VERSION",
    "POST_REGISTRATION_USER_GROUP_COST_GAP_CODE",
    "available_definition_refs",
    "definition_by_id",
    "definition_fingerprint",
    "semantic_definitions",
]
