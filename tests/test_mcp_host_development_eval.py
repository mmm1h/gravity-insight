from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/mcp_host_development_eval.py"
QUESTIONS = ROOT / "tests/fixtures/mcp_host_development_questions.json"
EVIDENCE = ROOT / "tests/fixtures/mcp_host_development_evidence.json"


def _load_evaluator():
    specification = importlib.util.spec_from_file_location(
        "gravity_mcp_host_development_eval", SCRIPT
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load MCP host development evaluator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class MCPHostDevelopmentEvalTests(unittest.TestCase):
    def test_frozen_suite_and_offline_evidence_are_reproducible(self) -> None:
        questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(20, len(questions["cases"]))
        expected = {case["expected_first_choice"] for case in questions["cases"]}
        self.assertEqual(
            {
                "gravity.inspect",
                "gravity.journey_can_run",
                "gravity.capability_describe",
                "gravity.execute",
                "gravity.export",
                "gravity.context_pack",
            },
            {
                choice.split(":", 2)[1]
                for choice in expected
                if choice.startswith("tool:")
            },
        )
        self.assertEqual(10, sum(choice.startswith("resource:") for choice in expected))

        rerun = _load_evaluator().evaluate(QUESTIONS)
        self.assertEqual(evidence["suite_sha256"], rerun["suite_sha256"])
        self.assertEqual(evidence["evaluator"], rerun["evaluator"])
        self.assertEqual(evidence["summary"], rerun["summary"])
        self.assertEqual(evidence["cases"], rerun["cases"])
        self.assertEqual(15, rerun["summary"]["first_choice_correct"])
        self.assertEqual(15, rerun["summary"]["legal_answers"])
        self.assertFalse(rerun["summary"]["first_choice_pass"])
        self.assertTrue(rerun["summary"]["legal_answer_pass"])
        self.assertEqual(120, rerun["summary"]["mcp_rpcs"])
        self.assertEqual(0, rerun["summary"]["internal_http_requests"])
        self.assertEqual(0, rerun["summary"]["production_http_requests"])


if __name__ == "__main__":
    unittest.main()
