from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from gravity_sdk import InputValidationError
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_semantic_compose_adapter import validate_semantic_compose_plan
from gravity_sdk.semantic_compose import (
    SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
    compiled_semantic_bytes,
    compile_semantic_compose,
    run_semantic_compose,
    semantic_compose_input_schema,
)
from gravity_sdk.semantic_compose_catalog import definition_by_id


APP_ID = 17
WINDOW = {"start": "2026-06-01", "end": "2026-07-10"}
DEFINITION = {"definition_id": "report.ap-cost-observation", "version": 1}
DEFINITION_V2 = {"definition_id": "report.ap-cost-observation", "version": 2}
METRIC = {"definition_id": "report.metric.ap-cost", "version": 1}
ACTIVATE_METRIC = {
    "definition_id": "report.metric.adclick-standard-activate-count",
    "version": 1,
}
CLICK_DIMENSION = {
    "definition_id": "report.dimension.click-company",
    "version": 1,
}
CLICK_JOIN = {
    "definition_id": "report.join.adreport-click-company",
    "version": 1,
}
CLICK_FILTER = {
    "member": {"definition_id": "report.filter.click-company", "version": 1},
    "operator": "IN",
    "values": ["bytedance"],
}


def request(
    grain="total", *, definition=DEFINITION, metric=METRIC,
    dimensions=(), filters=(), joins=(),
):
    return {
        "definition": copy.deepcopy(definition),
        "window": copy.deepcopy(WINDOW),
        "metric": copy.deepcopy(metric),
        "dimensions": [copy.deepcopy(item) for item in dimensions],
        "filters": [copy.deepcopy(item) for item in filters],
        "grain": {"definition_id": f"report.grain.{grain}", "version": 1},
        "joins": [copy.deepcopy(item) for item in joins],
    }


def native_result(app_id=APP_ID, rows=None):
    return {
        "schema_version": "gravity-insight.composite.multidim.v1",
        "ok": True,
        "status": "success",
        "exit_code": 0,
        "app_id": str(app_id),
        "network_called": True,
        "query_executed": True,
        "input_schema_version": "gravity-insight.multidim-input.v1",
        "validation": {
            "status": "validated_exclusions_only",
            "metrics": "validated_live",
            "data_dims": "exclusion_checked",
            "metrics_checked": 1,
            "data_dims_checked": 1,
            "metadata_operations": ["report.multidim.metric.list"],
        },
        "query": {
            "operation_id": "report.multidim.query",
            "ok": True,
            "status": "success",
            "data": {"list": rows or [{"click_company": "bytedance", "ap_cost": 12.5}]},
            "result_audit": {
                "schema_version": "gravity.result-audit.v1",
                "fact_paths": {"operation_id": "/operation_id"},
                "http_receipts": [{"receipt_id": "a" * 32, "storage_status": "stored"}],
            },
        },
        "total": None,
    }


class _NoNetwork:
    def __init__(self):
        self.calls = 0

    def __getattribute__(self, name):
        if name in {"read", "read_all", "batch", "request"}:
            object.__setattr__(self, "calls", object.__getattribute__(self, "calls") + 1)
            raise AssertionError("semantic preflight reached the client")
        return object.__getattribute__(self, name)


class _Workspace:
    def resolve_app(self, value):
        if value in {"main", APP_ID, str(APP_ID)}:
            return APP_ID
        raise ValueError("unknown App")


class SemanticComposeTests(unittest.TestCase):
    def _assert_zero_network_failure(self, value, field):
        client = _NoNetwork()
        with self.assertRaises(InputValidationError) as raised:
            run_semantic_compose(client, value, app_id=APP_ID)
        self.assertEqual(0, client.calls)
        self.assertEqual(field, raised.exception.field)
        self.assertIn("Allowed:", raised.exception.next_action)

    def test_unknown_member_fails_before_zero_upstream_requests(self):
        value = request()
        value["metric"] = {"definition_id": "report.metric.unknown", "version": 1}
        self._assert_zero_network_failure(value, "metric")

    def test_registered_but_forbidden_join_fails_before_zero_upstream_requests(self):
        self._assert_zero_network_failure(
            request(joins=[CLICK_JOIN]),
            "joins",
        )

    def test_metric_grain_conflict_fails_before_zero_upstream_requests(self):
        self._assert_zero_network_failure(request("hour"), "grain")

    def test_v2_filter_requires_its_grouped_dimension_before_network(self):
        self._assert_zero_network_failure(
            request(definition=DEFINITION_V2, filters=[CLICK_FILTER]),
            "filters",
        )

    def test_three_analyst_combinations_compile_deterministically(self):
        combinations = (
            request("total", dimensions=[CLICK_DIMENSION], joins=[CLICK_JOIN]),
            request("week"),
            request("day"),
        )
        compiled = [compile_semantic_compose(item, app_id=APP_ID) for item in combinations]
        for item, result in zip(combinations, compiled, strict=True):
            self.assertEqual(
                compiled_semantic_bytes(item, app_id=APP_ID),
                compiled_semantic_bytes(copy.deepcopy(item), app_id=APP_ID),
            )
            self.assertFalse(result["validation"]["network_called"])
            self.assertEqual("tier_b_governed_semantic", result["resolution_tier"])
            self.assertTrue(result["allowed_claims"])
        self.assertEqual(
            ["total", "week", "day"],
            [item["generated_query"]["inputs"]["time_dims"] for item in compiled],
        )

    def test_same_definition_id_versions_remain_distinct_in_results(self):
        original = definition_by_id(*("report.ap-cost-observation", 1))

        def versioned(_definition_id, version):
            value = copy.deepcopy(original)
            value["version"] = version
            value["description"] = f"version {version}"
            return value

        versions = []
        with (
            patch("gravity_sdk.semantic_compose.definition_by_id", side_effect=versioned),
            patch("gravity_sdk.semantic_compose.run_multidim_query", return_value=native_result()),
        ):
            for version in (1, 2):
                value = request()
                value["definition"]["version"] = version
                versions.append(run_semantic_compose(object(), value, app_id=APP_ID))
        self.assertEqual(
            [("report.ap-cost-observation", 1), ("report.ap-cost-observation", 2)],
            [
                (item["definition"]["definition_id"], item["definition"]["version"])
                for item in versions
            ],
        )
        self.assertNotEqual(
            versions[0]["definition"]["fingerprint"],
            versions[1]["definition"]["fingerprint"],
        )

    def test_real_v1_v2_definitions_coexist_and_v2_compiles_live_wire(self):
        schema = semantic_compose_input_schema()
        self.assertEqual(
            [DEFINITION, DEFINITION_V2], schema["x-registered-definitions"]
        )
        v1 = compile_semantic_compose(request(), app_id=APP_ID)
        filtered = request(
            definition=DEFINITION_V2,
            dimensions=[CLICK_DIMENSION],
            filters=[CLICK_FILTER],
            joins=[CLICK_JOIN],
        )
        v2 = compile_semantic_compose(filtered, app_id=APP_ID)
        self.assertEqual([1, 2], [v1["definition"]["version"], v2["definition"]["version"]])
        self.assertNotEqual(v1["definition"]["fingerprint"], v2["definition"]["fingerprint"])
        self.assertNotIn("data_conf", v1["generated_query"]["inputs"])
        self.assertFalse(v2["generated_query"]["inputs"]["data_conf"]["return_all_metrics"])
        self.assertEqual(
            {"field": "click_company", "operator": "IN", "values": ["bytedance"]},
            v2["generated_query"]["inputs"]["filters"][0],
        )
        self._assert_zero_network_failure(
            request("total", definition=DEFINITION_V2, metric=ACTIVATE_METRIC),
            "grain",
        )

    def test_result_carries_members_query_validation_and_allowed_claims(self):
        value = request("total", dimensions=[CLICK_DIMENSION], joins=[CLICK_JOIN])
        with patch(
            "gravity_sdk.semantic_compose.run_multidim_query",
            return_value=native_result(),
        ):
            result = run_semantic_compose(object(), value, app_id=APP_ID)
        self.assertEqual("gravity.semantic-compose-result.v1", result["schema_version"])
        self.assertEqual("governed_product", result["result_source"]["tier"])
        self.assertEqual("report.metric.ap-cost", result["semantic_members"]["metric"]["definition_id"])
        self.assertEqual("multidim", result["generated_query"]["name"])
        self.assertEqual("report.multidim.query", result["operation_id"])
        self.assertTrue(result["validation"]["result_eligible"])
        self.assertEqual(2, len(result["allowed_claims"]))
        self.assertEqual(12.5, result["result"]["query"]["data"]["list"][0]["ap_cost"])
        self.assertEqual("a" * 32, result["result_audit"]["http_receipts"][0]["receipt_id"])

    def test_schema_agent_and_plan_preflight_share_one_contract(self):
        schema = semantic_compose_input_schema()
        card = discover_capabilities("governed semantic composition", client=None)["candidates"][0]
        self.assertEqual(SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION, schema["schema_version"])
        self.assertEqual(1, schema["properties"]["filters"]["maxItems"])
        self.assertEqual(schema, card["input_schema"]["inputs"]["machine_schema"])
        plan_request = {
            "name": "semantic_compose",
            "input_schema_version": SEMANTIC_COMPOSE_INPUT_SCHEMA_VERSION,
            "app": "main",
            "inputs": request("total", dimensions=[CLICK_DIMENSION], joins=[CLICK_JOIN]),
        }
        context = AdapterContext(
            node_id="semantic",
            execution_id="semantic",
            kind="composite",
            workspace=_Workspace(),
            output_fields=(),
            dynamic_targets=(),
            max_pages=1,
            max_items=100,
        )
        validate_semantic_compose_plan(_Workspace(), plan_request, context)


if __name__ == "__main__":
    unittest.main()
