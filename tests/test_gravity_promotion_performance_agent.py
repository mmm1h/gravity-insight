import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_batch import capabilities_many
from gravity_sdk.agent_capabilities import authoritative_capability_cards
from gravity_sdk.agent_promotion_performance import (
    PROMOTION_PERFORMANCE_PLATFORMS,
    promotion_performance_query,
)


class PromotionPerformanceAgentTests(unittest.TestCase):
    def test_strong_intents_return_one_authoritative_closed_handoff(self):
        queries = (
            "promotion performance", "run a cross-platform promotion report",
            "show advertising performance", "推广表现", "请执行跨平台推广报表",
            "帮我查看跨平台投放报告",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(promotion_performance_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual((1, 1), (result["count"], result["total"]))
                self.assertEqual("promotion_performance", result["candidates"][0]["composite"])
        card = discover_capabilities(queries[0], client=None)["candidates"][0]
        self.assertEqual([card], authoritative_capability_cards([card]))
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertEqual(
            ["app", "start", "end", "platforms", "metrics"], card["missing_inputs"]
        )
        self.assertEqual(set(card["input_schema"]), set(card["input_template"]))
        self.assertEqual({
            "name": "promotion_performance",
            "app": "<workspace-app-alias-or-positive-id>",
            "start": "<start:YYYY-MM-DD>", "end": "<end:YYYY-MM-DD>",
            "platforms": ["<supported-promotion-platform>"],
            "metrics": ["<physical-metric-name>"],
        }, card["plan_node"]["request"])
        self.assertEqual(
            {"max_pages": 5, "max_items": 200}, card["plan_node"]["limits"]
        )
        enum = card["input_schema"]["platforms"]["enum"]
        self.assertEqual(set(PROMOTION_PERFORMANCE_PLATFORMS), set(enum))
        self.assertTrue({"bing", "xiaohongshu", "taptap", "wechat_video"}.isdisjoint(enum))

    def test_conflicts_fail_closed_without_raw_operation_fallback(self):
        queries = (
            "not promotion performance", "promotion performance export",
            "write promotion performance", "promotion optimization strategy",
            "promotion material performance", "promotion performance business pulse",
            "promotion performance multidim", "promotion performance attribution",
            "promotion performance dashboard", "saved promotion performance",
            "promotion performance segment", "promotion performance user journey",
            "raw promotion snapshot", "bing promotion report", "小红书推广表现",
            "taptap promotion performance", "视频号投放报表",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertFalse(promotion_performance_query(query))
                result = discover_capabilities(query, client=None)
                self.assertNotIn(
                    "promotion_performance",
                    [card.get("composite") for card in result["candidates"]],
                )
                self.assertFalse(any(
                    card.get("kind") == "operation" for card in result["candidates"]
                ))
                if query in {"not promotion performance", "raw promotion snapshot",
                             "bing promotion report", "小红书推广表现",
                             "taptap promotion performance", "视频号投放报表"}:
                    self.assertEqual("capability_gap", result["status"])

    def test_exact_raw_operation_selector_keeps_normal_discovery(self):
        operation_id = "promotion.bytedance.advertiser.list"

        class Client:
            def operations(self, **_options):
                return [{"operation_id": operation_id, "domain": "promotion",
                         "platform": "bytedance", "stability": "stable"}]

            def describe(self, selected):
                if selected != operation_id:
                    raise AssertionError("unexpected operation description")
                return {"operation_id": operation_id, "domain": "promotion",
                        "platform": "bytedance", "stability": "stable",
                        "effect": "read", "input_schema": {}}

        result = discover_capabilities(operation_id, client=Client())
        self.assertEqual([operation_id], [card["selector"] for card in result["candidates"]])

    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_batch_strong_intents_do_not_load_operation_inventory(self, _metadata):
        class NoOperationClient:
            def operation_inventory(self, **_options):
                raise AssertionError("Promotion Performance is a local Agent product")

        result = capabilities_many(
            ["cross platform promotion performance", {
                "id": "chinese", "query": "跨平台投放报表", "domain": "report",
            }], client=NoOperationClient(),
            workspace=SimpleNamespace(recipes={}, products={}, datasources={}),
        )
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(
            ["promotion_performance", "promotion_performance"],
            [item["result"]["candidates"][0]["composite"] for item in result["results"]],
        )


if __name__ == "__main__":
    unittest.main()
