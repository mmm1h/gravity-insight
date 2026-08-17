from __future__ import annotations

import unittest

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_capabilities import composite_capability_inventory
from gravity_sdk.agent_caller_language import (
    CALLER_LANGUAGE_SOURCES,
    caller_language_fields,
)
from gravity_sdk.agent_lexical_retrieval import (
    ALGORITHM,
    MINIMUM_SCORE,
    registered_documents,
    retrieve_registered_products,
)


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
        from gravity_sdk.agent_intent_text import affirmative_intent_text

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
        onelink = retrieve_registered_products(
            "核对商店公开资料与 App 的关联",
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
