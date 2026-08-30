from __future__ import annotations

import copy
import unittest

from gravity_insight.analysis_result_contract import (
    AnalysisResultContractError,
    compile_analysis_result,
)
from gravity_insight.data_quality import data_quality_result
from gravity_insight.execution_snapshot import build_execution_snapshot
from gravity_insight.context_contract import context_pack_digest


def context_pack():
    item = {
        "schema_version": "gravity.context-item.v1",
        "uri": "repo://demo/docs/context.md",
        "provider_uri": "context-provider://gravity/project-repo@1",
        "item_id": "example-context",
        "fact_id": "fact.example",
        "resource_type": "document",
        "title": "Example context",
        "entity_refs": ["entity://gravity/app@1"],
        "resolved_entity_refs": ["entity://gravity/app@1"],
        "valid_time": {"start": None, "end": None, "timezone": "UTC"},
        "effective_range": {"start": None, "end": None},
        "observed_at": "2026-08-22T00:00:00Z",
        "authority": "canonical",
        "source_revision": "3" * 40,
        "content_hash": "5" * 64,
        "freshness": "current",
        "source_trust": "project_authoritative",
        "supersedes": [],
        "sensitivity": "internal",
        "role": "data",
        "citation": {"path": "docs/context.md", "line_start": 1, "line_end": 1},
    }
    value = {
        "schema_version": "gravity.context-pack.v1",
        "status": "available",
        "provider": {
            "uri": "context-provider://gravity/project-repo@1",
            "digest": "2" * 64,
            "source_revision": "3" * 40,
        },
        "requirement": {
            "requirement_id": "context://project-repo/example@1",
            "digest": "1" * 64,
        },
        "skill_id": "skill://gravity.game/example@1.0.0",
        "journey_id": "analysis.example",
        "subject_entities": ["entity://gravity/app@1"],
        "resolved_entities": ["entity://gravity/app@1"],
        "requested_time": {
            "current": {"start": "2026-08-01", "end": "2026-08-07", "timezone": "UTC"}
        },
        "authority_policy": {
            "required": ["canonical"],
            "allow_supporting": True,
            "allow_unverified": False,
        },
        "items": [item],
        "alignment": {
            "matched": ["repo://demo/docs/context.md"],
            "excluded": [],
            "superseded": [],
        },
        "required_status": [
            {"item_id": "example-context", "status": "available", "reason_code": None}
        ],
        "conflicts": [],
        "gaps": [],
        "claims": {
            "confirmed_claims_allowed": True,
            "optional_context_complete": True,
            "authority_ceiling": "canonical",
        },
        "budget": {
            "max_files": 1,
            "max_file_bytes": 1024,
            "max_total_bytes": 1024,
            "max_total_lines": 10,
            "used_files": 1,
            "used_bytes": 12,
            "used_lines": 1,
        },
        "network_called": False,
    }
    value["pack_digest"] = context_pack_digest(value)
    return value


def execution_snapshot(*, context=True, status="resolved"):
    pack = context_pack()
    context_packs = (
        [
            {
                "requirement_uri": pack["requirement"]["requirement_id"],
                "requirement_digest": pack["requirement"]["digest"],
                "provider_uri": pack["provider"]["uri"],
                "provider_digest": pack["provider"]["digest"],
                "source_revision": pack["provider"]["source_revision"],
                "pack_digest": pack["pack_digest"],
                "status": pack["status"],
            }
        ]
        if context
        else []
    )
    return build_execution_snapshot(
        status=status,
        journey={"journey_id": "analysis.example", "version": 1, "digest": "a" * 64},
        skill={
            "uri": "skill://gravity.game/example@1.0.0",
            "version": "1.0.0",
            "manifest_digest": "b" * 64,
            "package_digest": "c" * 64,
            "resolution": "unlocked",
            "team_lock_digest": None,
            "hub_source_digest": None,
            "hub_source_reference": None,
            "trusted_pack_lock_digest": None,
            "trusted_pack_state_digest": None,
            "trusted_pack_verification_digest": None,
            "lifecycle": "reviewed",
            "readiness": "executable",
            "validation": "validated",
        },
        project_overlay={
            "uri": "skill://project.demo/example@1.0.0",
            "version": "1.0.0",
            "digest": "d" * 64,
            "source_revision": "3" * 40,
        },
        capabilities=[],
        semantics=[],
        operators=[],
        models=[],
        context_packs=context_packs,
        contracts={
            "input_schema_version": "gravity.example-input.v1",
            "analysis_result_schema_version": "gravity.analysis-result.v1",
            "execution_mode": "plan",
            "execution_owner": "example@1",
        },
    )


def success_result():
    snapshot = execution_snapshot()
    scope = {"app": "demo", "start": "2026-08-01", "end": "2026-08-07"}
    return {
        "schema_version": "gravity.analysis-result.v1",
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "question": "What changed?",
        "journey": copy.deepcopy(snapshot["journey"]),
        "skill": copy.deepcopy(snapshot["skill"]),
        "scope": scope,
        "semantics": copy.deepcopy(snapshot["semantics"]),
        "capabilities": copy.deepcopy(snapshot["capabilities"]),
        "operators": copy.deepcopy(snapshot["operators"]),
        "models": copy.deepcopy(snapshot["models"]),
        "context_packs": [context_pack()],
        "completeness": "complete",
        "data_quality": data_quality_result([{"check_id": "complete", "status": "pass", "scope": "example"}]),
        "evidence_level": "L2",
        "findings": [
            {
                "finding_type": "supported_association",
                "statement": "Returned rows changed.",
                "evidence_level": "L2",
                "fact_references": [{"step_id": "query", "path": "/rows/0/value"}],
                "supporting_references": [],
                "scope": scope,
                "limitations": ["Returned rows only."],
            }
        ],
        "excluded_factors": [],
        "hypotheses": [{"statement": "Example", "values": ["one"]}],
        "limitations": ["Returned rows only."],
        "allowed_claims": [{"claim_id": "returned-change", "statement": "Returned rows changed.", "scope": scope}],
        "forbidden_claims": ["causality"],
        "recommended_next_actions": [],
        "receipt_references": [{"receipt_id": "a" * 32, "storage_status": "stored"}],
        "execution_snapshot": snapshot,
        "can_run_status": "verified",
        "reason_codes": [],
        "network_called": True,
    }


def second_context_pack():
    value = context_pack()
    value["provider"] = {
        "uri": "context-provider://team/knowledge@1",
        "digest": "6" * 64,
        "source_revision": "release-2026.08.22",
    }
    value["requirement"] = {
        "requirement_id": "context://team/second@1",
        "digest": "7" * 64,
    }
    value["items"][0].update(
        {
            "uri": "provider://team/docs/second",
            "provider_uri": value["provider"]["uri"],
            "item_id": "external-second",
            "fact_id": "fact.external-second",
            "source_revision": value["provider"]["source_revision"],
            "source_trust": "reviewed",
            "citation": {
                "path": "team/docs/second",
                "line_start": 1,
                "line_end": 1,
            },
        }
    )
    value["alignment"]["matched"] = [value["items"][0]["uri"]]
    value["required_status"] = [
        {"item_id": "external-second", "status": "available", "reason_code": None}
    ]
    value["pack_digest"] = context_pack_digest(value)
    return value


def context_reference(value):
    return {
        "requirement_uri": value["requirement"]["requirement_id"],
        "requirement_digest": value["requirement"]["digest"],
        "provider_uri": value["provider"]["uri"],
        "provider_digest": value["provider"]["digest"],
        "source_revision": value["provider"]["source_revision"],
        "pack_digest": value["pack_digest"],
        "status": value["status"],
    }


class AnalysisResultContractTests(unittest.TestCase):
    def test_success_is_closed_and_snapshot_bound(self):
        value = success_result()
        self.assertEqual(value, compile_analysis_result(value))

    def test_snapshot_drift_and_context_body_fail_closed(self):
        drift = success_result()
        drift["journey"]["digest"] = "0" * 64
        with self.assertRaisesRegex(AnalysisResultContractError, "references disagree"):
            compile_analysis_result(drift)

        body = success_result()
        body["context_packs"][0]["items"][0]["content"] = "private"
        with self.assertRaisesRegex(AnalysisResultContractError, "Context bodies"):
            compile_analysis_result(body)

    def test_blocked_result_cannot_carry_conclusions(self):
        snapshot = execution_snapshot(context=False, status="blocked")
        blocked = {
            "schema_version": "gravity.analysis-result.v1",
            "ok": False,
            "status": "blocked",
            "exit_code": 4,
            "question": None,
            "journey": copy.deepcopy(snapshot["journey"]),
            "skill": copy.deepcopy(snapshot["skill"]),
            "scope": None,
            "semantics": [],
            "capabilities": [],
            "operators": [],
            "models": [],
            "context_packs": [],
            "completeness": "unknown",
            "data_quality": data_quality_result([]),
            "evidence_level": None,
            "findings": [],
            "excluded_factors": [],
            "hypotheses": [],
            "limitations": ["Dependency blocked."],
            "allowed_claims": [],
            "forbidden_claims": ["causality"],
            "recommended_next_actions": [],
            "receipt_references": [],
            "execution_snapshot": snapshot,
            "can_run_status": "blocked",
            "reason_codes": ["DEPENDENCY_BLOCKED"],
            "network_called": False,
        }
        self.assertEqual(blocked, compile_analysis_result(blocked))

        contradicted = copy.deepcopy(blocked)
        contradicted["findings"] = success_result()["findings"]
        with self.assertRaisesRegex(AnalysisResultContractError, "unsupported conclusions"):
            compile_analysis_result(contradicted)

    def test_multiple_context_packs_are_ordered_exact_and_lossless(self):
        value = success_result()
        second = second_context_pack()
        snapshot = value["execution_snapshot"]
        value["execution_snapshot"] = build_execution_snapshot(
            status=snapshot["status"],
            journey=snapshot["journey"],
            skill=snapshot["skill"],
            project_overlay=snapshot["project_overlay"],
            capabilities=snapshot["capabilities"],
            semantics=snapshot["semantics"],
            operators=snapshot["operators"],
            models=snapshot["models"],
            context_packs=[snapshot["context_packs"][0], context_reference(second)],
            contracts=snapshot["contracts"],
            runtime_version=snapshot["runtime"]["version"],
        )
        value["context_packs"].append(second)

        self.assertEqual(value, compile_analysis_result(value))

        missing = copy.deepcopy(value)
        missing["context_packs"].pop()
        with self.assertRaisesRegex(AnalysisResultContractError, "Context references"):
            compile_analysis_result(missing)

        reordered = copy.deepcopy(value)
        reordered["context_packs"].reverse()
        with self.assertRaisesRegex(AnalysisResultContractError, "Context references"):
            compile_analysis_result(reordered)

    def test_success_can_expose_findings_with_no_allowed_claims(self):
        value = success_result()
        value["allowed_claims"] = []

        self.assertEqual(value, compile_analysis_result(value))


if __name__ == "__main__":
    unittest.main()
