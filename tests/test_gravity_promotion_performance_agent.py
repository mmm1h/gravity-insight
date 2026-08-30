import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_insight.agent import discover_capabilities
from gravity_insight.agents.batch import capabilities_many
from gravity_insight.agents.capabilities import authoritative_capability_cards
from gravity_insight.agents.promotion_performance import (
    PROMOTION_PERFORMANCE_PLATFORMS,
    promotion_performance_query,
)


class PromotionPerformanceAgentTests(unittest.TestCase):
    def test_strong_intents_return_one_authoritative_closed_handoff(self):
        queries = (
            "promotion performance", "run a cross-platform promotion report",
            "show advertising performance", "推广表现", "请执行跨平台推广报表",
            "帮我查看跨平台投放报告", "promotion 跨平台报表",
            "推广 performance", "投放 report", "promotion performance 请查询",
            "请查询 promotion performance", "query promotion performance", "查询推广表现",
            "请查询跨平台推广报表",
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
            "Tap Tap promotion report", "Tap-Tap promotion report", "Tap_Tap promotion report",
            "WeChatVideo ad performance", "wechat-video ad performance",
            "red note promotion report", "red_note promotion report", "cannot run promotion report",
            "can't run promotion performance", "won't run promotion report",
            "这不是推广表现", "并非投放报表", "非推广表现", "不想看推广表现",
            "我不想要 promotion performance", "拒绝推广表现", "不看推广表现", "不查推广表现", "不查询推广表现",
            "推荐推广表现", "推广表现推荐", "推广投放方案报告",
            "publish promotion report", "remove promotion performance",
            "insert promotion report",
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
                if query != "promotion performance business pulse":
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
        self.assertFalse(promotion_performance_query("promotion query"))

    @patch("gravity_insight.agents.batch_sources.search_metadata", return_value={"results": []})
    def test_batch_product_intents_do_not_load_operation_inventory(self, _metadata):
        class NoOperationClient:
            def operation_inventory(self, **_options):
                raise AssertionError("Promotion Performance is a local Agent product")

        result = capabilities_many(
            ["promotion 跨平台报表", "推广 performance", "投放 report", {
                "id": "chinese", "query": "跨平台投放报表", "domain": "report",
            }, "Tap Tap promotion report", "WeChatVideo ad performance",
             "red note promotion report", "can't run promotion performance",
             "并非投放报表", "推广表现推荐", "publish promotion report"],
            client=NoOperationClient(),
            workspace=SimpleNamespace(recipes={}, products={}, datasources={}),
        )
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(
            ["success"] * 4 + ["capability_gap"] * 7,
            [item["status"] for item in result["results"]],
        )


if __name__ == "__main__":
    unittest.main()
