from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent_usability_eval.py"


def _load_module():
    specification = importlib.util.spec_from_file_location(
        "gravity_agent_usability_eval", SCRIPT
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load Agent usability evaluator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class AgentUsabilityEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = _load_module()

    def test_public_suite_is_frozen_and_complete(self) -> None:
        manifest, cases = self.subject.load_cases("development", None)
        self.assertEqual(240, len(cases))
        self.assertEqual(48, len({item["journey_id"] for item in cases}))
        self.assertEqual(480, manifest["total_case_count"])

    def test_fixed_holdout_key_path_is_ignored_and_untracked(self) -> None:
        key = ".local/agent-usability/holdout.key"
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", key], cwd=ROOT, check=False
        )
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", key],
            cwd=ROOT, check=False, capture_output=True,
        )
        self.assertEqual(0, ignored.returncode)
        self.assertNotEqual(0, tracked.returncode)

    def test_route_parameter_and_terminal_layers_are_independent(self) -> None:
        case = {
            "expected": {
                "route_key": "order_directory",
                "gap_code": None,
            }
        }
        card = {
            "kind": "composite",
            "composite": "order_directory",
            "required_inputs": ["app", "date"],
            "missing_inputs": ["app", "date"],
            "input_template": {"app": "<app>", "date": "<date>"},
            "natural_language_auto_execute": False,
            "plan_executable": True,
            "plan_node": {"kind": "composite"},
            "call_bound": {"scenarios": [{"input_sources": [{"inputs": ["app"]}]}]},
        }
        result = {"candidates": [card], "capability_gaps": []}
        selected, _, observed = self.subject.route_score(case, result)
        self.assertTrue(selected)
        self.assertEqual((True, "fillable"), self.subject.parameter_score(
            "order_directory", observed
        ))
        broken = {**card, "call_bound": {"scenarios": []}}
        self.assertEqual((False, "catalog_source_missing"),
                         self.subject.parameter_score("order_directory", broken))
        self.assertEqual((None, "skipped_production"),
                         self.subject.terminal_score(case, result))

    def test_exact_actionable_gap_is_an_offline_terminal(self) -> None:
        case = {"expected": {
            "route_key": "analysis_defaults_gap",
            "gap_code": "ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING",
        }}
        result = {
            "offline": True,
            "network_called": False,
            "candidates": [],
            "capability_gaps": [{
                "code": "ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING",
                "next_action": "Capture one shape-only response.",
            }],
        }
        self.assertTrue(self.subject.route_score(case, result)[0])
        self.assertEqual((True, "explicit_gap"),
                         self.subject.terminal_score(case, result))

    def test_recovery_suite_uses_no_transport(self) -> None:
        from gravity_sdk.client import GravityInsightClient

        blocker = self.subject.BlockedTransport()
        with tempfile.TemporaryDirectory() as cache, patch.dict(os.environ, {
            "GRAVITY_CACHE_HOME": cache,
            "LOCALAPPDATA": cache,
            "XDG_CACHE_HOME": cache,
        }):
            client = GravityInsightClient.from_env(transport=blocker)
            result, calls = self.subject.recovery_score(client)
        self.assertEqual(5, result["total"])
        self.assertGreaterEqual(result["passed"], 4)
        self.assertEqual(9, calls)
        self.assertEqual(0, blocker.attempts)

    def test_compare_rejects_different_suite_identity(self) -> None:
        before = {"suite_version": "v1", "suite_hashes": {}, "split": "all",
                  "case_count": 1, "trials": 4}
        after = {**before, "suite_version": "v2"}
        with self.assertRaisesRegex(ValueError, "not comparable"):
            self.subject.compare_results(before, after)


if __name__ == "__main__":
    unittest.main()
