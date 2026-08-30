from __future__ import annotations

import json
import unittest
from typing import Any, Mapping

from gravity_insight.analysis_primitives import (
    AnalysisCohort,
    AnalysisFilter,
    AnalysisMetric,
    AnalysisSpec,
    AnalysisStep,
)
from gravity_insight.analysis_query_batch import (
    BATCH_SCHEMA_VERSION,
    validate_analysis_query_batch,
)
from gravity_insight.analysis_spec import compile_query_spec
from gravity_insight.errors import InputValidationError
from gravity_insight.workspace import load_workspace


QUERY_ID = "1700000000000AAAAAAAAAAAAAAAAAAA"


class _NoPlanSDK:
    def __init__(self) -> None:
        self.workspace = load_workspace("examples/workspace")
        self.plan_called = False

    def validate_plan(self, _plan: Mapping[str, Any], **_options: Any) -> dict[str, Any]:
        self.plan_called = True
        return {"schema_version": "gravity.plan-result.v1", "results": []}


class AnalysisPrimitiveTests(unittest.TestCase):
    def test_all_five_typed_specs_compile_to_byte_identical_requests(self) -> None:
        metric = AnalysisMetric(
            "PresetAllCount", "PresetAllCount", data_type="INT"
        )
        cohort = AnalysisCohort("segment-42").as_filter()
        open_step = AnalysisStep("open", metric, filters=(cohort,))
        pay_step = AnalysisStep("pay", metric)
        condition = cohort.to_spec()
        dated = {
            "app": "101", "query_id": QUERY_ID,
            "start": "2026-08-01", "end": "2026-08-02",
        }
        cases = {
            "event": (
                {**dated, "steps": [{"event": "open", "metric": metric.for_step(), "conditions": [condition]}]},
                AnalysisSpec.event("2026-08-01", "2026-08-02", [open_step], app="101", query_id=QUERY_ID),
            ),
            "funnel": (
                {**dated, "steps": [open_step.to_spec(), pay_step.to_spec()], "window": {"unit": "day", "value": 1}},
                AnalysisSpec.funnel("2026-08-01", "2026-08-02", [open_step, pay_step], window_unit="day", window_value=1, app="101", query_id=QUERY_ID),
            ),
            "retention": (
                {**dated, "steps": [open_step.to_spec(), pay_step.to_spec()], "offset": 7, "period_calc_method": "SUM", "custom_before_method": "SUM", "total_calc_type": "DAY", "week_first_day": 1},
                AnalysisSpec.retention("2026-08-01", "2026-08-02", [open_step, pay_step], offset=7, period_calc_method="SUM", custom_before_method="SUM", total_calc_type="DAY", week_first_day=1, app="101", query_id=QUERY_ID),
            ),
            "property": (
                {"app": "101", "query_id": QUERY_ID, "property": metric.for_property(), "conditions": [condition]},
                AnalysisSpec.property(metric, filters=[cohort], app="101", query_id=QUERY_ID),
            ),
            "scatter": (
                {**dated, "steps": [open_step.to_spec()]},
                AnalysisSpec.scatter("2026-08-01", "2026-08-02", open_step, app="101", query_id=QUERY_ID),
            ),
        }
        for kind, (literal, typed) in cases.items():
            with self.subTest(kind=kind):
                old = compile_query_spec(kind, literal)
                new = compile_query_spec(kind, typed)
                self.assertEqual(old.operation_id, new.operation_id)
                encode = lambda value: json.dumps(value, separators=(",", ":")).encode()
                self.assertEqual(encode(old.inputs), encode(new.inputs))

    def test_incremental_edits_are_immutable_and_reject_wrong_positions(self) -> None:
        first = AnalysisMetric("PresetAllCount", "PresetAllCount")
        replacement = AnalysisMetric("revenue", "SumCount")
        condition = AnalysisFilter("country", "EQUALS", "user", ("CN",))
        base = AnalysisSpec.event(
            "2026-08-01", "2026-08-02", [AnalysisStep("open", first)]
        )
        changed = (
            base.with_app("101")
            .with_dates("2026-08-03", "2026-08-04")
            .replace_step_metric(replacement)
            .add_step_filter(condition)
        )
        self.assertNotIn("app", base)
        self.assertEqual("revenue", changed["steps"][0]["metric"]["field"])
        self.assertEqual(["CN"], changed["steps"][0]["conditions"][0]["value"])
        with self.assertRaises(InputValidationError):
            AnalysisSpec.scatter(
                "2026-08-01", "2026-08-02", AnalysisStep("open", first)
            ).add_global_filter(condition)
        with self.assertRaises(InputValidationError):
            AnalysisSpec.property(first)

    def test_kind_specific_illegal_filter_fails_before_plan_preflight(self) -> None:
        sdk = _NoPlanSDK()
        metric = AnalysisMetric("PresetAllCount", "PresetAllCount")
        spec = AnalysisSpec.funnel(
            "2026-08-01",
            "2026-08-02",
            [AnalysisStep("open", metric), AnalysisStep("pay", metric)],
            window_unit="day",
            window_value=1,
        ).add_global_filter(
            AnalysisFilter("country", "EQUALS", "user_property", ("CN",))
        )
        with self.assertRaisesRegex(InputValidationError, "must use type 'user'"):
            validate_analysis_query_batch(sdk, {
                "schema_version": BATCH_SCHEMA_VERSION,
                "queries": [{"id": "funnel", "kind": "funnel", "app": "demo", "spec": spec}],
            })
        self.assertFalse(sdk.plan_called)


if __name__ == "__main__":
    unittest.main()
