from __future__ import annotations

import copy
import unittest

from gravity_sdk.analysis_result_contract import (
    AnalysisResultContractError,
    compile_analysis_result,
)
from gravity_sdk.data_quality import data_quality_result
from gravity_sdk.execution_snapshot import build_execution_snapshot


def execution_snapshot(*, context=True, status="resolved"):
    context_packs = (
        [
            {
                "requirement_uri": "context://project-repo/example@1",
                "requirement_digest": "1" * 64,
                "provider_uri": "context-provider://gravity/project-repo@1",
                "provider_digest": "2" * 64,
                "source_revision": "3" * 40,
                "pack_digest": "4" * 64,
                "status": "available",
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
        "context_pack": {
            "requirement": {"requirement_id": "context://project-repo/example@1", "digest": "1" * 64},
            "provider": {"uri": "context-provider://gravity/project-repo@1", "digest": "2" * 64, "source_revision": "3" * 40},
            "pack_digest": "4" * 64,
            "status": "available",
            "items": [{"role": "data"}],
        },
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
        body["context_pack"]["items"][0]["content"] = "private"
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
            "context_pack": None,
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


if __name__ == "__main__":
    unittest.main()
