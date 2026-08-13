from __future__ import annotations

import unittest
import threading
import time
from copy import deepcopy
from typing import Any, Mapping
from unittest.mock import patch

from gravity_sdk.analysis_query_batch import (
    BATCH_SCHEMA_VERSION,
    MULTI_APP_BATCH_SCHEMA_VERSION,
    analysis_query_batch_schema,
    execute_analysis_query_batch,
    validate_analysis_query_batch,
)
from gravity_sdk.analysis_query_batch_cli import run_analysis_query_batch_command
from gravity_sdk.analysis_query_multi_app import analysis_query_multi_app_schema
from gravity_sdk.analysis_spec_cli import run_analysis_query_command
from gravity_sdk.errors import InputValidationError
from gravity_sdk.cli import build_parser
from gravity_sdk.onboarding import command_requires_credentials
from gravity_sdk.errors import PermissionUnavailableError
from gravity_sdk.sdk import GravitySDK
from gravity_sdk.workspace import load_workspace


def _query(query_id: str, kind: str = "event", *, secret: str = "open") -> dict[str, Any]:
    metric = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    dated = {"start": "2026-08-01", "end": "2026-08-02"}
    specs: dict[str, dict[str, Any]] = {
        "event": {**dated, "steps": [{"event": secret, "metric": metric}]},
        "funnel": {
            **dated,
            "steps": [
                {"event": secret, "metric": metric},
                {"event": "pay", "metric": metric},
            ],
            "window": {"unit": "day", "value": 1},
        },
        "retention": {
            **dated,
            "steps": [
                {"event": secret, "metric": metric},
                {"event": "return", "metric": metric},
            ],
            "offset": 7,
            "period_calc_method": "SUM",
            "custom_before_method": "SUM",
            "total_calc_type": "DAY",
            "week_first_day": 1,
        },
        "property": {
            "property": {
                "field": "PresetUserCount",
                "aggregation": "PresetUserCount",
                "data_type": "INT",
            }
        },
        "scatter": {**dated, "steps": [{"event": secret, "metric": metric}]},
    }
    return {"id": query_id, "kind": kind, "app": "demo", "spec": specs[kind]}


class FakeSDK:
    def __init__(self) -> None:
        self.workspace = load_workspace("examples/workspace")
        self.calls: list[tuple[str, Mapping[str, Any], int]] = []

    def validate_plan(self, plan: Mapping[str, Any], **options: Any) -> dict[str, Any]:
        self.calls.append(("validate", deepcopy(plan), options["max_workers"]))
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": True,
            "status": "validated",
            "dry_run": True,
            "declared_count": len(plan["nodes"]),
            "max_workers": options["max_workers"],
            "exit_code": 0,
            "results": [],
            "request": plan,
        }

    def execute_plan(self, plan: Mapping[str, Any], **options: Any) -> dict[str, Any]:
        self.calls.append(("execute", deepcopy(plan), options["max_workers"]))
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": True,
            "status": "success",
            "dry_run": False,
            "declared_count": len(plan["nodes"]),
            "success_count": len(plan["nodes"]),
            "failure_count": 0,
            "exit_code": 0,
            "max_workers": options["max_workers"],
            "results": [
                {"node_id": node["id"], "ok": True, "result": {"data": {}}}
                for node in plan["nodes"]
            ],
            "compiled_input": plan,
        }


class CountingInsight:
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.read_app_ids: list[str] = []
        self.lock = threading.Lock()

    def validate(self, _operation_id: str, _inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "needs_live_metadata"}

    def operations(self, **_options: Any) -> list[dict[str, str]]:
        return [{"operation_id": "analysis.retention.query"}]

    def read(self, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        app_id = str(inputs["app_id"])
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.read_app_ids.append(app_id)
        time.sleep(0.02)
        try:
            if app_id == "202":
                raise PermissionUnavailableError("not available")
            status = "empty" if app_id == "303" else "success"
            return {
                "schema_version": "gravity-insight.read.v1",
                "operation_id": operation_id,
                "ok": True,
                "status": status,
                "data": {"list": [] if status == "empty" else [{"total": int(app_id)}]},
            }
        finally:
            with self.lock:
                self.active -= 1

class AnalysisQueryBatchTests(unittest.TestCase):
    def test_all_five_specs_become_same_layer_plan_nodes_and_dry_run_delegates(self) -> None:
        sdk = FakeSDK()
        kinds = ("event", "funnel", "retention", "property", "scatter")
        payload = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "queries": [_query(kind, kind) for kind in kinds],
        }
        result = validate_analysis_query_batch(sdk, payload, max_workers=5)
        action, plan, workers = sdk.calls[0]
        self.assertEqual(("validate", 5), (action, workers))
        self.assertEqual(list(kinds), [node["id"] for node in plan["nodes"]])
        self.assertTrue(all(node["kind"] == "composite" for node in plan["nodes"]))
        self.assertTrue(all(node["request"]["name"] == "analysis_query" for node in plan["nodes"]))
        self.assertTrue(all("depends_on" not in node for node in plan["nodes"]))
        self.assertEqual((True, 5, []), (result["dry_run"], result["query_count"], result["results"]))
        self.assertNotIn("request", result)
        arguments = [
            "analysis", "query", "batch", "--input", "queries.json",
            "--concurrency", "5", "--dry-run",
        ]
        parsed = build_parser().parse_args(arguments)
        self.assertEqual("batch", parsed.analysis_query_command)
        self.assertFalse(command_requires_credentials(arguments, build_parser))
        parsed.input = payload
        with patch(
            "gravity_sdk.analysis_query_batch_cli.run_analysis_query_batch",
            return_value={"ok": True},
        ) as run:
            run_analysis_query_batch_command(
                parsed, sdk=sdk, object_input=lambda value: value
            )
        self.assertIs(sdk.workspace, run.call_args.kwargs["workspace"])
        scalar = build_parser().parse_args([
            "analysis", "query", "--kind", "event", "--spec-schema",
            "batch", "--input", "{}",
        ])
        with self.assertRaises(InputValidationError):
            run_analysis_query_batch_command(
                scalar, sdk=sdk, object_input=lambda value: value
            )
        self.assertEqual(1, len(sdk.calls))

    def test_invalid_or_duplicate_item_stops_before_any_sdk_plan_call(self) -> None:
        sdk = FakeSDK()
        invalid = _query("bad")
        invalid["spec"]["unknown"] = "private-value"
        payloads = [
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query("ok"), invalid]},
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query("same"), _query("same")]},
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query(f"q{i}") for i in range(33)]},
        ]
        for payload in payloads:
            with self.subTest(count=len(payload["queries"])), self.assertRaises(InputValidationError):
                execute_analysis_query_batch(sdk, payload)
            self.assertEqual([], sdk.calls)

    def test_execution_delegates_once_preserves_order_and_never_echoes_input(self) -> None:
        private = "person@example.com"
        sdk = FakeSDK()
        payload = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "queries": [_query("slow", secret=private), _query("fast", "scatter")],
        }
        result = execute_analysis_query_batch(sdk, payload, max_workers=2)
        self.assertEqual(["slow", "fast"], [item["node_id"] for item in result["results"]])
        self.assertEqual(["execute"], [call[0] for call in sdk.calls])
        self.assertEqual(2, result["max_workers"])
        self.assertNotIn(private, repr(result))
        self.assertNotIn("compiled_input", result)

    def test_explicit_apps_share_plan_budget_and_preserve_per_app_failures(self) -> None:
        query = _query("retention", "retention")
        query.pop("app")
        query["apps"] = [101, 202, 303]
        payload = {
            "schema_version": MULTI_APP_BATCH_SCHEMA_VERSION,
            "queries": [query],
        }

        observations = []
        for workers in (1, 3):
            insight = CountingInsight()
            result = execute_analysis_query_batch(
                GravitySDK(insight=insight, workspace="examples/workspace"),
                payload,
                max_workers=workers,
            )
            observations.append((insight, result))

        serial, concurrent = observations
        self.assertEqual((1, 3), (serial[0].peak, concurrent[0].peak))
        self.assertEqual(
            (["101", "202", "303"], ["101", "202", "303"]),
            (sorted(serial[0].read_app_ids), sorted(concurrent[0].read_app_ids)),
        )
        result = concurrent[1]
        self.assertEqual(("partial", 3, 2, 1, 1, 3), (
            result["status"], result["component_count"], result["success_count"],
            result["empty_count"], result["failure_count"], result["exit_code"],
        ))
        self.assertFalse(result["cross_app_aggregation"])
        self.assertEqual([101, 202, 303], [item["app"] for item in result["results"]])
        failed = result["results"][1]
        self.assertEqual(("retention", False, "error", "PERMISSION_UNAVAILABLE"), (
            failed["query_id"], failed["ok"], failed["status"], failed["error"]["code"],
        ))
        self.assertIsNone(failed["result"])
        self.assertEqual("empty", result["results"][2]["status"])

        rejected = deepcopy(payload)
        for apps, kind in (
            (["*"], "retention"),
            ([101, 101], "retention"),
            (["demo", 1001], "retention"),
            (list(range(1, 34)), "retention"),
            ([101], "scatter"),
        ):
            rejected["queries"][0]["apps"] = apps
            rejected["queries"][0]["kind"] = kind
            with self.subTest(apps=apps, kind=kind), self.assertRaises(InputValidationError):
                execute_analysis_query_batch(FakeSDK(), rejected)

        schema = analysis_query_multi_app_schema()
        self.assertEqual(
            (["id", "kind", "apps", "spec"], False, 32),
            (
                schema["input"]["required"],
                schema["output"]["all_apps_selector"],
                schema["execution"]["max_expanded_components"],
            ),
        )

    def test_scalar_cli_apps_only_changes_the_app_parameter(self) -> None:
        parsed = build_parser().parse_args([
            "analysis", "query", "--kind", "retention", "--spec", "spec.json",
            "--apps", "main,overseas", "--concurrency", "3",
        ])
        with patch(
            "gravity_sdk.sdk.GravitySDK.analysis_queries",
            return_value={"schema_version": "gravity.analysis-query-batch-result.v2"},
        ) as run:
            result = run_analysis_query_command(
                parsed,
                lambda **_options: type("Client", (), {
                    "schema": lambda _self, _operation: {"stability": "stable"}
                })(),
                lambda _value: _query("retention", "retention")["spec"],
                lambda *_args: ({}, []),
                lambda *_args: {},
            )
        payload = run.call_args.args[0]
        self.assertEqual("gravity.analysis-query-batch-result.v2", result["schema_version"])
        self.assertEqual(("gravity.analysis-query-batch.v2", ["main", "overseas"], 3), (
            payload["schema_version"], payload["queries"][0]["apps"],
            run.call_args.kwargs["max_workers"],
        ))


if __name__ == "__main__":
    unittest.main()
