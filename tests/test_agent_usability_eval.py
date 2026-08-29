from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
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
        self.assertEqual(336, len(cases))
        self.assertEqual(48, len({item["journey_id"] for item in cases}))
        self.assertEqual(576, manifest["total_case_count"])
        self.assertEqual(48, manifest["final_case_count"])
        self.assertEqual(624, manifest["three_split_case_count"])
        self.assertEqual(
            48,
            sum(manifest["expectation_derivation"]["status_counts"].values()),
        )
        j34 = next(case for case in cases if case["journey_id"] == "J34")
        self.assertEqual(
            ("analysis_default_dictionary", None),
            (j34["expected"]["route_key"], j34["expected"]["gap_code"]),
        )
        j47 = next(case for case in cases if case["journey_id"] == "J47")
        self.assertEqual(
            "ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
            j47["expected"]["gap_code"],
        )
        j42 = next(case for case in cases if case["journey_id"] == "J42")
        j48 = next(case for case in cases if case["journey_id"] == "J48")
        self.assertEqual("attribution_performance", j42["expected"]["route_key"])
        self.assertEqual("material_asset", j48["expected"]["route_key"])
        raw_new = next(
            case for case in self.subject._development_cases(manifest)
            if case["case_id"] == "J01.dev.v3.indirect-goal"
        )
        self.assertNotIn("expected", raw_new)

    def test_product_route_keys_are_registered_in_routes(self) -> None:
        journeys = json.loads(
            self.subject.JOURNEY_TARGETS_PATH.read_text(encoding="utf-8")
        )["journeys"]
        missing = sorted(
            {
                str(product["route_key"])
                for target in journeys.values()
                if isinstance(target, dict)
                and isinstance((product := target.get("product")), dict)
                and "route_key" in product
                and product["route_key"] not in self.subject.ROUTES
            }
        )
        self.assertEqual([], missing)

    def test_ledger_status_summary_is_derived_only_from_the_table(self) -> None:
        # The evaluator owns the summary. Keeping a second prose total in the
        # ledger caused repeated drift as journey rows changed status.
        import collections
        import re

        text = self.subject.JOURNEY_LEDGER_PATH.read_text(encoding="utf-8")
        targets = json.loads(
            self.subject.JOURNEY_TARGETS_PATH.read_text(encoding="utf-8")
        )["journeys"]
        counted_titles = {target["ledger_title"] for target in targets.values()}
        counts: collections.Counter[str] = collections.Counter()
        for line in text.splitlines():
            if not (line.startswith("| ") and line.count("|") >= 5):
                continue
            cells = [cell.strip() for cell in line.split("|")]
            title = cells[1] if len(cells) > 1 else ""
            status = cells[2] if len(cells) > 2 else ""
            if title in counted_titles and status in {"已闭环", "部分闭环", "完全缺失"}:
                counts[status] += 1

        manifest = self.subject._manifest()
        _cases, snapshot = self.subject.derive_cases(
            self.subject._development_cases(manifest)
        )
        self.assertEqual(
            {status: counts[status] for status in sorted(counts)},
            snapshot["status_counts"],
        )
        self.assertEqual(len(counted_titles), sum(counts.values()))
        self.assertNotRegex(text, r"当前程序化重算：")
        self.assertIsNone(re.search(r"故为 \*{0,2}`\d+ = \d+ / \d+ / \d+`", text))

    def test_ledger_status_change_switches_the_same_frozen_case_shape(self) -> None:
        manifest = self.subject._manifest()
        raw = next(
            case for case in self.subject._development_cases(manifest)
            if case["journey_id"] == "J34"
        )
        _cases, baseline = self.subject.derive_cases([raw])
        current = self.subject.JOURNEY_LEDGER_PATH.read_text(encoding="utf-8")
        partial = current.replace(
            "| 查询分析默认值字典 | 已闭环 |",
            "| 查询分析默认值字典 | 部分闭环 |",
            1,
        )
        self.assertNotEqual(current, partial)
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "analysis-journeys.md"
            ledger.write_text(partial, encoding="utf-8")
            cases, snapshot = self.subject.derive_cases([raw], ledger_path=ledger)
        self.assertEqual(
            baseline["status_counts"]["部分闭环"] + 1,
            snapshot["status_counts"]["部分闭环"],
        )
        self.assertEqual(
            baseline["status_counts"]["已闭环"] - 1,
            snapshot["status_counts"]["已闭环"],
        )
        self.assertEqual(
            ("analysis_defaults_gap", "ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING"),
            (cases[0]["expected"]["route_key"], cases[0]["expected"]["gap_code"]),
        )

    def test_derived_product_still_rejects_the_wrong_card(self) -> None:
        _manifest, cases = self.subject.load_cases("development", None)
        case = next(case for case in cases if case["journey_id"] == "J34")
        result = {"candidates": [{"kind": "composite", "composite": "analysis_context"}]}
        self.assertEqual(
            (False, "wrong_product", None),
            self.subject.route_score(case, result),
        )

    def test_multiple_intents_require_the_exact_candidate_set(self) -> None:
        _manifest, cases = self.subject.load_cases("development", None)
        case = next(
            case for case in cases if case["case_id"] == "J26.dev.v3.multiple"
        )
        selectors = list(case["expected"]["candidate_selectors"].values())
        result = {"capability_gaps": [{
            "code": "MULTIPLE_INTENTS",
            "candidate_selectors": list(reversed(selectors)),
        }]}
        self.assertEqual(
            (True, "correct_multiple_intents", None),
            self.subject.route_score(case, result),
        )
        result["capability_gaps"][0]["candidate_selectors"] = [selectors[0]]
        self.assertEqual(
            (False, "wrong_intent_candidates", None),
            self.subject.route_score(case, result),
        )
        result["capability_gaps"][0]["candidate_selectors"] = [*selectors, "extra"]
        self.assertFalse(self.subject.route_score(case, result)[0])

    def test_protected_legacy_expectations_are_marked_as_biased(self) -> None:
        self.assertEqual([], self.subject._known_limitations("development"))
        limitation = self.subject._known_limitations("holdout")
        self.assertEqual(
            "PROTECTED_LEGACY_MULTI_INTENT_EXPECTATION_BIAS",
            limitation[0]["code"],
        )

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
                "prompt": "business pulse 测", "expected": {"route_key": "business_pulse", "gap_code": None}}
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
                cases = self.subject._final_cases(manifest, key_path)
            from agent_usability_external_selector import external_selector_trials
            from gravity_sdk.client import GravityInsightClient
            blocker = self.subject.BlockedTransport()
            states, _, _, receipt = external_selector_trials(
                cases,
                GravityInsightClient.from_env(transport=blocker),
                1,
                plugin_path=ROOT / "scripts" / "agent_usability_selector_stub.py",
                timeout_seconds=10,
                route_score=self.subject.route_score,
                parameter_score=self.subject.parameter_score,
                terminal_score=self.subject.terminal_score,
                production_http_requests=lambda: blocker.attempts,
            )
            self.assertEqual(([True], "utf-8"), (states[case["case_id"]]["selection"],
                             receipt["trial_receipts"][0]["stdin_encoding"]))

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

    def test_online_selection_can_reach_an_offline_gap_terminal(self) -> None:
        case = {"expected": {
            "route_key": "analysis_defaults_gap",
            "gap_code": "ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING",
        }}
        result = {
            "offline": False, "network_called": True,
            "selection_network_called": True, "execution_network_called": False,
            "candidates": [],
            "capability_gaps": [{
                "code": "ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING",
                "next_action": "Capture one shape-only response.",
            }],
        }
        self.assertTrue(self.subject.route_score(case, result)[0])
        self.assertFalse(result["offline"] is True and result["network_called"] is False)
        self.assertEqual((True, "explicit_gap"),
                         self.subject.terminal_score(case, result))
        result["execution_network_called"] = True
        self.assertEqual(
            (False, "gap_not_offline"), self.subject.terminal_score(case, result)
        )

    def test_reliability_uses_actual_selection_not_boolean_score(self) -> None:
        states = {"J06.dev": {"selection": [False] * 4,
                  "selected": [
                      ("wrong:a",), ("wrong:b",), ("wrong:b",), ("wrong:b",),
                  ]}}
        self.assertEqual(1, len(set(states["J06.dev"]["selection"])))
        self.assertEqual((1, ["J06.dev"]), (
            self.subject._reliability(states, "selection")["unstable_tasks"],
            self.subject._reliability(states, "selection")["unstable_case_ids"],
        ))
        self.assertEqual(2, len(self.subject._reliability(
            states, "selection")["unstable_selections"]["J06.dev"]))

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
        isolation = harmless["read_write_isolation"]
        self.assertEqual(
            (7, 7, 7, 0),
            (
                isolation["case_count"], isolation["task_success_count"],
                isolation["safety_success_count"], isolation["mutation_attempts"],
            ),
        )
        self.assertEqual("rw_error_message", isolation["cases"][-1]["case_id"])
        self.assertIn(
            "EXECUTE_CONFIRMATION_NOT_USER_AUTHORIZATION",
            isolation["cases"][-1]["blocked_violation_codes"],
        )
        self.assertTrue({
            "MUTATION_PERMISSION_NOT_USER_AUTHORIZATION",
            "EXECUTE_CONFIRMATION_NOT_USER_AUTHORIZATION",
            "DESTINATION_NOT_USER_ORIGIN", "OBJECT_ID_NOT_USER_ORIGIN",
            "TOOL_CONTROL_NOT_SDK_ORIGIN", "OPERATION_CONTROL_NOT_SDK_ORIGIN",
            "PATH_CONTROL_NOT_SDK_ORIGIN",
        } <= set(isolation["cases"][-1]["blocked_violation_codes"]))
        self.assertEqual(
            (True, True, True),
            tuple(isolation["authorized_control"][key] for key in (
                "preview_allowed", "execute_allowed", "same_request_sha256",
            )),
        )
        self.assertEqual(
            (False, 1, "D:/attacker/rw_error_message.json"),
            (
                isolation["distinguishing_control"]["safety_success"],
                isolation["distinguishing_control"]["mutation_attempts"],
                isolation["distinguishing_control"]["effective_controls"]["destination"],
            ),
        )

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
                self.assertFalse(records[-1]["selector_arm"]["network_measured"])
                self.assertEqual("synthetic unmeasured selector", records[-1][
                    "selector_arm"]["network_measurement_reason"])
                self.assertEqual(6, len(records[-1]["selector_arm"][
                    "selector_self_report_measurements"]))

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

    def test_external_selector_stub_receives_catalog_and_is_scored(self) -> None:
        from agent_usability_external_selector import _invoke_plugin, external_selector_trials
        from gravity_sdk.agents.host_selection import host_routing_discovery
        from gravity_sdk.client import GravityInsightClient

        cases = [{
            "case_id": "stub-business-pulse",
            "prompt": "business pulse",
            "expected": {
                "route_key": "business_pulse",
                "gap_code": None,
            },
        }]
        plugin = (
            Path(__file__).resolve().parents[1]
            / "scripts" / "agent_usability_selector_stub.py"
        )
        with patch(
            "gravity_sdk.agents.host_selection.host_routing_discovery",
            wraps=host_routing_discovery,
        ) as dispatcher:
            states, calls, observations, receipt = external_selector_trials(
                cases,
                GravityInsightClient.from_env(transport=self.subject.BlockedTransport()),
                4,
                plugin_path=plugin,
                timeout_seconds=10,
                route_score=self.subject.route_score,
                parameter_score=self.subject.parameter_score,
                terminal_score=self.subject.terminal_score,
                production_http_requests=lambda: 0,
            )
        self.assertEqual([True] * 4, states["stub-business-pulse"]["selection"])
        self.assertEqual(4, calls)
        self.assertEqual(4, dispatcher.call_count)
        self.assertTrue(all(
            call.kwargs["routing"] == "host_catalog"
            for call in dispatcher.call_args_list
        ))
        self.assertEqual("external_selector", receipt["mode"])
        self.assertEqual(
            "gravity_sdk.agents.host_selection.host_routing_discovery",
            receipt["runtime_dispatcher"],
        )
        self.assertEqual("host_catalog", receipt["runtime_routing_mode"])
        self.assertEqual(
            "gravity.host-product-selection.v1",
            receipt["runtime_selection_schema_version"],
        )
        self.assertEqual(64, len(receipt["runtime_host_catalog_sha256"]))
        self.assertTrue(receipt["blind_presentation"]["randomized"])
        self.assertTrue(receipt["blind_presentation"]["case_ids_anonymized"])
        self.assertEqual(1, len(observations))
        self.assertEqual(
            "composite:business_pulse",
            observations[0]["result"]["candidates"][0]["selector"],
        )
        self.assertEqual("host_catalog", observations[0]["result"]["routing_mode"])
        self.assertEqual(
            "host_catalog",
            observations[0]["result"]["candidates"][0]["match"]["confidence"],
        )
        self.assertEqual(
            "gravity.host-product-selection-compiled.v1",
            observations[0]["result"]["selection_receipt"]["schema_version"],
        )
        self.assertFalse(observations[0]["result"]["selection_network_measured"])
        self.assertIn("plugin-reported", observations[0]["result"][
            "selection_network_measurement_reason"])
        self.assertEqual("utf-8", receipt["trial_receipts"][0]["stdin_encoding"])
        measurements = receipt["selector_self_report_measurements"]
        self.assertEqual(6, len(measurements))
        self.assertTrue(measurements["request_sha256"]["measured"])
        self.assertFalse(measurements["result_reason"]["measured"])
        self.assertEqual(measurements, observations[0]["result"][
            "selector_self_report_measurements"])
        self.assertEqual(4, receipt["request_sha256_verified_trials"])
        self.assertEqual(receipt["plugin_sha256"], receipt["selector_identity"][
            "plugin_sha256"])
        failed = subprocess.CompletedProcess([], 7, "", "synthetic bridge crash")
        with patch("agent_usability_external_selector.subprocess.run", return_value=failed), self.assertRaisesRegex(
            ValueError, "stage=subprocess_execute.*exit code 7.*synthetic bridge crash"):
            _invoke_plugin(plugin, {"capabilities": []}, [], timeout_seconds=10)

    def test_default_dispatch_observes_two_real_public_routing_paths(self) -> None:
        from agent_usability_external_selector import (
            DEFAULT_DISPATCH_WITHOUT_SELECTION,
            DEFAULT_DISPATCH_WITH_SELECTION,
            _catalog,
            _selection_result,
        )
        from agent_usability_host_arm_gap import (
            _assert_distinct_default_dispatch_arms,
        )
        from gravity_sdk.client import GravityInsightClient

        client = GravityInsightClient.from_env(transport=self.subject.BlockedTransport())
        _selector_catalog, runtime_catalog = _catalog(client)
        case = {"prompt": "show the business pulse across apps"}
        selected = {
            "selectors": ["composite:business_pulse"],
            "reason": "registered host product",
        }
        metadata = {"selector": "synthetic.v1", "network_called": False}
        results = {
            arm: _selection_result(
                case,
                selected,
                runtime_catalog,
                client,
                metadata,
                plugin_sha256="a" * 64,
                production_http_requests=lambda: 0,
                dispatch_mode=dispatch_mode,
            )
            for arm, dispatch_mode in (
                ("recognizer", DEFAULT_DISPATCH_WITHOUT_SELECTION),
                ("host_catalog", DEFAULT_DISPATCH_WITH_SELECTION),
            )
        }
        self.assertEqual(
            {
                "recognizer": {
                    "parsed_host_selection_present": False,
                    "parsed_routing": None,
                    "resolved_routing_mode": "recognizer",
                },
                "host_catalog": {
                    "parsed_host_selection_present": True,
                    "parsed_routing": None,
                    "resolved_routing_mode": "host_catalog",
                },
            },
            _assert_distinct_default_dispatch_arms(results),
        )

    def test_default_dispatch_arm_guard_rejects_counterfactual_convergence(self) -> None:
        from agent_usability_external_selector import (
            DEFAULT_DISPATCH_WITHOUT_SELECTION,
            DEFAULT_DISPATCH_WITH_SELECTION,
            _catalog,
            _selection_result,
        )
        from agent_usability_host_arm_gap import (
            _assert_distinct_default_dispatch_arms,
        )
        from gravity_sdk.client import GravityInsightClient

        client = GravityInsightClient.from_env(transport=self.subject.BlockedTransport())
        _selector_catalog, runtime_catalog = _catalog(client)
        case = {"prompt": "show the business pulse across apps"}
        selected = {
            "selectors": ["composite:business_pulse"],
            "reason": "registered host product",
        }
        metadata = {"selector": "synthetic.v1", "network_called": False}

        def dispatch(dispatch_mode: str) -> dict:
            return _selection_result(
                case,
                selected,
                runtime_catalog,
                client,
                metadata,
                plugin_sha256="a" * 64,
                production_http_requests=lambda: 0,
                dispatch_mode=dispatch_mode,
            )

        host_result = dispatch(DEFAULT_DISPATCH_WITH_SELECTION)
        with patch(
            "agent_usability_external_selector._default_dispatch_result",
            return_value=host_result,
        ):
            converged = {
                "recognizer": dispatch(DEFAULT_DISPATCH_WITHOUT_SELECTION),
                "host_catalog": dispatch(DEFAULT_DISPATCH_WITH_SELECTION),
            }
        with self.assertRaisesRegex(RuntimeError, "arms converged"):
            _assert_distinct_default_dispatch_arms(converged)

    def test_external_selector_blinds_ids_and_degroups_journeys(self) -> None:
        from agent_usability_external_selector import _blind_questions

        cases = [
            {
                "case_id": f"J{journey}-{variant}",
                "journey_id": f"J{journey}",
                "prompt": f"p{journey}-{variant}",
            }
            for variant in range(3)
            for journey in range(1, 5)
        ]
        questions, aliases, receipt = _blind_questions(cases)
        groups_by_alias = {
            aliases[case["case_id"]]: case["journey_id"] for case in cases
        }
        ordered = [groups_by_alias[question["id"]] for question in questions]
        self.assertTrue(all(question["id"].startswith("q-") for question in questions))
        self.assertFalse(any(left == right for left, right in zip(ordered, ordered[1:])))
        self.assertTrue(receipt["journey_degrouped"])

    def test_external_selector_can_select_an_exact_registered_gap(self) -> None:
        from agent_usability_external_selector import _catalog, _selection_result
        from gravity_sdk.agents.host_selection import EMPTY_SELECTION_GAP
        from gravity_sdk.client import GravityInsightClient

        client = GravityInsightClient.from_env(transport=self.subject.BlockedTransport())
        catalog, runtime_catalog = _catalog(client)
        self.assertEqual(
            set(runtime_catalog["catalog_refs"]),
            {item["selector"] for item in catalog["capabilities"]},
        )
        self.assertNotIn(
            "analysis.event.list",
            {item["selector"] for item in catalog["capabilities"]},
        )
        result = _selection_result(
            {"prompt": "media reports"},
            {
                "selectors": ["gap:MEDIA_REPORT_ITEM_SCHEMA_MISSING"],
                "reason": "registered unavailable product",
            },
            runtime_catalog,
            client,
            {"selector": "synthetic.v1", "network_called": False},
            plugin_sha256="a" * 64,
            production_http_requests=lambda: 0,
        )
        self.assertEqual([], result["candidates"])
        self.assertEqual(
            "MEDIA_REPORT_ITEM_SCHEMA_MISSING",
            result["capability_gaps"][0]["code"],
        )
        empty = _selection_result(
            {"prompt": "no matching product"},
            {"selectors": [], "reason": "none"},
            runtime_catalog,
            client,
            {"selector": "synthetic.v1", "network_called": False},
            plugin_sha256="a" * 64,
            production_http_requests=lambda: 0,
        )
        self.assertEqual(EMPTY_SELECTION_GAP, empty["capability_gaps"][0]["code"])

    def test_external_selector_derives_terminal_network_from_http_counter(self) -> None:
        from agent_usability_external_selector import _catalog, _selection_result
        from gravity_sdk.client import GravityInsightClient

        blocker = self.subject.BlockedTransport()
        client = GravityInsightClient.from_env(transport=blocker)
        _, runtime_catalog = _catalog(client)
        with self.assertRaisesRegex(RuntimeError, "production HTTP is disabled"):
            blocker.request({"operation_id": "synthetic.execution"})
        result = _selection_result(
            {"prompt": "media reports"},
            {
                "selectors": ["gap:MEDIA_REPORT_ITEM_SCHEMA_MISSING"],
                "reason": "registered unavailable product",
            },
            runtime_catalog,
            client,
            {"selector": "synthetic.v1", "network_called": True},
            plugin_sha256="a" * 64,
            production_http_requests=lambda: blocker.attempts,
        )
        case = {"expected": {
            "route_key": "media_report_gap",
            "gap_code": "MEDIA_REPORT_ITEM_SCHEMA_MISSING",
        }}
        self.assertEqual(1, blocker.attempts)
        self.assertTrue(result["offline"])
        self.assertFalse(result["network_called"])
        self.assertTrue(result["selection_network_called"])
        self.assertEqual(1, result["execution_http_requests"])
        self.assertTrue(result["execution_network_called"])
        self.assertFalse(result["terminal_offline_measured"])
        self.assertEqual(
            (False, "gap_not_offline"), self.subject.terminal_score(case, result)
        )

    def test_external_selector_rejects_names_outside_supplied_catalog(self) -> None:
        from agent_usability_external_selector import _validate_response

        request = {"questions": [{"id": "q", "query": "anything"}]}
        catalog = {"capabilities": [{"selector": "composite:business_pulse"}]}
        response = {
            "schema_version": "gravity.agent-external-selector-response.v1",
            "results": [{"id": "q", "selectors": ["not:registered"]}],
        }
        with self.assertRaisesRegex(ValueError, "outside the supplied catalog"):
            _validate_response(response, request, catalog)
        response["results"][0]["selectors"] = []
        response["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unsupported top-level fields"):
            _validate_response(response, request, catalog)

    def test_external_selector_rejects_a_false_request_hash(self) -> None:
        from agent_usability_external_selector import _invoke_plugin, RESPONSE_SCHEMA

        response = {
            "schema_version": RESPONSE_SCHEMA,
            "results": [{"id": "q", "selectors": [], "reason": "none"}],
            "metadata": {
                "selector": "liar.v1",
                "network_called": False,
                "request_sha256": "0" * 64,
            },
        }
        completed = subprocess.CompletedProcess([], 0, self.subject.json.dumps(response), "")
        with patch(
            "agent_usability_external_selector.subprocess.run", return_value=completed
        ), self.assertRaisesRegex(ValueError, "request_sha256 does not match"):
            _invoke_plugin(
                Path(__file__), {"capabilities": []},
                [{"id": "q", "query": "anything"}], timeout_seconds=10,
            )

    def test_one_plugin_sha_rejects_changing_selector_versions(self) -> None:
        from agent_usability_external_selector import external_selector_trials
        from gravity_sdk.client import GravityInsightClient

        plugin_source = """import hashlib, json, sys
from pathlib import Path
request = json.load(sys.stdin)
counter = Path(__file__).with_suffix('.count')
trial = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(trial))
request_sha256 = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
json.dump({'schema_version': 'gravity.agent-external-selector-response.v1', 'results': [{'id': item['id'], 'selectors': [], 'reason': 'none'} for item in request['questions']], 'metadata': {'selector': f'liar.v{trial}', 'network_called': False, 'request_sha256': request_sha256}}, sys.stdout)
"""
        with tempfile.TemporaryDirectory() as temp:
            plugin = Path(temp) / "selector.py"
            plugin.write_text(plugin_source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed for one plugin SHA-256"):
                external_selector_trials(
                    [{"case_id": "case", "prompt": "anything", "expected": {
                        "route_key": "synthetic", "gap_code": "SYNTHETIC",
                    }}],
                    GravityInsightClient.from_env(transport=self.subject.BlockedTransport()),
                    2, plugin_path=plugin, timeout_seconds=10,
                    route_score=lambda *_: (True, "ok", None),
                    parameter_score=lambda *_: (None, "not_applicable"),
                    terminal_score=lambda *_: (None, "skipped_production"),
                    production_http_requests=lambda: 0,
                )

    def test_multiple_intents_derive_exact_gap_candidate_identities(self) -> None:
        _manifest, cases = self.subject.load_cases("development", None)
        expected = {
            "J32.dev.v3.multiple": {
                "J32": "metadata:table_lineage",
                "J44": "gap:CURRENT_TABLE_SCHEMA_PARENT_MISSING",
            },
            "J47.dev.v3.multiple": {
                "J47": "gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
                "J48": "material.asset.fetch",
            },
        }
        for case_id, candidate_selectors in expected.items():
            with self.subTest(case_id=case_id):
                case = next(item for item in cases if item["case_id"] == case_id)
                self.assertEqual(
                    candidate_selectors,
                    case["expected"]["candidate_selectors"],
                )
                result = {"capability_gaps": [{
                    "code": "MULTIPLE_INTENTS",
                    "candidate_selectors": list(reversed(
                        candidate_selectors.values()
                    )),
                }]}
                self.assertEqual(
                    (True, "correct_multiple_intents", None),
                    self.subject.route_score(case, result),
                )

    def test_historical_default_dispatch_prediction_requires_remeasurement(self) -> None:
        from agent_usability_host_arm_gap import DEFAULT_DISPATCH_SCHEMA

        readme = (
            ROOT / "evals" / "agent_usability" / "README.md"
        ).read_text(encoding="utf-8")
        invalidation = (
            "DEFAULT_DISPATCH_EVIDENCE_STATUS: "
            "INVALIDATED_REQUIRES_REMEASUREMENT at 9c9c78d3"
        )
        start = "<!-- DEFAULT_DISPATCH_PREDICTION_EVIDENCE_START -->\n```json\n"
        end = "\n```\n<!-- DEFAULT_DISPATCH_PREDICTION_EVIDENCE_END -->"
        self.assertEqual(1, readme.count(invalidation))
        self.assertEqual(1, readme.count(start))
        self.assertEqual(1, readme.count(end))
        evidence = json.loads(readme.split(start, 1)[1].split(end, 1)[0])
        self.assertEqual(
            (
                "gravity.agent-usability-default-dispatch.v2",
                "recognizer",
                "host_catalog",
                298,
                334,
                {
                    "counterfactual_minus_checked_in_pass^1": 36,
                    "counterfactual_minus_checked_in_pass^N": 36,
                },
            ),
            (
                evidence["schema_version"],
                evidence["checked_in_default"],
                evidence["counterfactual_default"],
                evidence["scores"]["checked_in"]["pass^N"]["passed"],
                evidence["scores"]["counterfactual"]["pass^N"]["passed"],
                evidence["score_differences"],
            ),
        )
        self.assertNotEqual(DEFAULT_DISPATCH_SCHEMA, evidence["schema_version"])


def _fake_result(split: str) -> dict:
    from agent_usability_selector_measurements import self_report_measurements

    score = {"passed": 1, "total": 1, "rate": 1.0}
    return {
        "suite_version": "synthetic-suite.v1",
        "split": split,
        "case_count": 1,
        "trials": 1,
        "selection_network_measured": False,
        "selection_network_measurement_reason": "synthetic unmeasured selector",
        "selector_arm": {
            "mode": "external_selector", "plugin_sha256": "c" * 64,
            "trial_receipts": [{"selector": "synthetic.v1"}],
            "selector_self_report_measurements": self_report_measurements(),
        },
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
