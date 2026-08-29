from __future__ import annotations

import copy
import unittest

from gravity_sdk.analysis_playbook import (
    INPUT_SCHEMA_VERSION,
    compile_metric_anomaly_playbook,
    metric_anomaly_playbook_schema,
    run_metric_anomaly_playbook,
)
from gravity_sdk.errors import InputValidationError
from gravity_sdk.result_source import GOVERNED_PRODUCT, result_source
from gravity_sdk.semantic_compose import compile_semantic_compose
from tests.test_project_skill_overlay import project_semantic_source


APP_ID = 17
CURRENT = {"start": "2026-07-04", "end": "2026-07-10"}
REFERENCE = {"start": "2026-06-27", "end": "2026-07-03"}


def playbook_input(channel="bytedance"):
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "question": "AP cost fell; which returned channel moved with it?",
        "app": APP_ID,
        "current_window": copy.deepcopy(CURRENT),
        "reference_window": copy.deepcopy(REFERENCE),
        "hypothesis": {
            "statement": f"The observed change is concentrated in {channel}.",
            "values": [channel],
        },
    }


class FakePlanExecutor:
    def __init__(self, failure_step=None, failure_status=None):
        self.calls = []
        self.failure_step = failure_step
        self.failure_status = failure_status

    def __call__(self, plan):
        node_ids = [node["id"] for node in plan["nodes"]]
        self.calls.append(node_ids)
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": self.failure_step not in node_ids,
            "status": "partial" if self.failure_step in node_ids else "success",
            "exit_code": 3 if self.failure_step in node_ids else 0,
            "results": [self._item(node) for node in plan["nodes"]],
        }

    def _item(self, node):
        if node["id"] == self.failure_step:
            return {
                "node_id": node["id"],
                "execution_id": node["id"],
                "kind": "composite",
                "ok": False,
                "status": self.failure_status,
                "exit_code": 3,
                "result": None,
                "error": {
                    "code": "CAPABILITY_GAP" if self.failure_status == "capability_gap" else "PAGE_BOUND_REACHED",
                    "category": "upstream",
                    "next_action": "Retry only after the missing evidence is available.",
                },
                "blocked_by": [],
            }
        return success_item(node)


def success_item(node):
    step_id = node["id"]
    semantic_inputs = node["request"]["inputs"]
    compiled = compile_semantic_compose(semantic_inputs, app_id=APP_ID)
    current = semantic_inputs["window"] == CURRENT
    grouped = bool(semantic_inputs["dimensions"])
    filtered = bool(semantic_inputs["filters"])
    rows = rows_for(current, grouped, filtered, semantic_inputs)
    audit = {
        "schema_version": "gravity.result-audit.v1",
        "fact_paths": {"operation_id": "/operation_id"},
        "http_receipts": [
            {"receipt_id": (step_id.encode().hex() + "0" * 32)[:32], "storage_status": "stored"}
        ],
    }
    semantic = {
        "schema_version": "gravity.semantic-compose-result.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "resolution_tier": compiled["resolution_tier"],
        "definition": compiled["definition"],
        "semantic_members": compiled["semantic_members"],
        "generated_query": compiled["generated_query"],
        "validation": {**compiled["validation"], "network_called": True, "result_eligible": True},
        "allowed_claims": compiled["allowed_claims"],
        "operation_id": "report.multidim.query",
        "network_called": True,
        "query_executed": True,
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "error": None,
        "next_action": "Consume only the governed result.",
        "result_audit": audit,
        "result": {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True,
            "status": "success",
            "query": {
                "operation_id": "report.multidim.query",
                "ok": True,
                "status": "success",
                "data": {"list": rows},
                "result_audit": audit,
            },
        },
    }
    return {
        "node_id": step_id,
        "execution_id": step_id,
        "kind": "composite",
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "result": semantic,
        "error": None,
        "blocked_by": [],
    }


def rows_for(current, grouped, filtered, semantic_inputs):
    if not grouped:
        return [{"ap_cost": 70 if current else 100}]
    values = {"bytedance": 50 if current else 80, "tencent": 20}
    if filtered:
        selected = semantic_inputs["filters"][0]["values"][0]
        return [{"click_company": selected, "ap_cost": values[selected]}]
    return [
        {"click_company": channel, "ap_cost": value}
        for channel, value in values.items()
    ]


class AnalysisPlaybookTests(unittest.TestCase):
    def test_schema_and_preflight_compile_to_existing_semantic_plan(self):
        schema = metric_anomaly_playbook_schema()
        compiled = compile_metric_anomaly_playbook(playbook_input())

        self.assertEqual("metric-anomaly-localization", schema["playbook"]["playbook_id"])
        self.assertEqual(4, len(compiled["plan"]["nodes"]))
        self.assertEqual({"composite"}, {node["kind"] for node in compiled["plan"]["nodes"]})
        self.assertEqual(
            {"semantic_compose"},
            {node["request"]["name"] for node in compiled["plan"]["nodes"]},
        )

    def test_validated_project_binding_drives_the_existing_plan_compiler(self):
        base = compile_metric_anomaly_playbook(playbook_input())
        binding = project_semantic_source()["bindings"][0]
        binding["provider"]["definition"]["version"] = 3

        bound = compile_metric_anomaly_playbook(
            playbook_input(), semantic_binding=binding
        )

        definitions = {
            node["request"]["inputs"]["definition"]["version"]
            for node in bound["plan"]["nodes"]
        }
        self.assertEqual({3}, definitions)
        self.assertNotEqual(
            base["playbook"]["fingerprint"], bound["playbook"]["fingerprint"]
        )

    def test_completed_investigation_resumes_only_hypothesis_descendants(self):
        first_executor = FakePlanExecutor()
        first = run_metric_anomaly_playbook(
            object(), playbook_input(), execute_plan=first_executor
        )
        self.assertTrue(first["ok"])
        self.assertEqual(
            "gravity.metric-anomaly-conclusion.v1",
            first["conclusion"]["schema_version"],
        )
        self.assertEqual("selected_slice_moved_with_observed_decrease", first["conclusion"]["verdict"])
        self.assertEqual("-30", first["conclusion"]["returned_sum_absolute_change"])
        self.assertEqual("100", first["conclusion"]["selected_share_of_returned_sum_change_percent"])
        self.assertTrue(first["allowed_claims"])
        self.assertTrue(all(step["result_audit"] for step in first["steps"] if step["kind"] == "query"))

        second_executor = FakePlanExecutor()
        second = run_metric_anomaly_playbook(
            object(), playbook_input("tencent"),
            checkpoint=first,
            execute_plan=second_executor,
        )
        self.assertEqual(
            ["hypothesis", "validate_current", "validate_reference", "conclusion"],
            second["execution"]["invalidated_steps"],
        )
        self.assertEqual(
            ["compare_current", "compare_reference", "breakdown_current", "breakdown_reference"],
            second["execution"]["reused_steps"],
        )
        self.assertEqual([["validate_current", "validate_reference"]], second_executor.calls)
        self.assertEqual("selected_slice_did_not_move_with_observed_decrease", second["conclusion"]["verdict"])
        self.assertEqual("0", second["conclusion"]["selected_absolute_change"])
        breakdown_reference = next(step for step in second["steps"] if step["id"] == "breakdown_reference")
        self.assertEqual("reused", breakdown_reference["execution"])

    def test_partial_and_capability_gap_never_publish_a_conclusion(self):
        for status in ("partial", "capability_gap"):
            with self.subTest(status=status):
                result = run_metric_anomaly_playbook(
                    object(), playbook_input(),
                    execute_plan=FakePlanExecutor("validate_current", status),
                )
                self.assertFalse(result["ok"])
                self.assertEqual("evidence_incomplete", result["status"])
                self.assertIsNone(result["conclusion"])
                self.assertEqual([], result["allowed_claims"])
                self.assertTrue(result["stop"]["triggered"])
                self.assertEqual("validate_current", result["stop"]["missing_steps"][0]["step_id"])
                reference_breakdown = next(step for step in result["steps"] if step["id"] == "breakdown_reference")
                self.assertEqual("success", reference_breakdown["status"])

    def test_invalid_windows_fail_with_actionable_zero_execution_error(self):
        value = playbook_input()
        value["reference_window"] = copy.deepcopy(CURRENT)
        with self.assertRaises(InputValidationError) as raised:
            compile_metric_anomaly_playbook(value)
        self.assertEqual("reference_window.end", raised.exception.field)
        self.assertIn("actual value", str(raised.exception))
        self.assertIn("allowed value", str(raised.exception))
        self.assertTrue(raised.exception.next_action)


if __name__ == "__main__":
    unittest.main()
