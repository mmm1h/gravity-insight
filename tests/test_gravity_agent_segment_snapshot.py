import unittest
from gravity_sdk.agent_capabilities import analysis_query_spec_cards, composite_capability_cards
from gravity_sdk.agent_handoff import attach_plan_node

class SegmentSnapshotAgentTest(unittest.TestCase):
    def test_strict_snapshot_intent_and_handoff_are_table_driven(self) -> None:
        positives = ("segment_snapshot",
                     "inspect segment details history and daily calculation result",
                     "check segment details history daily user count result",
                     "检查分群详情历史和单日计算结果",
                     "inspect audience snapshot details history and result for 2026-08-12",
                     "查看分群快照详情历史和2026-08-12计算结果")
        for query in positives:
            with self.subTest(query=query):
                cards = composite_capability_cards(query, domain=None, platform=None)
                self.assertEqual(["segment_snapshot"], [c["composite"] for c in cards])
                card = attach_plan_node(cards[0], query)
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertEqual(["app", "ref", "date"], card["missing_inputs"])
                self.assertEqual(
                    {"name": "segment_snapshot", "app": "<workspace-app-alias-or-positive-id>",
                     "ref": "<segment-id-or-exact-name>", "date": "<date:YYYY-MM-DD>"},
                    card["plan_node"]["request"],
                )
        excluded = ("segment", "segment snapshot",
                    "segment members details history daily results",
                    "inspect segment details history daily result user list",
                    "export segment details history daily results", "评估分群规则命中人数和占比")
        for query in excluded:
            with self.subTest(excluded=query):
                self.assertEqual([], composite_capability_cards(query, domain=None, platform=None))
        self.assertEqual("segment_evaluate", analysis_query_spec_cards(
            "evaluate segment rule condition population count", domain=None, platform=None)[0]["composite"])
