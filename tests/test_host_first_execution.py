"""Offline execution controls; these do not measure a real Host's ordering."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import GravitySDK
from gravity_insight.cli import main
from gravity_insight.plan import execute_plan, PlanValidationError
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.workspace import load_workspace
from tests.test_http_receipt_durability import app_page, client_for, receipts, Response


class HostFirstExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = load_workspace(None, start=self.root, environ={}, cache_root=self.root / "cache")
        self.enterContext(patch("socket.socket", side_effect=AssertionError("real network")))
        self.enterContext(patch("gravity_insight.agent.discover_capabilities", side_effect=AssertionError("rediscovery")))
        self.enterContext(patch("gravity_insight.agents.host_catalog.host_product_catalog", side_effect=AssertionError("catalog reread")))
        self.enterContext(patch("gravity_insight.agents.lexical_retrieval.apply_lexical_fallback", side_effect=AssertionError("lexical reselection")))

    def run_plan(self, sdk, request, kind="run"):
        return execute_plan(
            {"schema_version": "gravity.plan.v1", "nodes": [{"id": "known", "kind": kind, "request": request}]},
            adapters=build_plan_adapters(sdk, workspace=self.workspace), workspace=self.workspace,
        )

    def client(self, root, responses):
        client = client_for(root, responses)
        client._metadata_cache.set_bypass(True)
        return client

    def test_known_read_uses_direct_cli_sdk_plan_and_existing_execution_receipts(self):
        inputs = {"page": 1, "page_size": 1}
        for surface in ("cli", "sdk", "plan"):
            with self.subTest(surface=surface):
                root = self.root / surface
                client = self.client(root, [app_page(1)])
                sdk = GravitySDK(insight=client, workspace=self.workspace)
                if surface == "cli":
                    stdout = io.StringIO()
                    with redirect_stdout(stdout), patch("gravity_insight.runtime.build_client", return_value=client):
                        code = main(["run", "app.list", "--input", json.dumps(inputs)])
                    self.assertEqual(0, code, stdout.getvalue())
                    result = json.loads(stdout.getvalue())
                elif surface == "sdk":
                    result = sdk.read("app.list", inputs)
                else:
                    result = self.run_plan(sdk, {"selector": "app.list", "inputs": inputs})
                    self.assertEqual("known", result["results"][0]["node_id"])
                self.assertTrue(result["ok"])
                [receipt] = receipts(root)
                self.assertEqual(("app.list", 200, False), (
                    receipt["operation_id"], receipt["http_status"], receipt["retry"],
                ))
                self.assertNotIn("synthetic", json.dumps(receipt))

    def test_permission_denial_uses_only_existing_auth_refresh_budget(self):
        from gravity_insight import Credential

        root = self.root / "denied"
        sdk = GravitySDK(insight=self.client(root, [Response({}, 403), Response({}, 403)]), workspace=self.workspace)
        with patch("tests.test_http_receipt_durability.Credentials.refresh", create=True, return_value=Credential("synthetic-token")) as refresh:
            result = sdk.read("app.list", {"page": 1, "page_size": 1})
        self.assertEqual((False, "PERMISSION_UNAVAILABLE"), (result["ok"], result["error"]["code"]))
        refresh.assert_called_once()
        self.assertEqual([("app.list", 403)] * 2, [
            (receipt["operation_id"], receipt["http_status"]) for receipt in receipts(root)
        ])

    def test_contract_drift_does_not_fall_back_or_retry(self):
        root = self.root / "drift"
        response = app_page(1)
        del response.payload["data"]["list"]
        sdk = GravitySDK(insight=self.client(root, [response]), workspace=self.workspace)
        result = sdk.read("app.list", {"page": 1, "page_size": 1})
        self.assertFalse(result["ok"])
        self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
        self.assertEqual(1, len(receipts(root)))

    def test_business_fact_gap_blocks_plan_before_any_request(self):
        root = self.root / "missing"
        sdk = GravitySDK(insight=self.client(root, []), workspace=self.workspace)
        with self.assertRaisesRegex(PlanValidationError, "requires spec"):
            self.run_plan(sdk, {"name": "analysis_query", "kind": "event"}, kind="composite")
        self.assertEqual([], receipts(root))


if __name__ == "__main__":
    unittest.main()
