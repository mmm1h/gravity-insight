import json, unittest
from unittest.mock import patch
from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_batch import capabilities_many
from gravity_sdk.agent_monetization_guard import (
    MONETIZATION_DETAIL_RAW_SELECTOR as READ,
    MONETIZATION_EXPORT_RAW_SELECTOR as EXPORT,
    monetization_guard_blocks_operation_fallback as guarded,
)
class NoScan:
    def blocked(self, *_args, **_options):
        raise AssertionError("monetization discovery must stay local")
    operations = operation_inventory = describe = export_capabilities = blocked
class MonetizationGuardAgentTests(unittest.TestCase):
    def test_approved_detail_intents_return_one_value_free_card(self):
        queries = (
            "monetization details", "monetization-details", "monetization directory", "monetization rows",
            "monetization list", "变现明细", "变现 目录", "monetization 变现明细",
            "无标识变现明细",
        )
        for query in queries:
            with self.subTest(query=query):
                result = discover_capabilities(query, client=NoScan())
                self.assertEqual((True, "success", ["monetization_detail"]), (
                    guarded(query), result["status"], [item["composite"] for item in result["candidates"]],
                ))
                card = result["candidates"][0]
                self.assertEqual(["app", "date"], card["missing_inputs"])
                self.assertEqual({
                    "name": "monetization_detail",
                    "app": "<workspace-app-alias-or-positive-id>",
                    "date": "<date:YYYY-MM-DD>",
                }, card["plan_node"]["request"])
                self.assertFalse(card["natural_language_auto_execute"])
    def test_unapproved_shapes_remain_local_value_free_gaps(self):
        queries = (
            "not monetization details", "export monetization detail", "write monetization details",
            "monetization details from 2026-08-01 to 2026-08-08", "monetization details ClientID north-secret",
            "monetization details user_id north-secret", "monetization details fields AdPlatform",
            "monetization details filter advertiser north-secret", "monetization details group by user",
            "带标识变现明细", "无标识变现明细按用户分组", "变现明细按标识筛选", "无标识变现明细跨日",
            "monetization details summary", "dashboard snapshot monetization details", "变现明细按用户分组",
            "变现明细聚合报表", f"{READ} north-secret", f"{READ.rsplit('.', 1)[0]} north-secret",
            f"{READ.removeprefix('analysis.')} north-secret", f"{EXPORT} north-secret",
        )
        for query in queries:
            with self.subTest(query=query):
                result = discover_capabilities(query, client=NoScan())
                self.assertEqual((True, "capability_gap", [], "monetization_detail"), (
                    guarded(query), result["status"], result["candidates"], result["query"],
                ))
                rendered = json.dumps(result, ensure_ascii=False)
                self.assertFalse(any(value in rendered for value in ("north-secret", "2026-08-01", READ, EXPORT)))
        with patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []}):
            batch = capabilities_many(queries, client=NoScan())
        self.assertTrue(all(item["status"] == "capability_gap" for item in batch["results"]))
    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_exact_raw_and_other_user_level_discovery_stay_compatible(self, _metadata):
        for query in (
            "monetization", "变现", "list monetization apps", "monetization report", "monetization summary",
            "monetization attribution", "monetization dashboard", f" {READ.upper()} ", EXPORT,
        ):
            self.assertFalse(guarded(query))
        client = GravityInsightClient.from_env()
        self.assertEqual(EXPORT, discover_capabilities(EXPORT, client=client)["query"])
        with patch.object(client, "operation_inventory", wraps=client.operation_inventory) as inventory, \
             patch.object(client, "describe", wraps=client.describe) as describe, \
             patch.object(client, "export_capabilities", wraps=client.export_capabilities) as exports:
            batch = capabilities_many([READ, "monetization details", "account user"], client=client)
        self.assertEqual(["success", "success", "success"],
                         [item["status"] for item in batch["results"]])
        self.assertEqual(READ, batch["results"][0]["result"]["candidates"][0]["selector"])
        self.assertEqual("monetization_detail",
                         batch["results"][1]["result"]["candidates"][0]["composite"])
        inventory.assert_called_once()
        exports.assert_not_called()
        self.assertEqual(1, sum(call.args == (READ,) for call in describe.call_args_list))
if __name__ == "__main__":
    unittest.main()
