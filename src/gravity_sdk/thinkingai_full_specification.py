"""Snapshot-bound compiler for the complete independent ThinkingAI content track."""

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
from .skill_contract import SkillContractError, compile_skill_manifest, skill_uri
from .thinkingai_inventory import validate_inventory_diff, validate_inventory_snapshot
from .thinkingai_representative import (
    validate_representative_eval,
    validate_representative_set,
)


SOURCE_SCHEMA_VERSION = "gravity.thinkingai-full-source.v1"
SPECIFICATION_SCHEMA_VERSION = "gravity.thinkingai-full-specification.v1"
EVAL_SCHEMA_VERSION = "gravity.thinkingai-full-eval.v1"
_SOURCE_SCHEMA = "thinkingai-full-source-v1.schema.json"
_SPECIFICATION_SCHEMA = "thinkingai-full-specification-v1.schema.json"
_EVAL_SCHEMA = "thinkingai-full-eval-v1.schema.json"
_MARKETING_NUMBER = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|x\b)|\b\d+(?:\.\d+)?\s*倍)"
)
_INSTRUCTION_MARKERS = (
    "ignore previous instructions",
    "system message",
    "developer message",
    "run this command",
)
_CAPABILITY_PROFILES = {
    "none": {
        "dependencies": [],
        "budget": (0, 0, 0),
        "data_quality": "unknown",
    },
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


class ThinkingAIFullSpecificationError(AgentRuntimeContractError):
    """A full content specification violates the approved CT03 boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_full_source(
    value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
) -> dict[str, Any]:
    source = _schema_copy(
        value,
        _SOURCE_SCHEMA,
        "THINKINGAI_FULL_SOURCE_INVALID",
        "full specification source",
    )
    snapshot = validate_inventory_snapshot(source_snapshot)
    representatives = validate_representative_set(representative_set)
    if source["source_snapshot_sha256"] != snapshot["snapshot_sha256"]:
        _invalid("THINKINGAI_FULL_SOURCE_INVALID", "source snapshot binding changed")

    source_items = {item["source_id"]: item for item in snapshot["items"]}
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
        _invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "full source does not exactly cover non-representative Skills and alternatives",
        )

    for definition in source["skills"]:
        source_item = source_items[definition["source_id"]]
        manifest = _manifest(definition, snapshot)
        _validate_new_manifest(manifest, definition, source_item, snapshot)
    for alternative in source["alternatives"]:
        source_item = source_items[alternative["source_id"]]
        if (
            source_item["mapping_kind"] != "out_of_scope_alternative"
            or source_item["future_skill_uri"] is not None
            or source_item["alternative_reason_code"] != alternative["reason_code"]
            or alternative["reason_code"] == "THINKINGAI_VENDOR_SPECIFIC_OPERATION"
            and source_item["license_review"] != "blocked"
            or alternative["reason_code"] == "AUTOMATIC_TEXT_TO_SQL_OUT_OF_SCOPE"
            and alternative["alternative_kind"] != "registered_sql_or_explorer"
        ):
            _invalid(
                "THINKINGAI_FULL_ALTERNATIVE_INVALID",
                "safe alternative conflicts with the CT01 mapping decision",
            )
        _validate_independent_text(
            "\n".join([alternative["guidance"], *alternative["next_evidence"]]),
            source_item["source_title"],
        )
    return source


def full_source_manifests(
    value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    source = compile_full_source(value, source_snapshot, representative_set)
    snapshot = validate_inventory_snapshot(source_snapshot)
    return tuple(_manifest(item, snapshot) for item in source["skills"])


def compile_full_specification(
    source_value: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    representative_set: Mapping[str, Any],
    hub_index: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = validate_inventory_snapshot(source_snapshot)
    representatives = validate_representative_set(representative_set)
    source = compile_full_source(source_value, snapshot, representatives)
    definitions = {item["source_id"]: item for item in source["skills"]}
    alternatives = {item["source_id"]: item for item in source["alternatives"]}
    representative_items = {
        item["source_id"]: item for item in representatives["representatives"]
    }
    skills = hub_index.get("skills") if isinstance(hub_index, Mapping) else None
    if not isinstance(skills, Mapping):
        _invalid("THINKINGAI_FULL_HUB_INVALID", "compiled Hub index is required")
    expected_uris = {
        item["future_skill_uri"]
        for item in snapshot["items"]
        if item["mapping_kind"] == "future_skill"
    }
    if set(skills) != expected_uris:
        _invalid(
            "THINKINGAI_FULL_HUB_INVALID",
            "full Hub index does not exactly contain the snapshot Skill set",
        )

    items = []
    for source_item in snapshot["items"]:
        source_id = source_item["source_id"]
        if source_item["mapping_kind"] == "future_skill":
            items.append(
                _skill_specification_item(
                    source_item,
                    skills[source_item["future_skill_uri"]],
                    definitions.get(source_id),
                    representative_items.get(source_id),
                    snapshot,
                )
            )
        else:
            items.append(_alternative_item(source_item, alternatives[source_id]))
    items.sort(key=lambda item: item["source_id"])
    skill_items = [item for item in items if item["skill"] is not None]
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
        "coverage_count": len(items),
        "specified_count": sum(item["specification"] == "specified" for item in items),
        "skill_specification_count": len(skill_items),
        "safe_alternative_count": sum(item["alternative"] is not None for item in items),
        "executable_count": sum(
            item["skill"]["readiness"] == "executable" for item in skill_items
        ),
        "blocked_count": sum(
            item["skill"]["readiness"] == "blocked" for item in skill_items
        ),
        "validated_count": sum(
            item["skill"]["validation"] == "validated" for item in skill_items
        ),
        "unvalidated_count": sum(
            item["skill"]["validation"] == "unvalidated" for item in skill_items
        ),
        "items": items,
        "network_called": False,
    }
    artifact["specification_sha256"] = canonical_digest(artifact)
    return validate_full_specification(artifact)


def validate_full_specification(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value,
        _SPECIFICATION_SCHEMA,
        "THINKINGAI_FULL_SPECIFICATION_INVALID",
        "full specification",
    )
    _digest(
        selected,
        "specification_sha256",
        "THINKINGAI_FULL_DIGEST_INVALID",
    )
    items = selected["items"]
    source_ids = [item["source_id"] for item in items]
    if source_ids != sorted(source_ids) or len(source_ids) != len(set(source_ids)):
        _invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "full specification identities are not sorted and unique",
        )
    skill_items = [item for item in items if item["skill"] is not None]
    alternative_items = [item for item in items if item["alternative"] is not None]
    counts = {
        "coverage_count": len(items),
        "specified_count": sum(item["specification"] == "specified" for item in items),
        "skill_specification_count": len(skill_items),
        "safe_alternative_count": len(alternative_items),
        "executable_count": sum(
            item["skill"]["readiness"] == "executable" for item in skill_items
        ),
        "blocked_count": sum(
            item["skill"]["readiness"] == "blocked" for item in skill_items
        ),
        "validated_count": sum(
            item["skill"]["validation"] == "validated" for item in skill_items
        ),
        "unvalidated_count": sum(
            item["skill"]["validation"] == "unvalidated" for item in skill_items
        ),
    }
    if any(selected[field] != count for field, count in counts.items()):
        _invalid("THINKINGAI_FULL_COUNT_INVALID", "full specification counts are not derived")
    for item in items:
        skill = item["skill"]
        alternative = item["alternative"]
        if (skill is None) == (alternative is None):
            _invalid(
                "THINKINGAI_FULL_COVERAGE_INVALID",
                "each item must select exactly one Skill or safe alternative",
            )
        if skill is not None:
            if (
                item["mapping_kind"] != "skill_specification"
                or item["distribution_allowed"] is not True
                or item["independent_authorship"] is not True
                or (skill["readiness"] == "executable")
                != (item["blocker_reason_codes"] == [])
            ):
                _invalid(
                    "THINKINGAI_FULL_STATE_INVALID",
                    "Skill state, distribution or blocker fields disagree",
                )
        elif (
            item["mapping_kind"] != "safe_alternative"
            or item["distribution_allowed"] is not False
            or item["independent_authorship"] is not False
            or item["blocker_reason_codes"] != [alternative["reason_code"]]
        ):
            _invalid(
                "THINKINGAI_FULL_ALTERNATIVE_INVALID",
                "safe alternative state disagrees with its reason",
            )
    return selected


def compile_full_eval(
    full_specification: Mapping[str, Any],
    representative_eval: Mapping[str, Any],
) -> dict[str, Any]:
    specification = validate_full_specification(full_specification)
    representative = validate_representative_eval(representative_eval)
    items = {item["source_id"]: item for item in specification["items"]}
    blockers = sorted(
        {
            reason
            for item in specification["items"]
            for reason in item["blocker_reason_codes"]
        }
    )
    cases = []
    control = next(
        item
        for item in specification["items"]
        if item["skill"] is not None
        and item["skill"]["readiness"] == "executable"
        and item["skill"]["validation"] == "validated"
    )
    cases.append(
        _eval_case(
            "supported-representative-control",
            control["source_id"],
            "supported_control",
            "pass",
            "success",
            [],
            ["returned-event-metric-observation"],
            ["causality"],
        )
    )
    for reason in blockers:
        item = next(
            selected
            for selected in specification["items"]
            if reason in selected["blocker_reason_codes"]
        )
        alternative = item["alternative"] is not None
        cases.append(
            _eval_case(
                "reason-" + reason.casefold().replace("_", "-"),
                item["source_id"],
                "safe_alternative" if alternative else "dependency_gap",
                "pass" if alternative else "blocked",
                "safe_alternative" if alternative else "blocked",
                [reason],
                [],
                ["all-business-claims"],
            )
        )
    cases.extend(
        [
            _eval_case(
                "blocked-forecast-claim-boundary",
                "game-revenue-forecast",
                "claim_boundary",
                "blocked",
                "blocked",
                items["game-revenue-forecast"]["blocker_reason_codes"],
                [],
                ["unvalidated-revenue-forecast", "invented-confidence", "causality"],
            ),
            _eval_case(
                "changed-source-requires-review",
                control["source_id"],
                "source_change_review",
                "review",
                "review_required",
                ["SOURCE_SPECIFICATION_REVIEW_REQUIRED"],
                [],
                ["silent-package-rewrite"],
            ),
            _eval_case(
                "removed-source-preserves-history",
                control["source_id"],
                "source_removal_history",
                "review",
                "historical",
                ["SOURCE_REMOVED_HISTORY_PRESERVED"],
                [],
                ["automatic-skill-deletion"],
            ),
            _eval_case(
                "tampered-full-specification-rejected",
                control["source_id"],
                "tamper_rejection",
                "reject",
                "rejected",
                ["THINKINGAI_FULL_DIGEST_INVALID"],
                [],
                ["all-business-claims"],
            ),
            _eval_case(
                "source-content-leakage-rejected",
                control["source_id"],
                "content_leakage_rejection",
                "reject",
                "rejected",
                ["THINKINGAI_FULL_CONTENT_LEAKAGE"],
                [],
                ["source-body-as-runtime-evidence"],
            ),
        ]
    )
    cases.sort(key=lambda item: item["case_id"])
    artifact = {
        "artifact_kind": "thinkingai_full_eval",
        "schema_version": EVAL_SCHEMA_VERSION,
        "suite_id": "thinkingai-full-specification-regression-v1",
        "specification_sha256": specification["specification_sha256"],
        "representative_eval_sha256": representative["eval_sha256"],
        "case_count": len(cases),
        "reason_codes_covered": blockers,
        "cases": cases,
        "network_called": False,
    }
    artifact["eval_sha256"] = canonical_digest(artifact)
    return validate_full_eval(artifact)


def validate_full_eval(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value,
        _EVAL_SCHEMA,
        "THINKINGAI_FULL_EVAL_INVALID",
        "full specification eval",
    )
    _digest(selected, "eval_sha256", "THINKINGAI_FULL_EVAL_INVALID")
    cases = selected["cases"]
    case_ids = [item["case_id"] for item in cases]
    if (
        selected["case_count"] != len(cases)
        or case_ids != sorted(case_ids)
        or len(case_ids) != len(set(case_ids))
        or selected["reason_codes_covered"]
        != sorted(set(selected["reason_codes_covered"]))
    ):
        _invalid("THINKINGAI_FULL_EVAL_INVALID", "eval counts or ordering changed")
    expected_status = {
        "pass": {"success", "safe_alternative"},
        "blocked": {"blocked"},
        "review": {"review_required", "historical"},
        "reject": {"rejected"},
    }
    for case in cases:
        if case["result_status"] not in expected_status[case["expected_outcome"]]:
            _invalid("THINKINGAI_FULL_EVAL_INVALID", "eval outcome and status disagree")
        if case["allowed_claims"] and case["result_status"] != "success":
            _invalid("THINKINGAI_FULL_EVAL_INVALID", "non-success eval allows claims")
        if case["network_called"] is not False:
            _invalid("THINKINGAI_FULL_EVAL_INVALID", "eval attempted network access")
    return selected


def compile_source_impact(
    full_specification: Mapping[str, Any], inventory_diff: Mapping[str, Any]
) -> dict[str, Any]:
    specification = validate_full_specification(full_specification)
    difference = validate_inventory_diff(inventory_diff)
    previous = difference["previous_snapshot"]
    if (
        previous is not None
        and previous["snapshot_sha256"] is not None
        and previous["snapshot_sha256"] != specification["source_snapshot_sha256"]
    ):
        _invalid(
            "THINKINGAI_FULL_SOURCE_IMPACT_INVALID",
            "source diff does not start from the specified snapshot",
        )
    current = {item["source_id"]: item for item in specification["items"]}
    changes = []
    for change in difference["changes"]:
        source_id = change["source_id"]
        item = current.get(source_id)
        if item is None:
            _invalid(
                "THINKINGAI_FULL_COVERAGE_INVALID",
                "source diff contains an identity without a full specification",
            )
        state = change["state"]
        action = {
            "added": "covered",
            "unchanged": "none",
            "changed": "review_required",
            "redirect": "review_required",
            "removed": "preserve_history",
        }[state]
        stable_reference = (
            item["skill"]["package_sha256"]
            if item["skill"] is not None
            else item["alternative"]["alternative_ref"]
        )
        changes.append(
            {
                "source_id": source_id,
                "source_state": state,
                "action": action,
                "stable_reference": stable_reference,
                "silent_rewrite_allowed": False,
            }
        )
    return {
        "schema_version": "gravity.thinkingai-full-source-impact.v1",
        "specification_sha256": specification["specification_sha256"],
        "inventory_diff_sha256": difference["diff_sha256"],
        "changes": sorted(changes, key=lambda item: item["source_id"]),
        "network_called": False,
    }


def _manifest(
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


def _validate_new_manifest(
    manifest: Mapping[str, Any],
    definition: Mapping[str, Any],
    source_item: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> None:
    blockers = set(definition["blocker_reason_codes"])
    required = set()
    if manifest["semantic_dependencies"]:
        required.add("SEMANTIC_DEFINITION_MISSING")
    if manifest["operator_dependencies"]:
        required.add("OPERATOR_UNAVAILABLE")
    if manifest["model_dependencies"]:
        required.update({"HUB_TRUSTED_PACK_MISSING", "MODEL_UNVALIDATED"})
    if manifest["context_dependencies"]["required"]:
        required.add("CONTEXT_REQUIRED_MISSING")
    if definition["capability_profile"] == "none":
        required.add("CAPABILITY_TRUST_CONTRACT_MISSING")
    if not required.issubset(blockers):
        _invalid(
            "THINKINGAI_FULL_DEPENDENCY_INVALID",
            "declared dependencies are not represented by blocker reasons",
        )
    if (
        source_item["mapping_kind"] != "future_skill"
        or source_item["future_skill_uri"] != skill_uri(manifest)
        or source_item["license_review"] != "approved"
        or source_item["independent_authorship"] != "required"
        or manifest["covers_journeys"] != []
        or manifest["readiness"] != "blocked"
        or manifest["validation"] != "unvalidated"
        or manifest["claim_policy"]["allowed"] != []
        or manifest["effects"] != ["read"]
        or manifest["provenance"]["source_revision"]
        != snapshot["source_observation"]["observation_sha256"]
    ):
        _invalid(
            "THINKINGAI_FULL_STATE_INVALID",
            "new Skill state, provenance or source mapping changed",
        )
    _validate_independent_text(_human_text(manifest), source_item["source_title"])


def _skill_specification_item(
    source_item: Mapping[str, Any],
    entry: Mapping[str, Any],
    definition: Mapping[str, Any] | None,
    representative: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = compile_skill_manifest(entry["manifest"], label="CT03 full Hub Skill")
    if representative is None:
        if definition is None:
            _invalid("THINKINGAI_FULL_COVERAGE_INVALID", "new Skill definition is missing")
        _validate_new_manifest(manifest, definition, source_item, snapshot)
        blockers = copy.deepcopy(definition["blocker_reason_codes"])
        next_evidence = copy.deepcopy(definition["next_evidence"])
    else:
        if definition is not None:
            _invalid("THINKINGAI_FULL_COVERAGE_INVALID", "representative was redefined")
        if (
            representative["skill_uri"] != skill_uri(manifest)
            or representative["manifest_sha256"] != canonical_digest(manifest)
            or representative["package_sha256"] != entry["package"]["package_digest"]
            or representative["archive_sha256"] != entry["archive"]["sha256"]
        ):
            _invalid(
                "THINKINGAI_FULL_REPRESENTATIVE_DRIFT",
                "CT02 representative package changed in the full Hub",
            )
        blockers = copy.deepcopy(representative["declared_blockers"])
        next_evidence = copy.deepcopy(
            _REPRESENTATIVE_NEXT_EVIDENCE[source_item["source_id"]]
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


def _eval_case(
    case_id: str,
    source_id: str,
    scenario: str,
    outcome: str,
    status: str,
    reasons: Sequence[str],
    allowed: Sequence[str],
    forbidden: Sequence[str],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "source_id": source_id,
        "scenario": scenario,
        "expected_outcome": outcome,
        "result_status": status,
        "reason_codes": sorted(reasons),
        "allowed_claims": sorted(allowed),
        "forbidden_claims": sorted(forbidden),
        "network_called": False,
    }


def _human_text(manifest: Mapping[str, Any]) -> str:
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


def _validate_independent_text(text: str, source_title: str) -> None:
    folded = text.casefold()
    if (
        source_title.casefold() in folded
        or _MARKETING_NUMBER.search(text)
        or any(marker in folded for marker in _INSTRUCTION_MARKERS)
    ):
        _invalid(
            "THINKINGAI_FULL_CONTENT_LEAKAGE",
            "independent content contains protected, marketing or instruction text",
        )


def _sorted_unique_ids(items: Sequence[Mapping[str, Any]], label: str) -> list[str]:
    identities = [item["source_id"] for item in items]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        _invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            f"{label} identities are not sorted and unique",
        )
    return identities


def _schema_copy(
    value: Mapping[str, Any], schema: str, code: str, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(code, f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise ThinkingAIFullSpecificationError(code, f"{label} is invalid") from exc
    return selected


def _digest(value: dict[str, Any], field: str, code: str) -> None:
    actual = value.pop(field)
    expected = canonical_digest(value)
    value[field] = actual
    if actual != expected:
        _invalid(code, "canonical digest changed")


def _invalid(reason_code: str, message: str) -> None:
    raise ThinkingAIFullSpecificationError(reason_code, message)


__all__ = [
    "EVAL_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "SPECIFICATION_SCHEMA_VERSION",
    "ThinkingAIFullSpecificationError",
    "compile_full_eval",
    "compile_full_source",
    "compile_full_specification",
    "compile_source_impact",
    "full_source_manifests",
    "validate_full_eval",
    "validate_full_specification",
]
