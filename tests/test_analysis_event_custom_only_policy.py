from __future__ import annotations

import unittest
from typing import Any

from gravity_insight._field_policy_analysis import validate_analysis_shape
from gravity_insight.errors import InputValidationError


QUERY_ID = "1700000000000AAAAAAAAAAAAAAAAAAA"


def _event_item(name: str, index: int = 0) -> dict[str, Any]:
    return {
        "event_name": name,
        "custom_name": name,
        "target": {"name": "PresetAllCount", "field": "PresetAllCount"},
        "conditions": [],
        "cond_logic": "AND",
        "event_index": index,
    }


def _inputs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "query_id": QUERY_ID,
        "app_id": "101",
        "query_item_list": [_event_item("open")],
        "group_by_list": [],
        "date_list": [
            {
                "start_date": "2026-08-01T00:00:00",
                "end_date": "2026-08-02T00:00:00",
            }
        ],
    }
    values.update(overrides)
    return values


def _custom_item(*, formula: str = "x1/x2") -> dict[str, Any]:
    return {
        "custom_name": "average duration",
        "formula": formula,
        "query_item_list": [
            _event_item("duration", 0),
            _event_item("users", 1),
        ],
        "decimal_point": "two_point",
        "event_index": 0,
    }


class AnalysisEventCustomOnlyPolicyTests(unittest.TestCase):
    def test_custom_only_event_with_valid_formula_is_accepted(self) -> None:
        references = validate_analysis_shape(
            "event",
            _inputs(
                query_item_list=[],
                custom_query_item_list=[_custom_item()],
            ),
        )

        self.assertEqual({"duration", "users"}, references.events)

    def test_event_with_no_ordinary_or_custom_items_is_rejected(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_shape(
                "event",
                _inputs(query_item_list=[], custom_query_item_list=[]),
            )

        self.assertEqual("custom_query_item_list", caught.exception.field)

    def test_custom_only_event_with_invalid_formula_is_rejected(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_shape(
                "event",
                _inputs(
                    query_item_list=[],
                    custom_query_item_list=[_custom_item(formula="x1^x2")],
                ),
            )

        self.assertEqual("custom_query_item_list[].formula", caught.exception.field)

    def test_funnel_with_one_item_still_requires_two(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_shape(
                "funnel",
                _inputs(query_item_list=[_event_item("open")]),
            )

        self.assertEqual("query_item_list", caught.exception.field)
        self.assertIn("allowed step count: 2 through 50", str(caught.exception))

    def test_retention_with_one_item_still_requires_two(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_shape(
                "retention",
                _inputs(query_item_list=[_event_item("open")]),
            )

        self.assertEqual("query_item_list", caught.exception.field)
        self.assertIn("allowed step count: 2 through 2", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
