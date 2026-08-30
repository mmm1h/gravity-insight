from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from gravity_insight.plan import AdapterContext
from gravity_insight.plan_analysis_adapter import (
    execute_analysis_query_plan,
    safe_analysis_envelope,
)
from gravity_insight.plan_execution import execute_plan
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.sdk import GravitySDK
from gravity_insight.workspace import load_workspace


def _uv_step(name: str) -> dict[str, object]:
    return {
        "event": name,
        "metric": {"field": "PresetUserCount", "aggregation": "PresetUserCount"},
    }


class FakeInsight:
    def validate(self, _operation_id, _inputs):
        return {"ok": True, "status": "valid"}

    def read(self, operation_id, inputs):
        return {
            "schema_version": "gravity-insight.read.v1",
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "data": {"list": [], "target_list": []},
            "warnings": [],
            "request": {"inputs": dict(inputs)},
        }


class AnalysisEnvelopeTruthTests(unittest.TestCase):
    def test_analysis_result_declares_funnel_rates_and_uv_additivity(self) -> None:
        sdk = GravitySDK(insight=FakeInsight(), workspace="examples/workspace")
        funnel = sdk.analysis_query(
            "funnel",
            {
                "start": "2026-08-01",
                "end": "2026-08-07",
                "steps": [_uv_step("open"), _uv_step("pay")],
                "window": {"unit": "day", "value": 7},
            },
            app="demo",
        )
        notes = funnel["interpretation"]
        self.assertEqual("gravity.analysis-interpretation.v1", notes["schema_version"])
        self.assertIs(False, notes["returns_conversion_rate"])
        self.assertEqual("step_n / step_{n-1}", notes["rate_denominators"]["previous_step"])
        self.assertEqual("step_n / step_1", notes["rate_denominators"]["first_step"])
        self.assertNotIn("conversion_rate", funnel.get("data") or {})
        self.assertEqual(
            {"non_additive"},
            {item["additivity"] for item in notes["metrics"]},
        )

        grouped = sdk.analysis_query(
            "event",
            {
                "start": "2026-08-01",
                "end": "2026-08-07",
                "steps": [_uv_step("open")],
                "group_by": [{"field": "$os", "source": "user"}],
            },
            app="demo",
        )
        self.assertEqual(
            [("PresetUserCount", "non_additive")],
            [
                (item["aggregation"], item["additivity"])
                for item in grouped["interpretation"]["metrics"]
            ],
        )
        self.assertNotIn("returns_conversion_rate", grouped["interpretation"])

    def test_plan_runtime_error_keeps_message_and_next_action(self) -> None:
        secret = "private-filter-value"
        raw = {
            "ok": False,
            "status": "error",
            "operation_id": "analysis.event.query",
            "request": {"inputs": {"filter": secret}},
            "data": {"list": [secret]},
            "error": {
                "category": "upstream",
                "code": "UPSTREAM_UNAVAILABLE",
                "message": "Gravity rejected the read operation.",
                "next_action": "Retry the same Analysis query after Gravity is available.",
                "retryable": True,
            },
        }
        envelope = safe_analysis_envelope(raw)
        self.assertEqual(
            "Gravity rejected the read operation.",
            envelope["error"]["message"],
        )
        self.assertEqual(
            "Retry the same Analysis query after Gravity is available.",
            envelope["error"]["next_action"],
        )
        self.assertNotIn("request", envelope)
        self.assertNotIn(secret, repr(envelope))

        workspace = load_workspace(
            Path(__file__).resolve().parents[1] / "examples" / "workspace"
        )

        class Insight:
            def operations(self, **_options):
                return []

            def validate(self, _operation_id, _inputs):
                return {"ok": True}

            def schema(self, _operation_id):
                return {"response_projection": {"data_keys": ["list"]}}

        class SDK:
            insight = Insight()

            def analysis_query(self, kind, spec, **_options):
                return deepcopy(raw)

        planned = execute_plan(
            {
                "schema_version": "gravity.plan.v1",
                "nodes": [{
                    "id": "q",
                    "kind": "composite",
                    "request": {
                        "name": "analysis_query",
                        "kind": "event",
                        "app": "demo",
                        "spec": {
                            "start": "2026-08-01",
                            "end": "2026-08-02",
                            "steps": [{
                                "event": "open",
                                "metric": {
                                    "field": "PresetAllCount",
                                    "aggregation": "PresetAllCount",
                                },
                            }],
                        },
                    },
                }],
            },
            adapters=build_plan_adapters(SDK(), workspace=workspace),
            workspace=workspace,
        )
        item = planned["results"][0]
        self.assertIsNone(item["result"])
        self.assertEqual(
            "Gravity rejected the read operation.",
            item["error"]["message"],
        )
        self.assertEqual(
            "Retry the same Analysis query after Gravity is available.",
            item["error"]["next_action"],
        )
        self.assertNotIn(secret, repr(planned))
        context = AdapterContext(
            "q", "q", "composite", workspace, (), (), 1, 200
        )
        self.assertNotIn(
            "request",
            execute_analysis_query_plan(
                SDK(),
                {
                    "name": "analysis_query",
                    "kind": "event",
                    "app": "demo",
                    "spec": {
                        "start": "2026-08-01",
                        "end": "2026-08-02",
                        "steps": [{
                            "event": "open",
                            "metric": {
                                "field": "PresetAllCount",
                                "aggregation": "PresetAllCount",
                            },
                        }],
                    },
                },
                context,
            ),
        )


if __name__ == "__main__":
    unittest.main()
