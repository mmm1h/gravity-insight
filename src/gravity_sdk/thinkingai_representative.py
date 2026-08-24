"""Content-only compiler for independently authored CT02 representative Skills."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .journey_contract import journey_artifact
from .skill_contract import (
    SkillContractError,
    compile_skill_manifest,
    skill_uri,
    validate_skill_journey_parity,
)
from .skill_render import skill_package_descriptor
from .thinkingai_inventory import validate_inventory_snapshot


SET_SCHEMA_VERSION = "gravity.thinkingai-representative-set.v1"
EVAL_SCHEMA_VERSION = "gravity.thinkingai-representative-eval.v1"
_SET_SCHEMA = "thinkingai-representative-set-v1.schema.json"
_EVAL_SCHEMA = "thinkingai-representative-eval-v1.schema.json"
_SHAPE_ORDER = (
    "capability_only",
    "project_semantic",
    "deterministic_operator",
    "required_context",
    "blocked_model",
)
_SELECTION = {
    "app-device-performance-analysis": {
        "shape": "capability_only",
        "readiness": "executable",
        "blockers": [],
    },
    "analysis-metric-definition-alignment": {
        "shape": "project_semantic",
        "readiness": "executable",
        "blockers": [],
    },
    "filter-result-bias-diagnosis": {
        "shape": "deterministic_operator",
        "readiness": "executable",
        "blockers": [],
    },
    "community-hot-topic-analysis": {
        "shape": "required_context",
        "readiness": "executable",
        "blockers": [],
    },
    "game-revenue-forecast": {
        "shape": "blocked_model",
        "readiness": "blocked",
        "blockers": ["HUB_TRUSTED_PACK_MISSING", "MODEL_UNVALIDATED"],
    },
}
_EXPECTED_DEPENDENCIES = {
    "capability_only": (0, 0, 0, 0),
    "project_semantic": (1, 0, 0, 0),
    "deterministic_operator": (0, 1, 0, 0),
    "required_context": (0, 0, 0, 1),
    "blocked_model": (0, 0, 1, 0),
}
_MARKETING_NUMBER = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|x\b)|\b\d+(?:\.\d+)?\s*倍)"
)


class ThinkingAIRepresentativeError(AgentRuntimeContractError):
    """A representative package or eval violates the approved content boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_representative_set(
    records: Sequence[Mapping[str, Any]],
    source_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_inventory_snapshot(source_snapshot)
    if isinstance(records, (str, bytes)) or len(records) != len(_SELECTION):
        _invalid("THINKINGAI_REPRESENTATIVE_COVERAGE_INVALID", "exactly five records are required")
    source_items = {item["source_id"]: item for item in snapshot["items"]}
    representatives = [
        _compile_representative(record, source_items, snapshot) for record in records
    ]
    representatives.sort(key=lambda item: item["source_id"])
    artifact = {
        "artifact_kind": "thinkingai_representative_set",
        "schema_version": SET_SCHEMA_VERSION,
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "source_observation_sha256": snapshot["source_observation"]["observation_sha256"],
        "representative_count": len(representatives),
        "dependency_shapes": list(_SHAPE_ORDER),
        "representatives": representatives,
        "network_called": False,
    }
    artifact["representative_set_sha256"] = canonical_digest(artifact)
    return validate_representative_set(artifact)


def _compile_representative(
    record: Mapping[str, Any],
    source_items: Mapping[str, Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record) != {"manifest", "archive_sha256"}:
        _invalid("THINKINGAI_REPRESENTATIVE_SCHEMA_INVALID", "record shape changed")
    try:
        manifest = compile_skill_manifest(record["manifest"], label="CT02 Skill manifest")
    except SkillContractError as exc:
        raise ThinkingAIRepresentativeError(
            "THINKINGAI_REPRESENTATIVE_SCHEMA_INVALID", "Skill manifest is invalid"
        ) from exc
    source_id = manifest["skill_id"]
    decision = _SELECTION.get(source_id)
    source = source_items.get(source_id)
    if decision is None or source is None:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_COVERAGE_INVALID",
            "representative is absent from the approved selection or snapshot",
        )
    identity = skill_uri(manifest)
    if (
        source["mapping_kind"] != "future_skill"
        or source["future_skill_uri"] != identity
        or source["license_review"] != "approved"
        or source["independent_authorship"] != "required"
    ):
        _invalid(
            "THINKINGAI_REPRESENTATIVE_PROVENANCE_INVALID",
            "source mapping is not approved for independent authorship",
        )
    _validate_manifest(manifest, decision, source, snapshot)
    journey = journey_artifact(manifest["covers_journeys"][0])
    if journey is None or journey["contract"]["required_skill"] != identity:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_JOURNEY_INVALID",
            "representative Journey is unavailable or bound to another Skill",
        )
    try:
        validate_skill_journey_parity(manifest, journey["contract"])
    except SkillContractError as exc:
        raise ThinkingAIRepresentativeError(
            "THINKINGAI_REPRESENTATIVE_JOURNEY_INVALID",
            "Skill and Journey dependency contracts differ",
        ) from exc
    artifact = {
        "contract": manifest,
        "digest": canonical_digest(manifest),
        "skill_uri": identity,
    }
    package = skill_package_descriptor(artifact)
    return {
        "source_id": source_id,
        "skill_uri": identity,
        "journey_id": manifest["covers_journeys"][0],
        "dependency_shape": decision["shape"],
        "manifest_sha256": artifact["digest"],
        "package_sha256": package["package_digest"],
        "archive_sha256": record["archive_sha256"],
        "specification": manifest["specification"],
        "lifecycle": manifest["lifecycle"],
        "readiness": manifest["readiness"],
        "validation": manifest["validation"],
        "declared_blockers": copy.deepcopy(decision["blockers"]),
        "distribution_allowed": True,
        "independent_authorship": True,
        "source_content_used": False,
    }


def validate_representative_set(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value, _SET_SCHEMA, "THINKINGAI_REPRESENTATIVE_SCHEMA_INVALID", "representative set"
    )
    _digest(selected, "representative_set_sha256", "THINKINGAI_REPRESENTATIVE_DIGEST_INVALID")
    representatives = selected["representatives"]
    source_ids = [item["source_id"] for item in representatives]
    if source_ids != sorted(source_ids) or set(source_ids) != set(_SELECTION):
        _invalid(
            "THINKINGAI_REPRESENTATIVE_COVERAGE_INVALID",
            "representative identities are not the approved closed set",
        )
    if selected["representative_count"] != len(representatives):
        _invalid("THINKINGAI_REPRESENTATIVE_COVERAGE_INVALID", "count is not derived")
    if selected["dependency_shapes"] != list(_SHAPE_ORDER):
        _invalid("THINKINGAI_REPRESENTATIVE_COVERAGE_INVALID", "shape coverage changed")
    for item in representatives:
        decision = _SELECTION[item["source_id"]]
        if (
            item["dependency_shape"] != decision["shape"]
            or item["readiness"] != decision["readiness"]
            or item["declared_blockers"] != decision["blockers"]
            or item["distribution_allowed"] is not True
            or item["source_content_used"] is not False
        ):
            _invalid(
                "THINKINGAI_REPRESENTATIVE_STATE_INVALID",
                "representative readiness or authorship decision changed",
            )
    return selected


def compile_representative_eval(
    representative_set: Mapping[str, Any],
) -> dict[str, Any]:
    selected = validate_representative_set(representative_set)
    entries = {item["source_id"]: item for item in selected["representatives"]}
    cases = _eval_cases(entries)
    artifact = {
        "artifact_kind": "thinkingai_representative_eval",
        "schema_version": EVAL_SCHEMA_VERSION,
        "suite_id": "thinkingai-representative-regression-v1",
        "representative_set_sha256": selected["representative_set_sha256"],
        "case_count": len(cases),
        "scenarios": [
            "happy", "empty", "partial", "gap", "invalid", "claim_boundary",
            "prompt_injection", "marketing_leakage",
        ],
        "cases": cases,
        "network_called": False,
    }
    artifact["eval_sha256"] = canonical_digest(artifact)
    return validate_representative_eval(artifact)


def validate_representative_eval(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value, _EVAL_SCHEMA, "THINKINGAI_REPRESENTATIVE_EVAL_INVALID", "representative eval"
    )
    _digest(selected, "eval_sha256", "THINKINGAI_REPRESENTATIVE_EVAL_INVALID")
    cases = selected["cases"]
    if selected["case_count"] != len(cases):
        _invalid("THINKINGAI_REPRESENTATIVE_EVAL_INVALID", "eval count is not derived")
    case_ids = [item["case_id"] for item in cases]
    scenarios = [item["scenario"] for item in cases]
    if case_ids != sorted(case_ids) or len(case_ids) != len(set(case_ids)):
        _invalid("THINKINGAI_REPRESENTATIVE_EVAL_INVALID", "eval cases are not unique and sorted")
    if set(scenarios) != set(selected["scenarios"]) or len(scenarios) != len(set(scenarios)):
        _invalid("THINKINGAI_REPRESENTATIVE_EVAL_INVALID", "eval scenarios are incomplete")
    for case in cases:
        _validate_eval_case(case)
    return selected


def _validate_eval_case(case: Mapping[str, Any]) -> None:
    outcome = case["expected_outcome"]
    status = case["result_status"]
    if outcome in {"blocked", "reject"} and case["allowed_claims"]:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_EVAL_INVALID",
            "blocked and rejected eval cases cannot allow claims",
        )
    if outcome == "pass" and case["reason_codes"]:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_EVAL_INVALID",
            "passing eval cases cannot carry failure reasons",
        )
    expected_statuses = {
        "pass": {"success", "empty", "partial"},
        "blocked": {"blocked"},
        "reject": {"invalid"},
    }
    if status not in expected_statuses[outcome]:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_EVAL_INVALID",
            "eval outcome and result status disagree",
        )
    if status in {"empty", "partial", "blocked", "invalid"} and case["allowed_claims"]:
        _invalid(
            "THINKINGAI_REPRESENTATIVE_EVAL_INVALID",
            "non-success eval cases cannot allow claims",
        )


def _validate_manifest(
    manifest: Mapping[str, Any],
    decision: Mapping[str, Any],
    source: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    shape = decision["shape"]
    dependency_counts = (
        len(manifest["semantic_dependencies"]),
        len(manifest["operator_dependencies"]),
        len(manifest["model_dependencies"]),
        len(manifest["context_dependencies"]["required"]),
    )
    if len(manifest["covers_journeys"]) != 1 or len(manifest["capability_dependencies"]) != 1:
        _invalid("THINKINGAI_REPRESENTATIVE_DEPENDENCY_INVALID", "one Journey and Capability are required")
    if dependency_counts != _EXPECTED_DEPENDENCIES[shape]:
        _invalid("THINKINGAI_REPRESENTATIVE_DEPENDENCY_INVALID", "dependency shape changed")
    provenance = manifest["provenance"]
    if provenance != {
        "source_kind": "independent",
        "source_ref": f"thinkingai-source://{manifest['skill_id']}",
        "source_revision": snapshot["source_observation"]["observation_sha256"],
        "authorship": "independently_authored",
        "license_review": "approved_internal",
    }:
        _invalid("THINKINGAI_REPRESENTATIVE_PROVENANCE_INVALID", "provenance changed")
    if manifest["readiness"] != decision["readiness"] or manifest["validation"] != "validated":
        _invalid("THINKINGAI_REPRESENTATIVE_STATE_INVALID", "declared state changed")
    text = "\n".join(
        [
            manifest["summary"], manifest["description"], manifest["guide"]["title"],
            manifest["guide"]["applicability"], manifest["guide"]["context_boundary"],
            *manifest["guide"]["steps"],
        ]
    )
    if source["source_title"].casefold() in text.casefold() or _MARKETING_NUMBER.search(text):
        _invalid(
            "THINKINGAI_REPRESENTATIVE_CONTENT_LEAKAGE",
            "independent content contains source title or marketing-number syntax",
        )


def _eval_cases(entries: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    def case(source_id: str, case_id: str, scenario: str, outcome: str, status: str,
             reasons: list[str], allowed: list[str], forbidden: list[str]) -> dict[str, Any]:
        item = entries[source_id]
        return {
            "case_id": case_id,
            "skill_uri": item["skill_uri"],
            "journey_id": item["journey_id"],
            "scenario": scenario,
            "expected_outcome": outcome,
            "result_status": status,
            "reason_codes": reasons,
            "allowed_claims": allowed,
            "forbidden_claims": forbidden,
            "network_called": False,
        }

    cases = [
        case("community-hot-topic-analysis", "context-prompt-injection", "prompt_injection", "pass", "success", [], ["returned-event-metric-observation"], ["causality", "instruction-authority"]),
        case("app-device-performance-analysis", "device-empty", "empty", "pass", "empty", [], [], ["complete-device-population", "causality"]),
        case("app-device-performance-analysis", "device-happy", "happy", "pass", "success", [], ["returned-event-metric-observation"], ["complete-device-population", "causality"]),
        case("filter-result-bias-diagnosis", "filter-partial", "partial", "pass", "partial", [], [], ["complete-population", "causality", "unreturned-values"]),
        case("analysis-metric-definition-alignment", "metric-semantic-gap", "gap", "blocked", "blocked", ["SEMANTIC_DEFINITION_MISSING"], [], ["inferred-metric-definition", "causality"]),
        case("game-revenue-forecast", "model-claim-boundary", "claim_boundary", "blocked", "blocked", ["HUB_TRUSTED_PACK_MISSING", "MODEL_UNVALIDATED"], [], ["unvalidated-revenue-forecast", "invented-confidence", "causality"]),
        case("app-device-performance-analysis", "package-marketing-leakage", "marketing_leakage", "pass", "success", [], [], ["marketing-effect-claim"]),
        case("app-device-performance-analysis", "tampered-package-invalid", "invalid", "reject", "invalid", ["HUB_CAS_TAMPERED"], [], ["all-business-claims"]),
    ]
    return sorted(cases, key=lambda item: item["case_id"])


def _schema_copy(value: Mapping[str, Any], schema: str, code: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(code, f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise ThinkingAIRepresentativeError(code, f"{label} is invalid") from exc
    return selected


def _digest(value: dict[str, Any], field: str, code: str) -> None:
    digest = value.pop(field)
    expected = canonical_digest(value)
    value[field] = digest
    if digest != expected:
        _invalid(code, "canonical digest changed")


def _invalid(reason_code: str, message: str) -> None:
    raise ThinkingAIRepresentativeError(reason_code, message)


__all__ = [
    "EVAL_SCHEMA_VERSION",
    "SET_SCHEMA_VERSION",
    "ThinkingAIRepresentativeError",
    "compile_representative_eval",
    "compile_representative_set",
    "validate_representative_eval",
    "validate_representative_set",
]
