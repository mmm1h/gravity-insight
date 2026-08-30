"""Value-free Operator/Model facet for additive gravity.receipt.v1 metadata."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)


SCHEMA_VERSION = "gravity.operator-model-receipt-facet.v1"
_SCHEMA_NAME = "operator-model-receipt-facet-v1.schema.json"
_OPERATOR_FIELDS = ("uri", "version", "digest", "assumptions_digest")
_MODEL_FIELDS = (
    "uri",
    "version",
    "digest",
    "lineage_digest",
    "evaluation_digest",
)


def operator_model_receipt_facet(
    *,
    operators: Sequence[Mapping[str, Any]] = (),
    models: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    selected_operators = _references(operators, _OPERATOR_FIELDS, "operators")
    selected_models = _references(models, _MODEL_FIELDS, "models")
    if not selected_operators and not selected_models:
        raise ValueError("operator_model receipt facet requires a dependency")
    dependencies = {
        "operators": selected_operators,
        "models": selected_models,
    }
    return validate_operator_model_receipt_facet(
        {
            "schema_version": SCHEMA_VERSION,
            **dependencies,
            "dependencies_digest": canonical_digest(dependencies),
        }
    )


def validate_operator_model_receipt_facet(
    value: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("operator_model receipt facet must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "Operator/Model receipt facet")
    except AgentRuntimeContractError as exc:
        raise ValueError("operator_model receipt facet is invalid") from exc
    dependencies = {
        "operators": selected["operators"],
        "models": selected["models"],
    }
    if selected["dependencies_digest"] != canonical_digest(dependencies):
        raise ValueError("operator_model receipt dependency digest changed")
    return selected


def _references(
    values: Sequence[Mapping[str, Any]], fields: tuple[str, ...], label: str
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{label} references must be an array")
    result = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} reference must be an object")
        if any(field not in value for field in fields):
            raise ValueError(f"{label} reference is missing required fields")
        result.append({field: copy.deepcopy(value[field]) for field in fields})
    uris = [item["uri"] for item in result]
    if len(uris) != len(set(uris)):
        raise ValueError(f"{label} references contain duplicate URIs")
    return sorted(result, key=lambda item: item["uri"])


__all__ = [
    "SCHEMA_VERSION",
    "operator_model_receipt_facet",
    "validate_operator_model_receipt_facet",
]
