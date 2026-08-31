from __future__ import annotations

import copy
from pathlib import Path
import unittest

from gravity_insight.skill_contract import SkillContractError, compile_skill_manifest
from scripts.generate_method_gap_report import CRITERIA, compact_report, library_report
from scripts.generate_skill_library import load_canonical_skills


ROOT = Path(__file__).resolve().parents[1]
COMPLETE_SKILLS = {
    "game-campaign-effect-evaluation",
    "ltv-payback-period-prediction",
    "payment-rate-anomaly-diagnosis",
}


class SkillMethodCompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = library_report(ROOT)

    def test_gate_has_exactly_seventeen_traceable_criteria(self) -> None:
        self.assertEqual(list(range(1, 18)), [item.item for item in CRITERIA])
        self.assertEqual(17, len({item.key for item in CRITERIA}))
        self.assertEqual({"structural", "proxy"}, {item.evaluation for item in CRITERIA})
        for item in CRITERIA:
            with self.subTest(item=item.item):
                self.assertEqual(item.evaluation == "proxy", item.proxy_for is not None)
                self.assertEqual(item.evaluation == "proxy", item.cannot_prove is not None)

    def test_report_covers_every_canonical_skill_and_every_item(self) -> None:
        self.assertEqual(40, self.report["summary"]["skill_count"])
        self.assertEqual(40, len(self.report["skills"]))
        for row in self.report["skills"]:
            with self.subTest(skill=row["skill_uri"]):
                self.assertEqual(17, len(row["items"]))
                self.assertEqual(17, row["achieved_count"] + row["missing_count"])
                self.assertEqual(row["method_complete"], not row["missing_items"])

    def test_compact_command_report_retains_each_skill_item_result(self) -> None:
        compact = compact_report(self.report)
        self.assertEqual(self.report["summary"], compact["summary"])
        self.assertTrue(all(len(row["items"]) == 17 for row in compact["skills"]))

    def test_exactly_three_sample_methods_are_complete(self) -> None:
        complete = {
            row["skill_id"] for row in self.report["skills"]
            if row["method_complete"]
        }
        self.assertEqual(COMPLETE_SKILLS, complete)
        self.assertEqual(3, self.report["summary"]["method_complete_true"])
        self.assertEqual(37, self.report["summary"]["method_complete_false"])
        for row in self.report["skills"]:
            if row["skill_id"] in COMPLETE_SKILLS:
                with self.subTest(skill=row["skill_id"]):
                    self.assertEqual(17, row["achieved_count"])
                    self.assertTrue(row["dependency_gaps"])

    def test_incomplete_skills_are_sorted_by_completion_cost(self) -> None:
        costs = [
            row["estimated_completion_cost"]
            for row in self.report["skills"]
            if not row["method_complete"]
        ]
        self.assertEqual(sorted(costs), costs)

    def test_unfinished_method_is_state_not_contract_failure(self) -> None:
        manifest = load_canonical_skills()[0]
        manifest.pop("method", None)
        self.assertEqual(manifest, compile_skill_manifest(manifest))

    def test_method_cross_references_fail_closed(self) -> None:
        complete = next(
            (item for item in load_canonical_skills() if "method" in item),
            None,
        )
        self.assertIsNotNone(complete)
        invalid = copy.deepcopy(complete)
        invalid["method"]["examples"]["eval_cases"][0]["expected_sections"] = [
            "missing-section",
            invalid["method"]["result"]["sections"][0]["section_id"],
        ]
        with self.assertRaisesRegex(SkillContractError, "unknown result section"):
            compile_skill_manifest(invalid)

    def test_unregistered_dependency_cannot_masquerade_as_available(self) -> None:
        complete = next(
            item for item in load_canonical_skills()
            if item["skill_id"] == "ltv-payback-period-prediction"
        )
        invalid = copy.deepcopy(complete)
        dependency = next(
            item for item in invalid["method"]["dependency_status"]
            if item["kind"] == "operator"
        )
        dependency["status"] = "available"
        with self.assertRaisesRegex(SkillContractError, "not registered"):
            compile_skill_manifest(invalid)

    def test_unresolved_dependencies_require_blocked_readiness(self) -> None:
        complete = next(
            item for item in load_canonical_skills()
            if item["skill_id"] == "payment-rate-anomaly-diagnosis"
        )
        invalid = copy.deepcopy(complete)
        invalid["readiness"] = "executable"
        with self.assertRaisesRegex(SkillContractError, "blocked readiness"):
            compile_skill_manifest(invalid)


if __name__ == "__main__":
    unittest.main()
