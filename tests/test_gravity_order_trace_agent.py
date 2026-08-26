import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_batch import capabilities_many
from gravity_sdk.agent_capabilities import authoritative_capability_cards
from gravity_sdk.agents.order_trace import ORDER_SPLIT_TRACE_RAW_SELECTOR, order_split_trace_query


class OrderSplitTraceAgentTests(unittest.TestCase):
    def test_strong_intents_return_one_value_free_authoritative_card(self):
        queries = (
            "order split trace", "split order details by TraceID",
            "read the order split trace", "inspect split-order trace details",
            "拆单追踪", "请查看拆单追溯", "按 TraceID 查拆单明细",
            "用 TraceID 查询拆单详情", "order split 追踪", "拆单明细 by TraceID",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(order_split_trace_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual(
                    ("success", 1, 1), (result["status"], result["count"], result["total"])
                )
                self.assertEqual("order_split_trace", result["candidates"][0]["composite"])
        result = discover_capabilities("use TraceID north-secret to inspect split order details", client=None)
        card = result["candidates"][0]
        self.assertEqual([card], authoritative_capability_cards([card]))
        self.assertEqual(["app", "date", "trace_id"], card["missing_inputs"])
        self.assertTrue(card["input_schema"]["trace_id"]["sensitive"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertEqual({
            "name": "order_split_trace",
            "app": "<workspace-app-alias-or-positive-id>",
            "date": "<date:YYYY-MM-DD>",
            "trace_id": "<explicit-sensitive-trace-id>",
        }, card["plan_node"]["request"])
        self.assertEqual(
            {"max_pages": 1000, "max_items": 100000},
            card["plan_node"]["limits"],
        )
        self.assertNotIn("north-secret", json.dumps(result, ensure_ascii=False))
        other = discover_capabilities("use TraceID south-secret to inspect split order details", client=None)
        self.assertEqual(card["plan_node"]["id"], other["candidates"][0]["plan_node"]["id"])
        self.assertNotIn("south-secret", json.dumps(other, ensure_ascii=False))

    def test_conflicts_fail_closed_without_raw_operation_fallback(self):
        queries = (
            "do not inspect order split trace", "can't read split order trace",
            "export order split trace", "write order split trace",
            "update order split trace", "refund order split trace",
            "order split trace net revenue", "attribution order split trace",
            "user journey order split trace", "order split trace monetization",
            "promotion order split trace", "material order split trace",
            "dashboard order split trace", "template order split trace",
            "run saved order split trace", "order split trace segment",
            "audience order split trace", "cohort order split trace",
            "permission UI order split trace", "不要查拆单追踪", "导出拆单追踪",
            "别拆单追踪", "写拆单追踪",
            "拆单追踪退款判断", "拆单追踪净收入", "归因拆单追踪",
            "运行已保存的拆单追踪", "保存拆单追踪", "分群拆单追踪",
            "人群拆单追踪", "受众拆单追踪",
            "用户旅程拆单追踪", "推广拆单追踪", "素材拆单追踪", "看板拆单追踪",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertFalse(order_split_trace_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual("capability_gap", result["status"])
                self.assertEqual([], result["candidates"])
                self.assertNotIn(query, json.dumps(result, ensure_ascii=False))

    def test_adjacent_authoritative_products_remain_unique(self):
        cases = (
            ("run saved analysis order split trace north-secret", "saved_analysis"),
            ("运行已保存的拆单追踪分析 north-secret", "saved_analysis"),
            ("保存分析拆单追踪 north-secret", "saved_analysis"),
            ("inspect segment details history daily result order split trace north-secret", "segment_snapshot"),
            ("检查分群详情历史和单日计算结果的拆单追踪 north-secret", "segment_snapshot"),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertFalse(order_split_trace_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual(("success", 1), (result["status"], result["count"]))
                self.assertEqual(expected, result["candidates"][0]["composite"])
                self.assertNotIn("north-secret", json.dumps(result, ensure_ascii=False))

    def test_exact_raw_selector_keeps_expert_operation_discovery(self):
        class Client:
            def operations(self, **_options):
                return [{"operation_id": ORDER_SPLIT_TRACE_RAW_SELECTOR,
                         "domain": "analysis", "stability": "stable"}]

            def describe(self, selected):
                if selected != ORDER_SPLIT_TRACE_RAW_SELECTOR:
                    raise AssertionError("unexpected operation description")
                return {"operation_id": selected, "domain": "analysis",
                        "stability": "stable", "effect": "read", "input_schema": {}}

        result = discover_capabilities(ORDER_SPLIT_TRACE_RAW_SELECTOR, client=Client())
        self.assertEqual(
            [ORDER_SPLIT_TRACE_RAW_SELECTOR],
            [card["selector"] for card in result["candidates"]],
        )

    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_batch_positive_and_blocked_intents_never_load_operations(self, _metadata):
        class NoOperationClient:
            def export_capabilities(self):
                raise AssertionError("blocked Order Split Trace must not scan exports")

            def operation_inventory(self, **_options):
                raise AssertionError("Order Split Trace is a local Agent product")

        result = capabilities_many(
            ["order split trace", "拆单追踪", "export order split trace", "导出拆单追踪", "归因拆单追踪",
             "run saved order split trace", "分群拆单追踪"],
            client=NoOperationClient(),
            workspace=SimpleNamespace(recipes={}, products={}, datasources={}),
        )
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(
            ["success", "success", "capability_gap", "capability_gap", "capability_gap",
             "capability_gap", "capability_gap"],
            [item["status"] for item in result["results"]],
        )


if __name__ == "__main__":
    unittest.main()
