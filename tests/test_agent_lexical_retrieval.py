from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agents.batch import capabilities_many
from gravity_sdk.agents.capabilities import composite_capability_inventory
from gravity_sdk.agents.caller_language import (
    CALLER_LANGUAGE_SOURCES,
    caller_language_fields,
)
from gravity_sdk.agents.discovery_support import (
    HOST_CATALOG_ARGV,
    UNRANKED_OPERATIONS,
    apply_unranked_operation_handoff,
)
from gravity_sdk.agents.lexical_retrieval import (
    ALGORITHM,
    MINIMUM_SCORE,
    registered_documents,
    retrieve_registered_products,
)
from gravity_sdk.agents.sql_product_discovery import WORKSPACE_SQL_NAME_ALGORITHM
from gravity_sdk.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]


class AgentLexicalRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()
        cls.inventory = composite_capability_inventory()

    def test_zero_candidate_fallback_reuses_one_registered_card(self) -> None:
        result = discover_capabilities(
            "看看覆盖数上传数来源和状态", client=self.client, limit=5
        )

        self.assertEqual(
            ["composite:custom_audience"],
            [card["selector"] for card in result["candidates"]],
        )
        receipt = result["match_policy"]["zero_candidate_lexical_fallback"]
        self.assertEqual("single_match", receipt["disposition"])
        self.assertEqual(ALGORITHM, receipt["algorithm"])
        self.assertGreaterEqual(receipt["top_score"], MINIMUM_SCORE)
        self.assertEqual(
            ALGORITHM,
            result["candidates"][0]["match"]["lexical_retrieval"]["algorithm"],
        )

    def test_low_confidence_abstains_and_multiple_hits_are_not_ranked(self) -> None:
        unrelated = retrieve_registered_products(
            "utterly unrelated quantum weather",
            composite_inventory=self.inventory,
        )
        self.assertEqual("below_threshold", unrelated.disposition)
        self.assertEqual((), unrelated.matches)
        result = discover_capabilities(
            "utterly unrelated quantum weather", client=self.client, limit=5
        )
        self.assertEqual([], result["candidates"])
        self.assertEqual(
            "below_threshold",
            result["match_policy"]["zero_candidate_lexical_fallback"]["disposition"],
        )

        multiple = retrieve_registered_products(
            "business_pulse custom_audience",
            composite_inventory=self.inventory,
        )
        self.assertEqual("multiple_matches", multiple.disposition)
        self.assertEqual(
            {"composite:business_pulse", "composite:custom_audience"},
            {match.document.selector for match in multiple.matches},
        )

    def test_verbose_paraphrase_rescue_requires_clear_indexed_evidence(self) -> None:
        selected = retrieve_registered_products(
            "帮忙还原某位用户一天内的画像、时间线和回传，账号与日期稍后提供。",
            composite_inventory=self.inventory,
        )
        self.assertEqual("composite:user_journey", selected.matches[0].document.selector)
        self.assertEqual("selected", selected.receipt()["indexed_rescue"]["reason"])

        adjacent = retrieve_registered_products(
            "那个页面里保存的筛选和收藏内容，其他细节随后再确认。",
            composite_inventory=self.inventory,
        )
        self.assertEqual("below_threshold", adjacent.disposition)
        self.assertNotEqual("selected", adjacent.receipt()["indexed_rescue"]["reason"])

    def test_high_confidence_product_card_is_not_handed_off(self) -> None:
        result = discover_capabilities(
            "custom audience status", client=self.client, limit=5
        )
        self.assertEqual(
            "composite:custom_audience", result["candidates"][0]["selector"]
        )
        self.assertNotIn("next", result)
        kept, gaps = apply_unranked_operation_handoff(
            "app.list",
            (
                ("operation", {"operation_id": "app.list", "agent_match": {"exact_selector": True}}),
                ("operation", {"operation_id": "app.detail"}),
                ("operation", {"operation_id": "app.app_info.get"}),
            ),
            (),
        )
        self.assertEqual("app.list", kept[0][1]["operation_id"])
        self.assertEqual((), gaps)

    def test_unranked_raw_operations_hand_choice_to_host_catalog(self) -> None:
        ranked = (
            ("operation", {"operation_id": "analysis.account_user.list"}),
            ("operation", {"operation_id": "analysis.event_property_value.list"}),
            ("operation", {"operation_id": "analysis.monetization_detail.list"}),
            ("catalog", {"kind": "composite", "selector": "composite:app_snapshot"}),
        )
        kept, gaps = apply_unranked_operation_handoff(
            "排那位用户当天的时间线和回传", ranked, ()
        )
        self.assertEqual([], kept)
        gap = gaps[0]
        self.assertEqual(UNRANKED_OPERATIONS, gap["code"])
        self.assertEqual(HOST_CATALOG_ARGV, gap["next"]["argv"])
        self.assertEqual(
            [
                "analysis.account_user.list",
                "analysis.event_property_value.list",
                "analysis.monetization_detail.list",
            ],
            gap["ranked_operation_ids"],
        )

    def test_existing_recognizer_result_is_not_replaced(self) -> None:
        result = discover_capabilities(
            "custom audience status", client=self.client, limit=5
        )
        self.assertEqual(
            "composite:custom_audience", result["candidates"][0]["selector"]
        )
        self.assertEqual(
            "not_needed",
            result["match_policy"]["zero_candidate_lexical_fallback"]["disposition"],
        )

        negated = discover_capabilities(
            "不要运行看板图表。", client=self.client, limit=5
        )
        self.assertEqual(("capability_gap", []), (
            negated["status"], negated["candidates"]
        ))
        self.assertEqual(
            "not_needed",
            negated["match_policy"]["zero_candidate_lexical_fallback"]["disposition"],
        )

    def test_retrieval_is_deterministic(self) -> None:
        decisions = [
            retrieve_registered_products(
                "custom_audience",
                composite_inventory=self.inventory,
            ).receipt()
            for _ in range(4)
        ]
        self.assertTrue(all(item == decisions[0] for item in decisions))
        self.assertEqual("single_match", decisions[0]["disposition"])
        self.assertEqual(
            "composite:custom_audience",
            decisions[0]["matches"][0]["selector"],
        )

    def test_indirect_workspace_sql_owner_uses_only_exact_registered_products(self) -> None:
        prompt = "有个团队已审过的跨表汇总口径，想按登记名称和时间窗把结果跑出来。"
        workspace = load_workspace(ROOT / "examples/workspace/gravity.toml")
        missing = discover_capabilities(
            prompt, client=self.client, workspace=replace(workspace, products={})
        )
        self.assertEqual([], missing["candidates"])
        self.assertEqual(
            "WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED",
            missing["capability_gaps"][0]["code"],
        )
        self.assertEqual(
            WORKSPACE_SQL_NAME_ALGORITHM,
            missing["match_policy"]["zero_candidate_lexical_fallback"]["algorithm"],
        )

        named = capabilities_many(
            [{"id": "sql", "query": (
                "团队已审过的 daily event summary 跨表汇总口径，按登记名称和时间窗跑出结果。"
            )}],
            client=self.client,
            workspace=workspace,
        )["results"][0]["result"]
        self.assertEqual(["sql:daily-event-summary"], [
            card["selector"] for card in named["candidates"]
        ])
        self.assertTrue(named["candidates"][0]["match"]["exact_registered_name"])
        self.assertNotIn("sql", named["candidates"][0])
        self.assertEqual("gravity", named["candidates"][0]["next"]["argv"][0])

        unnamed = discover_capabilities(prompt, client=self.client, workspace=workspace)
        self.assertEqual([], unnamed["candidates"])
        self.assertEqual(
            "WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED",
            unnamed["capability_gaps"][0]["code"],
        )

    def test_indirect_workspace_sql_owner_preserves_adjacent_boundaries(self) -> None:
        from gravity_sdk.agents import sql_product_gap as sql_gap

        self.assertFalse(sql_gap.registered_sql_product_intent(
            "按时间窗汇总多个 App 的业务趋势和小时脉搏。"
        ))
        self.assertFalse(sql_gap.registered_sql_product_intent(
            "临时写个查询语句做跨表汇总，不需要登记产品。"
        ))
        self.assertEqual((), sql_gap.registered_sql_product_names(
            "不要运行 daily-event-summary。", ({"name": "daily-event-summary"},)
        ))
        aggregate = discover_capabilities(
            "按平台、广告位和日期汇总变现结果", client=self.client
        )
        self.assertEqual("report.get.query", aggregate["candidates"][0]["selector"])

    def test_authoritative_caller_language_is_indexed(self) -> None:
        decision = retrieve_registered_products(
            "看起始行为后的用户留存",
            composite_inventory=self.inventory,
        )

        self.assertEqual(
            ["analysis.query.spec:retention"],
            [match.document.selector for match in decision.matches],
        )
        self.assertEqual(
            ("docs/analysis-journeys.md", "docs/agent-workflow.md"),
            CALLER_LANGUAGE_SOURCES,
        )
        self.assertEqual([], [
            document.selector
            for document in registered_documents(composite_inventory=self.inventory)
            if not caller_language_fields(document.selector)
        ])

    def test_operation_products_are_indexed_and_negated_reframes_keep_the_positive(self) -> None:
        from gravity_sdk.agents.intent_text import affirmative_intent_text

        selectors = {
            document.selector
            for document in registered_documents(composite_inventory=self.inventory)
        }
        self.assertTrue(
            {
                "app.list",
                "app.app_info.get",
                "report.get.query",
                "export.material.report.start",
            }.issubset(selectors)
        )
        self.assertEqual(
            "看公司层面的资源消耗随时间怎么变",
            affirmative_intent_text(
                "不是看某个 App 的业务量，我要看公司层面的资源消耗随时间怎么变。"
            ),
        )
        self.assertEqual(
            "",
            affirmative_intent_text("不要运行看板图表。"),
        )
        shared = "帮我找出我自己的、别人共享给我的以及 masterkey 报表，并读取报表定义。"
        self.assertEqual(shared, affirmative_intent_text(shared))
        self.assertEqual("", affirmative_intent_text("别给我素材报表"))
        self.assertEqual(
            "横比各平台素材表现",
            affirmative_intent_text("不是查计划或账户余额，我要横比各平台素材表现。"),
        )
        contrast = "这个行为每天发生量是不是在上升？"
        self.assertEqual(contrast, affirmative_intent_text(contrast))
        exclusive = "要看各平台独有字段而不是通用目录。"
        self.assertEqual(exclusive, affirmative_intent_text(exclusive))
        onelink = retrieve_registered_products(
            "查看 App 的 OneLink 与公开信息绑定",
            composite_inventory=self.inventory,
        )
        self.assertEqual("single_match", onelink.disposition)
        self.assertEqual("app.app_info.get", onelink.matches[0].document.selector)
        aggregate = retrieve_registered_products(
            "按平台广告位汇总变现收入",
            composite_inventory=self.inventory,
        )
        self.assertEqual("single_match", aggregate.disposition)
        self.assertEqual("report.get.query", aggregate.matches[0].document.selector)


if __name__ == "__main__":
    unittest.main()
