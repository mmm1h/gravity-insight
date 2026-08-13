from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.cli import main
from gravity_sdk.company_usage import OPERATION_ID, company_usage
from gravity_sdk.errors import ContractChangedError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_report_adapter import execute_report_composite, validate_report_composite

class Client:
    def __init__(self, status="success"):
        self.status = status
        self.calls = []

    def batch(self, requests, *, max_workers=6, max_pages=1_000,
              max_total_items=100_000):
        self.calls.append((requests, {
            "max_workers": max_workers, "max_pages": max_pages,
            "max_total_items": max_total_items,
        }))
        native = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": OPERATION_ID,
            "status": self.status,
            "data": {"list": [] if self.status == "empty" else [{"date": "2026-08-01"}]},
            "page": {"number": 1, "size": 100,
                     "item_count": 0 if self.status == "empty" else 1,
                     "total_pages": 1, "total_items": 0 if self.status == "empty" else 1,
                     "has_more": False, "pages_fetched": 1,
                     "fetch_strategy": "single_page", "max_workers": 1},
            "truncated": False, "next_page_input": None,
        }
        return [{"operation_id": OPERATION_ID, "request_id": "usage",
                 "ok": True, "status": self.status, "data": native}]


class CompanyUsageTests(unittest.TestCase):
    def test_core_sdk_and_cli_use_one_complete_read(self):
        client = Client()
        result = company_usage(client, max_pages=7, max_items=40)
        requests, options = client.calls[0]
        self.assertEqual(
            (1, "success", ["company"]),
            (result["source_count"], result["status"], result["scopes"]),
        )
        self.assertEqual(
            (OPERATION_ID, True, 40),
            (requests[0]["operation_id"], requests[0]["read_all"],
             requests[0]["inputs"]["page_size"]),
        )
        self.assertEqual({"max_workers": 1, "max_pages": 7, "max_total_items": 40}, options)
        self.assertEqual("2026-08-01", result["results"][0]["data"]["data"]["list"][0]["date"])

        sdk = GravitySDK(insight=Client())
        self.assertEqual("success", sdk.company_usage(max_items=2)["status"])
        stdout = io.StringIO()
        with patch("gravity_sdk.business_pulse_cli.runtime.build_client", return_value=Client()), \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(0, main(["reports", "usage", "--max-items", "2"]))
        self.assertEqual("gravity-insight.company-usage.v1", json.loads(stdout.getvalue())["schema_version"])

    def test_empty_and_contract_drift_are_explicit(self):
        self.assertEqual("empty", company_usage(Client("empty"))["status"])
        client = Client()
        original = client.batch
        client.batch = lambda requests, **options: [
            {**original(requests, **options)[0], "operation_id": "other.operation"}]
        with self.assertRaises(RuntimeError):
            company_usage(client)

        client = Client()
        client.batch = lambda _requests, **_options: [{
            "operation_id": OPERATION_ID, "request_id": "usage", "ok": True,
            "status": "success", "data": {"operation_id": "other.operation",
            "status": "success", "data": {"list": []}}}]
        with self.assertRaises(ContractChangedError):
            company_usage(client)
        client = Client(); original = client.batch
        client.batch = lambda requests, **options: [{**original(requests, **options)[0],
            "data": {**original(requests, **options)[0]["data"], "data": {"list": [{"secret": 1}]}}}]
        with self.assertRaises(ContractChangedError): company_usage(client)

        client = Client()
        client.batch = lambda _requests, **_options: [{
            "operation_id": OPERATION_ID, "request_id": "usage", "ok": False,
            "status": "permission_unavailable", "data": None,
            "error": {"code": "PERMISSION_UNAVAILABLE", "category": "upstream",
                      "message": "safe", "raw": "hidden"},
        }]
        failed = company_usage(client)
        self.assertEqual(("permission_unavailable", 3), (failed["status"], failed["exit_code"]))
        self.assertNotIn("raw", failed["results"][0]["error"])
        self.assertNotEqual("safe", failed["results"][0]["error"]["message"])

        client = Client(); original = client.batch
        client.batch = lambda requests, **options: [{**original(requests, **options)[0],
            "data": {**original(requests, **options)[0]["data"], "truncated": True,
                     "next_page_input": {"page": 2, "page_size": 100},
                     "page": {**original(requests, **options)[0]["data"]["page"], "has_more": True}}}]
        partial = company_usage(client)
        self.assertEqual((False, "partial", 2, "PAGINATION_LIMIT", {"page": 2, "page_size": 100}),
            (partial["ok"], partial["status"], partial["exit_code"], partial["results"][0]["error"]["code"], partial["results"][0]["continuation"]))
        drift = company_usage(Client("contract_changed_additive"))
        self.assertEqual((False, "contract_changed", 3, None),
            (drift["ok"], drift["status"], drift["exit_code"], drift["results"][0]["data"]))

    def test_plan_and_agent_are_machine_fillable_and_call_bound(self):
        context = AdapterContext(
            node_id="usage", execution_id="usage", kind="composite",
            workspace=object(), output_fields=(), dynamic_targets=(),
            max_pages=5, max_items=10)
        validate_report_composite({"name": "company_usage"}, context, object(), frozenset())
        sdk = type("SDK", (), {"company_usage": lambda _self, **options: options})()
        self.assertEqual(10, execute_report_composite(
            sdk, {"name": "company_usage"}, context)["max_items"])

        result = discover_capabilities("公司资源用量", client=None, domain="report")
        card = result["candidates"][0]
        self.assertEqual(("company_usage", [], {"name": "company_usage"}),
                         (card["composite"], card["missing_inputs"],
                          card["plan_node"]["request"]))
        self.assertEqual("gravity.agent-call-bound.v1", card["call_bound"]["schema_version"])
        self.assertEqual((1, 2), (card["call_bound"]["known_inputs"], card["call_bound"]["unknown_capability"]))
