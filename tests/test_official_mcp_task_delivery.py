from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import GravitySDK
from gravity_insight.journey_contract import JourneyContractError, journey_artifact, load_journey_contract, validate_journey_bindings
from gravity_insight.journey_ledger import load_packaged_journey_ledger
from gravity_insight.journey_service import JourneyService
from gravity_insight.mcp.server import MCPServer
from gravity_insight.workspace import Workspace, WorkspaceDefaults
from tests.test_journey_execution_readiness import Trust
from tests.test_mcp_tools import tool_call


def workspace(root):
    return Workspace(path=None, root=root, state_root=root / "state", apps={"main": 7},
                     defaults=WorkspaceDefaults(app="main", timezone="Asia/Shanghai", time_window=None),
                     datasources={}, products={}, recipes={})


class CurrentTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = workspace(self.root)
        self.calls = []
        self.after_read = lambda: None
        self.native = {"schema_version": "gravity-insight.read.v1", "ok": True, "status": "success",
                       "completeness": "unknown", "network_called": True, "data": {"safe": "value"}}

        def read(operation, inputs):
            self.calls.append((operation, copy.deepcopy(inputs)))
            self.after_read()
            return self.native

        self.sdk = GravitySDK(workspace=self.workspace, insight=SimpleNamespace(read=read))
        self.trust = Trust()
        self.service = JourneyService(self.sdk, capability_trust=self.trust)

    def tearDown(self):
        self.temp.cleanup()

    def test_fixed_operation_uses_real_sdk_signature_and_keeps_native_result(self):
        result = self.service.run("analysis.app-configuration", {"app": "main"})
        self.assertEqual(self.native, result)
        self.assertEqual([("app.detail", {"app_id": "7"})], self.calls)
        rejected = self.service.run("analysis.app-configuration", {"app": "main", "operation_id": "app.list"})
        self.assertEqual("invalid", rejected["status"])
        self.assertEqual(1, len(self.calls))

    def test_dependency_change_discards_the_observation_without_reexecution(self):
        self.after_read = lambda: self.workspace.apps.update(main=8)
        result = self.service.run("analysis.app-configuration", {"app": "main"})
        self.assertFalse(result["ok"])
        self.assertIn("PROJECT_APP_BINDING_CHANGED", result["reason_codes"])
        self.assertEqual(1, len(self.calls))
        self.assertNotIn("data", result)
        self.assertTrue(result["network_called"])

    def test_composite_requires_its_own_trust_before_any_execution(self):
        self.trust.status = "quarantined"
        result = self.service.run("analysis.order-report", {"app": "main", "date": "2026-09-01"})
        self.assertIn("DEPENDENCY_QUARANTINED", result["reason_codes"])
        self.assertEqual([], self.calls)
        self.assertFalse(result["network_called"])
        self.assertEqual("composite:order_directory", result["capabilities"][0]["selector"])

    def test_product_handoffs_use_real_signatures_and_the_original_typed_inputs(self):
        cases = (
            ("analysis.order-report", "order_directory", "gravity-insight.order-directory.v1", {"app": "main", "date": "2026-09-01"}),
            ("analysis.monetization-report", "monetization_detail", "gravity-insight.monetization-detail.v1", {"app": "main", "date": "2026-09-01"}),
            ("analysis.material-report", "material_performance", "gravity-insight.material-performance.v1",
             {"apps": ["main"], "start": "2026-09-01", "end": "2026-09-01", "platforms": ["aggregate"], "metrics": {"aggregate": ["AdClick"]}, "gravity_metrics": []}),
            ("analysis.ad-report", "multidim_query", "gravity-insight.composite.multidim.v1",
             {"app": "main", "inputs": {"date_list": ["2026-09-01", "2026-09-01"], "time_dims": "day", "metrics_list": ["cost"]}}),
        )
        for identity, method, schema, inputs in cases:
            with self.subTest(identity=identity):
                native = {**self.native, "schema_version": schema}
                with patch.object(self.sdk, method, autospec=True, return_value=native) as owner:
                    result = self.service.run(identity, inputs)
                self.assertIs(native, result)
                owner.assert_called_once()
                self.assertEqual(1, owner.call_args.kwargs["max_pages"])
                self.assertEqual(1000, owner.call_args.kwargs["max_items"])
                self.assertIs(self.workspace, owner.call_args.kwargs["workspace"])
        self.assertEqual([], self.calls)

    def test_event_handoff_compiles_the_fixed_event_kind_without_a_second_engine(self):
        from tests.test_gravity_analysis_spec import step

        spec = {"steps": [step("open")], "date_ranges": [{"start": "2026-09-01", "end": "2026-09-01"}]}
        with patch.object(self.sdk, "analysis_query", autospec=True, return_value=self.native) as owner:
            result = self.service.run("analysis.event-trend", {"app": "main", "spec": spec})
        self.assertIs(self.native, result)
        owner.assert_called_once()
        self.assertEqual("event", owner.call_args.kwargs["kind"])
        self.assertEqual(spec, owner.call_args.kwargs["spec"])
        self.assertEqual([], self.calls)

    def test_static_field_discovery_executes_without_constructing_a_target_client(self):
        def forbidden():
            raise AssertionError("offline vocabulary constructed a target client")
        sdk = GravitySDK(workspace=self.workspace, insight_factory=forbidden, sql_factory=forbidden)
        blocked = JourneyService(sdk).run("analysis.user-report-fields", {"query": "", "limit": 3})
        self.assertFalse(blocked["ok"])
        self.assertFalse(blocked["network_called"])
        service = JourneyService(sdk, capability_trust=Trust())
        result = service.run("analysis.user-report-fields", {"query": "", "limit": 3})
        self.assertTrue(result["ok"])
        self.assertEqual("user_report_field", result["kind"])
        self.assertEqual("gravity.metadata-search.v1", result["schema_version"])
        self.assertEqual(3, len(result["results"]))
        invalid = service.run("analysis.user-report-fields", {"database": "other-account.db"})
        self.assertEqual("invalid", invalid["status"])

    def test_local_catalog_trust_revocation_discards_data_and_keeps_zero_target_fact(self):
        def forbidden():
            raise AssertionError("local catalog constructed a target client")
        sdk = GravitySDK(workspace=self.workspace, insight_factory=forbidden, sql_factory=forbidden)
        trust = Trust()
        service = JourneyService(sdk, capability_trust=trust)
        owner = sdk.analysis_vocabulary

        def revoke(**inputs):
            value = owner(**inputs)
            trust.status = "quarantined"
            return value

        with patch.object(sdk, "analysis_vocabulary", side_effect=revoke):
            result = service.run("analysis.user-report-fields", {"limit": 3})
        self.assertFalse(result["ok"])
        self.assertIn("DEPENDENCY_QUARANTINED", result["reason_codes"])
        self.assertNotIn("results", result)
        self.assertFalse(result["network_called"])

    def test_discovery_exposes_real_nested_inputs_and_new_registration_cannot_claim_legacy_evidence(self):
        desc = self.service.describe("analysis.event-properties")["input_contract"]
        self.assertEqual("rejected", desc["additional_fields"])
        self.assertIn("item_schema", desc["fields"]["filters"])
        realtime = self.service.describe("analysis.realtime-event-catalog")["input_contract"]
        self.assertIn("machine_schema", realtime["fields"]["properties"])
        contract = journey_artifact("analysis.app-configuration")["contract"]
        contract["display_binding"]["runtime_contract"] = "analysis.user-report"
        path = self.root / "invalid.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaises(JourneyContractError):
            load_journey_contract(path)
        legacy = journey_artifact("analysis.event-trend")["contract"]
        legacy["display_binding"] = {"runtime_contract": legacy["journey_id"]}
        with self.assertRaises(JourneyContractError):
            validate_journey_bindings([legacy], load_packaged_journey_ledger())


class CompleteDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls = 0
        self.value = {"schema_version": "gravity-insight.read.v1", "ok": False, "status": "partial", "exit_code": 2,
                      "network_called": True, "completeness": "unknown", "allowed_claims": ["returned-scope-only"],
                      "forbidden_claims": ["complete-population"], "data": {"rows": [{"value": "安全示例" * 40000}]}}

        def run(*_args):
            self.calls += 1
            return self.value

        self.journeys = SimpleNamespace(run=run)
        self.server = MCPServer(SimpleNamespace(workspace=workspace(self.root), journeys=self.journeys))

    def tearDown(self):
        self.temp.cleanup()

    def test_one_execution_publishes_full_unicode_json_and_keeps_partial_facts(self):
        path = self.root / "完整结果.json"
        result = tool_call(self.server, "gravity.execute", {
            "journey_id": "analysis.realtime-event-catalog", "inputs": {},
            "output": {"destination": str(path), "confirm": True},
        })
        delivery = result["structuredContent"]["result"]
        encoded = path.read_bytes()
        self.assertEqual(self.value, json.loads(encoded))
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), delivery["publication"]["sha256"])
        self.assertEqual(len(encoded), delivery["publication"]["size_bytes"])
        self.assertFalse(delivery["publication"]["preview_applied"])
        self.assertEqual("partial", delivery["status"])
        self.assertEqual(2, delivery["exit_code"])
        self.assertEqual("unknown", delivery["source_result"]["completeness"])
        self.assertEqual(["complete-population"], delivery["source_result"]["forbidden_claims"])
        self.assertTrue(result["isError"])
        self.assertEqual(1, self.calls)
        self.assertLessEqual(len(result["content"][0]["text"].encode("utf-8")), 100000)

    def test_unconfirmed_and_invalid_destination_stop_before_execution(self):
        for output in ({"destination": str(self.root / "no.json"), "confirm": False},
                       {"destination": str(self.root), "confirm": True}):
            with self.subTest(output=output):
                result = tool_call(self.server, "gravity.execute", {"journey_id": "analysis.user-report", "inputs": {}, "output": output})
                self.assertTrue(result["isError"])
        self.assertEqual(0, self.calls)
        self.assertFalse((self.root / "no.json").exists())

    def test_terminal_failure_preserves_existing_destination(self):
        path = self.root / "existing.json"
        path.write_text("original", encoding="utf-8")
        self.value = {"schema_version": "fixture.error.v1", "ok": False, "status": "error", "network_called": True}
        result = tool_call(self.server, "gravity.execute", {"journey_id": "analysis.user-report", "inputs": {},
                           "output": {"destination": str(path), "confirm": True}})
        self.assertTrue(result["isError"])
        self.assertEqual("original", path.read_text(encoding="utf-8"))
        self.assertEqual(1, self.calls)

    def test_budget_failure_retains_execution_truth_and_does_not_retry(self):
        result = tool_call(self.server, "gravity.execute", {"journey_id": "analysis.user-report", "inputs": {}, "max_output_bytes": 1024})
        error = result["structuredContent"]["result"]
        self.assertTrue(error["network_called"])
        self.assertEqual("partial", error["source_status"])
        self.assertEqual(2, error["source_exit_code"])
        self.assertFalse(error["error"]["retryable"])
        self.assertEqual(1, self.calls)
        self.assertLessEqual(len(result["content"][0]["text"].encode("utf-8")), 1024)

    def test_exception_after_owner_invocation_cannot_claim_zero_network(self):
        def fail(*_args):
            self.calls += 1
            raise RuntimeError("private upstream detail")
        self.journeys.run = fail
        result = tool_call(self.server, "gravity.execute", {"journey_id": "analysis.user-report", "inputs": {}})
        self.assertIsNone(result["structuredContent"]["result"]["network_called"])
        self.assertNotIn("private upstream detail", result["content"][0]["text"])
        self.assertEqual(1, self.calls)


if __name__ == "__main__":
    unittest.main()
