from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gravity_insight.agent import discover_capabilities
from gravity_insight.cli import build_parser, run
from gravity_insight.derived_metrics import SPEC_SCHEMA_VERSION, derive_metrics
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.plan import execute_plan
from gravity_insight.sdk import GravitySDK
from gravity_insight.workspace import load_workspace


def source(rows, status="success"):
    return {
        "schema_version": "fictional.result.v1",
        "result_source": {
            "schema_version": "gravity.result-source.v1",
            "tier": "governed_product",
            "semantic_verification": "product_contract",
        },
        "ok": status != "partial",
        "status": status,
        "data": {"list": rows},
    }


def spec(*calculations, places=4):
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "rows_path": "/data/list",
        "decimal_places": places,
        "calculations": list(calculations),
    }


def ratio():
    return {
        "operator": "ratio",
        "result_name": "orion_ratio",
        "numerator": "orion_a",
        "denominator": "orion_b",
    }


class Insight:
    def operations(self, **_options):
        return []


class DerivedMetricsTests(unittest.TestCase):
    def test_zero_denominator_is_not_a_zero_result(self):
        result = derive_metrics(source([{"orion_a": 0, "orion_b": 0}]), spec(ratio()))
        cell = result["derived_metrics"]["calculations"][0]["rows"][0]["result"]
        self.assertEqual(
            ("not_calculable", "denominator_zero", False),
            (cell["status"], cell["reason"], "value" in cell),
        )

    def test_missing_column_is_distinct_from_zero(self):
        result = derive_metrics(source([{"orion_a": 0}]), spec(ratio()))
        cell = result["derived_metrics"]["calculations"][0]["rows"][0]["result"]
        self.assertEqual(
            ("missing_column", ["orion_b"]),
            (cell["reason"], cell["missing_columns"]),
        )

    def test_partial_is_amplified_for_ratio_share_and_reconciliation(self):
        calculations = (
            ratio(),
            {"operator": "share", "result_name": "orion_share", "value": "orion_a"},
            {
                "operator": "reconcile",
                "result_name": "orion_check",
                "observed": "orion_key",
                "expected": ["nova", "quasar"],
            },
        )
        result = derive_metrics(
            source([{"orion_a": 2, "orion_b": 4, "orion_key": "nova"}], "partial"),
            spec(*calculations),
        )["derived_metrics"]
        ratio_cell = result["calculations"][0]["rows"][0]["result"]
        share_cell = result["calculations"][1]["rows"][0]["result"]
        reconciliation = result["calculations"][2]
        self.assertEqual(("partial", "calculated_from_partial"), (result["status"], ratio_cell["status"]))
        self.assertEqual("upstream_partial_total", share_cell["reason"])
        self.assertEqual((False, ["quasar"]), (reconciliation["missing_is_definitive"], reconciliation["missing"]))

    def test_decimal_precision_and_large_integer_difference_are_exactly_declared(self):
        calculations = (
            ratio(),
            {
                "operator": "change",
                "result_name": "orion_change",
                "value": "orion_amount",
                "period": "orion_period",
                "baseline": "old",
                "current": "new",
                "keys": ["orion_key"],
            },
        )
        rows = [
            {"orion_a": 1, "orion_b": 8, "orion_amount": 9007199254740993, "orion_period": "old", "orion_key": "nova"},
            {"orion_a": 1, "orion_b": 8, "orion_amount": 9007199254740994, "orion_period": "new", "orion_key": "nova"},
        ]
        result = derive_metrics(source(rows), spec(*calculations, places=2))["derived_metrics"]
        self.assertEqual("0.12", result["calculations"][0]["rows"][0]["result"]["value"])
        self.assertEqual("1", result["calculations"][1]["rows"][0]["absolute_change"]["value"])
        self.assertIn("PRECISION_ROUNDED", {item["code"] for item in result["warnings"]})

    def test_change_alignment_and_reconciliation_are_identity_based(self):
        calculations = (
            {
                "operator": "change", "result_name": "orion_change", "value": "orion_value",
                "period": "orion_period", "baseline": "old", "current": "new", "keys": ["orion_key"],
            },
            {
                "operator": "reconcile", "result_name": "orion_check", "observed": "orion_key",
                "expected": ["nova", "pulsar"],
            },
        )
        rows = [
            {"orion_key": "nova", "orion_period": "new", "orion_value": 15},
            {"orion_key": "nova", "orion_period": "old", "orion_value": 10},
            {"orion_key": "quasar", "orion_period": "new", "orion_value": 7},
        ]
        result = derive_metrics(source(rows), spec(*calculations))["derived_metrics"]
        change, reconciliation = result["calculations"]
        nova = next(item for item in change["rows"] if item["keys"]["orion_key"] == "nova")
        self.assertEqual(("5", "0.5000"), (nova["absolute_change"]["value"], nova["relative_change"]["value"]))
        self.assertEqual((["nova"], ["pulsar"], ["quasar"]),
                         (reconciliation["present"], reconciliation["missing"], reconciliation["unexpected"]))

    def test_reconciliation_of_a_complete_empty_source_reports_all_missing(self):
        calculation = {
            "operator": "reconcile", "result_name": "orion_check",
            "observed": "orion_key", "expected": ["nova", "quasar"],
        }
        result = derive_metrics(source([], "empty"), spec(calculation))["derived_metrics"]
        reconciliation = result["calculations"][0]
        self.assertEqual(
            ("empty", ["nova", "quasar"], True),
            (result["status"], reconciliation["missing"],
             reconciliation["missing_is_definitive"]),
        )

    def test_sdk_cli_plan_and_end_to_end_source_propagation(self):
        raw = source([{"orion_a": 1, "orion_b": 4}], "partial")
        definition = spec(ratio())
        sdk = GravitySDK(insight=Insight())
        sdk_result = sdk.derive_metrics(raw, definition)
        args = build_parser().parse_args(["derive", "--input", json.dumps({"source": raw, "spec": definition})])
        cli_result = run(args)
        plan = {"schema_version": "gravity.plan.v1", "nodes": [{
            "id": "derive", "kind": "composite",
            "request": {"name": "derived_metrics", "source": raw, "spec": definition},
        }]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = load_workspace(None, start=root, environ={}, cache_root=root / "cache")
            plan_result = execute_plan(
                plan, adapters=build_plan_adapters(sdk, workspace=workspace), workspace=workspace
            )
        ratio_result = sdk_result["derived_metrics"]["calculations"][0]["rows"][0]["result"]
        self.assertEqual("0.2500", ratio_result["value"])
        self.assertEqual(
            ("partial", "calculated_from_partial"),
            (
                sdk_result["derived_metrics"]["status"],
                ratio_result["status"],
            ),
        )
        self.assertEqual(sdk_result, cli_result)
        self.assertEqual("caller_defined", plan_result["results"][0]["result_source"]["tier"])
        self.assertEqual(raw["result_source"], sdk_result["result_source"])
        self.assertEqual("caller_defined", sdk_result["derived_metrics"]["result_source"]["tier"])

    def test_agent_requires_binding_then_executes_a_workspace_declaration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = load_workspace(None, start=root, environ={}, cache_root=root / "cache")
            gap = discover_capabilities("orion rate", client=None, workspace=plain)
            self.assertEqual("DERIVED_METRIC_BINDING_REQUIRED", gap["capability_gaps"][0]["code"])
            (root / "gravity.toml").write_text(
                '''schema_version = 1
[apps]
demo = 1001
[defaults]
app = "demo"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"
[datasources]
[products]
[semantic_context]
schema_version = "gravity.semantic-context.v1"
[[semantic_context.derived_metrics]]
name = "orion-efficiency"
phrases = ["orion efficiency"]
description = "Fictional caller formula."
spec = { schema_version = "gravity.derived-metrics-spec.v1", rows_path = "/data/list", decimal_places = 3, calculations = [{ operator = "ratio", result_name = "orion_ratio", numerator = "orion_a", denominator = "orion_b" }] }
''', encoding="utf-8")
            workspace = load_workspace(root / "gravity.toml", environ={}, cache_root=root / "cache")
            card = discover_capabilities("orion efficiency", client=None, workspace=workspace)["candidates"][0]
            self.assertEqual((["source"], "caller_workspace"), (card["missing_inputs"], card["description_origin"]))
            request = dict(card["plan_node"]["request"])
            request["source"] = source([{"orion_a": 3, "orion_b": 4}])
            node = {**card["plan_node"], "request": request}
            sdk = GravitySDK(insight=Insight(), workspace=workspace)
            receipt = execute_plan(
                {"schema_version": "gravity.plan.v1", "nodes": [node]},
                adapters=build_plan_adapters(sdk, workspace=workspace),
                workspace=workspace,
            )
            executed = receipt["results"][0]["result"]
            self.assertEqual("0.750", executed["derived_metrics"]["calculations"][0]["rows"][0]["result"]["value"])


if __name__ == "__main__":
    unittest.main()
