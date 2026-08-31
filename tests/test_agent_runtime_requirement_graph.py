from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.validate_agent_runtime_requirement_graph import (
    RequirementGraphError,
    validate_markdown_projection,
    validate_repository,
    validate_requirement_graph,
    validate_spec_status_projection,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"


class AgentRuntimeRequirementGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = json.loads(INDEX.read_text(encoding="utf-8"))
        self.markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")

    def test_current_requirement_graph_and_markdown_projection_are_valid(self) -> None:
        summary = validate_repository(INDEX, INDEX_MARKDOWN)
        self.assertEqual("gravity.agent-runtime-components.v1", self.document["schema_version"])
        self.assertEqual(summary["component_count"], summary["markdown_component_count"])
        self.assertGreater(summary["maturity_counts"]["stable"], 0)
        self.assertGreater(summary["maturity_counts"]["bounded"], 0)
        self.assertGreater(summary["maturity_counts"]["experimental"], 0)

    def test_missing_requirement_file_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["components"][0]["machine_sources"][0] = "missing-machine-owner.json"
        with self.assertRaisesRegex(RequirementGraphError, "path does not exist"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_unknown_requirement_dependency_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["components"][0]["reference"] = "missing-reference.md"
        with self.assertRaisesRegex(RequirementGraphError, "path does not exist"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_unknown_milestone_dependency_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["components"][0]["maturity"] = "released"
        with self.assertRaisesRegex(RequirementGraphError, "maturity is invalid"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_requirement_cycle_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["requirements"] = []
        with self.assertRaisesRegex(RequirementGraphError, "component index keys are invalid"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_duplicate_requirement_or_milestone_id_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["components"].append(copy.deepcopy(changed["components"][0]))
        with self.assertRaisesRegex(RequirementGraphError, "duplicate component ID"):
            validate_requirement_graph(changed, index_path=INDEX)

    def test_missing_markdown_requirement_row_is_rejected(self) -> None:
        changed = "\n".join(
            line for line in self.markdown.splitlines() if not line.startswith("| `execution-kernel`")
        )
        with self.assertRaisesRegex(RequirementGraphError, "component IDs differ"):
            validate_markdown_projection(self.document, changed)

    def test_markdown_requirement_status_drift_is_rejected(self) -> None:
        changed = self.markdown.replace(
            "| `execution-kernel` | `stable` |",
            "| `execution-kernel` | `bounded` |",
            1,
        )
        with self.assertRaisesRegex(RequirementGraphError, "maturity differs"):
            validate_markdown_projection(self.document, changed)

    def test_markdown_milestone_status_drift_is_rejected(self) -> None:
        changed = self.markdown + "\n## Milestones\n"
        with self.assertRaisesRegex(RequirementGraphError, "retired Milestones"):
            validate_markdown_projection(self.document, changed)

    def test_spec_status_drift_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        component = next(item for item in changed["components"] if item["id"] == "mcp-stdio")
        component.pop("limits")
        with self.assertRaisesRegex(RequirementGraphError, "limits must state"):
            validate_spec_status_projection(changed, index_path=INDEX)


class R17DeliveryBaselineEvidenceTests(unittest.TestCase):
    def test_file_counts_are_explicit_immutable_delivery_evidence(self) -> None:
        document = json.loads(INDEX.read_text(encoding="utf-8"))
        self.assertNotIn("requirements", document)
        self.assertNotIn("milestones", INDEX_MARKDOWN.read_text(encoding="utf-8").lower())
        package = next(item for item in document["components"] if item["id"] == "package-facade")
        self.assertIn(
            "../../tests/fixtures/agent_module_reference_dispositions.json",
            package["machine_sources"],
        )


if __name__ == "__main__":
    unittest.main()
