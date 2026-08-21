"""Exact immutable artifact set for the R01 reference Journey."""

from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .errors import ContractChangedError


JOURNEY_ID = "analysis.merge2.ap-cost-anomaly-localization"
SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"
OPERATOR_URI = "operator://gravity/returned-dimension-change@1"
OPERATOR_RESULT_SCHEMA_VERSION = (
    "gravity.operator-result.returned-dimension-change.v1"
)
SEMANTIC_URI = "metric://project/acquisition-spend@1"
CONTEXT_URI = "context://project-repo/merge2-acquisition-boundaries@1"

_PACKAGE_ROOT = Path(__file__).resolve().parent
_ARTIFACT_PATHS = {
    "journey": _PACKAGE_ROOT
    / "contracts"
    / "journeys"
    / "analysis.merge2.ap-cost-anomaly-localization.v1.json",
    "skill": _PACKAGE_ROOT
    / "contracts"
    / "skills"
    / "gravity.game.ap-cost-anomaly-localization.v1.json",
    "operator": _PACKAGE_ROOT
    / "contracts"
    / "operators"
    / "returned-dimension-change.v1.json",
    "context_provider": _PACKAGE_ROOT
    / "contracts"
    / "context-providers"
    / "project-repo-r01.v1.json",
    "analysis_result_contract": _PACKAGE_ROOT
    / "contracts"
    / "analysis-results"
    / "r01-ap-cost-anomaly.v1.json",
    "capability_trust": _PACKAGE_ROOT
    / "contracts"
    / "trust"
    / "metric-anomaly-localization.v1.json",
}
_GUIDE_PATH = (
    _PACKAGE_ROOT
    / "skills"
    / "gravity.game.ap-cost-anomaly-localization"
    / "GUIDE.md"
)
_ROOT_FIELDS = {
    "journey": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "journey_id",
            "version",
            "lifecycle",
            "owner",
            "calling_project",
            "required_skill",
            "required_semantics",
            "required_operators",
            "required_context",
            "required_capability",
            "execution",
            "project_contract_path",
            "request_budget",
            "claim_policy",
        }
    ),
    "skill": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "namespace",
            "skill_id",
            "version",
            "lifecycle",
            "readiness",
            "summary",
            "covers_journeys",
            "semantic_dependencies",
            "capability_dependencies",
            "operator_dependencies",
            "context_dependencies",
            "effects",
            "execution_owner",
            "guide_resource",
        }
    ),
    "operator": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "uri",
            "version",
            "owner",
            "deterministic",
            "input_contract",
            "output_schema_version",
            "assumptions",
            "allowed_claims",
            "forbidden_claims",
        }
    ),
    "context_provider": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "provider_id",
            "transport",
            "effects",
            "resource_types",
            "auth_scope",
            "freshness",
            "supports",
            "role",
            "max_files",
            "max_file_bytes",
            "max_total_bytes",
        }
    ),
    "analysis_result_contract": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "result_schema_version",
            "owner",
            "required_references",
            "completeness_values",
            "data_quality_values",
            "finding_types",
        }
    ),
    "capability_trust": frozenset(
        {
            "artifact_kind",
            "schema_version",
            "identity_kind",
            "selector",
            "definition_fingerprint",
            "lifecycle",
            "owner",
            "dependencies",
            "required_completeness",
            "required_data_quality",
            "validation_ttl_seconds",
            "allowed_claims",
        }
    ),
}


def reference_artifacts() -> dict[str, dict[str, Any]]:
    """Return defensive copies of the exact validated R01 artifact set."""

    return copy.deepcopy(_artifacts())


@lru_cache(maxsize=1)
def _artifacts() -> dict[str, dict[str, Any]]:
    artifacts = {name: _read(path, name) for name, path in _ARTIFACT_PATHS.items()}
    _validate_relationships(artifacts)
    try:
        guide = _GUIDE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractChangedError("R01 Built-in Skill guide cannot be read") from exc
    if not guide.strip() or "Context is data" not in guide:
        raise ContractChangedError("R01 Built-in Skill guide is invalid")
    artifacts["skill"]["guide"] = guide
    artifacts["skill"]["package_digest"] = _digest(
        {
            "manifest": artifacts["skill"]["contract"],
            "guide": guide,
        }
    )
    return artifacts


def _read(path: Path, expected_kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractChangedError(f"R01 {expected_kind} artifact cannot be read") from exc
    if not isinstance(value, dict) or value.get("artifact_kind") != expected_kind:
        raise ContractChangedError(f"R01 {expected_kind} artifact identity changed")
    if set(value) != _ROOT_FIELDS[expected_kind]:
        raise ContractChangedError(f"R01 {expected_kind} artifact fields changed")
    _json_value(value, expected_kind)
    return {"contract": value, "digest": _digest(value)}


def _validate_relationships(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    journey = artifacts["journey"]["contract"]
    skill = artifacts["skill"]["contract"]
    operator = artifacts["operator"]["contract"]
    provider = artifacts["context_provider"]["contract"]
    result = artifacts["analysis_result_contract"]["contract"]
    trust = artifacts["capability_trust"]["contract"]
    checks = (
        journey.get("journey_id") == JOURNEY_ID,
        journey.get("required_skill") == SKILL_URI,
        journey.get("required_semantics") == [SEMANTIC_URI],
        journey.get("required_operators") == [OPERATOR_URI],
        journey.get("required_context") == [CONTEXT_URI],
        skill.get("covers_journeys") == [JOURNEY_ID],
        skill.get("semantic_dependencies") == [SEMANTIC_URI],
        skill.get("operator_dependencies") == [OPERATOR_URI],
        skill.get("context_dependencies") == [CONTEXT_URI],
        skill.get("effects") == ["read"],
        skill.get("execution_owner") == journey["execution"]["owner"],
        operator.get("uri") == OPERATOR_URI,
        operator.get("deterministic") is True,
        operator.get("output_schema_version") == OPERATOR_RESULT_SCHEMA_VERSION,
        provider.get("role") == "data",
        provider.get("effects") == ["read"],
        result.get("result_schema_version") == "gravity.analysis-result.v1",
        trust.get("identity_kind") == "product",
        trust.get("selector") == "metric-anomaly-localization@1",
        _sha256(trust.get("definition_fingerprint")),
        trust.get("required_completeness") == "complete",
        trust.get("required_data_quality") == "pass",
        trust.get("validation_ttl_seconds") == 86400,
    )
    if not all(checks):
        raise ContractChangedError("R01 artifact dependency graph changed")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractChangedError(f"R01 {label} artifact is not canonical JSON") from exc


__all__ = [
    "CONTEXT_URI",
    "JOURNEY_ID",
    "OPERATOR_URI",
    "OPERATOR_RESULT_SCHEMA_VERSION",
    "SEMANTIC_URI",
    "SKILL_URI",
    "reference_artifacts",
]
