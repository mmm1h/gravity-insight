from __future__ import annotations

import unittest
from copy import deepcopy

from gravity_insight.analysis_period_compare import compare_analysis_periods
from gravity_insight.analysis_spec_cli import run_analysis_query_command
from gravity_insight.cli import build_parser
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_analysis_adapter import (
    execute_analysis_query_plan,
    validate_analysis_query_plan,
)
from gravity_insight.sdk import GravitySDK
from gravity_insight.workspace import load_workspace
from gravity_insight.agents.analysis import analysis_query_spec_cards
from gravity_insight.agents.handoff import attach_plan_node


def spec():
    return {
        "app": "101", "start": "2026-08-08", "end": "2026-08-08",
        "steps": [{"event": "purchase", "metric": {
            "field": "PresetAllCount", "aggregation": "PresetAllCount"}}],
    }


def envelope(values, status="success"):
    return {"schema_version": "gravity-insight.read.v1", "ok": True,
            "status": status, "operation_id": "analysis.event.query",
            "data": {"list": [[{"event_index": 0, "target": values}]],
                     "target_list": ["purchase"], "default_limit": 50,
                     "date_list": []}}


class Client:
    def __init__(self, results): self.results, self.calls = results, []
    def validate(self, operation_id, inputs): return {"ok": True, "status": "valid"}
    def schema(self, operation_id): return {"stability": "stable"}
    def batch(self, requests, **options):
        self.calls.append((deepcopy(requests), options))
        return [{"operation_id": "analysis.event.query", "request_id": name,
                 "ok": result.get("ok", True), "status": result["status"], "data": result}
                for name, result in zip(("baseline", "current"), self.results)]


class AnalysisPeriodCompareTests(unittest.TestCase):
    def test_happy_path_calculates_registered_metric_and_marks_zero_base(self):
        client = Client([envelope({"purchase": 10, "zero": 0}),
                         envelope({"purchase": 15, "zero": 3})])
        result = compare_analysis_periods(
            client, "event", spec(), baseline_start="2026-08-01",
            baseline_end="2026-08-01", max_workers=2)
        self.assertEqual(("success", 2), (result["status"], len(result["delta"]["items"])))
        relative = {item["baseline_value"]: item["relative_change"]
                    for item in result["delta"]["items"]}
        self.assertEqual({"status": "calculated", "percent": 50.0}, relative[10])
        self.assertEqual({"status": "not_calculable", "reason": "baseline_zero"},
                         relative[0])
        self.assertEqual((2, 1), (client.calls[0][1]["max_workers"],
                                 client.calls[0][1]["max_pages"]))

    def test_empty_and_failed_windows_never_fabricate_delta(self):
        cases = [
            ([envelope({}, "empty"), envelope({"purchase": 4})],
             "partial", "baseline_empty"),
            ([{"ok": False, "status": "error", "error": {"code": "UPSTREAM"}},
              envelope({"purchase": 4})], "partial", "window_failed"),
        ]
        for windows, status, reason in cases:
            with self.subTest(reason=reason):
                result = compare_analysis_periods(
                    Client(windows), "event", spec(), baseline_start="2026-08-01",
                    baseline_end="2026-08-01")
                self.assertEqual((status, "not_calculated", reason, []),
                                 (result["status"], result["delta"]["status"],
                                  result["delta"]["reason"], result["delta"]["items"]))

    def test_unregistered_result_field_and_undated_kind_fail_closed(self):
        changed = envelope({"purchase": 1})
        changed["data"]["unknown"] = {"purchase": 9}
        result = compare_analysis_periods(
            Client([changed, changed]), "event", spec(),
            baseline_start="2026-08-01", baseline_end="2026-08-01")
        self.assertEqual(("capability_gap", "capability_gap"),
                         (result["status"], result["delta"]["reason"]))
        property_result = compare_analysis_periods(
            Client([]), "property", {}, baseline_start="2026-08-01",
            baseline_end="2026-08-01")
        self.assertEqual(("capability_gap", False),
                         (property_result["status"], property_result["network_called"]))

    def test_sdk_cli_and_plan_use_the_same_compare_envelope(self):
        client = Client([envelope({"purchase": 2}), envelope({"purchase": 4})])
        sdk = GravitySDK(insight=client)
        result = sdk.analysis_query(
            "event", spec(), compare_start="2026-08-01", compare_end="2026-08-01")
        self.assertEqual("gravity-insight.analysis-period-compare.v1",
                         result["schema_version"])
        args = build_parser().parse_args([
            "analysis", "query", "--kind", "event", "--spec", "{}",
            "--compare-start", "2026-08-01", "--compare-end", "2026-08-01"])
        cli = run_analysis_query_command(
            args, lambda **_options: client, lambda _value: spec(),
            lambda *_args: ({}, []), lambda *_args: {})
        self.assertEqual("calculated", cli["delta"]["status"])
        request = {"name": "analysis_query", "kind": "event", "app": "101",
                   "spec": spec(), "compare_start": "2026-08-01",
                   "compare_end": "2026-08-01"}
        context = AdapterContext(
            "compare", "compare", "composite", load_workspace(None), (), (), 1, 200)
        validate_analysis_query_plan(client, context.workspace, request, context)
        planned = execute_analysis_query_plan(sdk, request, context)
        self.assertEqual(("success", "calculated"),
                         (planned["status"], planned["delta"]["status"]))

    def test_agent_card_requires_explicit_compare_dates_and_rejects_property(self):
        ordinary = analysis_query_spec_cards(
            "event analysis", domain="analysis", platform=None)[0]
        self.assertNotIn("compare_start", ordinary["missing_inputs"])
        card = analysis_query_spec_cards(
            "event analysis period compare", domain="analysis", platform=None)[0]
        self.assertEqual(["app", "spec", "compare_start", "compare_end"],
                         card["missing_inputs"])
        filled = {**card, "compare_start": "2026-08-01", "compare_end": "2026-08-07"}
        request = attach_plan_node(filled, "compare periods")["plan_node"]["request"]
        self.assertEqual(("2026-08-01", "2026-08-07"),
                         (request["compare_start"], request["compare_end"]))
        gap = analysis_query_spec_cards(
            "property analysis period compare", domain="analysis", platform=None)[0]
        self.assertEqual((False, "capability_gap"),
                         (gap["plan_executable"], gap["execution_mode"]))

if __name__ == "__main__":
    unittest.main()
