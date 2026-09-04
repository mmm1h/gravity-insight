from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from scripts.repository_map import (
    MAP_PATH,
    MAP_FACT_SCHEMA,
    MAP_SCHEMA,
    REQUIRED_MAP_FIELDS,
    RepositoryMapError,
    build_repository_map,
    build_task_context,
    canonical_json_bytes,
    classify_change_risk,
    decode_repository_map,
    encode_repository_map,
    load_repository_map,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class RepositoryMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.transport = json.loads(MAP_PATH.read_bytes())
        cls.document = load_repository_map(MAP_PATH)

    def test_checked_in_projection_is_reproducible_and_current(self) -> None:
        first = build_repository_map(ROOT)
        second = build_repository_map(ROOT)
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(first, self.document)

    def test_every_required_field_is_derived_or_has_a_null_reason(self) -> None:
        self.assertEqual(set(REQUIRED_MAP_FIELDS), set(self.document["field_derivation"]))
        for entry in self.document["entries"]:
            self.assertTrue(set(REQUIRED_MAP_FIELDS).issubset(entry))
            for field in REQUIRED_MAP_FIELDS:
                if entry[field] is None:
                    self.assertIn(field, entry["unavailable"])
                else:
                    self.assertNotIn(field, entry["unavailable"])

    def test_map_uses_the_existing_canonical_module_graph(self) -> None:
        graph = self.document["module_graph"]
        self.assertEqual("gravity-insight-runtime-possible-module-dependency-graph.v1", graph["definition_id"])
        self.assertEqual(graph["node_count"], len(graph["edges"]))
        self.assertEqual(graph["edge_count"], sum(len(values) for values in graph["edges"].values()))

    def test_v2_transport_round_trip_preserves_every_v1_fact(self) -> None:
        facts = build_repository_map(ROOT)
        transport = encode_repository_map(facts)
        validate_contract(transport, MAP_SCHEMA)
        decoded = decode_repository_map(transport)
        validate_contract(decoded, MAP_FACT_SCHEMA)
        self.assertEqual(facts["schema_version"], decoded["schema_version"])
        self.assertEqual(facts["counts"], decoded["counts"])
        self.assertEqual(facts["issue_index"], decoded["issue_index"])
        self.assertEqual(facts["module_graph"], decoded["module_graph"])
        self.assertEqual(len(facts["entries"]), len(decoded["entries"]))
        for expected, actual in zip(facts["entries"], decoded["entries"], strict=True):
            self.assertEqual(set(expected), set(actual))
            for field in expected:
                self.assertEqual(expected[field], actual[field], (expected["id"], field))
        self.assertEqual(facts, decoded)

    def test_v2_transport_rejects_out_of_range_table_references(self) -> None:
        invalid_entry = copy.deepcopy(self.transport)
        invalid_entry["entries"]["rows"][0][0] = -(
            len(invalid_entry["entries"]["strings"]) + 1
        )
        invalid_issue = copy.deepcopy(self.transport)
        first_issue = next(iter(invalid_issue["issue_index"]["issues"]))
        invalid_issue["issue_index"]["issues"][first_issue][0][0] = len(
            invalid_issue["issue_index"]["paths"]
        )
        invalid_graph = copy.deepcopy(self.transport)
        invalid_graph["module_graph"]["edges"][0] = [
            len(invalid_graph["module_graph"]["nodes"])
        ]
        for invalid, message in (
            (invalid_entry, "entry string index is out of range"),
            (invalid_issue, "issue path index is out of range"),
            (invalid_graph, "module graph target index is out of range"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(RepositoryMapError, message):
                    decode_repository_map(invalid)

    def test_history_and_archive_are_absent_from_current_indexes(self) -> None:
        current_paths = {
            path
            for entry in self.document["entries"]
            for path in [*(entry["current_docs"] or []), *(entry["source_files"] or [])]
        }
        current_paths.update(
            location["path"]
            for locations in self.document["issue_index"].values()
            for location in locations
        )
        self.assertFalse(any(path.startswith("docs/archive/") for path in current_paths))

    def test_five_context_entry_modes_validate_and_return_runnable_gates(self) -> None:
        cases = (
            ("issue", "19"),
            ("journey", "analysis.event-trend"),
            ("skill", "game-revenue-forecast"),
            ("selector", "analysis.query.spec:event"),
            ("changed_files", ["src/gravity_insight/agents/analysis.py"]),
        )
        for kind, value in cases:
            with self.subTest(kind=kind):
                pack = build_task_context(kind, value, root=ROOT, map_document=self.document)
                validate_contract(pack, "task-context-pack-v1.schema.json")
                self.assertTrue(pack["minimal_references"])
                self.assertTrue(pack["focused_gate"])
                self.assertEqual(6, len(pack["full_gate"]))
                self.assertIn(pack["risk_assessment"]["level"], {"low", "medium", "high"})
                self.assertTrue(pack["risk_assessment"]["selected_commands"])
                self.assertFalse(any("PYTHONPATH" in command for command in pack["full_gate"]))
                self.assertFalse(
                    any(
                        reference["path"].startswith("docs/archive/")
                        for reference in pack["minimal_references"]
                    )
                )
                pytest_commands = [
                    command for command in pack["focused_gate"] if " -m pytest " in command
                ]
                self.assertEqual(1, len(pytest_commands))
                self.assertNotIn(".json", pytest_commands[0])

    def test_changed_file_impact_is_derived_from_reverse_graph(self) -> None:
        pack = build_task_context(
            "changed_files",
            "src/gravity_insight/agents/analysis.py",
            root=ROOT,
            map_document=self.document,
        )
        graph = self.document["module_graph"]["edges"]
        expected = sorted(
            source
            for source, dependencies in graph.items()
            if "gravity_insight.agents.analysis" in dependencies
        )
        self.assertEqual(expected, pack["impact_scope"]["direct_dependents"])
        self.assertGreater(pack["impact_scope"]["transitive_dependents"]["count"], 0)

    def test_graph_owner_change_reaches_the_existing_graph_regression_test(self) -> None:
        pack = build_task_context(
            "changed_files",
            "tests/agent_migration_characterization.py",
            root=ROOT,
            map_document=self.document,
        )
        commands = "\n".join(pack["focused_gate"])
        self.assertIn("tests/test_agent_module_migration_characterization.py", commands)
        self.assertEqual(["debt:14"], pack["matched_entries"])
        self.assertLess(pack["size_comparison"]["pack_bytes"], 100_000)

    def test_current_graph_owner_change_reaches_the_graph_regression_test(self) -> None:
        pack = build_task_context(
            "changed_files",
            "src/gravity_insight/governance/module_graph.py",
            root=ROOT,
            map_document=self.document,
        )
        commands = "\n".join(pack["focused_gate"])
        self.assertIn("tests/test_agent_module_migration_characterization.py", commands)
        self.assertEqual(["debt:14"], pack["matched_entries"])

    def test_risk_classification_uses_the_highest_match_and_fails_closed(self) -> None:
        cases = (
            (["tests/test_provider_subprocess.py"], "low", "self_review"),
            (["scripts/check_installed_wheel_consumer.py"], "medium", "independent_review"),
            (
                [
                    "docs/reference/cli.md",
                    "src/gravity_insight/contracts/routes/registry.json",
                ],
                "high",
                "adversarial_review",
            ),
            (
                ["src/gravity_insight/sql/failures.py"],
                "high",
                "adversarial_review",
            ),
            (["unknown/top-level.file"], "high", "adversarial_review"),
        )
        for paths, level, review in cases:
            with self.subTest(paths=paths):
                result = classify_change_risk(
                    paths,
                    focused_gate=["focused"],
                    full_gate=["full"],
                    python="python",
                )
                self.assertEqual(level, result["level"])
                self.assertEqual(review, result["review_mode"])
        high = classify_change_risk(
            ["src/gravity_insight/contracts/routes/registry.json"],
            focused_gate=["focused"],
            full_gate=["full"],
            python="python",
        )
        self.assertEqual("full", high["selected_commands"][0])
        self.assertTrue(any("run_integrated_validation.py" in item for item in high["selected_commands"]))
        self.assertTrue(any("test_control_plane_lifecycle.py" in item for item in high["selected_commands"]))

    def test_task_context_exposes_risk_specific_command_sets(self) -> None:
        low = build_task_context(
            "changed_files",
            "tests/test_provider_subprocess.py",
            root=ROOT,
            map_document=self.document,
        )
        medium = build_task_context(
            "changed_files",
            "scripts/check_installed_wheel_consumer.py",
            root=ROOT,
            map_document=self.document,
        )
        high = build_task_context(
            "changed_files",
            "src/gravity_insight/contracts/routes/registry.json",
            root=ROOT,
            map_document=self.document,
        )
        self.assertEqual("low", low["risk_assessment"]["level"])
        self.assertEqual("medium", medium["risk_assessment"]["level"])
        self.assertTrue(
            any("check_installed_wheel_consumer.py" in item for item in medium["risk_assessment"]["selected_commands"])
        )
        self.assertEqual("high", high["risk_assessment"]["level"])

    def test_machine_projection_is_compact_and_directly_consumed(self) -> None:
        payload = MAP_PATH.read_bytes()
        parsed = json.loads(payload)
        self.assertEqual("gravity.repository-map.v2", parsed["schema_version"])
        self.assertEqual(self.document, decode_repository_map(parsed))
        self.assertLess(len(payload), 255_000)


if __name__ == "__main__":
    unittest.main()
