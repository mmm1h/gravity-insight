from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import unittest

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import SCHEMA_VERSION as AGENT_SCHEMA_VERSION, discover_capabilities
from gravity_sdk.agent_catalog import SCHEMA_VERSION, _inventory, run_agent_catalog_command
from gravity_sdk.agents.catalog_parity import validate_catalog_parity
from gravity_sdk.agent_product_inventory import canonical_capability_cards
from gravity_sdk.agent_unavailable import registered_unavailable_gaps
from gravity_sdk.agent_unavailable import unavailable_journey_gap
from gravity_sdk.multidim_contract import (
    MULTIDIM_COHORT_HORIZON_GAP_CODE,
    multidim_multi_key_contract,
)


def _args(action: str, **values: object) -> SimpleNamespace:
    return SimpleNamespace(agent_catalog_command=action, **values)


class AgentCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()

    def test_categories_are_manifest_and_card_derived_offline(self) -> None:
        result = run_agent_catalog_command(_args("categories"), self.client)
        self.assertEqual(SCHEMA_VERSION, result["schema_version"])
        self.assertTrue(result["offline"])
        self.assertFalse(result["network_called"])
        analysis = next(item for item in result["categories"] if item["name"] == "analysis")
        self.assertGreater(analysis["composites"], 0)
        self.assertGreater(analysis["operations"], 0)

    def test_category_is_bounded_and_describe_reuses_existing_card(self) -> None:
        listed = run_agent_catalog_command(
            _args("category", name="analysis", limit=1, offset=0), self.client
        )
        self.assertEqual("get_category_capabilities", listed["mode"])
        self.assertEqual(1, listed["count"])
        self.assertEqual(1, len(listed["capabilities"]))

        described = run_agent_catalog_command(
            _args("describe", selector="composite:analysis_context"), self.client
        )
        self.assertEqual("describe_capability", described["mode"])
        self.assertEqual("composite:analysis_context", described["capability"]["selector"])
        self.assertEqual("read", described["capability"]["effect"])

    def test_unknown_category_and_selector_point_at_catalog_browse(self) -> None:
        from gravity_sdk.errors import InputValidationError

        with self.assertRaises(InputValidationError) as category_error:
            run_agent_catalog_command(
                _args("category", name="nope", limit=20, offset=0), self.client
            )
        self.assertEqual("name", category_error.exception.field)
        self.assertIn("agent-catalog categories", category_error.exception.next_action)
        with self.assertRaises(InputValidationError) as selector_error:
            run_agent_catalog_command(
                _args("describe", selector="not.a.selector"), self.client
            )
        self.assertEqual("selector", selector_error.exception.field)
        self.assertIn("agent-catalog category", selector_error.exception.next_action)

    def test_existing_agent_protocol_is_unchanged(self) -> None:
        result = discover_capabilities("event analysis", client=self.client)
        self.assertEqual(AGENT_SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("discover_and_describe", result["mode"])

    def test_registered_gap_inventory_has_seven_unique_machine_codes(self) -> None:
        """Went 6 -> 7 for issue #25's post-contract Multidim cohort horizon.

        The added gap keeps upstream-unavailable cohort semantics out of caller
        input blame and explicitly forbids generic event-retention substitution.
        """

        gaps = registered_unavailable_gaps()
        self.assertEqual(7, len(gaps))
        self.assertEqual(7, len({gap["code"] for gap in gaps}))

    def test_post_contract_multidim_discovery_returns_the_registered_gap(self) -> None:
        contract = multidim_multi_key_contract()
        gap = unavailable_journey_gap(
            f"query multidim acquisition cohort horizon D{contract.maximum + 30}"
        )

        self.assertIsNotNone(gap)
        self.assertEqual(MULTIDIM_COHORT_HORIZON_GAP_CODE, gap["code"])
        self.assertEqual("multidim_cohort_horizon", gap["journey"])
        self.assertEqual(contract.reason, gap["reason"])
        self.assertEqual(contract.next_action, gap["next_action"])
        self.assertFalse(gap["network_called"])
        self.assertNotIn("use generic event retention", gap["next_action"])
        self.assertIn("do not substitute generic event retention", gap["next_action"])

    def test_catalog_has_complete_cards_gaps_and_contract_status_parity(self) -> None:
        inventory = _inventory(self.client)
        products = canonical_capability_cards(self.client)
        gaps = registered_unavailable_gaps()
        operations = tuple(self.client.operations(stability=None))
        product_items = {
            item["selector"]: item for item in inventory
            if item["identity_kind"] == "product"
        }
        gap_items = {
            item["gap_code"]: item for item in inventory
            if item["identity_kind"] == "capability_gap"
        }
        self.assertEqual(97, len(products))
        self.assertEqual({card["selector"] for card in products}, set(product_items))
        self.assertEqual({gap["code"] for gap in gaps}, set(gap_items))
        self.assertTrue(all(not item["executable"] for item in gap_items.values()))
        self.assertTrue(all(item["next_action"] for item in gap_items.values()))

        root = Path(__file__).resolve().parents[1]
        expectation_path = root / "scripts" / "agent_usability_expectations.py"
        spec = importlib.util.spec_from_file_location("catalog_expectations", expectation_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        expectations = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(expectations)
        targets, _, _ = expectations._targets(expectations.TARGETS_PATH)
        statuses, _ = expectations._ledger_statuses(targets, expectations.LEDGER_PATH)
        ledger_gaps = {
            target["gap"]["gap_code"]
            for journey, target in targets.items()
            if statuses[journey] != "已闭环"
        }
        self.assertLessEqual(ledger_gaps, set(gap_items))

        raw = next(item for item in inventory if item["selector"] == "app.realtime_event.list")
        missing = gap_items["MEDIA_REPORT_ITEM_SCHEMA_MISSING"]
        self.assertEqual("raw_operation", raw["identity_kind"])
        self.assertFalse(raw["product_equivalent"])
        self.assertEqual("registered_unavailable", missing["catalog_status"])

        conflicted = [dict(item) for item in inventory]
        target = next(
            item for item in conflicted if item["selector"] == "app.realtime_event.list"
        )
        target["executable"] = False
        with self.assertRaisesRegex(
            RuntimeError, "operation executable-status drift.*app.realtime_event.list"
        ):
            validate_catalog_parity(
                conflicted,
                product_cards=products,
                operations=operations,
                gaps=gaps,
            )

    def test_every_public_mutation_action_has_a_safe_catalog_handoff(self) -> None:
        from gravity_sdk.kanban_mutation import kanban_mutation_schema
        from gravity_sdk.metadata_template_mutation import metadata_template_mutation_schema
        from gravity_sdk.segment_mutation_cli import MUTATION_ACTIONS

        cards = [
            card for card in canonical_capability_cards(self.client)
            if card.get("effect") == "mutation"
        ]
        by_kind = {
            kind: {card["mutation_action"] for card in cards if card["kind"] == kind}
            for kind in (
                "segment_mutation", "report_mutation", "kanban_mutation",
                "custom_metric_mutation", "metadata_template_mutation",
                "saved_analysis_mutation", "realtime_event_mutation",
            )
        }
        self.assertEqual(set(MUTATION_ACTIONS), by_kind["segment_mutation"])
        self.assertEqual(
            {
                "create-report", "delete-report",
                "create-subscription", "delete-subscription",
            },
            by_kind["report_mutation"],
        )
        self.assertEqual(
            set(kanban_mutation_schema()["actions"]),
            by_kind["kanban_mutation"],
        )
        self.assertEqual(
            {"create", "update", "delete"},
            by_kind["custom_metric_mutation"],
        )
        self.assertEqual(
            set(metadata_template_mutation_schema()["actions"]),
            by_kind["metadata_template_mutation"],
        )
        self.assertEqual(
            {"create", "update", "delete"},
            by_kind["saved_analysis_mutation"],
        )
        self.assertEqual({"update"}, by_kind["realtime_event_mutation"])
        self.assertEqual(43, len(cards))

        stable_mutations = {
            item["operation_id"]
            for item in self.client.operations(stability="stable")
            if self.client.describe(item["operation_id"]).get("effect") == "mutation"
        }
        coverage = Counter(
            operation_id
            for card in cards
            for operation_id in (card.get("operation_ids") or (card["operation_id"],))
        )
        scaffolding = {"report.template.create", "report.template.update"}
        self.assertEqual(stable_mutations - scaffolding, set(coverage))
        self.assertTrue(scaffolding.isdisjoint(coverage))
        self.assertEqual(
            {
                "analysis.dataanalysis.segment.update",
                "analysis.datamanageconfig.kanban.dashboard.delete",
                "analysis.datamanageconfig.kanban.dashboard.update",
                "report.report.update",
                "report.confmetric.custom.metric.update",
                "metadata.event.property.template.079c8246.create",
            },
            {operation_id for operation_id, count in coverage.items() if count == 2},
        )
        self.assertEqual(
            {"analysis.report_config.update"},
            {operation_id for operation_id, count in coverage.items() if count == 3},
        )
        self.assertTrue(all(count in {1, 2, 3} for count in coverage.values()))

        for card in cards:
            with self.subTest(selector=card["selector"]):
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertTrue(card["confirmation_required"])
                self.assertIn(card["mutation_action"], card["match"]["matched_terms"])
                self.assertFalse(card["next"]["ready_without_input"])
                self.assertEqual("--dry-run", card["next"]["argv"][-1])
                self.assertEqual("--execute", card["next"]["then_argv"][-1])
                self.assertEqual(
                    card["next"]["argv"][:-1], card["next"]["then_argv"][:-1]
                )
                if card["kind"] in {
                    "kanban_mutation", "custom_metric_mutation",
                    "metadata_template_mutation",
                }:
                    self.assertTrue(card["plan_executable"])
                    self.assertEqual(
                        ("preview", "execute"),
                        (
                            card["next"]["plan_node"]["request"]["mode"],
                            card["next"]["then_plan_node"]["request"]["mode"],
                        ),
                    )
                else:
                    self.assertFalse(card["plan_executable"])

    def test_gap_describe_is_explicitly_unavailable(self) -> None:
        result = run_agent_catalog_command(
            _args(
                "describe",
                selector="gap:MEDIA_REPORT_ITEM_SCHEMA_MISSING",
            ),
            self.client,
        )
        self.assertFalse(result["capability"]["executable"])
        self.assertEqual("unavailable", result["capability"]["availability"])
        self.assertIn("media report", result["next_action"])

    def test_named_gap_describe_envelope_keeps_the_gap_argv(self) -> None:
        result = run_agent_catalog_command(
            _args(
                "describe",
                selector="gap:ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
            ),
            self.client,
        )
        gap = result["capability"]
        self.assertEqual(
            ["gravity", "export", "list-capabilities"],
            gap["next"]["argv"],
        )
        self.assertEqual(gap["next"]["argv"], result["next"]["argv"])
        self.assertEqual(gap["next_action"], result["next_action"])

    def test_product_describe_envelope_does_not_advertise_plan_run(self) -> None:
        result = run_agent_catalog_command(
            _args("describe", selector="analysis.query.spec:event"),
            self.client,
        )
        self.assertEqual(
            ["gravity", "plan", "run", "--input", "<plan.json>"],
            result["capability"]["next"]["argv"],
        )
        self.assertNotIn("next", result)
        self.assertIn("never executes", result["next_action"])

    def test_same_selector_describe_surfaces_keep_the_full_input_contract(self) -> None:
        from gravity_sdk.find import run_operation_command

        for selector in ("report.get.query", "app.list", "app.app_info.get"):
            with self.subTest(selector=selector):
                agent = run_agent_catalog_command(
                    _args("describe", selector=selector), self.client
                )
                ops = run_operation_command(
                    SimpleNamespace(
                        operation_command="describe", operation_id=selector
                    ),
                    self.client,
                    lambda *_args: None,
                )
                self.assertEqual(
                    set(ops["input_schema"]), set(agent["capability"]["input_schema"])
                )
                self.assertEqual("operations", ops["surface"]["name"])
                self.assertEqual("agent-catalog", agent["surface"]["name"])
                self.assertEqual(
                    ["gravity", "operations", "describe", selector],
                    agent["surface"]["complete_contract"],
                )

    def test_products_precede_raw_operations_and_metadata_cards_are_actionable(self) -> None:
        inventory = _inventory(self.client)
        ranks = {"product": 0, "raw_operation": 1, "capability_gap": 2}
        for domain in {item["domain"] for item in inventory}:
            ordered = [
                ranks[item["identity_kind"]]
                for item in inventory if item["domain"] == domain
            ]
            self.assertEqual(sorted(ordered), ordered, domain)

        first_page = run_agent_catalog_command(
            _args("category", name="analysis", limit=20, offset=0), self.client
        )
        selectors = [item["selector"] for item in first_page["capabilities"]]
        self.assertIn("analysis.query.spec:event", selectors)
        self.assertTrue(all(
            item["identity_kind"] == "product"
            for item in first_page["capabilities"]
        ))

        for query, selector, kind in (
            ("只同步指定 App 的元数据", "metadata:sync_app", "composite"),
            ("show local metadata status", "metadata:status", "metadata_search"),
        ):
            result = discover_capabilities(query, client=self.client)
            card = result["candidates"][0]
            self.assertEqual(selector, card["selector"])
            self.assertEqual(kind, card["plan_node"]["kind"])


class AgentGuideGenerationTests(unittest.TestCase):
    def test_committed_guides_match_the_contract_generator(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "generate_agent_skills.py"
        spec = importlib.util.spec_from_file_location("agent_guides", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path, content in module.render_documents().items():
            with self.subTest(path=path.name):
                self.assertEqual(content, path.read_text(encoding="utf-8"))


class AgentTaskGuideCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.guides = cls.root / "docs" / "agent-skills"
        cls.client = GravityInsightClient.from_env()

    def test_funnel_guide_names_hit_phrases_and_denies_conversion_rate(self) -> None:
        text = (self.guides / "funnel.md").read_text(encoding="utf-8")
        index = (self.guides / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 看多步行为的转化漏斗 |", index)
        self.assertIn("](funnel.md)", index)
        self.assertIn("转化漏斗", text)
        self.assertIn("看多步行为的转化漏斗", text)
        self.assertIn("analysis.task.handoff", text)
        self.assertIn("不返回转化率", text)
        self.assertIn("previous_step", text)
        self.assertIn("first_step", text)
        result = discover_capabilities("转化漏斗", client=self.client, limit=1)
        self.assertEqual("analysis.query.spec:funnel", result["candidates"][0]["selector"])
        self.assertTrue(result["candidates"][0]["executable"])
        long_ask = discover_capabilities(
            "注册到后续行为的漏斗，近 7 天每步人数", client=self.client, limit=1
        )
        self.assertEqual("analysis.task.handoff", long_ask["candidates"][0]["selector"])
        self.assertFalse(long_ask["candidates"][0]["executable"])

    def test_retention_guide_names_hit_phrase_and_treats_empty_as_legal(self) -> None:
        text = (self.guides / "retention.md").read_text(encoding="utf-8")
        index = (self.guides / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 看起始行为后的用户留存 |", index)
        self.assertIn("](retention.md)", index)
        self.assertIn("某起始事件后的次日和 7 日留存", text)
        self.assertIn("analysis.query.spec:retention", text)
        self.assertIn("空信封", text)
        self.assertIn("offset", text)
        result = discover_capabilities(
            "某起始事件后的次日和 7 日留存", client=self.client, limit=2
        )
        self.assertEqual(
            "analysis.query.spec:retention", result["candidates"][0]["selector"]
        )
        self.assertTrue(result["candidates"][0]["executable"])

    def test_export_guide_requires_request_column_codes_and_completion_status(self) -> None:
        text = (self.guides / "user-detail-export.md").read_text(encoding="utf-8")
        index = (self.guides / "index.md").read_text(encoding="utf-8")
        self.assertIn("| 把某一天的用户明细导出成文件 |", index)
        self.assertIn("](user-detail-export.md)", index)
        self.assertIn("把某一天的用户明细导出成文件并下载", text)
        self.assertIn("export.analysis.user_detail.start", text)
        self.assertIn("ClientID,CreateTime", text)
        self.assertIn("客户ID,注册时间", text)
        self.assertIn("completion_status", text)
        self.assertIn("`complete`", text)
        self.assertIn("`truncated`", text)
        self.assertIn("`partial`", text)
        result = discover_capabilities(
            "把某一天的用户明细导出成文件并下载", client=self.client, limit=1
        )
        self.assertEqual(
            "export.analysis.user_detail.start", result["candidates"][0]["selector"]
        )
        self.assertTrue(result["candidates"][0]["executable"])


if __name__ == "__main__":
    unittest.main()
