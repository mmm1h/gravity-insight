import unittest

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agents.capabilities import (
    authoritative_capability_cards,
    composite_capability_cards,
)
from gravity_sdk.agents.handoff import attach_plan_node


class SavedAnalysisAgentTest(unittest.TestCase):
    def test_common_replay_requests_produce_one_safe_fillable_card(self) -> None:
        queries = (
            "saved analysis",
            "run saved analysis daily-purchases",
            "replay saved report report-42",
            "prepare saved analysis weekly retention",
            "运行保存分析 日购趋势",
            "按引用 report-42 重放已保存报表",
        )
        expected = {
            "name": "saved_analysis",
            "app": "<workspace-app-alias-or-positive-id>",
            "ref": "<saved-analysis-id-or-exact-name>",
            "start": "<start:YYYY-MM-DD>",
            "end": "<end:YYYY-MM-DD>",
            "mode": "run",
        }
        for query in queries:
            with self.subTest(query=query):
                cards = composite_capability_cards(query, domain=None, platform=None)
                self.assertEqual(["saved_analysis"], [c["composite"] for c in cards])
                card = attach_plan_node(cards[0], query)
                self.assertEqual(["app", "ref", "start", "end"], card["missing_inputs"])
                self.assertEqual(expected, card["plan_node"]["request"])
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertEqual([card], authoritative_capability_cards([card]))

        discovered = discover_capabilities("run saved analysis report-42", client=None)
        self.assertEqual((1, 1), (discovered["count"], discovered["total"]))
        self.assertEqual("saved_analysis", discovered["candidates"][0]["composite"])

    def test_ui_and_ambiguous_saved_requests_fail_closed(self) -> None:
        for query in (
            "saved",
            "create saved analysis",
            "saved report templates",
            "show saved report layout",
            "查看保存报表收藏和权限",
            "保存这个分析",
            "帮我保存这个分析",
            "dashboard saved filters",
        ):
            with self.subTest(query=query):
                self.assertNotIn(
                    "saved_analysis",
                    [
                        card["composite"]
                        for card in composite_capability_cards(
                            query, domain=None, platform=None
                        )
                    ],
                )


if __name__ == "__main__":
    unittest.main()
