from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any, Mapping
from unittest.mock import patch

from gravity_sdk.analysis_query_batch import (
    BATCH_SCHEMA_VERSION,
    execute_analysis_query_batch,
    validate_analysis_query_batch,
)
from gravity_sdk.analysis_query_batch_cli import run_analysis_query_batch_command
from gravity_sdk.errors import InputValidationError
from gravity_sdk.cli import build_parser
from gravity_sdk.onboarding import command_requires_credentials
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


if __name__ == "__main__":
    unittest.main()
