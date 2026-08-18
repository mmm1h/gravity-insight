from __future__ import annotations

import unittest

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_discovery_support import (
    CATALOG_BROWSE_ARGV,
    HOST_CATALOG_ARGV,
    NO_CANDIDATE_NEXT_ACTION,
    UNRANKED_OPERATIONS,
    UNRANKED_OPERATIONS_NEXT_ACTION,
    discovery_next_fields,
    unranked_operations_gap,
)


class DiscoveryNextFieldsTests(unittest.TestCase):
    def test_named_gap_next_is_copied_onto_the_envelope(self) -> None:
        gap = {
            "code": "ANALYSIS_EXPORT_FILE_CONTRACT_MISSING",
            "next_action": (
                "Run `gravity export list-capabilities` to see the seven callable "
                "Analysis families and their required inputs, then re-run the "
                "discovery naming the family you want."
            ),
            "next": {"argv": ["gravity", "export", "list-capabilities"]},
        }

        fields = discovery_next_fields(False, [gap])

        self.assertEqual(gap["next_action"], fields["next_action"])
        self.assertEqual(gap["next"]["argv"], fields["next"]["argv"])
        self.assertNotEqual(CATALOG_BROWSE_ARGV, fields["next"]["argv"])

    def test_gap_without_specific_next_keeps_the_generic_browse(self) -> None:
        fields = discovery_next_fields(False, [{"kind": "draft_capability_gap"}])

        self.assertEqual(NO_CANDIDATE_NEXT_ACTION, fields["next_action"])
        self.assertEqual(CATALOG_BROWSE_ARGV, fields["next"]["argv"])

        empty = discovery_next_fields(False, [])
        self.assertEqual(NO_CANDIDATE_NEXT_ACTION, empty["next_action"])
        self.assertEqual(CATALOG_BROWSE_ARGV, empty["next"]["argv"])

    def test_unranked_operations_keep_the_host_catalog_handoff(self) -> None:
        gap = unranked_operations_gap(
            "排那位用户当天的时间线和回传",
            (
                "analysis.account_user.list",
                "analysis.event_property_value.list",
                "analysis.monetization_detail.list",
            ),
        )

        fields = discovery_next_fields(False, [gap])

        self.assertEqual(UNRANKED_OPERATIONS, gap["code"])
        self.assertEqual(UNRANKED_OPERATIONS_NEXT_ACTION, fields["next_action"])
        self.assertEqual(HOST_CATALOG_ARGV, fields["next"]["argv"])

    def test_specific_action_without_argv_does_not_invent_browse_next(self) -> None:
        fields = discovery_next_fields(
            False,
            [{
                "code": "MULTIPLE_INTENTS",
                "next_action": (
                    "For each candidate_selectors value, call gravity agent "
                    "--input <selector> independently; execute only after each "
                    "discovery returns one authoritative product card."
                ),
            }],
        )

        self.assertIn("gravity agent --input <selector>", fields["next_action"])
        self.assertNotIn("next", fields)

    def test_candidates_keep_the_recipe_preference(self) -> None:
        fields = discovery_next_fields(
            True,
            [{
                "next_action": "this gap must not replace the candidate next_action",
                "next": {"argv": ["gravity", "export", "list-capabilities"]},
            }],
        )

        self.assertIn("Prefer a recipe", fields["next_action"])
        self.assertNotIn("next", fields)


class DiscoveryEnvelopeNextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()

    def test_export_discovery_envelope_uses_the_named_gap_argv(self) -> None:
        result = discover_capabilities("导出分析结果", client=self.client)
        gap = result["capability_gaps"][0]

        self.assertEqual("ANALYSIS_EXPORT_FILE_CONTRACT_MISSING", gap["code"])
        self.assertEqual(gap["next"]["argv"], result["next"]["argv"])
        self.assertEqual(
            ["gravity", "export", "list-capabilities"], result["next"]["argv"]
        )
        self.assertEqual(gap["next_action"], result["next_action"])
        self.assertNotEqual(CATALOG_BROWSE_ARGV, result["next"]["argv"])

    def test_absent_capability_envelope_still_browses_the_catalog(self) -> None:
        result = discover_capabilities(
            "utterly unrelated quantum weather", client=self.client
        )
        gap = result["capability_gaps"][0]

        self.assertEqual("NO_CANDIDATE", gap["code"])
        self.assertEqual(NO_CANDIDATE_NEXT_ACTION, result["next_action"])
        self.assertEqual(CATALOG_BROWSE_ARGV, result["next"]["argv"])

    def test_unranked_discovery_envelope_still_hands_off_to_host(self) -> None:
        result = discover_capabilities(
            "排那位用户当天的时间线和回传", client=self.client
        )
        gap = result["capability_gaps"][0]

        self.assertEqual(UNRANKED_OPERATIONS, gap["code"])
        self.assertEqual(UNRANKED_OPERATIONS_NEXT_ACTION, result["next_action"])
        self.assertEqual(HOST_CATALOG_ARGV, result["next"]["argv"])

    def test_candidate_discovery_envelope_next_action_is_unchanged(self) -> None:
        result = discover_capabilities("event analysis", client=self.client)

        self.assertEqual("success", result["status"])
        self.assertTrue(result["candidates"])
        self.assertIn("Prefer a recipe", result["next_action"])
        self.assertNotIn("next", result)
