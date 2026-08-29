"""Independent CT03 source definitions compiled into standard Skill manifests."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .skill_contract import SkillContractError, compile_skill_manifest, skill_uri
from .thinkingai_full_shared import (
    ThinkingAIFullSpecificationError,
    invalid,
    schema_copy,
    validate_independent_text,
)
from .thinkingai_inventory import validate_inventory_snapshot
from .thinkingai_representative import validate_representative_set


SOURCE_SCHEMA_VERSION = "gravity.thinkingai-full-source.v1"
_SOURCE_SCHEMA = "thinkingai-full-source-v1.schema.json"
_CAPABILITY_PROFILES = {
    "none": {"dependencies": [], "budget": (0, 0, 0), "data_quality": "unknown"},
    "event": {
        "dependencies": [
            {
                "identity_kind": "product",
                "selector": "analysis.query.spec:event",
                "contract_version": "1",
                "minimum_trust": "stable",
                "completeness": "unknown",
                "data_quality": "pass",
            }
        ],
        "budget": (1, 1, 2),
        "data_quality": "pass",
    },
    "anomaly": {
        "dependencies": [
            {
                "identity_kind": "product",
                "selector": "metric-anomaly-localization@1",
                "contract_version": "1",
                "minimum_trust": "stable",
                "completeness": "unknown",
                "data_quality": "pass",
            }
        ],
        "budget": (2, 3, 3),
        "data_quality": "pass",
    },
    "pulse": {
        "dependencies": [
            {
                "identity_kind": "composite",
                "selector": "composite:business_pulse",
                "contract_version": "1",
                "minimum_trust": "stable",
                "completeness": "unknown",
                "data_quality": "pass",
            }
        ],
        "budget": (2, 3, 3),
        "data_quality": "pass",
    },
}


def compile_full_source(
    value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
) -> dict[str, Any]:
    source = schema_copy(
        value,
        _SOURCE_SCHEMA,
        "THINKINGAI_FULL_SOURCE_INVALID",
        "full specification source",
    )
    snapshot = validate_inventory_snapshot(source_snapshot)
    representatives = validate_representative_set(representative_set)
    if source["source_snapshot_sha256"] != snapshot["snapshot_sha256"]:
        invalid("THINKINGAI_FULL_SOURCE_INVALID", "source snapshot binding changed")
    if (
        representatives["source_snapshot_sha256"] != snapshot["snapshot_sha256"]
        or representatives["source_observation_sha256"]
        != snapshot["source_observation"]["observation_sha256"]
    ):
        invalid(
            "THINKINGAI_FULL_REPRESENTATIVE_DRIFT",
            "representative set is not bound to the source snapshot",
        )
    source_items = {item["source_id"]: item for item in snapshot["items"]}
    _validate_coverage(source, snapshot, representatives)
    for definition in source["skills"]:
        manifest = build_manifest(definition, snapshot)
        validate_new_manifest(
            manifest, definition, source_items[definition["source_id"]], snapshot
        )
    for alternative in source["alternatives"]:
        _validate_alternative(alternative, source_items[alternative["source_id"]])
    return source


def full_source_manifests(
    value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    source = compile_full_source(value, source_snapshot, representative_set)
    snapshot = validate_inventory_snapshot(source_snapshot)
    return tuple(build_manifest(item, snapshot) for item in source["skills"])


def build_manifest(
    definition: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    profile = _CAPABILITY_PROFILES[definition["capability_profile"]]
    minimum, maximum, discovery = profile["budget"]
    capabilities = copy.deepcopy(profile["dependencies"])
    manifest = {
        "artifact_kind": "skill",
        "schema_version": "gravity.skill.v1",
        "namespace": "gravity.game",
        "skill_id": definition["source_id"],
        "version": "1.0.0",
        "specification": "specified",
        "lifecycle": "reviewed",
        "readiness": "blocked",
        "validation": "unvalidated",
        "summary": definition["summary"],
        "description": definition["description"],
        "runtime_requires": ">=0.3,<0.4",
        "covers_journeys": [],
        "capability_dependencies": capabilities,
        "semantic_dependencies": sorted(definition["semantic_dependencies"]),
        "operator_dependencies": sorted(definition["operator_dependencies"]),
        "model_dependencies": sorted(definition["model_dependencies"]),
        "context_dependencies": {
            "required": sorted(definition["context_dependencies"]),
            "optional": [],
        },
        "routing": {
            "product_hints": sorted(item["selector"] for item in capabilities),
            "host_catalog_required": True,
            "recognizer_fallback_allowed": bool(capabilities),
        },
        "requirements": {
            "completeness": "unknown",
            "data_quality": profile["data_quality"],
        },
        "claim_policy": {
            "allowed": [],
            "forbidden": sorted(definition["forbidden_claims"]),
            "forbidden_without_context": [],
        },
        "effects": ["read"],
        "request_budget": {
            "known_requests_min": minimum,
            "known_requests_max": maximum,
            "unknown_discovery_max": discovery,
            "runtime_additional_requests": 0,
        },
        "output_schema": "gravity.analysis-result.v1",
        "provenance": {
            "source_kind": "independent",
            "source_ref": f"thinkingai-source://{definition['source_id']}",
            "source_revision": snapshot["source_observation"]["observation_sha256"],
            "authorship": "independently_authored",
            "license_review": "approved_internal",
        },
        "guide": {
            "title": definition["title"],
            "applicability": definition["applicability"],
            "steps": copy.deepcopy(definition["steps"]),
            "context_boundary": definition["context_boundary"],
        },
    }
    try:
        return compile_skill_manifest(
            manifest, label=f"CT03 Skill source {definition['source_id']}"
        )
    except SkillContractError as exc:
        raise ThinkingAIFullSpecificationError(
            "THINKINGAI_FULL_SKILL_INVALID", "generated Skill manifest is invalid"
        ) from exc


def validate_new_manifest(
    manifest: Mapping[str, Any],
    definition: Mapping[str, Any],
    source_item: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    blockers = set(definition["blocker_reason_codes"])
    required = _required_blockers(manifest, definition["capability_profile"])
    if not required.issubset(blockers):
        invalid(
            "THINKINGAI_FULL_DEPENDENCY_INVALID",
            "declared dependencies are not represented by blocker reasons",
        )
    _validate_source_mapping(manifest, source_item, snapshot)
    _validate_new_state(manifest)
    validate_independent_text(human_text(manifest), source_item["source_title"])


def human_text(manifest: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            manifest["summary"],
            manifest["description"],
            manifest["guide"]["title"],
            manifest["guide"]["applicability"],
            manifest["guide"]["context_boundary"],
            *manifest["guide"]["steps"],
        ]
    )


def _validate_coverage(
    source: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    representatives: Mapping[str, Any],
) -> None:
    representative_ids = {
        item["source_id"] for item in representatives["representatives"]
    }
    expected_skills = {
        item["source_id"]
        for item in snapshot["items"]
        if item["mapping_kind"] == "future_skill"
    } - representative_ids
    expected_alternatives = {
        item["source_id"]
        for item in snapshot["items"]
        if item["mapping_kind"] == "out_of_scope_alternative"
    }
    skill_ids = _sorted_unique_ids(source["skills"], "Skill source")
    alternative_ids = _sorted_unique_ids(source["alternatives"], "alternative source")
    if set(skill_ids) != expected_skills or set(alternative_ids) != expected_alternatives:
        invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "full source does not exactly cover Skills and alternatives",
        )


def _validate_alternative(
    alternative: Mapping[str, Any], source_item: Mapping[str, Any]
) -> None:
    checks = (
        source_item["mapping_kind"] == "out_of_scope_alternative",
        source_item["future_skill_uri"] is None,
        source_item["alternative_reason_code"] == alternative["reason_code"],
    )
    if not all(checks):
        invalid(
            "THINKINGAI_FULL_ALTERNATIVE_INVALID",
            "safe alternative conflicts with the CT01 mapping decision",
        )
    if (
        alternative["reason_code"] == "THINKINGAI_VENDOR_SPECIFIC_OPERATION"
        and source_item["license_review"] != "blocked"
    ):
        invalid("THINKINGAI_FULL_ALTERNATIVE_INVALID", "vendor license state changed")
    if (
        alternative["reason_code"] == "AUTOMATIC_TEXT_TO_SQL_OUT_OF_SCOPE"
        and alternative["alternative_kind"] != "registered_sql_or_explorer"
    ):
        invalid("THINKINGAI_FULL_ALTERNATIVE_INVALID", "SQL alternative changed")
    validate_independent_text(
        "\n".join([alternative["guidance"], *alternative["next_evidence"]]),
        source_item["source_title"],
    )


def _required_blockers(
    manifest: Mapping[str, Any], capability_profile: str
) -> set[str]:
    required = set()
    mappings = (
        (manifest["semantic_dependencies"], "SEMANTIC_DEFINITION_MISSING"),
        (manifest["operator_dependencies"], "OPERATOR_UNAVAILABLE"),
        (manifest["context_dependencies"]["required"], "CONTEXT_REQUIRED_MISSING"),
    )
    required.update(reason for values, reason in mappings if values)
    if manifest["model_dependencies"]:
        required.update({"HUB_TRUSTED_PACK_MISSING", "MODEL_UNVALIDATED"})
    if capability_profile == "none":
        required.add("CAPABILITY_TRUST_CONTRACT_MISSING")
    return required


def _validate_source_mapping(
    manifest: Mapping[str, Any],
    source_item: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    checks = (
        source_item["mapping_kind"] == "future_skill",
        source_item["future_skill_uri"] == skill_uri(manifest),
        source_item["license_review"] == "approved",
        source_item["independent_authorship"] == "required",
        manifest["provenance"]["source_revision"]
        == snapshot["source_observation"]["observation_sha256"],
    )
    if not all(checks):
        invalid("THINKINGAI_FULL_STATE_INVALID", "Skill source mapping changed")


def _validate_new_state(manifest: Mapping[str, Any]) -> None:
    checks = (
        manifest["covers_journeys"] == [],
        manifest["readiness"] == "blocked",
        manifest["validation"] == "unvalidated",
        manifest["claim_policy"]["allowed"] == [],
        manifest["effects"] == ["read"],
    )
    if not all(checks):
        invalid("THINKINGAI_FULL_STATE_INVALID", "new Skill state changed")


def _sorted_unique_ids(items: Sequence[Mapping[str, Any]], label: str) -> list[str]:
    identities = [item["source_id"] for item in items]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            f"{label} identities are not sorted and unique",
        )
    return identities


__all__ = [
    "SOURCE_SCHEMA_VERSION",
    "build_manifest",
    "compile_full_source",
    "full_source_manifests",
    "human_text",
    "validate_new_manifest",
]
