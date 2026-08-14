from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.cli import main
from gravity_sdk.custom_audience import OPERATION_ID, custom_audiences
from gravity_sdk.errors import ContractChangedError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_custom_audience_adapter import execute_custom_audience_plan, validate_custom_audience_plan


SAFE_ROW = {
    "advertiser_id": 11, "cover_num": 1200,
    "create_time": "2026-08-01 12:00:00", "custom_audience_id": 22,
    "data_source_id": "source-1", "delivery_status": "available",
    "id": 33, "isdel": 0,
    "modify_time": "2026-08-02 12:00:00", "name": "retained audience",
    "source": "upload", "status": 1, "upload_num": 1000,
}


class Client:
    def __init__(self, status="success", row=None, *, truncated=False):
        self.status = status
        self.row = SAFE_ROW if row is None else row
        self.truncated = truncated
        self.calls = []

    def batch(self, requests, *, max_workers=6, max_pages=1_000,
              max_total_items=100_000):
        self.calls.append((requests, max_workers, max_pages, max_total_items))
        rows = [] if self.status == "empty" else [dict(self.row)]
        native = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": OPERATION_ID,
            "status": self.status,
            "data": {"list": rows},
            "page": {
                "number": 1, "size": requests[0]["inputs"]["page_size"],
                "item_count": len(rows), "total_pages": 2 if self.truncated else 1,
                "total_items": len(rows) + int(self.truncated),
                "has_more": self.truncated, "pages_fetched": 1,
                "fetch_strategy": "single_page", "max_workers": 1,
            },
            "truncated": self.truncated,
            "next_page_input": (
                {"page": 2, "page_size": requests[0]["inputs"]["page_size"]}
                if self.truncated else None
            ),
        }
        return [{"operation_id": OPERATION_ID, "request_id": "custom_audiences",
                 "ok": True, "status": self.status, "data": native}]


class CustomAudienceTests(unittest.TestCase):
    def test_core_sdk_cli_and_plan_use_one_complete_read(self):
        client = Client()
        result = custom_audiences(client, max_pages=7, max_items=40)
        requests, workers, pages, items = client.calls[0]
        self.assertEqual((1, "success", ["company"]), (
            result["source_count"], result["status"], result["scopes"],
        ))
        self.assertEqual((OPERATION_ID, True, 40), (
            requests[0]["operation_id"], requests[0]["read_all"],
            requests[0]["inputs"]["page_size"],
        ))
        self.assertEqual((1, 7, 40), (workers, pages, items))
        row = result["results"][0]["data"]["data"]["list"][0]
        self.assertEqual(SAFE_ROW, row)

        sdk = GravitySDK(insight=Client())
        self.assertEqual("success", sdk.custom_audiences(max_items=2)["status"])
        stdout = io.StringIO()
        with patch("gravity_sdk.promotion_cli.runtime.build_client", return_value=Client()), \
                contextlib.redirect_stdout(stdout):
            code = main(["promotion", "custom-audiences", "--max-items", "2"])
        self.assertEqual(0, code)
        self.assertEqual(
            "gravity-insight.custom-audience.v1",
            json.loads(stdout.getvalue())["schema_version"],
        )

        context = AdapterContext(
            node_id="audiences", execution_id="audiences", kind="composite",
            workspace=object(), output_fields=(), dynamic_targets=(),
            max_pages=5, max_items=10,
        )
        validate_custom_audience_plan(
            {"name": "custom_audience"}, context, frozenset()
        )
        plan_sdk = type(
            "SDK", (), {"custom_audiences": lambda _self, **options: options}
        )()
        self.assertEqual(10, execute_custom_audience_plan(
            plan_sdk, {"name": "custom_audience"}, context
        )["max_items"])

    def test_empty_partial_gap_and_unregistered_fields_are_distinct(self):
        self.assertEqual("empty", custom_audiences(Client("empty"))["status"])
        partial = custom_audiences(Client(truncated=True))
        self.assertEqual((False, "partial", "PAGINATION_LIMIT"), (
            partial["ok"], partial["status"], partial["results"][0]["error"]["code"],
        ))
        additive = custom_audiences(Client("contract_changed_additive"))
        self.assertEqual((False, "contract_changed", "CONTRACT_CHANGED"), (
            additive["ok"], additive["status"], additive["results"][0]["error"]["code"],
        ))

        gap_client = Client()
        gap_client.batch = lambda *_args, **_kwargs: [{
            "operation_id": OPERATION_ID,
            "request_id": "custom_audiences",
            "ok": False,
            "status": "unavailable",
            "data": None,
            "error": {"code": "UNSUPPORTED", "category": "local", "raw": "hidden"},
        }]
        gap = custom_audiences(gap_client)
        self.assertEqual(("unavailable", "unavailable", "UNSUPPORTED"), (
            gap["status"], gap["results"][0]["status"],
            gap["results"][0]["error"]["code"],
        ))
        self.assertNotIn("raw", gap["results"][0]["error"])

        for field in (
            "cid", "company", "create_user_id", "create_user_name", "tag",
            "update_user_id", "update_user_name", "new_user_level_field",
        ):
            with self.subTest(field=field), self.assertRaises(ContractChangedError):
                custom_audiences(Client(row={**SAFE_ROW, field: "hidden"}))

    def test_agent_card_is_executable_and_mixed_intent_is_not_ambiguous(self):
        result = discover_capabilities(
            "查看自定义人群覆盖与状态", client=None, domain="promotion"
        )
        card = result["candidates"][0]
        self.assertEqual(("custom_audience", [], True), (
            card["composite"], card["missing_inputs"], card["plan_executable"],
        ))
        self.assertEqual(
            {"name": "custom_audience"}, card["plan_node"]["request"]
        )
        self.assertEqual("gravity.agent-call-bound.v1", card["call_bound"]["schema_version"])
        self.assertEqual((1, 2), (
            card["call_bound"]["known_inputs"],
            card["call_bound"]["unknown_capability"],
        ))

        mixed = discover_capabilities(
            "custom audience coverage status and promotion performance", client=None
        )
        gap = mixed["capability_gaps"][0]
        self.assertEqual("MULTIPLE_INTENTS", gap["code"])
        self.assertEqual({
            "composite:custom_audience", "composite:promotion_performance",
        }, set(gap["candidate_selectors"]))

if __name__ == "__main__":
    unittest.main()
