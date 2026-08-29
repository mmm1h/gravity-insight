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
            item["id"]: item["status"] for item in self.document["requirements"]
        }

    def test_current_repository_reports_exact_unfinished_requirements(self) -> None:
        result = evaluate_promotion_readiness(INDEX, INDEX_MARKDOWN)
        unfinished = {
            item["id"]
            for item in result["requirements"]
            if "requirement_not_fixed_dev" in item["blockers"]
        }
        self.assertEqual(set(), unfinished)
        self.assertTrue(result["all_index_requirements_fixed_dev"])
        self.assertTrue(result["status_parity"])
        self.assertTrue(result["ready"])

    def test_all_fixed_and_matching_is_ready(self) -> None:
        document = copy.deepcopy(self.document)
        requirement_rows = copy.deepcopy(self.requirement_rows)
        spec_statuses = dict(self.spec_statuses)
        for item in document["requirements"]:
            item["status"] = "fixed_dev"
            requirement_rows[item["id"]]["status"] = "fixed_dev"
            spec_statuses[item["id"]] = "fixed_dev"
        result = build_promotion_readiness(
            document, requirement_rows, self.milestone_rows, spec_statuses
        )
        self.assertTrue(result["ready"])
        self.assertEqual(0, result["summary"]["blocker_count"])

    def test_spec_status_drift_is_a_named_blocker(self) -> None:
        spec_statuses = dict(self.spec_statuses)
        spec_statuses["R15"] = "in_progress"
        result = build_promotion_readiness(
            self.document,
            self.requirement_rows,
            self.milestone_rows,
            spec_statuses,
        )
        r15 = next(item for item in result["requirements"] if item["id"] == "R15")
        self.assertIn("spec_status_mismatch", r15["blockers"])
        self.assertFalse(result["status_parity"])

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
        self.assertIn("dependency_not_fixed_dev", r02["blockers"])


if __name__ == "__main__":
    unittest.main()
