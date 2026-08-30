from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.check_promotion_readiness import (
    build_promotion_readiness,
    evaluate_promotion_readiness,
)
from scripts.validate_agent_runtime_requirement_graph import (
    parse_markdown_milestone_table,
    parse_markdown_requirement_table,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"


class PromotionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(INDEX.read_text(encoding="utf-8"))
        markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")
        self.requirement_rows = parse_markdown_requirement_table(markdown)
        self.milestone_rows = parse_markdown_milestone_table(markdown)
        self.spec_statuses = {
            item["id"]: "fixed_dev" for item in self.document["requirements"]
        }

    def test_current_repository_reports_completed_promotion_and_r10_exception(self) -> None:
        result = evaluate_promotion_readiness(INDEX, INDEX_MARKDOWN)
        self.assertTrue(result["all_index_requirements_main_integrated"])
        self.assertTrue(result["projection_parity"])
        self.assertTrue(result["promotion_complete"])
        self.assertEqual(["R10"], result["release_exceptions"])
        self.assertEqual(25, result["summary"]["main_integrated_requirement_count"])
        self.assertEqual(7, result["summary"]["main_integrated_milestone_count"])

    def test_all_released_with_historical_delivery_evidence_is_complete(self) -> None:
        document = copy.deepcopy(self.document)
        requirement_rows = copy.deepcopy(self.requirement_rows)
        spec_statuses = dict(self.spec_statuses)
        document["main_integration"]["release_exceptions"] = []
        for item in document["requirements"]:
            item["status"] = "released"
            requirement_rows[item["id"]]["status"] = "released"
        result = build_promotion_readiness(
            document, requirement_rows, self.milestone_rows, spec_statuses
        )
        self.assertTrue(result["promotion_complete"])
        self.assertEqual(0, result["summary"]["blocker_count"])

    def test_historical_spec_status_drift_is_a_named_blocker(self) -> None:
        spec_statuses = dict(self.spec_statuses)
        spec_statuses["R15"] = "in_progress"
        result = build_promotion_readiness(
            self.document,
            self.requirement_rows,
            self.milestone_rows,
            spec_statuses,
        )
        r15 = next(item for item in result["requirements"] if item["id"] == "R15")
        self.assertIn("historical_spec_delivery_status_mismatch", r15["blockers"])
        self.assertFalse(result["projection_parity"])

    def test_unfinished_dependency_is_reported_on_dependent_node(self) -> None:
        document = copy.deepcopy(self.document)
        r01 = next(item for item in document["requirements"] if item["id"] == "R01")
        r01["status"] = "in_progress"
        rows = copy.deepcopy(self.requirement_rows)
        rows["R01"]["status"] = "in_progress"
        specs = dict(self.spec_statuses)
        specs["R01"] = "in_progress"
        result = build_promotion_readiness(
            document, rows, self.milestone_rows, specs
        )
        r02 = next(item for item in result["requirements"] if item["id"] == "R02")
        self.assertEqual({"R01": "in_progress"}, r02["dependencies"])
        self.assertIn("dependency_not_main_integrated", r02["blockers"])

    def test_undeclared_merged_main_requirement_is_a_blocker(self) -> None:
        document = copy.deepcopy(self.document)
        rows = copy.deepcopy(self.requirement_rows)
        r15 = next(item for item in document["requirements"] if item["id"] == "R15")
        r15["status"] = "merged_main"
        rows["R15"]["status"] = "merged_main"
        result = build_promotion_readiness(
            document, rows, self.milestone_rows, self.spec_statuses
        )
        r15_result = next(
            item for item in result["requirements"] if item["id"] == "R15"
        )
        self.assertIn("undeclared_release_exception", r15_result["blockers"])
        self.assertFalse(result["promotion_complete"])

    def test_every_reason_code_has_specific_remediation(self) -> None:
        expected_actions = {
            "requirement_not_main_integrated": "Complete and merge the requirement",
            "milestone_not_main_integrated": "Complete and merge the milestone",
            "index_markdown_status_mismatch": "Status cell",
            "historical_spec_delivery_status_mismatch": "historical delivery status",
            "undeclared_release_exception": "main_integration.release_exceptions",
            "release_exception_status_mismatch": "exception status exactly match",
            "dependency_not_main_integrated": "every ID listed in dependencies",
            "milestone_parent_mismatch": "Parent requirement cell",
            "milestone_dependencies_mismatch": "Dependencies cell",
        }

        def base() -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, dict[str, object]], dict[str, str]]:
            return (
                {
                    "requirements": [
                        {
                            "id": "R1",
                            "status": "released",
                            "dependencies": [],
                            "milestones": [
                                {"id": "M1", "status": "released", "dependencies": []}
                            ],
                        }
                    ],
                    "main_integration": {"release_exceptions": []},
                },
                {"R1": {"status": "released"}},
                {"M1": {"status": "released", "parent_id": "R1", "dependencies": []}},
                {"R1": "fixed_dev"},
            )

        cases = {}
        document, rows, milestones, statuses = base()
        document["requirements"][0]["status"] = "in_progress"
        rows["R1"]["status"] = "in_progress"
        cases["requirement_not_main_integrated"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        document["requirements"][0]["milestones"][0]["status"] = "in_progress"
        milestones["M1"]["status"] = "in_progress"
        cases["milestone_not_main_integrated"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        rows["R1"]["status"] = "merged_main"
        cases["index_markdown_status_mismatch"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        statuses["R1"] = "in_progress"
        cases["historical_spec_delivery_status_mismatch"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        document["requirements"][0]["status"] = "merged_main"
        rows["R1"]["status"] = "merged_main"
        cases["undeclared_release_exception"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        document["requirements"][0]["status"] = "merged_main"
        rows["R1"]["status"] = "merged_main"
        document["main_integration"]["release_exceptions"] = [{"id": "R1", "status": "released"}]
        cases["release_exception_status_mismatch"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        document["requirements"].insert(0, {"id": "R0", "status": "in_progress", "dependencies": [], "milestones": []})
        rows["R0"] = {"status": "in_progress"}
        statuses["R0"] = "fixed_dev"
        document["requirements"][1]["dependencies"] = ["R0"]
        cases["dependency_not_main_integrated"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        milestones["M1"]["parent_id"] = "R0"
        cases["milestone_parent_mismatch"] = (document, rows, milestones, statuses)

        document, rows, milestones, statuses = base()
        milestones["M1"]["dependencies"] = ["R0"]
        cases["milestone_dependencies_mismatch"] = (document, rows, milestones, statuses)

        for code, (document, rows, milestones, statuses) in cases.items():
            with self.subTest(code=code):
                result = build_promotion_readiness(document, rows, milestones, statuses)
                blocker = next(item for item in result["blockers"] if item["code"] == code)
                self.assertIn(expected_actions[code], blocker["remediation"])


if __name__ == "__main__":
    unittest.main()
