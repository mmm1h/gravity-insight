import base64
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_batch import capabilities_many
from gravity_sdk.agent_batch_sources import AgentSourceSnapshot
from gravity_sdk.agent_capabilities import authoritative_capability_cards, composite_capability_inventory
from gravity_sdk.agent_order_directory import (
    ORDER_DIRECTORY_CAPABILITY, ORDER_DIRECTORY_RAW_SELECTORS,
    ORDER_DIRECTORY_SAFE_FIELDS, order_directory_query,
)
from gravity_sdk.plan import PlanAdapter, PlanAdapters, execute_plan
class NoDiscovery:
    def operations(self, **_options):
        raise AssertionError("must not scan operations")
    operation_inventory = operations
    def describe(self, _selector):
        raise AssertionError("must not describe operations")
    def export_capabilities(self):
        raise AssertionError("must not scan exports")
class OrderDirectoryAgentTests(unittest.TestCase):
    def test_strong_intents_return_one_value_free_authoritative_card(self):
        queries = (
            "order directory", "order detail report", "list daily orders", "ordinary order details",
            "订单目录", "订单明细", "订单列表", "单日订单报表", "请查看订单详情", "普通订单列表",
            "read 订单明细", "order directory 请查看", "非常需要订单目录",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(order_directory_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual(("success", ["order_directory"]),
                                 (result["status"], [item["composite"] for item in result["candidates"]]))
        result = discover_capabilities("read order details north-secret for 2026-08-08", client=None)
        card = result["candidates"][0]
        self.assertEqual([card], authoritative_capability_cards([card]))
        self.assertEqual((["app", "date"], False),
                         (card["missing_inputs"], card["natural_language_auto_execute"]))
        self.assertEqual({"name": "order_directory", "app": "<workspace-app-alias-or-positive-id>",
                          "date": "<date:YYYY-MM-DD>"}, card["plan_node"]["request"])
        self.assertEqual({"max_pages": 1000, "max_items": 100000}, card["plan_node"]["limits"])
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertFalse(any(value in rendered for value in ("north-secret", "2026-08-08", "TraceID")))
        self.assertTrue(all(field in card["description"] for field in ORDER_DIRECTORY_SAFE_FIELDS))
        self.assertEqual("success", discover_capabilities("订单目录", client=NoDiscovery())["status"])
    def test_conflict_matrix_is_claimed_then_fails_closed(self):
        queries = (
            "do not list order details", "export order directory", "write order details",
            "order detail by TraceID secret-42", "split order directory", "refund order details",
            "order directory net revenue", "successful order details", "attribution order directory",
            "user journey order details", "order directory monetization", "promotion order directory",
            "material order details", "dashboard order directory", "saved order directory",
            "segment order details", "permission UI order directory", "analysis.order_detail.list secret/export",
            "weekly order detail report", "order details from 2026-08-01 to 2026-08-08",
            "order detail between 2026-08-01 and 2026-08-08", "analysis.order_split_detail.list foo", "please run analysis.order_detail.list",
            "写入订单明细", "按TraceID查订单明细", "拆单订单目录", "订单明细退款判断",
            "订单目录净收入", "订单明细是否成功", "归因订单目录", "用户旅程订单明细",
            "订单目录变现", "推广订单目录", "素材订单明细", "看板订单目录", "保存订单明细",
            "分群订单目录", "权限界面订单目录", "按字段筛选订单明细", "跨日订单报表",
            "非订单目录", "拒绝订单明细", "export 订单明细", "订单目录 refund", "business pulse order directory", "经营脉搏订单目录",
        )
        for query in queries:
            with self.subTest(query=query):
                self.assertFalse(order_directory_query(query))
                result = discover_capabilities(query, client=None)
                self.assertEqual(("capability_gap", [], "order_directory"),
                                 (result["status"], result["candidates"], result["query"]))
                self.assertNotIn("secret-42", json.dumps(result, ensure_ascii=False))
        self.assertEqual("capability_gap", discover_capabilities(
            "please run analysis.order_detail.list secret-42", client=NoDiscovery())["status"])
    def test_adjacent_products_and_exact_raw_selectors_stay_unique(self):
        adjacent = (("order split trace", "order_split_trace"),
                    ("run saved analysis order directory secret-42", "saved_analysis"), ("run saved order directory", "saved_analysis"), ("运行已保存的订单目录", "saved_analysis"),
                    ("inspect segment details history daily result order directory", "segment_snapshot"))
        for query, expected in adjacent:
            result = discover_capabilities(query, client=None)
            self.assertEqual([expected], [item["composite"] for item in result["candidates"]])
        for query in ("order split trace order directory", "订单目录拆单追踪"):
            result = discover_capabilities(query, client=None)
            self.assertEqual(("capability_gap", []), (result["status"], result["candidates"]))
        class Client:
            def operations(self, **_options):
                return [{"operation_id": value, "domain": "analysis", "stability": "stable"}
                        for value in ORDER_DIRECTORY_RAW_SELECTORS]
            def describe(self, value):
                return {"operation_id": value, "domain": "analysis", "stability": "stable",
                        "effect": "read", "input_schema": {}}
        for selector in ORDER_DIRECTORY_RAW_SELECTORS:
            result = discover_capabilities(selector, client=Client())
            self.assertEqual([selector], [item["selector"] for item in result["candidates"]])
    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_pure_batch_deep_copies_and_plan_node_dry_runs(self, _metadata):
        result = capabilities_many(
            ["order directory", "订单明细", "export order details", "跨日订单报表",
             "order details from 2026-08-01 to 2026-08-08", "analysis.order_detail.list secret"], client=NoDiscovery(),
            workspace=SimpleNamespace(recipes={}, products={}, datasources={}))
        self.assertEqual(["success", "success", "capability_gap", "capability_gap", "capability_gap", "capability_gap"],
                         [item["status"] for item in result["results"]])
        first = discover_capabilities("order directory", client=None)["candidates"][0]
        first["input_schema"]["app"]["type"] = first["input_template"]["date"] = "poison"
        first["plan_node"]["request"]["app"] = "poison"
        first["plan_node"]["limits"]["max_pages"] = -1
        fresh = discover_capabilities("订单目录", client=None)["candidates"][0]
        self.assertEqual(("string|integer", "<date:YYYY-MM-DD>",
                          "<workspace-app-alias-or-positive-id>", 1000),
                         (fresh["input_schema"]["app"]["type"], fresh["input_template"]["date"],
                          fresh["plan_node"]["request"]["app"], fresh["plan_node"]["limits"]["max_pages"]))
        inventory = composite_capability_inventory()
        definition = next(item for item in inventory if item["name"] == "order_directory")
        definition["input_schema"]["app"]["type"] = "poison"
        definition["plan_node_limits"]["max_items"] = -1
        copied = next(item for item in composite_capability_inventory() if item["name"] == "order_directory")
        self.assertEqual(("string|integer", 100000),
                         (copied["input_schema"]["app"]["type"], copied["plan_node_limits"]["max_items"]))
        node = copy.deepcopy(fresh["plan_node"])
        node["request"].update({"app": "main", "date": "2026-08-08"})
        calls = []
        adapter = PlanAdapter(lambda *_args: self.fail("dry-run executed"),
                              lambda request, context: calls.append((request, context.max_workers)))
        dry = execute_plan({"schema_version": "gravity.plan.v1", "nodes": [node]},
                           adapters=PlanAdapters(composite=adapter), workspace=object(), dry_run=True)
        self.assertEqual(("validated", 1, 1), (dry["status"], len(calls), calls[0][1]))
    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_mixed_batch_caches_raw_describe_and_continuation_is_safe(self, _metadata):
        selector = sorted(ORDER_DIRECTORY_RAW_SELECTORS)[0]
        class CountingClient:
            inventory_calls = export_calls = 0
            describe_calls = []
            def operation_inventory(self, **_options):
                self.inventory_calls += 1
                return [{"operation_id": selector, "domain": "analysis", "stability": "stable"}]
            def describe(self, value):
                self.describe_calls.append(value)
                return {"operation_id": value, "domain": "analysis", "stability": "stable",
                        "effect": "read", "input_schema": {}}
            def export_capabilities(self):
                self.export_calls += 1
                return {"operations": []}
        client = CountingClient()
        batch = capabilities_many([selector, "order directory", "export order directory"], client=client,
                                  workspace=SimpleNamespace(recipes={}, products={}, datasources={}))
        self.assertEqual(["success", "success", "capability_gap"],
                         [item["status"] for item in batch["results"]])
        self.assertEqual((1, [selector], 0),
                         (client.inventory_calls, client.describe_calls, client.export_calls))
        sources = AgentSourceSnapshot(None, (), (), (), (),
                                      (copy.deepcopy(ORDER_DIRECTORY_CAPABILITY),
                                       copy.deepcopy(ORDER_DIRECTORY_CAPABILITY)), (), "0" * 64)
        query = "read order details north-secret for 2026-08-08"
        first = discover_capabilities(query, client=None, sources=sources, limit=1)
        token = first["continuation_token"]
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8"))
        self.assertEqual("order_directory", payload["query"])
        self.assertFalse(any(value in json.dumps(first) for value in ("north-secret", "2026-08-08")))
        second = discover_capabilities(query, client=None, sources=sources, limit=1, continuation=token)
        self.assertEqual((2, "success", 1), (first["total"], second["status"], second["count"]))
if __name__ == "__main__":
    unittest.main()
