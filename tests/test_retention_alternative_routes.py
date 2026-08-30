"""Executable replacements for upstream-rejected Retention cohort shapes."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from gravity_insight.analysis_spec import analysis_query_spec_schema, compile_query_spec
from gravity_insight.errors import InputValidationError
from gravity_insight.segment_mutation import create_segment_from_analysis
from gravity_insight.segment_spec import compile_segment_spec


_METRIC = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
_COHORT_DAY = "2026-08-01"
_RETURN_DAY = "2026-08-02"


def _step(event: str) -> dict[str, Any]:
    return {"event": event, "metric": dict(_METRIC)}


def _segment_condition(segment_id: str = "42") -> dict[str, Any]:
    return {
        "field": segment_id,
        "source": "segment",
        "operator": "TRUE",
        "values": [],
        "segment_type": "LATEST",
    }


def _launch_rule() -> dict[str, Any]:
    return {
        "event": "$MPLaunch",
        "did": True,
        "target": dict(_METRIC),
        "did_condition": {"operator": "GTE", "values": [1]},
        "date_range": {
            "type": "static",
            "start": _RETURN_DAY,
            "end": _RETURN_DAY,
        },
    }


def _segment_spec(
    name: str,
    property_rules: list[dict[str, Any]],
    *,
    include_launch: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "start": _COHORT_DAY,
        "end": _RETURN_DAY,
        "logic": "AND",
        "property_rules": {
            "logic": "AND",
            "groups": [{"logic": "AND", "rules": property_rules}],
        },
    }
    if include_launch:
        result["event_rules"] = {
            "logic": "AND",
            "groups": [{"logic": "AND", "rules": [_launch_rule()]}],
        }
    return result


class _PreviewOnlyClient:
    def __init__(self) -> None:
        self.previews: list[tuple[str, Mapping[str, Any]]] = []

    def _preview_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.previews.append((operation_id, inputs))
        return {
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "network_called": False,
        }

    def read(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("a segment mutation dry-run must not read upstream")


class RetentionAlternativeRouteTests(unittest.TestCase):
    def test_machine_schema_stops_advertising_rejected_retention_inputs(self) -> None:
        schema = analysis_query_spec_schema()
        retention = schema["kind_schemas"]["retention"]
        self.assertEqual(0, retention["properties"]["property_conditions"]["maxItems"])
        before_after = schema["definitions"]["retention_before_after"]
        self.assertNotIn("before_custom", before_after["properties"])

    def test_registration_payment_cohort_compiles_through_funnel_and_segment(self) -> None:
        funnel = {
            "start": _COHORT_DAY,
            "end": _COHORT_DAY,
            "global_filters": [{
                "operator": "EQUALS",
                "field": "$ea_click_company",
                "type": "user",
                "value": ["sanitized-source"],
            }],
            "global_logic": "AND",
            "steps": [_step("$UserFirstRegister"), _step("$PayEvent")],
            "window": {"unit": "today", "value": 1},
        }

        compiled = compile_query_spec("funnel", funnel, app=101)
        self.assertEqual(
            {"start_date": _COHORT_DAY, "end_date": _COHORT_DAY},
            compiled.inputs["date_list"][0],
        )
        self.assertEqual(
            ["$UserFirstRegister", "$PayEvent"],
            [item["event_name"] for item in compiled.inputs["query_item_list"]],
        )
        self.assertEqual("user", compiled.inputs["global_conditions"][0]["type"])
        self.assertEqual({"type": "today", "val": 1}, compiled.inputs["stat_time_window"])

        client = _PreviewOnlyClient()
        preview = create_segment_from_analysis(
            client,
            funnel,
            app=101,
            name="reg-pay-d1",
            step=1,
            is_loss=False,
            execute=False,
        )
        self.assertEqual("preview", preview["status"])
        self.assertFalse(preview["network_called"])
        mutation_inputs = client.previews[0][1]
        self.assertEqual(1, mutation_inputs["segment_conf"]["step"])
        self.assertFalse(mutation_inputs["segment_conf"]["is_loss"])
        self.assertNotIn("segment_conf", preview["source_analysis"]["inputs"])

        denominator = compile_segment_spec(
            _segment_spec("reg-pay-base", [_segment_condition()], include_launch=False),
            app=101,
        )
        numerator = compile_segment_spec(
            _segment_spec("reg-pay-return", [_segment_condition()], include_launch=True),
            app=101,
        )
        base = denominator.inputs["user_property_rules"]["groups"][0]["conditions"][0]
        launch = numerator.inputs["user_event_rules"]["groups"][0]["conditions"][0]
        self.assertEqual(
            {"field": "42", "type": "user_segment", "operator": "TRUE", "value": [], "segment_type": "LATEST"},
            base,
        )
        self.assertEqual("$MPLaunch", launch["event_name"])
        self.assertEqual(
            {"date_type": "static", "date": [_RETURN_DAY, _RETURN_DAY]},
            launch["date_range"],
        )

    def test_first_pay_property_cohort_compiles_as_two_aggregate_segment_rules(self) -> None:
        first_pay = {
            "field": "first_pay_time",
            "source": "user",
            "operator": "RANGE_IN",
            "values": [1785513600000, 1785599999999],
        }
        denominator = compile_segment_spec(
            _segment_spec("first-pay-base", [first_pay], include_launch=False),
            app=101,
        )
        numerator = compile_segment_spec(
            _segment_spec("first-pay-return", [first_pay], include_launch=True),
            app=101,
        )

        condition = denominator.inputs["user_property_rules"]["groups"][0]["conditions"][0]
        self.assertEqual(
            {
                "field": "first_pay_time",
                "type": "user",
                "operator": "RANGE_IN",
                "value": [1785513600000, 1785599999999],
            },
            condition,
        )
        self.assertEqual([], denominator.inputs["user_event_rules"]["groups"])
        self.assertEqual(
            "$MPLaunch",
            numerator.inputs["user_event_rules"]["groups"][0]["conditions"][0]["event_name"],
        )

    def test_rejected_retention_shapes_fail_closed_with_exact_migrations(self) -> None:
        base = {
            "start": _COHORT_DAY,
            "end": _RETURN_DAY,
            "steps": [_step("$PayEvent"), _step("$MPLaunch")],
            "offset": 2,
            "period_calc_method": "SUM",
            "custom_before_method": "SUM",
            "total_calc_type": "DAY",
            "week_first_day": 1,
        }
        custom_before = {
            **base,
            "query_item_before_after": {
                "name": "reg-pay",
                "before_custom": {
                    "list": [
                        {"event_name": "$UserFirstRegister", "target": {"field": "PresetAllCount", "name": "PresetAllCount"}},
                        {"event_name": "$PayEvent", "target": {"field": "PresetAllCount", "name": "PresetAllCount"}},
                    ],
                    "formula": "x1*x2",
                },
            },
        }
        property_condition = {
            **base,
            "property_conditions": [{
                "field": "first_pay_time",
                "operator": "RANGE_IN",
                "type": "user",
                "value": [1785513600000, 1785599999999],
            }],
        }

        with self.assertRaises(InputValidationError) as custom_error:
            compile_query_spec("retention", custom_before, app=101)
        self.assertEqual(
            "query_item_before_after.before_custom", custom_error.exception.field
        )
        self.assertEqual(
            'actual value: {"non_empty":true}; Retention query_item_before_after.before_custom is not supported by the upstream Retention endpoint',
            str(custom_error.exception),
        )
        self.assertIn("--kind funnel", custom_error.exception.next_action)
        self.assertIn("--step 1 --matched", custom_error.exception.next_action)

        with self.assertRaises(InputValidationError) as property_error:
            compile_query_spec("retention", property_condition, app=101)
        self.assertEqual("property_conditions", property_error.exception.field)
        self.assertEqual(
            'actual value: {"count":1}; Retention property_conditions are not supported by the upstream Retention endpoint',
            str(property_error.exception),
        )
        self.assertIn("segment evaluate --spec-schema", property_error.exception.next_action)
        self.assertIn("numerator.part / denominator.part", property_error.exception.next_action)


if __name__ == "__main__":
    unittest.main()
