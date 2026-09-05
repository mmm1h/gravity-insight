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


class SkillJourneyContractGateTests(unittest.TestCase):
    def test_valid_link_and_unlinked_skill_pass(self) -> None:
        unlinked = _skill(covered=[])
        unlinked.update({"skill_id": "unlinked", "namespace": "gravity.other"})

        code, receipt = check_contracts([_skill(), unlinked], [_journey()])

        self.assertEqual(0, code)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(2, receipt["skill_contract_count"])
        self.assertEqual(1, receipt["linked_skill_count"])
        self.assertEqual(1, receipt["checked_link_count"])

    def test_claim_policy_drift_fails_closed(self) -> None:
        skill = _skill()
        skill["claim_policy"] = {
            "allowed": ["outside", "explicitly-forbidden"],
            "forbidden": [],
        }
        journey = _journey()
        journey["claim_policy"] = {
            "allowed": ["returned-observation"],
            "forbidden": ["explicitly-forbidden", "causality"],
        }

        code, receipt = check_contracts([skill], [journey])

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
        code, receipt = check_contracts([_skill()], [])

        self.assertEqual(1, code)
        self.assertEqual(
            ["skill-journey-reference-missing"],
            [item["detector"] for item in receipt["findings"]],
        )

    def test_required_skill_must_be_reciprocal(self) -> None:
        journey = _journey()
        journey["required_skill"] = "skill://gravity.sample/missing@1.0.0"

        code, receipt = check_contracts([_skill()], [journey])

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

                code, receipt = check_contracts([skill], [_journey()])

                self.assertEqual(1, code)
                self.assertIn(
                    detector,
                    {item["detector"] for item in receipt["findings"]},
                )

    def test_current_repository_is_consistent_and_ci_runs_gate(self) -> None:
        code, receipt = check_repository(ROOT)
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertEqual(0, code, receipt)
        self.assertEqual(44, receipt["skill_contract_count"])
        self.assertGreater(receipt["journey_contract_count"], 0)
        self.assertIn("python scripts/check_skill_journey_contracts.py", workflow)


if __name__ == "__main__":
    unittest.main()
