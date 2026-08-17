from __future__ import annotations

import copy
import unittest

from unittest.mock import patch

from gravity_sdk.agent import run_agent_command
from gravity_sdk.agent_host_catalog import (
    SELECTION_SCHEMA_VERSION,
    host_product_catalog,
    validate_host_catalog_projection,
)
from gravity_sdk.agent_host_selection import (
    EMPTY_SELECTION_GAP,
    DEFAULT_ROUTING_MODE,
    assess_host_product_selection,
    compile_host_product_selection,
    resolve_host_product_selection,
)
from gravity_sdk.agent_product_inventory import canonical_capability_cards
from gravity_sdk.agent_unavailable import registered_unavailable_gaps
from gravity_sdk.cli import build_parser
from gravity_sdk.client import GravityInsightClient
from gravity_sdk.errors import InputValidationError


class _NoNetwork:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("host selection must not request Gravity")


class HostProductSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()
        cls.catalog = host_product_catalog(cls.client)

    def response(self, *refs: str, decision: str | None = None) -> dict:
        count = len(refs)
        return {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "catalog_sha256": self.catalog["catalog_sha256"],
            "query": "compare this week with last week using one analysis definition",
            "decision": decision or (
                "abstained" if not count else "selected" if count == 1 else "multiple_intents"
            ),
            "reason": {"summary": "catalog boundaries checked", "needs_clarification": not refs},
            "candidates": [
                {
                    "catalog_ref": ref,
                    "reason": {"goal_match": "requested result", "boundary_check": "neighbor excluded"},
                }
                for ref in refs
            ],
        }

    def test_host_catalog_is_exact_card_gap_projection_without_raw_operations(self) -> None:
        cards = canonical_capability_cards(self.client)
        gaps = registered_unavailable_gaps()
        refs = {item["catalog_ref"] for item in self.catalog["entries"]}
        self.assertEqual(99, len(refs))
        self.assertEqual(
            {card["selector"] for card in cards} | {f"gap:{gap['code']}" for gap in gaps},
            refs,
        )
        self.assertNotIn("analysis.event.list", refs)
        validate_host_catalog_projection(self.catalog, product_cards=cards, gaps=gaps)
        drifted = copy.deepcopy(self.catalog)
        drifted["entries"][0]["does_and_returns"] = "forged"
        with self.assertRaisesRegex(RuntimeError, "owner projection drift"):
            validate_host_catalog_projection(drifted, product_cards=cards, gaps=gaps)

    def test_zero_and_multiple_candidates_have_deterministic_canonical_gaps(self) -> None:
        query = self.response()["query"]
        empty = resolve_host_product_selection(query, self.response(), self.client)
        self.assertEqual(EMPTY_SELECTION_GAP, empty["capability_gaps"][0]["code"])
        self.assertNotIn("operation_id", empty["capability_gaps"][0])

        multiple = resolve_host_product_selection(
            query,
            self.response("composite:derived_metrics", "analysis.query.spec"),
            self.client,
        )
        gap = multiple["capability_gaps"][0]
        self.assertEqual("MULTIPLE_INTENTS", gap["code"])
        self.assertEqual(
            ["analysis.query.spec", "composite:derived_metrics"],
            gap["candidate_selectors"],
        )

    def test_malformed_forged_product_and_direct_operation_fail_closed(self) -> None:
        query = self.response()["query"]
        malformed = self.response("analysis.query.spec")
        malformed["candidates"][0]["reason"].pop("boundary_check")
        with self.assertRaisesRegex(InputValidationError, "HOST_SELECTION_REASON_INVALID"):
            compile_host_product_selection(query, malformed, self.client)

        for forged in ("product:not-registered", "analysis.event.list"):
            with self.subTest(forged=forged):
                report = assess_host_product_selection(
                    query, self.response(forged), self.client
                )
                self.assertFalse(report["allowed"])
                self.assertIn(
                    "HOST_PRODUCT_IDENTITY_MISMATCH",
                    {item["code"] for item in report["violations"]},
                )
        direct = self.response("analysis.query.spec")
        direct["candidates"][0]["operation"] = "analysis.event.list"
        self.assertFalse(assess_host_product_selection(query, direct, self.client)["allowed"])

    def test_single_product_is_repository_described_and_sdk_source_bound(self) -> None:
        query = self.response()["query"]
        result = resolve_host_product_selection(
            query, self.response("analysis.query.spec"), self.client
        )
        self.assertEqual("analysis.query.spec", result["candidates"][0]["selector"])
        self.assertEqual("host_catalog", result["candidates"][0]["match"]["confidence"])
        self.assertEqual(
            "gravity.host-source.v1 sdk_contract/instruction",
            result["selection_receipt"]["source_boundary"],
        )
        self.assertIn("plan_node", result["candidates"][0])

    def test_selecting_a_mutation_product_has_no_write_effect(self) -> None:
        query = self.response()["query"]
        transport = _NoNetwork()
        with patch.object(self.client._executor._transport, "request", transport.request):
            result = resolve_host_product_selection(
                query, self.response("analysis.segment.mutation:delete"), self.client
            )
        card = result["candidates"][0]
        self.assertEqual(0, transport.calls)
        self.assertEqual("mutation", card["effect"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertFalse(card["next"]["ready_without_input"])

    def test_cli_default_and_unspecified_behavior_remain_recognizer(self) -> None:
        args = build_parser().parse_args(["agent", "event analysis"])
        self.assertEqual(DEFAULT_ROUTING_MODE, args.routing)
        self.assertIsNone(args.host_selection)
        result = run_agent_command(args, self.client)
        self.assertEqual("discover_and_describe", result["mode"])
        self.assertNotIn("routing_mode", result)
        self.assertEqual("analysis.query.spec:event", result["candidates"][0]["selector"])


if __name__ == "__main__":
    unittest.main()
