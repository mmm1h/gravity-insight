from __future__ import annotations

import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.bilibili_account_performance import (
    OPERATION_ID,
    bilibili_account_performance,
)
from gravity_sdk.cli import main
from gravity_sdk.errors import PaginationError, UnknownOperationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_bilibili_account_performance_adapter import (
    execute_bilibili_account_performance_plan,
    validate_bilibili_account_performance_plan,
)


ROW = {
    "advertiser_id": 17,
    "average_cost_per_thousand": 1.2,
    "click_count": 4,
    "click_rate": 0.25,
    "cost_per_click": 0.3,
    "product_name": "sample-product",
    "san_lian_launch_total_consume": 0,
    "show_count": 16,
    "total_cash_consume": 1.2,
    "total_consume": 1.2,
    "total_red_packet_consume": 0,
    "total_special_red_packet_consume": 0,
}
TOTAL = {key: value for key, value in ROW.items() if key not in {
    "advertiser_id", "product_name"
}}


class Client:
    def __init__(self, *, rows=None, error=None, mutate=None):
        self.rows = [ROW] if rows is None else rows
        self.error = error
        self.mutate = mutate
        self.calls = []

    def read_all(
        self,
        operation_id,
        inputs,
        *,
        max_pages=1_000,
        max_items=100_000,
        max_workers=6,
    ):
        self.calls.append((operation_id, copy.deepcopy(inputs), {
            "max_pages": max_pages,
            "max_items": max_items,
            "max_workers": max_workers,
        }))
        if self.error is not None:
            raise self.error
        rows = copy.deepcopy(self.rows)
        status = "empty" if not rows else "success"
        value = {
            "schema_version": "gravity-insight.read.v1",
            "status": status,
            "source": {
                "system": "gravity_insight",
                "domain": "promotion",
                "resource": "account",
                "platform": "bilibili",
            },
            "fetched_at": "2026-08-14T00:00:00Z",
            "schema_fingerprint": "a" * 64,
            "operation_id": operation_id,
            "contract_version": "1",
            "request": {"inputs": copy.deepcopy(inputs)},
            "page": {
                "number": 1,
                "size": inputs["page_size"],
                "item_count": len(rows),
                "total_pages": 1,
                "total_items": len(rows),
                "has_more": False,
                "pages_fetched": 1,
                "fetch_strategy": "single_page",
                "max_workers": max_workers,
            },
            "data": {
                "list": rows,
                "page_info": {
                    "page": 1,
                    "page_size": inputs["page_size"],
                    "total_number": len(rows),
                    "total_page": 1,
                },
                "total": copy.deepcopy(TOTAL),
            },
            "warnings": [],
            "error": None,
        }
        return self.mutate(value) if self.mutate is not None else value


class BilibiliAccountPerformanceTests(unittest.TestCase):
    def test_core_sdk_and_cli_share_one_bounded_product(self):
        client = Client()
        result = bilibili_account_performance(
            client,
            "2026-08-01",
            "2026-08-07",
            max_workers=2,
            max_pages=7,
            max_items=40,
        )
        operation_id, inputs, options = client.calls[0]
        self.assertEqual(OPERATION_ID, operation_id)
        self.assertEqual(["2026-08-01", "2026-08-07"], inputs["date_list"])
        self.assertEqual({"max_pages": 7, "max_items": 40, "max_workers": 2}, options)
        self.assertEqual(
            ("gravity-insight.bilibili-account-performance.v1", "success", 1),
            (result["schema_version"], result["status"], result["returned_items"]),
        )
        self.assertNotIn("advertiser_name", result["data"]["list"][0])

        sdk_result = GravitySDK(insight=Client()).bilibili_account_performance(
            "2026-08-01", "2026-08-07", max_items=2
        )
        self.assertEqual("success", sdk_result["status"])

        stdout = io.StringIO()
        with patch("gravity_sdk.promotion_cli.runtime.build_client", return_value=Client()), \
                contextlib.redirect_stdout(stdout):
            exit_code = main([
                "promotion", "bilibili-account-performance",
                "--start", "2026-08-01", "--end", "2026-08-07",
                "--max-items", "2",
            ])
        self.assertEqual(0, exit_code)
        self.assertEqual(
            "gravity-insight.bilibili-account-performance.v1",
            json.loads(stdout.getvalue())["schema_version"],
        )

    def test_empty_partial_unavailable_and_unknown_fields_are_distinct(self):
        empty = bilibili_account_performance(
            Client(rows=[]), "2026-08-01", "2026-08-07"
        )
        partial = bilibili_account_performance(
            Client(error=PaginationError("limit")),
            "2026-08-01",
            "2026-08-07",
        )
        unavailable = bilibili_account_performance(
            Client(error=UnknownOperationError("missing")),
            "2026-08-01",
            "2026-08-07",
        )
        drift = bilibili_account_performance(
            Client(mutate=lambda value: {
                **value,
                "data": {
                    **value["data"],
                    "list": [{**value["data"]["list"][0], "advertiser_name": "hidden"}],
                },
            }),
            "2026-08-01",
            "2026-08-07",
        )
        over_budget = bilibili_account_performance(
            Client(rows=[ROW, ROW]),
            "2026-08-01",
            "2026-08-07",
            max_items=1,
        )
        self.assertEqual((True, "empty", 0), (
            empty["ok"], empty["status"], empty["returned_items"]
        ))
        self.assertEqual((False, "partial", "PAGINATION_LIMIT"), (
            partial["ok"], partial["status"], partial["error"]["code"]
        ))
        self.assertEqual((False, "unavailable", "UNKNOWN_OPERATION"), (
            unavailable["ok"], unavailable["status"], unavailable["error"]["code"]
        ))
        self.assertEqual((False, "contract_changed", []), (
            drift["ok"], drift["status"], drift["data"]["list"]
        ))
        self.assertEqual("contract_changed", over_budget["status"])

    def test_plan_revalidates_the_exact_request_and_product_fields(self):
        request = {
            "name": "bilibili_account_performance",
            "start": "2026-08-01",
            "end": "2026-08-07",
        }
        context = AdapterContext(
            node_id="bili",
            execution_id="bili",
            kind="composite",
            workspace=object(),
            output_fields=(),
            dynamic_targets=(),
            max_pages=5,
            max_items=10,
        )
        validate_bilibili_account_performance_plan(request, context, object())
        result = execute_bilibili_account_performance_plan(
            GravitySDK(insight=Client()), request, context
        )
        self.assertEqual(("success", 1), (result["status"], result["limits"]["max_workers"]))

        good = copy.deepcopy(result)
        good["rogue"] = "not allowed"
        sdk = type("SDK", (), {
            "bilibili_account_performance": lambda _self, *_args, **_options: good
        })()
        closed = execute_bilibili_account_performance_plan(sdk, request, context)
        self.assertEqual((False, "contract_changed"), (closed["ok"], closed["status"]))

    def test_agent_routes_account_profile_without_weakening_generic_promotion(self):
        discovered = discover_capabilities(
            "B站账户投放表现", client=None, domain="promotion"
        )
        card = discovered["candidates"][0]
        self.assertEqual(1, len(discovered["candidates"]))
        self.assertEqual(
            ("bilibili_account_performance", ["start", "end"], True),
            (card["composite"], card["missing_inputs"], card["plan_executable"]),
        )
        self.assertEqual(
            {
                "name": "bilibili_account_performance",
                "start": "<start:YYYY-MM-DD>",
                "end": "<end:YYYY-MM-DD>",
            },
            card["plan_node"]["request"],
        )
        self.assertEqual(
            ("gravity.agent-call-bound.v1", 1, 2),
            (
                card["call_bound"]["schema_version"],
                card["call_bound"]["known_inputs"],
                card["call_bound"]["unknown_capability"],
            ),
        )
        generic = discover_capabilities(
            "B站推广表现", client=None, domain="promotion"
        )["candidates"][0]
        self.assertEqual("promotion_performance", generic["composite"])
        both = discover_capabilities(
            "B站账户投放表现以及B站推广表现", client=None, domain="promotion"
        )
        self.assertEqual([], both["candidates"])
        self.assertEqual("MULTIPLE_INTENTS", both["capability_gaps"][0]["code"])


if __name__ == "__main__":
    unittest.main()
