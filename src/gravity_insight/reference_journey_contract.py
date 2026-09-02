"""Exact Runtime-owned artifact set for the R01 reference Journey."""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any, Mapping

from .capability_contract import capability_contract
from .context_contract import PROJECT_REPO_PROVIDER_URI, project_repo_provider_artifact
from .errors import ContractChangedError
from .journey_contract import journey_artifact
from .operator_ids import (
    RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA,
    RETURNED_DIMENSION_CHANGE_URI,
)
from .operator_registry import OperatorRegistry


JOURNEY_ID = "analysis.merge2.ap-cost-anomaly-localization"
SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"
OPERATOR_URI = RETURNED_DIMENSION_CHANGE_URI
OPERATOR_RESULT_SCHEMA_VERSION = RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA
SEMANTIC_URI = "metric://project/acquisition-spend@1"
CONTEXT_URI = "context://project-repo/merge2-acquisition-boundaries@1"

def reference_artifacts() -> dict[str, dict[str, Any]]:
    """Return defensive copies of the exact Runtime-owned R01 artifacts."""

    return copy.deepcopy(_artifacts())


@lru_cache(maxsize=1)
def _artifacts() -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    artifacts["context_provider"] = project_repo_provider_artifact()
    journey = journey_artifact(JOURNEY_ID)
    capability = capability_contract("product", "metric-anomaly-localization@1")
    operator = OperatorRegistry().artifact(OPERATOR_URI)
    if journey is None or capability is None or operator is None:
        raise ContractChangedError(
            "R01 Journey, Capability or Operator artifact is missing"
        )
    artifacts["journey"] = journey
    artifacts["capability"] = capability
    artifacts["operator"] = operator
    _validate_relationships(artifacts)
    return artifacts


def _validate_relationships(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    journey = artifacts["journey"]["contract"]
    operator = artifacts["operator"]["contract"]
    provider = artifacts["context_provider"]["contract"]
    capability = artifacts["capability"]["contract"]
    checks = (
        journey.get("journey_id") == JOURNEY_ID,
        journey.get("display_binding", {}).get("legacy_display_key")
        == journey.get("display_name"),
        journey.get("required_skill") == SKILL_URI,
        journey.get("required_semantics") == [SEMANTIC_URI],
        journey.get("required_operators") == [OPERATOR_URI],
        journey.get("required_context") == [CONTEXT_URI],
        journey.get("required_models") == [],
        journey.get("required_capabilities")
        == [
            {
                "identity_kind": "product",
                "selector": "metric-anomaly-localization@1",
                "contract_version": "1",
                "minimum_trust": "stable",
                "completeness": "complete",
                "data_quality": "pass",
            }
        ],
        operator.get("uri") == OPERATOR_URI,
        operator.get("deterministic") is True,
        operator.get("lifecycle") == "active",
        operator.get("schemas", {}).get("output", {}).get("schema_version")
        == OPERATOR_RESULT_SCHEMA_VERSION,
        operator.get("method", {}).get("method_id")
        == "returned-dimension-change",
        provider.get("uri") == PROJECT_REPO_PROVIDER_URI,
        provider.get("role") == "data",
        provider.get("effects") == ["read"],
        set(provider.get("supports", ()))
        == {"list", "search", "read", "index", "pack", "verify"},
        capability.get("identity_kind") == "product",
        capability.get("selector") == "metric-anomaly-localization@1",
        capability.get("selector")
        == journey["required_capabilities"][0]["selector"],
        _sha256(capability.get("provider", {}).get("fingerprint")),
        capability.get("declared_completeness") == "unknown",
        capability.get("required_data_quality") == "pass",
        capability.get("validation_ttl_seconds") == 86400,
    )
    if not all(checks):
        raise ContractChangedError("R01 artifact dependency graph changed")


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
__all__ = [
    "CONTEXT_URI",
    "JOURNEY_ID",
    "OPERATOR_URI",
    "OPERATOR_RESULT_SCHEMA_VERSION",
    "SEMANTIC_URI",
    "SKILL_URI",
    "reference_artifacts",
]
