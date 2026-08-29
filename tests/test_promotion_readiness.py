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


if __name__ == "__main__":
    unittest.main()
