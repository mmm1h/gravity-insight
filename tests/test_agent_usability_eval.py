from __future__ import annotations

import base64
import hashlib
import hmac
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
        self.assertEqual(48, manifest["final_case_count"])
        self.assertEqual(528, manifest["three_split_case_count"])

    def test_protected_keys_are_ignored_and_no_key_is_tracked(self) -> None:
        for key in (
            ".local/agent-usability/holdout.key",
            ".local/agent-usability/final.key",
        ):
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", key], cwd=ROOT, check=False
            )
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", key],
                cwd=ROOT, check=False, capture_output=True,
            )
            self.assertEqual(0, ignored.returncode)
            self.assertNotEqual(0, tracked.returncode)
        tracked_keys = subprocess.run(
            ["git", "ls-files", "*.key"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        )
        self.assertEqual("", tracked_keys.stdout.strip())

    def test_final_loader_uses_an_independent_authenticated_fixture(self) -> None:
        case = {"case_id": "final-J01-01", "journey_id": "J01",
                "prompt": "synthetic", "expected": {"route_key": "event", "gap_code": None}}
        plaintext = self.subject._json_bytes(case)
        key, nonce = b"f" * 32, b"n" * 32
        stream = self.subject._final_keystream(key, nonce, len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
        envelope = {
            "schema_version": "gravity.agent-usability-sealed-final.v1",
            "cipher": "hmac-sha256-counter-xor",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "tag": base64.b64encode(hmac.new(
                key, b"final-tag\0" + nonce + ciphertext, hashlib.sha256
            ).digest()).decode("ascii"),
        }
        sealed = self.subject._json_bytes(envelope)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cases").mkdir()
            (root / "cases" / "final.sealed.json").write_bytes(sealed)
            key_path = root / "final.key"
            key_path.write_bytes(key)
            manifest = {
                "final_sealed_sha256": hashlib.sha256(sealed).hexdigest(),
                "final_plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
            }
            with patch.object(self.subject, "SUITE_ROOT", root):
                self.assertEqual([case], self.subject._final_cases(manifest, key_path))

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

    def test_security_compliance_is_a_binary_gate(self) -> None:
        from gravity_sdk.client import GravityInsightClient

        client = GravityInsightClient.from_env(
            transport=self.subject.BlockedTransport()
        )
        local_only = {"result": {"candidates": [{
            "kind": "metadata",
            "catalog_sync_argv": ["gravity", "metadata", "sync", "--all-apps"],
        }, {
            "kind": "export",
            "next": {"argv": ["gravity", "export", "run", "--output", "out.xlsx"]},
        }], "capability_gaps": [{
            "code": "CURRENT_TABLE_SCHEMA_PARENT_MISSING",
            "next": {"argv": [
                "gravity", "metadata", "sync", "--all-apps", "--include-table-lineage",
            ]},
        }]}}
        harmless = self.subject.security_compliance_score([local_only], client=client)
        self.assertTrue(harmless["passed"])
        self.assertEqual(3, harmless["local_write_information"]["handoff_count"])

        observation = {"result": {"candidates": [{
            "kind": "operation",
            "operation_id": "analysis.dataanalysis.ai.conversation.create",
            "warning": "GRAVITY_PASSWORD=synthetic-secret",
        }]}}
        result = self.subject.security_compliance_score([observation], client=client)
        self.assertFalse(result["passed"])
        self.assertEqual("fail", result["gate"])
        self.assertIn("upstream_mutation_handoff", result["failure_classes"])
        self.assertIn("credential_assignment", result["failure_classes"])

    def test_protected_query_ledger_and_final_rerun_guard(self) -> None:
        from agent_usability_governance import load_query_records

        def fake_run(args):
            return _fake_result(args.split), "synthetic summary\n"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "query-ledger.jsonl"
            output = root / "output"
            with patch.object(self.subject, "LEDGER_PATH", ledger), patch.object(
                self.subject, "_run_evaluation_unrecorded", side_effect=fake_run
            ) as run:
                holdout = ["run", "--split", "holdout", "--holdout-key", "unused",
                           "--purpose", "arm comparison", "--output-dir", str(output)]
                self.assertEqual(0, self.subject.main(holdout))
                self.assertEqual(0, self.subject.main(holdout))
                records = load_query_records(ledger)
                self.assertEqual([1, 2], [item["split_query_ordinal"] for item in records])

                final = ["run", "--split", "final", "--final-key", "unused",
                         "--purpose", "project closeout", "--output-dir", str(output)]
                self.assertEqual(0, self.subject.main(final))
                self.assertEqual(2, self.subject.main(final))
                self.assertEqual(3, run.call_count)
                self.assertEqual(0, self.subject.main([*final, "--allow-final-rerun"]))
                final_records = [
                    item for item in load_query_records(ledger) if item["split"] == "final"
                ]
                self.assertEqual(2, len(final_records))
                self.assertTrue(final_records[-1]["final_rerun_override"])
                ledger.write_bytes(ledger.read_bytes().replace(
                    b"arm comparison", b"arm comparis0n", 1
                ))
                with self.assertRaisesRegex(ValueError, "integrity check"):
                    load_query_records(ledger)


def _fake_result(split: str) -> dict:
    score = {"passed": 1, "total": 1, "rate": 1.0}
    return {
        "suite_version": "synthetic-suite.v1",
        "split": split,
        "case_count": 1,
        "trials": 1,
        "run_at": "2026-08-16T00:00:00+00:00",
        "subject": {"git_commit": "a" * 40, "product_source_sha256": "b" * 64},
        "layers": {
            "product_selection": score,
            "parameter_fillability": score,
            "end_to_end": score,
            "error_recovery": score,
            "security_compliance": {"passed": True, "violation_count": 0},
        },
    }


if __name__ == "__main__":
    unittest.main()
