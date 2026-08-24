"""Eval and source-diff impact contracts for CT03 full specifications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest
from .thinkingai_full_shared import invalid, schema_copy, verify_digest
from .thinkingai_full_specification import validate_full_specification
from .thinkingai_inventory import validate_inventory_diff
from .thinkingai_representative import validate_representative_eval


EVAL_SCHEMA_VERSION = "gravity.thinkingai-full-eval.v1"
_EVAL_SCHEMA = "thinkingai-full-eval-v1.schema.json"


def compile_full_eval(
    full_specification: Mapping[str, Any],
    representative_eval: Mapping[str, Any],
) -> dict[str, Any]:
    specification = validate_full_specification(full_specification)
    representative = validate_representative_eval(representative_eval)
    if (
        representative["representative_set_sha256"]
        != specification["representative_set_sha256"]
    ):
        invalid(
            "THINKINGAI_FULL_EVAL_INVALID",
            "representative eval is not bound to the full specification",
        )
    blockers = _blockers(specification)
    control = _supported_control(specification)
    cases = [
        _eval_case(
            "supported-representative-control",
            control["source_id"],
            "supported_control",
            "pass",
            "success",
            [],
            ["returned-event-metric-observation"],
            ["causality"],
        ),
        *_reason_cases(specification, blockers),
        *_governance_cases(specification, control["source_id"]),
    ]
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
    selected = schema_copy(
        value,
        _EVAL_SCHEMA,
        "THINKINGAI_FULL_EVAL_INVALID",
        "full specification eval",
    )
    verify_digest(selected, "eval_sha256", "THINKINGAI_FULL_EVAL_INVALID")
    cases = selected["cases"]
    case_ids = [item["case_id"] for item in cases]
    checks = (
        selected["case_count"] == len(cases),
        case_ids == sorted(case_ids),
        len(case_ids) == len(set(case_ids)),
        selected["reason_codes_covered"]
        == sorted(set(selected["reason_codes_covered"])),
    )
    if not all(checks):
        invalid("THINKINGAI_FULL_EVAL_INVALID", "eval counts or ordering changed")
    for case in cases:
        _validate_case(case)
    return selected


def compile_source_impact(
    full_specification: Mapping[str, Any],
    inventory_diff: Mapping[str, Any],
    current_full_specification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    specification = validate_full_specification(full_specification)
    difference = validate_inventory_diff(inventory_diff)
    current_specification = (
        validate_full_specification(current_full_specification)
        if current_full_specification is not None
        else None
    )
    current_specification = _validate_impact_baseline(
        specification, difference, current_specification
    )
    baseline = {item["source_id"]: item for item in specification["items"]}
    current = (
        {item["source_id"]: item for item in current_specification["items"]}
        if current_specification is not None
        else {}
    )
    changes = [
        _impact_item(change, baseline, current) for change in difference["changes"]
    ]
    return {
        "schema_version": "gravity.thinkingai-full-source-impact.v1",
        "specification_sha256": specification["specification_sha256"],
        "current_specification_sha256": (
            current_specification["specification_sha256"]
            if current_specification is not None
            else None
        ),
        "inventory_diff_sha256": difference["diff_sha256"],
        "changes": sorted(changes, key=lambda item: item["source_id"]),
        "network_called": False,
    }


def _blockers(specification: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            reason
            for item in specification["items"]
            for reason in item["blocker_reason_codes"]
        }
    )


def _supported_control(specification: Mapping[str, Any]) -> Mapping[str, Any]:
    return next(
        item
        for item in specification["items"]
        if item["skill"] is not None
        and item["skill"]["readiness"] == "executable"
        and item["skill"]["validation"] == "validated"
    )


def _reason_cases(
    specification: Mapping[str, Any], blockers: Sequence[str]
) -> list[dict[str, Any]]:
    cases = []
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
    return cases


def _governance_cases(
    specification: Mapping[str, Any], control_id: str
) -> list[dict[str, Any]]:
    items = {item["source_id"]: item for item in specification["items"]}
    return [
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
            control_id,
            "source_change_review",
            "review",
            "review_required",
            ["SOURCE_SPECIFICATION_REVIEW_REQUIRED"],
            [],
            ["silent-package-rewrite"],
        ),
        _eval_case(
            "removed-source-preserves-history",
            control_id,
            "source_removal_history",
            "review",
            "historical",
            ["SOURCE_REMOVED_HISTORY_PRESERVED"],
            [],
            ["automatic-skill-deletion"],
        ),
        _eval_case(
            "tampered-full-specification-rejected",
            control_id,
            "tamper_rejection",
            "reject",
            "rejected",
            ["THINKINGAI_FULL_DIGEST_INVALID"],
            [],
            ["all-business-claims"],
        ),
        _eval_case(
            "source-content-leakage-rejected",
            control_id,
            "content_leakage_rejection",
            "reject",
            "rejected",
            ["THINKINGAI_FULL_CONTENT_LEAKAGE"],
            [],
            ["source-body-as-runtime-evidence"],
        ),
    ]


def _validate_case(case: Mapping[str, Any]) -> None:
    expected_status = {
        "pass": {"success", "safe_alternative"},
        "blocked": {"blocked"},
        "review": {"review_required", "historical"},
        "reject": {"rejected"},
    }
    if case["result_status"] not in expected_status[case["expected_outcome"]]:
        invalid("THINKINGAI_FULL_EVAL_INVALID", "eval outcome and status disagree")
    if case["allowed_claims"] and case["result_status"] != "success":
        invalid("THINKINGAI_FULL_EVAL_INVALID", "non-success eval allows claims")
    if case["network_called"] is not False:
        invalid("THINKINGAI_FULL_EVAL_INVALID", "eval attempted network access")


def _validate_impact_baseline(
    specification: Mapping[str, Any],
    difference: Mapping[str, Any],
    current_specification: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    previous = difference["previous_snapshot"]
    current = difference["current_snapshot"]
    if previous is None or previous["snapshot_sha256"] is None:
        if specification["source_snapshot_sha256"] != current["snapshot_sha256"]:
            invalid(
                "THINKINGAI_FULL_SOURCE_IMPACT_INVALID",
                "initial source diff does not end at the specified snapshot",
            )
        if current_specification is not None:
            invalid(
                "THINKINGAI_FULL_SOURCE_IMPACT_INVALID",
                "initial source diff accepts one current specification",
            )
        return specification
    if previous["snapshot_sha256"] != specification["source_snapshot_sha256"]:
        invalid(
            "THINKINGAI_FULL_SOURCE_IMPACT_INVALID",
            "source diff does not start from the specified snapshot",
        )
    has_added = any(change["state"] == "added" for change in difference["changes"])
    if current_specification is None:
        if has_added:
            invalid(
                "THINKINGAI_FULL_COVERAGE_INVALID",
                "added source requires a current full specification",
            )
        return None
    if current_specification["source_snapshot_sha256"] != current["snapshot_sha256"]:
        invalid(
            "THINKINGAI_FULL_SOURCE_IMPACT_INVALID",
            "current specification does not match the diff target snapshot",
        )
    return current_specification


def _impact_item(
    change: Mapping[str, Any],
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_id = change["source_id"]
    item = (
        current.get(source_id)
        if change["state"] == "added"
        else baseline.get(source_id)
    )
    if item is None:
        invalid(
            "THINKINGAI_FULL_COVERAGE_INVALID",
            "source diff contains an identity without a full specification",
        )
    action = {
        "added": "covered",
        "unchanged": "none",
        "changed": "review_required",
        "redirect": "review_required",
        "removed": "preserve_history",
    }[change["state"]]
    stable_reference = (
        item["skill"]["package_sha256"]
        if item["skill"] is not None
        else item["alternative"]["alternative_ref"]
    )
    return {
        "source_id": source_id,
        "source_state": change["state"],
        "action": action,
        "stable_reference": stable_reference,
        "silent_rewrite_allowed": False,
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


__all__ = [
    "EVAL_SCHEMA_VERSION",
    "compile_full_eval",
    "compile_source_impact",
    "validate_full_eval",
]
