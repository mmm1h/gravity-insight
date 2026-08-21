from __future__ import annotations

import copy
import unittest

from gravity_sdk.reference_journey_operator import (
    ReferenceOperatorError,
    SCHEMA_VERSION,
    returned_dimension_change,
)


def request(**overrides):
    value = {
        "current_rows": [
            {"click_company": "bytedance", "ap_cost": 50},
            {"click_company": "tencent", "ap_cost": 20},
        ],
        "reference_rows": [
            {"click_company": "bytedance", "ap_cost": 80},
            {"click_company": "tencent", "ap_cost": 20},
        ],
        "selected_key": "bytedance",
        "selected_current": 50,
        "selected_reference": 80,
        "current_rows_path": "/current",
        "reference_rows_path": "/reference",
        "selected_current_path": "/selected/current",
        "selected_reference_path": "/selected/reference",
    }
    value.update(overrides)
    return value


class ReferenceJourneyOperatorTests(unittest.TestCase):
    def test_golden_result_is_deterministic_and_observational(self):
        first = returned_dimension_change(**request())
        second = returned_dimension_change(**copy.deepcopy(request()))

        self.assertEqual(first, second)
        self.assertEqual("gravity.operator-result.returned-dimension-change.v1", SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, first["schema_version"])
        self.assertEqual("-30", first["returned_sum_absolute_change"])
        self.assertEqual(
            "100", first["selected_share_of_returned_sum_change_percent"]
        )
        self.assertIn("not a causal attribution", first["statement"])
        self.assertNotIn("complete", first["statement"].casefold())
        self.assertEqual(
            ["bytedance", "tencent"],
            [item["key"] for item in first["returned_dimension_changes"]],
        )

    def test_zero_baselines_and_zero_change_are_explicit(self):
        zero_reference = returned_dimension_change(
            **request(
                current_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                reference_rows=[{"click_company": "bytedance", "ap_cost": 0}],
                selected_current=5,
                selected_reference=0,
            )
        )
        self.assertIsNone(zero_reference["relative_change_percent"])

        no_change = returned_dimension_change(
            **request(
                current_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                reference_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                selected_current=5,
                selected_reference=5,
            )
        )
        self.assertIsNone(no_change["selected_share_of_returned_sum_change_percent"])

    def test_invalid_facts_fail_closed(self):
        cases = (
            {"current_rows": []},
            {
                "current_rows": [
                    {"click_company": "same", "ap_cost": 1},
                    {"click_company": "same", "ap_cost": 2},
                ]
            },
            {
                "current_rows": [
                    {"click_company": "bytedance", "ap_cost": float("nan")}
                ]
            },
            {"selected_current": 49},
            {"selected_key": "missing"},
        )
        for override in cases:
            with self.subTest(override=override), self.assertRaises(
                ReferenceOperatorError
            ):
                returned_dimension_change(**request(**override))

    def test_fact_paths_reference_only_supplied_rows(self):
        result = returned_dimension_change(**request())
        paths = [item["path"] for item in result["fact_references"]]
        self.assertEqual(
            [
                "/reference/0/ap_cost",
                "/reference/1/ap_cost",
                "/current/0/ap_cost",
                "/current/1/ap_cost",
                "/selected/reference",
                "/selected/current",
            ],
            paths,
        )


if __name__ == "__main__":
    unittest.main()
