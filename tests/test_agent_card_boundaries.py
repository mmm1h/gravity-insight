from __future__ import annotations

import copy
import unittest
import unittest.mock

from gravity_sdk.agent_host_catalog import (
    host_product_catalog,
    owner_boundaries,
    validate_host_catalog_projection,
)
from gravity_sdk.agent_product_inventory import canonical_capability_cards
from gravity_sdk.agent_unavailable import registered_unavailable_gaps
from gravity_sdk.client import GravityInsightClient


GENERIC = (
    "Use only for this exact returned object or action; keep neighboring products separate."
)
MUTATION = (
    "Selection is read-only; preview and execute still require the governed user authorization flow."
)


def _card(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "selector": "composite:fixture",
        "description": "读取固定快照；不执行邻近查询。",
        "required_inputs": ("app",),
        "effect": "read",
        "executable": True,
        "boundaries": ("不执行邻近查询。",),
    }
    payload.update(overrides)
    return payload


class OwnerBoundaryFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()
        cls.cards = canonical_capability_cards(cls.client)
        cls.catalog = host_product_catalog(cls.client)

    def test_every_canonical_product_card_declares_non_empty_boundaries(self) -> None:
        for card in self.cards:
            with self.subTest(selector=card["selector"]):
                clauses = owner_boundaries(card)
                self.assertTrue(clauses)
                self.assertTrue(all(isinstance(item, str) and item.strip() for item in clauses))

    def test_missing_or_empty_owner_boundaries_fail_closed(self) -> None:
        missing = _card()
        missing.pop("boundaries")
        with self.assertRaisesRegex(RuntimeError, "must declare non-empty boundaries"):
            owner_boundaries(missing)
        with self.assertRaisesRegex(RuntimeError, "must declare non-empty boundaries"):
            owner_boundaries(_card(boundaries=()))
        with self.assertRaisesRegex(RuntimeError, "non-empty strings"):
            owner_boundaries(_card(boundaries=(" ",)))

    def test_composite_inventory_rejects_a_card_without_boundaries(self) -> None:
        from gravity_sdk.agent_capabilities import composite_capability_inventory
        from gravity_sdk.agent_composite_inventory import COMPOSITE_CAPABILITIES

        broken = dict(COMPOSITE_CAPABILITIES[0])
        broken.pop("boundaries", None)
        with unittest.mock.patch(
            "gravity_sdk.agent_capabilities._COMPOSITE_CAPABILITIES",
            (broken, *COMPOSITE_CAPABILITIES[1:]),
        ):
            with self.assertRaisesRegex(RuntimeError, "must declare non-empty boundaries"):
                composite_capability_inventory()

    def test_description_rewrite_does_not_drop_owner_boundaries(self) -> None:
        card = _card(
            description="读取固定快照，用逗号连接限制只做展示。",
            boundaries=("不执行邻近查询。", "不要用于事件趋势。"),
        )
        self.assertEqual(
            ["不执行邻近查询。", "不要用于事件趋势。"],
            owner_boundaries(card),
        )

    def test_host_projection_equals_owner_boundaries(self) -> None:
        cards = {card["selector"]: card for card in self.cards}
        for entry in self.catalog["entries"]:
            if entry["identity_kind"] != "product":
                continue
            with self.subTest(selector=entry["catalog_ref"]):
                self.assertEqual(
                    owner_boundaries(cards[entry["catalog_ref"]]),
                    entry["boundaries"],
                )

    def test_forged_or_deleted_host_boundaries_are_projection_drift(self) -> None:
        cards = canonical_capability_cards(self.client)
        gaps = registered_unavailable_gaps()
        drifted = copy.deepcopy(self.catalog)
        product = next(item for item in drifted["entries"] if item["identity_kind"] == "product")
        product["boundaries"] = [GENERIC]
        with self.assertRaisesRegex(RuntimeError, "owner projection drift"):
            validate_host_catalog_projection(drifted, product_cards=cards, gaps=gaps)

    def test_mutation_cards_keep_the_authorization_boundary(self) -> None:
        mutations = [card for card in self.cards if card.get("effect") == "mutation"]
        self.assertTrue(mutations)
        for card in mutations:
            with self.subTest(selector=card["selector"]):
                self.assertIn(MUTATION, owner_boundaries(card))
        with self.assertRaisesRegex(RuntimeError, "mutation authorization boundary"):
            owner_boundaries(_card(effect="mutation", boundaries=("自然语言永不自动写入。",)))

    def test_adjacent_product_owner_boundaries_survive_projection(self) -> None:
        expected = {
            "app.list": "不用于 App 治理快照",
            "composite:dashboard_snapshot": "不执行图表",
            "analysis.query.spec:funnel": "不返回转化率",
            "report.get.query": "不是单日逐行变现明细",
            "composite:derived_metrics": "不要用于用同一 Analysis Spec 重跑两个时期",
        }
        by_ref = {item["catalog_ref"]: item for item in self.catalog["entries"]}
        for selector, fragment in expected.items():
            with self.subTest(selector=selector):
                text = " ".join(by_ref[selector]["boundaries"])
                self.assertIn(fragment, text)
