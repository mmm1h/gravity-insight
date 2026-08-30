from __future__ import annotations

import json
import unittest

from gravity_insight.agents.analysis_task import analysis_task_cards


class GravityAgentAnalysisTaskTests(unittest.TestCase):
    def test_explicit_analysis_tasks_are_unique_and_product_intents_are_excluded(self) -> None:
        cases = (
            ("analyze purchase trends", True),
            ("weekly active user count", True),
            ("conversion funnel analysis", True),
            ("cohort retention", True),
            ("分析过去7天成交用户数和转化率", True),
            ("查看付费用户占比", True),
            ("saved analysis trend", False),
            ("saved funnel analysis", False),
            ("保存的漏斗分析", False),
            ("评估人群规则命中人数", False),
            ("segment members analysis", False),
            ("受众详情分析", False),
            ("material report export", False),
            ("user journey analysis", False),
            ("customer journey funnel", False),
            ("用户路径分析", False),
            ("analysis", True),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                cards = analysis_task_cards(query, metadata_rows=())
                self.assertEqual(1 if expected else 0, len(cards))
                if expected:
                    self.assertEqual("analysis_task", cards[0]["kind"])
                    self.assertEqual("strong", cards[0]["match"]["confidence"])
        self.assertEqual([], analysis_task_cards("purchase trend", metadata_rows=(), domain="report"))
        self.assertEqual([], analysis_task_cards("purchase trend", metadata_rows=(), platform="material"))

    def test_card_uses_only_local_candidates_and_keeps_plan_non_executable(self) -> None:
        rows = (
            {"kind": "event", "app_id": "7", "name": "Purchase", "cname": "购买", "operation_id": "analysis.event.list", "payload": {"wire": "secret"}},
            {"kind": "user_property", "app_id": "7", "name": "PaidUser", "cname": "付费用户", "operation_id": "analysis.user_property.list"},
            {"kind": "metric", "scope": "workspace", "name": "ConversionRate", "cname": "转化率", "source": "report_metrics", "operation_id": "report.multidim.metric.list"},
            {"kind": "template", "name": "Purchase dashboard"},
            {"kind": "metric", "name": "UnrelatedRevenue", "cname": "收入"},
        )
        for metadata_rows, missing in ((rows, False), (None, True)):
            with self.subTest(catalog_missing=missing):
                card = analysis_task_cards("分析购买和付费用户转化率", metadata_rows=metadata_rows)[0]
                self.assertEqual(["app", "kind", "time", "steps|metrics"], card["missing_decisions"])
                self.assertEqual("<explicit-event|funnel|retention|property|scatter>", card["input_template"]["kind"])
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertFalse(card["plan_executable"])
                self.assertIsNone(card["plan_node"])
                self.assertEqual("analysis_query", card["plan_template"]["request"]["name"])
                self.assertEqual("<explicit-gravity-insight.analysis-query-spec.v1-object>", card["plan_template"]["request"]["spec"])
                self.assertEqual(missing, card["catalog_missing"])
                if missing:
                    self.assertEqual(["gravity", "metadata", "sync", "--all-apps"], card["catalog_sync_argv"])
                else:
                    candidates = [item for values in card["metadata_candidates"].values() for item in values]
                    self.assertEqual({"Purchase", "PaidUser", "ConversionRate"}, {item["name"] for item in candidates})
                    self.assertTrue(all(item["selected"] is False for item in candidates))
                    rendered = json.dumps(card, ensure_ascii=False)
                    self.assertNotIn("secret", rendered)
                    self.assertNotIn("UnrelatedRevenue", rendered)


if __name__ == "__main__":
    unittest.main()
