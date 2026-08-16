from __future__ import annotations

from types import SimpleNamespace
import importlib.util
from pathlib import Path
import unittest

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import SCHEMA_VERSION as AGENT_SCHEMA_VERSION, discover_capabilities
from gravity_sdk.agent_catalog import SCHEMA_VERSION, _inventory, run_agent_catalog_command
from gravity_sdk.agent_catalog_parity import validate_catalog_parity
from gravity_sdk.agent_product_inventory import canonical_capability_cards
from gravity_sdk.agent_unavailable import registered_unavailable_gaps


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

    def test_existing_agent_protocol_is_unchanged(self) -> None:
        result = discover_capabilities("event analysis", client=self.client)
        self.assertEqual(AGENT_SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("discover_and_describe", result["mode"])

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
        self.assertEqual(42, len(products))
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
        missing = gap_items["REALTIME_EVENT_CATALOG_CONTRACT_MISSING"]
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

    def test_gap_describe_is_explicitly_unavailable(self) -> None:
        result = run_agent_catalog_command(
            _args(
                "describe",
                selector="gap:REALTIME_EVENT_CATALOG_CONTRACT_MISSING",
            ),
            self.client,
        )
        self.assertFalse(result["capability"]["executable"])
        self.assertEqual("unavailable", result["capability"]["availability"])
        self.assertIn("non-empty catalog", result["next_action"])


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


if __name__ == "__main__":
    unittest.main()
