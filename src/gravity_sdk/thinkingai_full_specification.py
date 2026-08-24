"""Coverage matrix for the complete independent ThinkingAI content track."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import canonical_digest
from .skill_contract import compile_skill_manifest, skill_uri
from .thinkingai_full_shared import (
    ThinkingAIFullSpecificationError,
    invalid,
    schema_copy,
    verify_digest,
)
from .thinkingai_full_source import (
    SOURCE_SCHEMA_VERSION,
    compile_full_source,
    full_source_manifests,
    validate_new_manifest,
)
from .thinkingai_inventory import validate_inventory_snapshot
from .thinkingai_representative import validate_representative_set


SPECIFICATION_SCHEMA_VERSION = "gravity.thinkingai-full-specification.v1"
_SPECIFICATION_SCHEMA = "thinkingai-full-specification-v1.schema.json"
_DEPENDENCY_FIELDS = (
    "covers_journeys",
    "capability_dependencies",
    "semantic_dependencies",
    "operator_dependencies",
    "model_dependencies",
    "context_dependencies",
    "requirements",
    "request_budget",
)
_REPRESENTATIVE_NEXT_EVIDENCE = {
    "analysis-metric-definition-alignment": [
        "Provide an exact project Semantic Definition and App binding, then rerun the existing Journey evaluation."
    ],
    "app-device-performance-analysis": [
        "Install the exact project lock and validate the declared event, metric, grouping, Trust and data-quality inputs."
    ],
    "community-hot-topic-analysis": [
        "Provide a bounded project community Context requirement and rerun entity, time and authority alignment."
    ],
    "filter-result-bias-diagnosis": [
        "Install the exact project lock and rerun the registered Operator golden and Journey dependency gates."
    ],
    "game-revenue-forecast": [
        "Approve an exact trusted Model artifact with lineage, evaluation, expiry and safe horizon before any forecast claim."
    ],
}


def compile_full_specification(
    source_value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
    hub_index: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_inventory_snapshot(source_snapshot)
    representatives = validate_representative_set(representative_set)
    source = compile_full_source(source_value, snapshot, representatives)
    skills = _compiled_skills(hub_index, snapshot)
    items = _build_items(source, snapshot, representatives, skills)
    counts = _derived_counts(items)
    artifact = {
        "artifact_kind": "thinkingai_full_specification",
        "schema_version": SPECIFICATION_SCHEMA_VERSION,
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "source_observation_sha256": snapshot["source_observation"][
            "observation_sha256"
        ],
        "representative_set_sha256": representatives[
            "representative_set_sha256"
        ],
        **counts,
        "items": items,
        "network_called": False,
    }
    artifact["specification_sha256"] = canonical_digest(artifact)
    return validate_full_specification(artifact)


def validate_full_specification(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = schema_copy(
        value,
        _SPECIFICATION_SCHEMA,
        "THINKINGAI_FULL_SPECIFICATION_INVALID",
        "full specification",
    )
    verify_digest(
        selected,
        "specification_sha256",
        "THINKINGAI_FULL_DIGEST_INVALID",
    )
    items = selected["items"]
    source_ids = [item["source_id"] for item in items]
    if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
        invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "full specification identities are not sorted and unique",
        )
    counts = _derived_counts(items)
    if any(selected[field] != count for field, count in counts.items()):
        invalid("THINKINGAI_FULL_COUNT_INVALID", "counts are not derived")
    for item in items:
        _validate_item(item)
    return selected


def _compiled_skills(
    hub_index: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> Mapping[str, Any]:
    skills = hub_index.get("skills") if isinstance(hub_index, Mapping) else None
    if not isinstance(skills, Mapping):
        invalid("THINKINGAI_FULL_HUB_INVALID", "compiled Hub index is required")
    expected = {
        item["future_skill_uri"]
        for item in snapshot["items"]
        if item["mapping_kind"] == "future_skill"
    }
    if set(skills) != expected:
        invalid(
            "THINKINGAI_FULL_HUB_INVALID",
            "full Hub index does not exactly contain the snapshot Skill set",
        )
    return skills


def _build_items(
    source: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    representatives: Mapping[str, Any],
    skills: Mapping[str, Any],
) -> list[dict[str, Any]]:
    definitions = {item["source_id"]: item for item in source["skills"]}
    alternatives = {item["source_id"]: item for item in source["alternatives"]}
    representative_items = {
        item["source_id"]: item for item in representatives["representatives"]
    }
    items = []
    for source_item in snapshot["items"]:
        source_id = source_item["source_id"]
        if source_item["mapping_kind"] == "future_skill":
            item = _skill_specification_item(
                source_item,
                skills[source_item["future_skill_uri"]],
                definitions.get(source_id),
                representative_items.get(source_id),
                snapshot,
            )
        else:
            item = _alternative_item(source_item, alternatives[source_id])
        items.append(item)
    return sorted(items, key=lambda item: item["source_id"])


def _derived_counts(items: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "coverage_count": len(items),
        "specified_count": 0,
        "skill_specification_count": 0,
        "safe_alternative_count": 0,
        "executable_count": 0,
        "blocked_count": 0,
        "validated_count": 0,
        "unvalidated_count": 0,
    }
    for item in items:
        counts["specified_count"] += item["specification"] == "specified"
        skill = item["skill"]
        if skill is None:
            counts["safe_alternative_count"] += 1
            continue
        counts["skill_specification_count"] += 1
        counts["executable_count"] += skill["readiness"] == "executable"
        counts["blocked_count"] += skill["readiness"] == "blocked"
        counts["validated_count"] += skill["validation"] == "validated"
        counts["unvalidated_count"] += skill["validation"] == "unvalidated"
    return counts


def _validate_item(item: Mapping[str, Any]) -> None:
    skill = item["skill"]
    alternative = item["alternative"]
    if (skill is None) == (alternative is None):
        invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "each item must select exactly one Skill or safe alternative",
        )
    if skill is not None:
        checks = (
            item["mapping_kind"] == "skill_specification",
            item["distribution_allowed"] is True,
            item["independent_authorship"] is True,
            (skill["readiness"] == "executable")
            == (item["blocker_reason_codes"] == []),
        )
        if not all(checks):
            invalid("THINKINGAI_FULL_STATE_INVALID", "Skill state fields disagree")
        return
    checks = (
        item["mapping_kind"] == "safe_alternative",
        item["distribution_allowed"] is False,
        item["independent_authorship"] is False,
        item["blocker_reason_codes"] == [alternative["reason_code"]],
    )
    if not all(checks):
        invalid(
            "THINKINGAI_FULL_ALTERNATIVE_INVALID",
            "safe alternative state disagrees with its reason",
        )


def _skill_specification_item(
    source_item: Mapping[str, Any],
    entry: Mapping[str, Any],
    definition: Mapping[str, Any] | None,
    representative: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = compile_skill_manifest(entry["manifest"], label="CT03 full Hub Skill")
    blockers, next_evidence = _skill_state(
        source_item, entry, manifest, definition, representative, snapshot
    )
    dependencies = {field: copy.deepcopy(manifest[field]) for field in _DEPENDENCY_FIELDS}
    return {
        "source_id": source_item["source_id"],
        "source_content_sha256": source_item["source_content_sha256"],
        "gravity_taxonomy_ids": copy.deepcopy(source_item["gravity_taxonomy_ids"]),
        "mapping_kind": "skill_specification",
        "license_review": source_item["license_review"],
        "specification": "specified",
        "blocker_reason_codes": sorted(blockers),
        "next_evidence": sorted(next_evidence),
        "distribution_allowed": True,
        "independent_authorship": True,
        "source_content_used": False,
        "skill": {
            "skill_uri": skill_uri(manifest),
            "manifest_sha256": canonical_digest(manifest),
            "package_sha256": entry["package"]["package_digest"],
            "archive_sha256": entry["archive"]["sha256"],
            "artifact_path": entry["archive"]["path"],
            "specification": manifest["specification"],
            "lifecycle": manifest["lifecycle"],
            "readiness": manifest["readiness"],
            "validation": manifest["validation"],
            "dependency_contract_sha256": canonical_digest(dependencies),
        },
        "alternative": None,
    }


def _skill_state(
    source_item: Mapping[str, Any],
    entry: Mapping[str, Any],
    manifest: Mapping[str, Any],
    definition: Mapping[str, Any] | None,
    representative: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    if representative is None:
        if definition is None:
            invalid("THINKINGAI_FULL_COVERAGE_INVALID", "new definition is missing")
        validate_new_manifest(manifest, definition, source_item, snapshot)
        return (
            copy.deepcopy(definition["blocker_reason_codes"]),
            copy.deepcopy(definition["next_evidence"]),
        )
    if definition is not None:
        invalid("THINKINGAI_FULL_COVERAGE_INVALID", "representative was redefined")
    _validate_representative_entry(representative, manifest, entry)
    return (
        copy.deepcopy(representative["declared_blockers"]),
        copy.deepcopy(_REPRESENTATIVE_NEXT_EVIDENCE[source_item["source_id"]]),
    )


def _validate_representative_entry(
    representative: Mapping[str, Any],
    manifest: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> None:
    checks = (
        representative["skill_uri"] == skill_uri(manifest),
        representative["manifest_sha256"] == canonical_digest(manifest),
        representative["package_sha256"] == entry["package"]["package_digest"],
        representative["archive_sha256"] == entry["archive"]["sha256"],
    )
    if not all(checks):
        invalid(
            "THINKINGAI_FULL_REPRESENTATIVE_DRIFT",
            "CT02 representative package changed in the full Hub",
        )


def _alternative_item(
    source_item: Mapping[str, Any], alternative: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "source_id": source_item["source_id"],
        "source_content_sha256": source_item["source_content_sha256"],
        "gravity_taxonomy_ids": copy.deepcopy(source_item["gravity_taxonomy_ids"]),
        "mapping_kind": "safe_alternative",
        "license_review": source_item["license_review"],
        "specification": "specified",
        "blocker_reason_codes": [alternative["reason_code"]],
        "next_evidence": sorted(copy.deepcopy(alternative["next_evidence"])),
        "distribution_allowed": False,
        "independent_authorship": False,
        "source_content_used": False,
        "skill": None,
        "alternative": {
            "alternative_kind": alternative["alternative_kind"],
            "alternative_ref": alternative["alternative_ref"],
            "guidance": alternative["guidance"],
            "reason_code": alternative["reason_code"],
        },
    }


__all__ = [
    "SOURCE_SCHEMA_VERSION",
    "SPECIFICATION_SCHEMA_VERSION",
    "ThinkingAIFullSpecificationError",
    "compile_full_source",
    "compile_full_specification",
    "full_source_manifests",
    "validate_full_specification",
]
