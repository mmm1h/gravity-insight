from __future__ import annotations

import copy
import unittest

from scripts.check_skill_journey_contracts import (
    ROOT,
    check_contracts,
    check_repository,
)


def _skill(*, covered: list[str] | None = None) -> dict:
    return {
        "skill_id": "sample-skill",
        "namespace": "gravity.sample",
        "version": "1.0.0",
        "covers_journeys": covered if covered is not None else ["analysis.sample"],
        "claim_policy": {
            "allowed": ["returned-observation"],
            "forbidden": ["causality"],
            "forbidden_without_context": [],
        },
        "capability_dependencies": [
            {
                "identity_kind": "product",
                "selector": "sample.read",
                "contract_version": "1",
                "minimum_trust": "stable",
                "completeness": "complete",
                "data_quality": "pass",
            }
        ],
        "semantic_dependencies": ["metric://sample/value@1"],
        "operator_dependencies": ["operator://gravity/sample@1"],
        "model_dependencies": ["model://gravity/sample@1"],
        "context_dependencies": {
            "required": ["context://project/sample@1"],
            "optional": [],
        },
        "request_budget": {
            "known_requests_min": 1,
            "known_requests_max": 2,
            "unknown_discovery_max": 1,
            "runtime_additional_requests": 0,
        },
        "requirements": {"completeness": "complete", "data_quality": "pass"},
    }


def _journey() -> dict:
    skill = _skill()
    return {
        "journey_id": "analysis.sample",
        "required_skill": "skill://gravity.sample/sample-skill@1.0.0",
        "claim_policy": {
            "allowed": ["returned-observation"],
            "forbidden": ["causality"],
        },
        "required_capabilities": copy.deepcopy(skill["capability_dependencies"]),
        "required_semantics": copy.deepcopy(skill["semantic_dependencies"]),
        "required_operators": copy.deepcopy(skill["operator_dependencies"]),
        "required_models": copy.deepcopy(skill["model_dependencies"]),
        "required_context": copy.deepcopy(
            skill["context_dependencies"]["required"]
        ),
        "request_budget": {
            **copy.deepcopy(skill["request_budget"]),
            "acceptance_production_requests": 0,
        },
    }


def _model() -> dict:
    return {
        "uri": "model://gravity/sample@1",
        "claim_policy": {
            "validated": [
                "deterministic-scenario-over-caller-bound-parameters"
            ],
            "scenario": ["unvalidated-project-calibration-scenario"],
            "forbidden": [
                "causality",
                "project-accuracy-guarantee",
                "guaranteed-future-outcome",
            ],
        },
    }


def _capability(
    selector: str,
    *,
    identity_kind: str = "product",
    completeness: str = "complete",
    allowed_claims: list[str] | None = None,
    dependencies: list[dict] | None = None,
) -> dict:
    return {
        "identity_kind": identity_kind,
        "selector": selector,
        "contract_version": "1",
        "lifecycle": "active",
        "declared_completeness": completeness,
        "required_data_quality": "pass",
        "allowed_claims": allowed_claims or [],
        "dependencies": dependencies or [],
    }


class SkillJourneyContractGateTests(unittest.TestCase):
    def test_valid_link_and_unlinked_skill_pass(self) -> None:
        unlinked = _skill(covered=[])
        unlinked.update({"skill_id": "unlinked", "namespace": "gravity.other"})

        code, receipt = check_contracts(
            [_skill(), unlinked], [_journey()], [_model()]
        )

        self.assertEqual(0, code)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(2, receipt["skill_contract_count"])
        self.assertEqual(1, receipt["linked_skill_count"])
        self.assertEqual(1, receipt["checked_link_count"])
        self.assertEqual(1, receipt["model_contract_count"])
        self.assertEqual(2, receipt["checked_skill_model_link_count"])
        self.assertEqual(1, receipt["checked_journey_model_link_count"])

    def test_claim_policy_drift_fails_closed(self) -> None:
        skill = _skill()
        skill["claim_policy"] = {
            "allowed": ["outside", "explicitly-forbidden"],
            "forbidden": [],
            "forbidden_without_context": [],
        }
        journey = _journey()
        journey["claim_policy"] = {
            "allowed": ["returned-observation"],
            "forbidden": ["explicitly-forbidden", "causality"],
        }

        code, receipt = check_contracts([skill], [journey], [_model()])

        self.assertEqual(1, code)
        self.assertEqual("fail", receipt["status"])
        self.assertEqual(
            {
                "skill-allowed-claims-outside-journey",
                "skill-allowed-claims-forbidden-by-journey",
                "journey-forbidden-claims-missing-from-skill",
            },
            {item["detector"] for item in receipt["findings"]},
        )

    def test_unknown_journey_reference_fails_closed(self) -> None:
        code, receipt = check_contracts([_skill()], [], [_model()])

        self.assertEqual(1, code)
        self.assertEqual(
            ["skill-journey-reference-missing"],
            [item["detector"] for item in receipt["findings"]],
        )

    def test_required_skill_must_be_reciprocal(self) -> None:
        journey = _journey()
        journey["required_skill"] = "skill://gravity.sample/missing@1.0.0"

        code, receipt = check_contracts([_skill()], [journey], [_model()])

        self.assertEqual(1, code)
        self.assertEqual(
            {
                "journey-required-skill-mismatch",
                "journey-required-skill-missing",
            },
            {item["detector"] for item in receipt["findings"]},
        )

    def test_shared_dependencies_and_budget_must_match(self) -> None:
        mutations = (
            ("capability_dependencies", "skill-journey-dependency-mismatch"),
            ("semantic_dependencies", "skill-journey-dependency-mismatch"),
            ("operator_dependencies", "skill-journey-dependency-mismatch"),
            ("model_dependencies", "skill-journey-dependency-mismatch"),
            ("context_dependencies", "skill-journey-dependency-mismatch"),
            ("request_budget", "skill-journey-request-budget-mismatch"),
        )
        for field, detector in mutations:
            with self.subTest(field=field):
                skill = _skill()
                if field == "context_dependencies":
                    skill[field]["required"] = []
                elif field == "request_budget":
                    skill[field]["known_requests_max"] = 3
                else:
                    skill[field] = []

                code, receipt = check_contracts(
                    [skill], [_journey()], [_model()]
                )

                self.assertEqual(1, code)
                self.assertIn(
                    detector,
                    {item["detector"] for item in receipt["findings"]},
                )

    def test_skill_summary_requirement_must_match_journey(self) -> None:
        skill = _skill()
        skill["requirements"]["completeness"] = "unknown"

        code, receipt = check_contracts([skill], [_journey()], [_model()])

        self.assertEqual(1, code)
        self.assertEqual(
            ["skill-journey-requirement-mismatch"],
            [item["detector"] for item in receipt["findings"]],
        )
        self.assertEqual("completeness", receipt["findings"][0]["dimension"])

    def test_model_claim_vocabulary_fails_closed(self) -> None:
        cases = (
            ("causal claim", "model-claim-id-invalid"),
            ("unknown-stable-claim", "model-claim-id-unknown"),
        )
        for claim, detector in cases:
            with self.subTest(claim=claim):
                model = _model()
                model["claim_policy"]["forbidden"] = [claim]

                code, receipt = check_contracts([], [], [model])

                self.assertEqual(1, code)
                self.assertEqual(
                    [detector],
                    [item["detector"] for item in receipt["findings"]],
                )

    def test_model_forbidden_claims_constrain_dependents(self) -> None:
        model = _model()
        model["claim_policy"]["forbidden"].append("returned-observation")

        code, receipt = check_contracts([_skill()], [_journey()], [model])

        self.assertEqual(1, code)
        self.assertEqual(
            {
                "journey-allowed-claims-forbidden-by-model",
                "skill-allowed-claims-forbidden-by-model",
            },
            {item["detector"] for item in receipt["findings"]},
        )
        self.assertEqual(
            {"model://gravity/sample@1"},
            {item["model_uri"] for item in receipt["findings"]},
        )

    def test_missing_model_references_fail_closed(self) -> None:
        code, receipt = check_contracts([_skill()], [_journey()], [])

        self.assertEqual(1, code)
        self.assertEqual(
            {"journey-model-reference-missing", "skill-model-reference-missing"},
            {item["detector"] for item in receipt["findings"]},
        )

    def test_claim_dependency_reachability_fails_closed_at_every_claim_layer(self) -> None:
        dependency = _capability("sample.read", completeness="unknown")
        requirement = copy.deepcopy(_skill()["capability_dependencies"][0])
        publisher = _capability(
            "sample.publisher",
            completeness="unknown",
            allowed_claims=["returned-observation"],
            dependencies=[requirement],
        )

        code, receipt = check_contracts(
            [_skill()],
            [_journey()],
            [_model()],
            capabilities=[dependency, publisher],
        )

        self.assertEqual(1, code)
        self.assertEqual("fail", receipt["status"])
        findings = [
            item
            for item in receipt["findings"]
            if item["detector"] == "claim-dependency-requirement-unreachable"
        ]
        self.assertEqual(3, len(findings))
        self.assertEqual({"completeness"}, {item["dimension"] for item in findings})
        self.assertEqual(
            {"sample.read"}, {item["dependency_selector"] for item in findings}
        )
        self.assertEqual(
            {"product:sample.publisher"},
            {item["capability_id"] for item in findings} - {"<none>"},
        )
        self.assertEqual(
            {"sample-skill"},
            {item["skill_id"] for item in findings} - {"<none>"},
        )
        self.assertEqual(
            {"analysis.sample"},
            {item["journey_id"] for item in findings} - {"<none>"},
        )

    def test_current_repository_is_consistent_and_ci_runs_gate(self) -> None:
        code, receipt = check_repository(ROOT)
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertEqual(0, code, receipt)
        self.assertEqual(44, receipt["skill_contract_count"])
        self.assertEqual(13, receipt["journey_contract_count"])
        self.assertEqual(8, receipt["model_contract_count"])
        self.assertEqual(6, receipt["checked_skill_model_link_count"])
        self.assertEqual(2, receipt["checked_journey_model_link_count"])
        self.assertEqual(5, receipt["referenced_model_count"])
        self.assertEqual(3, receipt["claim_bearing_capability_count"])
        self.assertGreater(receipt["checked_claim_dependency_count"], 0)
        self.assertIn("python scripts/check_skill_journey_contracts.py", workflow)


if __name__ == "__main__":
    unittest.main()
