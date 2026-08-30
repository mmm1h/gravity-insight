"""Retention custom-before raw-operation depth remains bounded and reproducible.

Reported as issue #21 by a work-dashboard consumer. The compact schema lets a
caller put a condition on one ``before_custom.list[]`` component. The raw
operation contract must retain the measured depth for evidence and saved
artifact handling even though the compact Retention compiler now rejects this
upstream-unsupported cohort before dispatch.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from gravity_insight import models
from gravity_insight.models import _is_bounded_json_value, _validate_date_range
from gravity_insight.operation_input_field import (
    _input_type_valid,
    parse_input_field,
    validate_input_field,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "src" / "gravity_insight" / "contracts" / "operations"
    / "analysis.retention.query.json"
)
_TARGET = {"name": "DistinctCount", "field": "$UserID"}
_CONDITION = {
    "field": "os", "operator": "EQUALS", "value": ["android"], "type": "user"
}


def _event(name: str, **extra: object) -> dict[str, object]:
    return {"event_name": name, "target": dict(_TARGET), **extra}


def _before_after(*, condition_on_component: bool) -> dict[str, object]:
    first = (
        _event("$UserFirstRegister", conditions=[dict(_CONDITION)])
        if condition_on_component
        else _event("$UserFirstRegister")
    )
    custom: dict[str, object] = {
        "list": [first, _event("$PayEvent")],
        "formula": "x1*x2",
    }
    if not condition_on_component:
        custom["conditions"] = [dict(_CONDITION)]
    return {"before_custom": custom, "formula": "*", "name": "regpay"}


def _field():
    config = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return parse_input_field(
        models.InputField,
        "query_item_before_after",
        config["operation"]["input_fields"]["query_item_before_after"],
        freeze_json=lambda value: value,
        missing=object(),
    )


def _validate(value: object) -> None:
    validate_input_field(
        _field(),
        value,
        is_bounded_json_value=_is_bounded_json_value,
        matches_input_type=_input_type_valid,
        validate_date_range=_validate_date_range,
        validate_filters=lambda *args, **kwargs: None,
    )


class RetentionCustomBeforeDepthTests(unittest.TestCase):
    def test_a_condition_on_one_custom_before_component_is_accepted(self) -> None:
        """The raw operation contract still admits the registered wire shape."""

        _validate(_before_after(condition_on_component=True))

    def test_a_condition_on_the_custom_before_itself_stays_accepted(self) -> None:
        """The shallower placement already worked; widening must not change it."""

        _validate(_before_after(condition_on_component=False))

    def test_the_declared_depth_is_the_measured_requirement(self) -> None:
        """Pin why the number is what it is, so nobody trims it back by guess."""

        deepest = _before_after(condition_on_component=True)

        self.assertFalse(_is_bounded_json_value(deepest, max_depth=6))
        self.assertTrue(_is_bounded_json_value(deepest, max_depth=7))
        self.assertEqual(7, _field().max_depth)

    def test_depth_is_not_widened_beyond_what_the_shape_needs(self) -> None:
        """A blanket-large limit would stop bounding anything; keep it exact."""

        self.assertLessEqual(_field().max_depth, 7)


class CustomBeforeRejectionRemedyTests(unittest.TestCase):
    """Issue #21: the remedy told the caller to add a group they already sent."""

    _UPSTREAM = {"extra": {"error": "入参错误：group_by_list缺失create_time"}}
    _GROUPS = [{"type": "default_event", "field": "create_time", "group_by": "day"}]

    def _classify(self, inputs: dict[str, object]) -> tuple[str, str, str]:
        from gravity_insight.semantic_rejection import classify_read_rejection

        return classify_read_rejection(
            self._UPSTREAM,
            operation_id="analysis.retention.query",
            request_inputs=inputs,
        )

    def test_remedy_stops_asking_for_a_group_the_caller_already_sent(self) -> None:
        field, _, next_action = self._classify({
            "group_by_list": list(self._GROUPS),
            "query_item_before_after": _before_after(condition_on_component=False),
        })

        self.assertEqual("group_by_list", field)
        self.assertNotIn("add create_time/day", next_action)
        self.assertNotIn("compact time_grain=day", next_action)
        self.assertIn("already contains create_time/day", next_action)
        self.assertIn("issue #21", next_action)

    def test_the_genuinely_missing_group_still_gets_the_original_remedy(self) -> None:
        _, _, next_action = self._classify({
            "group_by_list": [],
            "query_item_before_after": _before_after(condition_on_component=False),
        })

        self.assertIn("add create_time/day", next_action)

    def test_plain_retention_that_already_grouped_is_not_told_to_regroup(self) -> None:
        """Issue #23 widened this: the contradiction is not custom-before specific.

        This case previously asserted the original "add create_time/day" remedy.
        That was wrong for the same reason #21 was -- the caller already sent the
        group -- it just took a second report to see it without a custom before.
        """

        _, _, next_action = self._classify({"group_by_list": list(self._GROUPS)})

        self.assertNotIn("add create_time/day", next_action)
        self.assertIn("issue #23", next_action)


if __name__ == "__main__":
    unittest.main()
