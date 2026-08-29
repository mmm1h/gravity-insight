from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.run_integrated_validation import (
    POST_RELEASE_GATES,
    _summary,
    gate_specs,
    integrated_green,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"


class IntegratedValidationTests(unittest.TestCase):
    def test_gate_inventory_matches_canonical_governance(self) -> None:
        contract = json.loads(INDEX.read_text(encoding="utf-8"))[
            "integrated_validation"
        ]
        gates = gate_specs(ROOT / ".venv/Scripts/python.exe", ROOT / "tmp/test")
        names = [gate.name for gate in gates]
        self.assertEqual(contract["included_gates"], names)
        self.assertEqual(len(names), len(set(names)))

    def test_green_requires_clean_dev_same_head_complete_zero_exit_set(self) -> None:
        before = {
            "branch_is_dev": True,
            "clean": True,
            "independent_venv": True,
            "head": "a" * 40,
        }
        after = {"clean": True, "head": "a" * 40}
        gates = [{"exit_code": 0}, {"exit_code": 0}]
        self.assertTrue(
            integrated_green(before, after, gates, complete_gate_set=True)
        )
        for changed in (
            {"before": {**before, "branch_is_dev": False}},
            {"before": {**before, "clean": False}},
            {"before": {**before, "independent_venv": False}},
            {"after": {**after, "clean": False}},
            {"after": {**after, "head": "b" * 40}},
            {"gates": [{"exit_code": 1}]},
            {"complete_gate_set": False},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(
                    integrated_green(
                        changed.get("before", before),
                        changed.get("after", after),
                        changed.get("gates", gates),
                        complete_gate_set=changed.get("complete_gate_set", True),
                    )
                )

    def test_live_pypi_provenance_is_only_a_post_release_exclusion(self) -> None:
        contract = json.loads(INDEX.read_text(encoding="utf-8"))[
            "integrated_validation"
        ]
        self.assertEqual("release_provenance_live_pypi", POST_RELEASE_GATES[0]["name"])
        self.assertEqual(
            ["release_provenance_live_pypi"],
            [item["name"] for item in contract["excluded_post_release_gates"]],
        )
        self.assertIn("release_provenance_offline_fixture", contract["included_gates"])

    def test_log_summary_preserves_required_gate_numbers(self) -> None:
        output = "\n".join(
            [
                "2016 passed, 4754 subtests passed in 1.0s",
                "check: 237 operations, 11 manifests",
                "PASS gravity-insight-quality: debt_files=13, debt_functions=4, debt_complexity=12, debt_operation_literals=9",
                "- Cases: 336",
                "Security compliance hard gate: PASS (violations: 0)",
                "Production HTTP requests: 0",
            ]
        )
        summary = _summary(output)
        self.assertEqual((2016, 4754), (summary["passed"], summary["subtests_passed"]))
        self.assertEqual((237, 11), (summary["operations"], summary["manifests"]))
        self.assertEqual(
            {"files": 13, "functions": 4, "complexity": 12, "operation_literals": 9},
            summary["quality_debt"],
        )
        self.assertEqual((336, "PASS", 0), (
            summary["usability_cases"],
            summary["security_gate"],
            summary["production_http_requests"],
        ))


if __name__ == "__main__":
    unittest.main()
