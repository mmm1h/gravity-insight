from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.check_promotion_readiness import (
    REMEDIATION_BY_CODE,
    build_promotion_readiness,
    evaluate_promotion_readiness,
)
from scripts.validate_agent_runtime_requirement_graph import (
    parse_markdown_requirement_table,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"


class PromotionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(INDEX.read_text(encoding="utf-8"))
        markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")
        self.component_rows = parse_markdown_requirement_table(markdown)

    def test_current_repository_reports_completed_promotion_and_r10_exception(self) -> None:
        result = evaluate_promotion_readiness(INDEX, INDEX_MARKDOWN)
        self.assertTrue(result["all_components_owned"])
        self.assertTrue(result["projection_parity"])
        self.assertTrue(result["promotion_complete"])
        self.assertEqual(["mcp-stdio"], result["release_exceptions"])
        self.assertEqual(
            result["summary"]["component_count"],
            result["summary"]["owned_component_count"],
        )

    def test_all_released_with_historical_delivery_evidence_is_complete(self) -> None:
        result = build_promotion_readiness(self.document, self.component_rows)
        self.assertTrue(result["promotion_complete"])
        self.assertEqual(0, result["summary"]["blocker_count"])

    def test_historical_spec_status_drift_is_a_named_blocker(self) -> None:
        rows = copy.deepcopy(self.component_rows)
        rows["sql-explorer"]["maturity"] = "stable"
        result = build_promotion_readiness(self.document, rows)
        component = next(item for item in result["components"] if item["id"] == "sql-explorer")
        self.assertIn("index_markdown_maturity_mismatch", component["blockers"])
        self.assertFalse(result["projection_parity"])

    def test_unfinished_dependency_is_reported_on_dependent_node(self) -> None:
        document = copy.deepcopy(self.document)
        component = next(item for item in document["components"] if item["id"] == "sql-explorer")
        component["machine_sources"] = []
        result = build_promotion_readiness(document, self.component_rows)
        item = next(value for value in result["components"] if value["id"] == "sql-explorer")
        self.assertIn("machine_owner_missing", item["blockers"])

    def test_undeclared_merged_main_requirement_is_a_blocker(self) -> None:
        document = copy.deepcopy(self.document)
        component = next(item for item in document["components"] if item["id"] == "mcp-stdio")
        component["maturity"] = "stable"
        rows = copy.deepcopy(self.component_rows)
        rows["mcp-stdio"]["maturity"] = "stable"
        result = build_promotion_readiness(document, rows)
        item = next(value for value in result["components"] if value["id"] == "mcp-stdio")
        self.assertIn("experimental_not_declared", item["blockers"])
        self.assertFalse(result["promotion_complete"])

    def test_every_reason_code_has_specific_remediation(self) -> None:
        self.assertEqual(
            {
                "machine_owner_missing",
                "bounded_limits_missing",
                "index_markdown_maturity_mismatch",
                "experimental_not_declared",
            },
            set(REMEDIATION_BY_CODE),
        )
        for code, remediation in REMEDIATION_BY_CODE.items():
            with self.subTest(code=code):
                self.assertTrue(remediation)


if __name__ == "__main__":
    unittest.main()
