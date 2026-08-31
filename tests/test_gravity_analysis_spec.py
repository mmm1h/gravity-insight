from __future__ import annotations

import unittest
from typing import Any, Mapping
from unittest.mock import patch

from gravity_insight._field_policy_shared import ANALYSIS_TIME_GROUPS
from gravity_insight.analysis_spec import analysis_query_spec_schema, compile_query_spec
from gravity_insight.errors import InputValidationError
from gravity_insight.sdk import GravitySDK


def metric() -> dict[str, str]:
    return {"field": "PresetAllCount", "aggregation": "PresetAllCount"}


def step(name: str) -> dict[str, Any]:
    return {"event": name, "metric": metric()}


class FakeInsight:
    def __init__(self) -> None:
        self.validated: list[tuple[str, Mapping[str, Any]]] = []
        self.reads: list[tuple[str, Mapping[str, Any]]] = []

    def validate(self, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        self.validated.append((operation_id, inputs))
        return {
            "ok": True,
            "status": "needs_live_metadata",
            "live_metadata_dependencies": ["analysis.event.list"],
        }

    def read(self, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        self.reads.append((operation_id, inputs))
        return {"ok": True, "status": "success", "data": {"list": []}}


class AnalysisQuerySpecTests(unittest.TestCase):
    def test_machine_schema_uses_standard_types_and_matches_controlled_variants(self) -> None:
        schema = analysis_query_spec_schema()
        allowed_types = {"array", "boolean", "integer", "null", "number", "object", "string"}

        def inspect(value: Any) -> None:
            if isinstance(value, Mapping):
                declared = value.get("type")
                if isinstance(declared, str):
                    self.assertIn(declared, allowed_types)
                elif isinstance(declared, list):
                    self.assertTrue(set(declared) <= allowed_types)
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(schema)
        zones = schema["definitions"]["scatter_zone"]["oneOf"]
        self.assertEqual(["type"], zones[0]["required"])
        self.assertEqual("dispersed", zones[1]["properties"]["type"]["const"])
        self.assertEqual(["type", "ranges"], zones[2]["required"])
        event_schema = schema["kind_schemas"]["event"]
        self.assertEqual(
            "#/definitions/aggregate",
            event_schema["properties"]["aggregate"]["$ref"],
        )
        self.assertIn(
            "custom",
            schema["definitions"]["group_by"]["properties"]["bucket"]["enum"],
        )
        self.assertTrue(
            schema["kind_schemas"]["event"]["properties"]["query_id"]["pattern"]
        )
        grains_by_kind = {
            kind: set(schema["kind_schemas"][kind]["properties"]["time_grain"]["enum"])
            for kind in ("event", "funnel", "retention", "scatter")
        }
        self.assertEqual(
            ANALYSIS_TIME_GROUPS - {"hour", "minute"},
            grains_by_kind["event"],
        )
        self.assertIn("total", grains_by_kind["event"])
        for kind in ("funnel", "retention", "scatter"):
            self.assertEqual(ANALYSIS_TIME_GROUPS, grains_by_kind[kind])
        funnel_notes = schema["kind_schemas"]["funnel"]["notes"]
        self.assertFalse(funnel_notes["returns_conversion_rate"])
        self.assertIn("step_n / step_1", funnel_notes["rate_denominators"]["first_step"])
        self.assertIn("step_n / step_{n-1}", funnel_notes["rate_denominators"]["previous_step"])
        self.assertEqual(4, funnel_notes["window_funnel_mode"])
        with self.assertRaises(InputValidationError):
            compile_query_spec(
                "scatter",
                {
                    "app": "101", "start": "2026-08-01", "end": "2026-08-02",
                    "steps": [step("purchase")],
                    "zone": {"type": "default", "ranges": [1, 2]},
                },
            )

    def test_compiles_all_five_stable_query_shapes(self) -> None:
        dated = {"app": "101", "start": "2026-08-01", "end": "2026-08-02"}
        cases = {
            "event": {**dated, "steps": [step("open")], "time_grain": "day"},
            "funnel": {
                **dated,
                "steps": [step("open"), step("purchase")],
                "window": {"unit": "day", "value": 1},
            },
            "retention": {
                **dated,
                "steps": [step("open"), step("return")],
                "offset": 7,
                "period_calc_method": "SUM",
                "custom_before_method": "SUM",
                "total_calc_type": "DAY",
                "week_first_day": 1,
            },
            "property": {
                "app": "101",
                "property": {
                    "field": "PresetUserCount",
                    "aggregation": "PresetUserCount",
                    "data_type": "INT",
                },
            },
            "scatter": {**dated, "steps": [step("purchase")]},
        }
        for kind, spec in cases.items():
            with self.subTest(kind=kind):
                compiled = compile_query_spec(kind, spec)
                self.assertEqual(f"analysis.{kind}.query", compiled.operation_id)
                self.assertEqual("101", compiled.inputs["app_id"])
                self.assertTrue(compiled.inputs["query_id"])
        self.assertEqual(2, len(compile_query_spec("funnel", cases["funnel"]).inputs["query_item_list"]))
        self.assertEqual("default", compile_query_spec("scatter", cases["scatter"]).inputs["query_item_list"][0]["calc_zone"]["zone_type"])

    def test_production_proven_compact_controls_compile_to_exact_wire(self) -> None:
        dated = {"app": "101", "start": "2026-08-01", "end": "2026-08-01"}
        event = compile_query_spec("event", {
            **dated, "steps": [step("open")], "return_hierarchy_list": True,
        }).inputs
        funnel = compile_query_spec("funnel", {
            **dated, "steps": [step("open"), step("pay")],
            "window": {"unit": "today", "value": 1},
        }).inputs
        before_after = {
            "after": {"event_name": "pay", "target": {
                "name": "PresetAllCount", "field": "PresetAllCount"}},
            "formula": "+", "decimal_point": "two_point",
            "before_decimal_point": "integer", "a_to_b": True, "name": "return",
        }
        retention = compile_query_spec("retention", {
            **dated, "steps": [step("open"), step("pay")], "offset": 7,
            "period_calc_method": "SUM", "custom_before_method": "SUM",
            "total_calc_type": "DAY", "week_first_day": 1,
            "query_item_before_after": before_after,
        }).inputs
        scatter = compile_query_spec("scatter", {
            **dated, "steps": [step("pay")], "zone": {"type": "dispersed"},
        }).inputs
        self.assertIs(True, event["return_hierarchy_list"])
        self.assertEqual({"type": "today", "val": 1}, funnel["stat_time_window"])
        self.assertEqual(before_after, retention["query_item_before_after"])
        self.assertEqual("day", retention["group_by_list"][0]["group_by"])
        self.assertEqual(
            "user",
            compile_query_spec(
                "retention",
                {**dated, "steps": [step("open"), step("pay")], "offset": 7,
                 "period_calc_method": "SUM", "custom_before_method": "SUM",
                 "total_calc_type": "DAY", "week_first_day": 1,
                 "group_by": [{"field": "$os", "source": "user"}]},
            ).inputs["group_by_list"][1]["type"],
        )
        self.assertEqual({"zone_type": "dispersed", "range_list": []},
                         scatter["query_item_list"][0]["calc_zone"])
        self.assertNotIn("return_hierarchy_list", compile_query_spec(
            "event", {**dated, "steps": [step("open")] }).inputs)
        for rejected in ("split_event", "custom_query_item_list"):
            with self.subTest(rejected=rejected), self.assertRaises(InputValidationError):
                compile_query_spec("event", {
                    **dated, "steps": [step("open")], rejected: []})

    def test_invalid_semantics_stop_before_client_validation(self) -> None:
        sdk = GravitySDK(insight=FakeInsight())
        with self.assertRaisesRegex(InputValidationError, "offset"):
            sdk.compile_analysis_query(
                "retention",
                {
                    "app": "101",
                    "start": "2026-08-01",
                    "end": "2026-08-02",
                    "steps": [step("open"), step("return")],
                },
            )
        self.assertEqual([], sdk.insight.validated)

    def test_event_subday_grains_fail_before_dispatch_and_daily_control_still_succeeds(self) -> None:
        insight = FakeInsight()
        sdk = GravitySDK(insight=insight)
        spec = {
            "app": "101",
            "start": "2026-08-01",
            "end": "2026-08-01",
            "return_hierarchy_list": True,
            "steps": [
                {
                    "event": "$MPLaunch",
                    "metric": {
                        "field": "PresetUserCount",
                        "aggregation": "PresetUserCount",
                    },
                }
            ],
        }

        for grain in ("hour", "minute"):
            with self.subTest(grain=grain), self.assertRaises(InputValidationError) as caught:
                sdk.analysis_query("event", {**spec, "time_grain": grain})

            detail = caught.exception.to_error_detail(
                operation_id="analysis.event.query"
            ).to_dict()
            self.assertEqual(
                ("INPUT_INVALID", "caller", "time_grain", False),
                (
                    detail["code"],
                    detail["category"],
                    detail["field"],
                    detail["retryable"],
                ),
            )
            self.assertIn("allowed values", detail["message"])
            allowed = detail["message"].partition("allowed values:")[2]
            self.assertNotIn('"hour"', allowed)
            self.assertNotIn('"minute"', allowed)
            self.assertIn("Change only `time_grain` to `day`", detail["next_action"])
            self.assertIn("No SDK path has verified", detail["next_action"])
            self.assertIn("do not retry", detail["next_action"])
            self.assertIn(f"create_time/{grain}", detail["next_action"])
            self.assertNotIn("concurrency", detail["next_action"])
            self.assertNotIn("$MPLaunch", repr(detail))
            self.assertNotIn("101", repr(detail))
            self.assertEqual(([], []), (insight.validated, insight.reads))

        daily = {**spec, "time_grain": "day"}
        result = sdk.analysis_query("event", daily)
        self.assertEqual((True, "success"), (result["ok"], result["status"]))
        self.assertEqual(1, len(insight.validated))
        self.assertEqual(1, len(insight.reads))
        operation_id, inputs = insight.reads[0]
        self.assertEqual("analysis.event.query", operation_id)
        self.assertEqual(
            [{"type": "default_event", "field": "create_time", "group_by": "day"}],
            inputs["group_by_list"],
        )
        total = compile_query_spec("event", {**spec, "time_grain": "total"})
        self.assertEqual("total", total.inputs["group_by_list"][0]["group_by"])

    def test_property_acquisition_id_group_fails_before_client_validation(self) -> None:
        sdk = GravitySDK(insight=FakeInsight())
        with self.assertRaises(InputValidationError) as caught:
            sdk.compile_analysis_query("property", {
                "app": "101",
                "property": {"field": "PresetUserCount", "aggregation": "PresetUserCount", "data_type": "INT"},
                "group_by": [{"field": "$ea_gid", "source": "user"}],
            })
        self.assertEqual("group_by[0].field", caught.exception.field)
        self.assertIn("actual value", str(caught.exception))
        self.assertIn("$ea_gid", str(caught.exception))
        self.assertIn("gravity metadata properties", str(caught.exception.next_action))
        self.assertEqual([], sdk.insight.validated)

    def test_public_compile_uses_field_policy_and_redacts_preview_values(self) -> None:
        dated = {
            "app": "101",
            "start": "2026-08-01",
            "end": "2026-08-02",
            "steps": [step("open"), step("purchase")],
        }
        with self.assertRaises(InputValidationError):
            compile_query_spec(
                "funnel", {**dated, "window": {"unit": "day", "value": 365}}
            )
        with self.assertRaisesRegex(InputValidationError, "provide both overrides"):
            compile_query_spec("event", {**dated, "steps": [step("open")]}, start="2026-08-03")
        private = "person@example.com"
        insight = FakeInsight()
        preview = GravitySDK(insight=insight).compile_analysis_query(
            "event",
            {
                **dated,
                "steps": [{
                    **step("open"),
                    "conditions": [{
                        "operator": "EQUALS",
                        "field": "account",
                        # type=user_property is rejected offline for event (#22);
                        # this case is about redaction, so use the supported type.
                        "type": "user",
                        "value": [private],
                    }],
                }],
            },
        )
        self.assertTrue(preview["input_values_redacted"])
        self.assertNotIn(private, repr(preview))
        self.assertIsNone(preview["plan_node"])

    def test_sdk_compile_and_execute_share_the_same_compiler(self) -> None:
        insight = FakeInsight()
        sdk = GravitySDK(insight=insight, workspace="examples/workspace")
        spec = {
            "start": "2026-08-01",
            "end": "2026-08-02",
            "steps": [step("open"), step("purchase")],
            "window": {"unit": "day", "value": 1},
        }
        prepared = sdk.compile_analysis_query("funnel", spec, app="demo")
        result = sdk.analysis_query("funnel", spec, app="demo")
        self.assertFalse(prepared["network_called"])
        self.assertEqual("1001", prepared["compiled_input"]["app_id"])
        self.assertEqual("success", result["status"])
        self.assertEqual("analysis.funnel.query", insight.reads[0][0])
        with patch(
            "gravity_insight.analysis_query_batch.run_analysis_query_batch",
            return_value={"status": "validated"},
        ) as run_batch:
            batch = sdk.analysis_queries(
                {"schema_version": "gravity.analysis-query-batch.v1", "queries": []},
                max_workers=4,
                dry_run=True,
            )
        self.assertEqual("validated", batch["status"])
        self.assertEqual((4, True), (
            run_batch.call_args.kwargs["max_workers"],
            run_batch.call_args.kwargs["dry_run"],
        ))


if __name__ == "__main__":
    unittest.main()
