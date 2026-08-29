from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_agent_runtime_requirement_graph import (
    RequirementGraphError,
    validate_markdown_projection,
    validate_requirement_graph,
    validate_repository,
    validate_spec_status_projection,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
R17_SPECIFICATION = ROOT / "specs/agent-runtime/R17-agent-module-package-migration.md"


class AgentRuntimeRequirementGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(INDEX.read_text(encoding="utf-8"))
        self.markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")

    def test_current_requirement_graph_and_markdown_projection_are_valid(self) -> None:
        summary = validate_repository(INDEX, INDEX_MARKDOWN)
        self.assertEqual(
            summary["requirement_count"], summary["markdown_requirement_count"]
        )
        self.assertEqual(summary["requirement_count"], summary["spec_status_count"])
        self.assertEqual(7, summary["markdown_milestone_count"])
        self.assertGreaterEqual(summary["graph_node_count"], summary["requirement_count"])

    def test_missing_requirement_file_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["requirements"][0]["path"] = "missing-requirement.md"
        with self.assertRaisesRegex(RequirementGraphError, "path does not exist"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_unknown_requirement_dependency_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["requirements"][0]["dependencies"] = ["R-NOT-REGISTERED"]
        with self.assertRaisesRegex(RequirementGraphError, "unknown dependency"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_unknown_milestone_dependency_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        r13c = next(item for item in changed["requirements"] if item["id"] == "R13C")
        r13c["milestone_dependencies"] = ["R12-NOT-REGISTERED"]
        with self.assertRaisesRegex(RequirementGraphError, "unknown dependency"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_requirement_cycle_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        r00 = next(item for item in changed["requirements"] if item["id"] == "R00")
        r00["dependencies"] = ["R01"]
        with self.assertRaisesRegex(RequirementGraphError, "R00 -> R01 -> R00"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_duplicate_requirement_or_milestone_id_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["requirements"][0]["milestones"] = [
            {"id": "R01", "status": "fixed_dev", "dependencies": []}
        ]
        with self.assertRaisesRegex(RequirementGraphError, "duplicate requirement ID"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_missing_markdown_requirement_row_is_rejected(self) -> None:
        changed = "\n".join(
            line for line in self.markdown.splitlines() if not line.startswith("| [R00]")
        )
        with self.assertRaisesRegex(RequirementGraphError, "requirement IDs differ"):
            validate_markdown_projection(self.document, changed)

    def test_markdown_requirement_status_drift_is_rejected(self) -> None:
        changed = self.markdown.replace(
            "| [R00](R00-product-constitution.md) | Product constitution and directive governance | - | `fixed_dev` |",
            "| [R00](R00-product-constitution.md) | Product constitution and directive governance | - | `specified` |",
            1,
        )
        with self.assertRaisesRegex(RequirementGraphError, "R00 status differs"):
            validate_markdown_projection(self.document, changed)

    def test_markdown_milestone_status_drift_is_rejected(self) -> None:
        changed = self.markdown.replace(
            "| R12-B | R12 | R12-A | `fixed_dev` |",
            "| R12-B | R12 | R12-A | `in_progress` |",
            1,
        )
        with self.assertRaisesRegex(RequirementGraphError, "R12-B milestone projection"):
            validate_markdown_projection(self.document, changed)

    def test_spec_status_drift_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        r15 = next(item for item in changed["requirements"] if item["id"] == "R15")
        r15["status"] = "in_progress"
        with self.assertRaisesRegex(RequirementGraphError, "R15 spec status differs"):
            validate_spec_status_projection(changed, index_path=INDEX)


class R17DeliveryBaselineEvidenceTests(unittest.TestCase):
    def test_file_counts_are_explicit_immutable_delivery_evidence(self) -> None:
        document = json.loads(INDEX.read_text(encoding="utf-8"))
        requirement = next(
            item for item in document["requirements"] if item["id"] == "R17"
        )
        scope = requirement["scope"]
        self.assertEqual("immutable_delivery_baseline", scope["file_count_evidence_role"])
        self.assertEqual(
            requirement["delivery_acceptance"]["maintenance_baseline"],
            scope["file_count_evidence_revision"],
        )
        specification = " ".join(
            R17_SPECIFICATION.read_text(encoding="utf-8").split()
        )
        self.assertIn("immutable delivery-baseline evidence", specification)
        self.assertIn("not rolling limits on the evolving package", specification)


if __name__ == "__main__":
    unittest.main()
