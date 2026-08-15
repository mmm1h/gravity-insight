from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.advertiser_profile import (
    OPERATION_ID,
    SCHEMA_VERSION,
    advertiser_profile,
)
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.cli import main
from gravity_sdk.errors import ContractChangedError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_adapters import build_plan_adapters


class Client:
    def __init__(self, status: str = "success") -> None:
        self.status = status
        self.calls = []

    def batch(
        self, requests, *, max_workers=6, max_pages=1_000,
        max_total_items=100_000,
    ):
        self.calls.append((requests, max_workers, max_pages, max_total_items))
        rows = [] if self.status == "empty" else [{
            "advertiser_id": "synthetic-advertiser",
            "advertiser_balance": 10.5,
            "advertiser_budget_mode": "INFINITE",
            "advertiser_name": "registered advertiser",
            "advertiser_remark": "registered remark",
            "advertiser_system_status": "STATUS_ENABLE",
            "company": "registered company",
            "delay": 0,
            "operator_id": 17,
            "operator_name": "registered operator",
            "project_list": [{"project_id": "project-1"}],
            "stat_cost": "1.25",
        }]
        count = len(rows)
        native = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": OPERATION_ID,
            "status": self.status,
            "data": {
                "list": rows,
                "page_info": {
                    "page": 1, "page_size": 10,
                    "total_number": count, "total_page": 1,
                },
                "total": [{"stat_cost": "1.25"}] if rows else [],
                "update_at": "2026-08-14 10:00:00",
            },
            "page": {
                "number": 1, "size": 10, "item_count": count,
                "total_pages": 1, "total_items": count,
                "has_more": False, "pages_fetched": 1,
                "fetch_strategy": "single_page", "max_workers": 1,
            },
            "truncated": False,
            "next_page_input": None,
        }
        return [{
            "operation_id": OPERATION_ID,
            "request_id": "advertisers",
            "ok": True,
            "status": self.status,
            "data": native,
        }]


class AdvertiserProfileTests(unittest.TestCase):
    def test_core_sdk_and_cli_share_one_complete_read(self) -> None:
        client = Client()
        result = advertiser_profile(
            client, "2026-08-11", "2026-08-11", max_pages=8, max_items=21
        )
        request, workers, pages, items = client.calls[0]
        self.assertEqual((SCHEMA_VERSION, "success"), (
            result["schema_version"], result["status"]
        ))
        self.assertEqual((OPERATION_ID, True, 10), (
            request[0]["operation_id"], request[0]["read_all"],
            request[0]["inputs"]["page_size"],
        ))
        self.assertEqual((1, 8, 21), (workers, pages, items))

        sdk = GravitySDK(insight=Client())
        self.assertEqual(
            "success",
            sdk.advertiser_profile("2026-08-11", "2026-08-11")["status"],
        )
        stdout = io.StringIO()
        with patch("gravity_sdk.promotion_cli.runtime.build_client", return_value=Client()), \
                contextlib.redirect_stdout(stdout):
            code = main([
                "promotion", "advertiser-profile", "--start", "2026-08-11",
                "--end", "2026-08-11", "--max-items", "2",
            ])
        self.assertEqual(0, code)
        self.assertEqual(SCHEMA_VERSION, json.loads(stdout.getvalue())["schema_version"])

    def test_empty_partial_failure_and_unknown_fields_are_distinct(self) -> None:
        self.assertEqual(
            "empty",
            advertiser_profile(Client("empty"), "2026-08-11", "2026-08-11")["status"],
        )
        partial = Client()
        original = partial.batch

        def truncated(requests, **options):
            value = original(requests, **options)[0]
            value["data"]["truncated"] = True
            value["data"]["next_page_input"] = {"page": 2, "page_size": 10}
            value["data"]["page"]["has_more"] = True
            return [value]

        partial.batch = truncated
        result = advertiser_profile(partial, "2026-08-11", "2026-08-11")
        self.assertEqual((False, "partial", "PAGINATION_LIMIT"), (
            result["ok"], result["status"], result["results"][0]["error"]["code"]
        ))

        failed = Client()
        failed.batch = lambda _requests, **_options: [{
            "operation_id": OPERATION_ID, "request_id": "advertisers",
            "ok": False, "status": "unavailable", "data": None,
            "error": {
                "code": "UNSUPPORTED", "category": "local",
                "message": "raw upstream text",
            },
        }]
        result = advertiser_profile(failed, "2026-08-11", "2026-08-11")
        self.assertEqual((False, "unavailable", "UNSUPPORTED"), (
            result["ok"], result["status"], result["results"][0]["error"]["code"]
        ))
        self.assertNotEqual(
            "raw upstream text", result["results"][0]["error"]["message"]
        )

        drift = Client()
        original = drift.batch

        def unknown_field(requests, **options):
            value = original(requests, **options)[0]
            value["data"]["data"]["list"][0]["new_upstream_field"] = "unknown"
            return [value]

        drift.batch = unknown_field
        with self.assertRaises(ContractChangedError):
            advertiser_profile(drift, "2026-08-11", "2026-08-11")

    def test_plan_and_agent_handoff_are_closed_and_unambiguous(self) -> None:
        context = AdapterContext(
            node_id="advertisers", execution_id="advertisers", kind="composite",
            workspace=object(), output_fields=(), dynamic_targets=(),
            max_pages=8, max_items=21,
        )

        class SDK:
            workspace = object()
            insight = type("Insight", (), {"operations": lambda _self, **_kw: []})()

            def advertiser_profile(self, start, end, **options):
                return {"start": start, "end": end, **options}

        adapters = build_plan_adapters(SDK())
        request = {
            "name": "advertiser_profile",
            "start": "2026-08-11",
            "end": "2026-08-11",
        }
        adapters.composite.validate(request, context)
        executed = adapters.composite.execute(request, context)
        self.assertEqual((8, 21), (executed["max_pages"], executed["max_items"]))

        result = discover_capabilities(
            "巨量广告主账户", client=None, domain="promotion"
        )
        card = result["candidates"][0]
        self.assertEqual(("advertiser_profile", ["start", "end"]), (
            card["composite"], card["missing_inputs"]
        ))
        self.assertTrue(card["plan_executable"])
        self.assertEqual(request["name"], card["plan_node"]["request"]["name"])
        self.assertEqual(
            "gravity.agent-call-bound.v1", card["call_bound"]["schema_version"]
        )
        promotion = discover_capabilities("promotion performance", client=None)
        self.assertEqual(
            ["promotion_performance"],
            [item["composite"] for item in promotion["candidates"]],
        )
        advertiser = discover_capabilities("Read the current Bytedance advertiser spend, balance, budget mode, and status.", client=None)
        self.assertEqual(
            ["advertiser_profile"],
            [item["composite"] for item in advertiser["candidates"]],
        )


if __name__ == "__main__":
    unittest.main()
