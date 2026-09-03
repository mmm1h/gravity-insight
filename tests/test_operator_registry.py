from __future__ import annotations

import copy
from decimal import Decimal
import unittest
from unittest.mock import patch

import gravity_insight.operator_registry as registry_module
from gravity_insight.operator_contract import (
    OperatorContractError,
    compile_operator_contract,
)
from gravity_insight.operator_ids import (
    GOVERNED_METHOD_URIS,
    RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA,
    RETURNED_DIMENSION_CHANGE_URI,
    SIGNIFICANCE_TEST_URI,
)
from gravity_insight.operator_registry import OperatorRegistry


def operator_input(**overrides):
    value = {
        "current_rows": [
            {"click_company": "bytedance", "ap_cost": 50},
            {"click_company": "tencent", "ap_cost": 20},
        ],
        "reference_rows": [
            {"click_company": "bytedance", "ap_cost": 80},
            {"click_company": "tencent", "ap_cost": 20},
        ],
        "selected_key": "bytedance",
        "selected_current": 50,
        "selected_reference": 80,
        "current_rows_path": "/current",
        "reference_rows_path": "/reference",
        "selected_current_path": "/selected/current",
        "selected_reference_path": "/selected/reference",
        "units": {
            "current": "platform_reported_cost",
            "reference": "platform_reported_cost",
            "output": "platform_reported_cost",
        },
        "additivity": "additive",
    }
    value.update(overrides)
    return value


class OperatorRegistryTests(unittest.TestCase):
    def test_runtime_operator_inventory_is_exact_and_described_formally(self) -> None:
        registry = OperatorRegistry()

        listed = registry.list()
        described = registry.describe(RETURNED_DIMENSION_CHANGE_URI)
        artifact = described["operator"]

        expected = {
            RETURNED_DIMENSION_CHANGE_URI,
            SIGNIFICANCE_TEST_URI,
            *GOVERNED_METHOD_URIS.values(),
        }
        self.assertEqual(11, listed["count"])
        self.assertEqual(expected, {item["uri"] for item in listed["operators"]})
        self.assertEqual("gravity.operator.v1", artifact["contract"]["schema_version"])
        self.assertEqual(
            RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA,
            artifact["contract"]["schemas"]["output"]["schema_version"],
        )
        self.assertRegex(artifact["digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(artifact["assumptions_digest"], r"^[0-9a-f]{64}$")
        self.assertFalse(listed["network_called"])

    def test_governed_methods_execute_their_exact_golden_inputs(self) -> None:
        registry = OperatorRegistry()
        for method, uri in GOVERNED_METHOD_URIS.items():
            with self.subTest(method=method):
                artifact = registry.artifact(uri)
                case = artifact["golden"]["cases"][0]
                first = registry.execute(uri, case["input"])
                second = registry.execute(uri, copy.deepcopy(case["input"]))
                self.assertEqual(first, second)
                self.assertEqual("success", first["status"])
                self.assertEqual(method, first["result"]["method"])
                self.assertTrue(first["result"]["limitations"])
                self.assertTrue(first["result"]["ranked_rows"])
                self.assertEqual(case["expected"], first["result"])

    def test_governed_method_rejects_extra_values_and_parameters(self) -> None:
        registry = OperatorRegistry()
        uri = GOVERNED_METHOD_URIS["campaign-outcome-evaluation"]
        artifact = registry.artifact(uri)
        inputs = copy.deepcopy(artifact["golden"]["cases"][0]["input"])
        inputs["rows"][0]["values"]["undeclared"] = 1
        self.assertEqual(
            ["OPERATOR_INPUT_INVALID"],
            registry.execute(uri, inputs)["reason_codes"],
        )

        inputs = copy.deepcopy(artifact["golden"]["cases"][0]["input"])
        inputs["parameters"]["undeclared"] = 1
        self.assertEqual(
            ["OPERATOR_INPUT_INVALID"],
            registry.execute(uri, inputs)["reason_codes"],
        )

    def test_governed_methods_reject_invalid_method_specific_numbers(self) -> None:
        registry = OperatorRegistry()
        cases = (
            (
                "scenario-projection",
                lambda value: value["parameters"].__setitem__(
                    "horizon_days", 1.5
                ),
            ),
            (
                "ltv-payback-period",
                lambda value: value["rows"][1]["values"].__setitem__(
                    "cumulative_value", 50
                ),
            ),
            (
                "sentiment-aggregation",
                lambda value: value["rows"][0]["values"].__setitem__(
                    "count", 1.5
                ),
            ),
        )
        for method, mutate in cases:
            with self.subTest(method=method):
                uri = GOVERNED_METHOD_URIS[method]
                artifact = registry.artifact(uri)
                inputs = copy.deepcopy(artifact["golden"]["cases"][0]["input"])
                mutate(inputs)
                result = registry.execute(uri, inputs)
                self.assertFalse(result["ok"])
                self.assertEqual(
                    ["OPERATOR_INPUT_INVALID"], result["reason_codes"]
                )

    def test_golden_result_is_deterministic_and_observational(self) -> None:
        registry = OperatorRegistry()
        first = registry.execute(RETURNED_DIMENSION_CHANGE_URI, operator_input())
        second = registry.execute(
            RETURNED_DIMENSION_CHANGE_URI, copy.deepcopy(operator_input())
        )

        self.assertEqual(first, second)
        self.assertEqual("success", first["status"])
        result = first["result"]
        self.assertEqual(RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA, result["schema_version"])
        self.assertEqual("-30", result["returned_sum_absolute_change"])
        self.assertEqual("100", result["selected_share_of_returned_sum_change_percent"])
        self.assertIn("not a causal attribution", result["statement"])
        self.assertNotIn("complete", result["statement"].casefold())
        self.assertEqual(
            ["bytedance", "tencent"],
            [item["key"] for item in result["returned_dimension_changes"]],
        )
        self.assertTrue(first["operator"]["limitations"])

    def test_zero_baselines_and_zero_change_are_explicit(self) -> None:
        registry = OperatorRegistry()
        zero_reference = registry.execute(
            RETURNED_DIMENSION_CHANGE_URI,
            operator_input(
                current_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                reference_rows=[{"click_company": "bytedance", "ap_cost": 0}],
                selected_current=5,
                selected_reference=0,
            ),
        )["result"]
        no_change = registry.execute(
            RETURNED_DIMENSION_CHANGE_URI,
            operator_input(
                current_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                reference_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                selected_current=5,
                selected_reference=5,
            ),
        )["result"]

        self.assertIsNone(zero_reference["relative_change_percent"])
        self.assertIsNone(no_change["selected_share_of_returned_sum_change_percent"])

    def test_single_slice_change_property_and_rounding_are_stable(self) -> None:
        registry = OperatorRegistry()
        for current in range(11):
            with self.subTest(current=current):
                result = registry.execute(
                    RETURNED_DIMENSION_CHANGE_URI,
                    operator_input(
                        current_rows=[{"click_company": "bytedance", "ap_cost": current}],
                        reference_rows=[{"click_company": "bytedance", "ap_cost": 5}],
                        selected_current=current,
                        selected_reference=5,
                    ),
                )["result"]
                self.assertEqual(
                    Decimal(current - 5), Decimal(result["returned_sum_absolute_change"])
                )
                expected = (
                    "selected_slice_moved_with_observed_decrease"
                    if current < 5
                    else "no_observed_returned_sum_decrease"
                )
                self.assertEqual(expected, result["verdict"])

        rounded = registry.execute(
            RETURNED_DIMENSION_CHANGE_URI,
            operator_input(
                current_rows=[{"click_company": "bytedance", "ap_cost": 4}],
                reference_rows=[{"click_company": "bytedance", "ap_cost": 3}],
                selected_current=4,
                selected_reference=3,
            ),
        )["result"]
        self.assertEqual("33.33", rounded["relative_change_percent"])

    def test_invalid_facts_units_additivity_and_resources_have_stable_reasons(self) -> None:
        cases = (
            (None, "OPERATOR_INPUT_INVALID"),
            ({"current_rows": []}, "OPERATOR_SAMPLE_INSUFFICIENT"),
            (
                {
                    "current_rows": [
                        {"click_company": "same", "ap_cost": 1},
                        {"click_company": "same", "ap_cost": 2},
                    ]
                },
                "OPERATOR_DIMENSION_INVALID",
            ),
            (
                {"current_rows": [{"click_company": "bytedance", "ap_cost": float("nan")}]},
                "OPERATOR_INPUT_INVALID",
            ),
            ({"selected_current": 49}, "OPERATOR_CROSSCHECK_FAILED"),
            ({"selected_key": "missing"}, "OPERATOR_CROSSCHECK_FAILED"),
            (
                {
                    "units": {
                        "current": "USD",
                        "reference": "CNY",
                        "output": "USD",
                    }
                },
                "OPERATOR_UNIT_MISMATCH",
            ),
            ({"additivity": "non_additive"}, "OPERATOR_ADDITIVITY_UNSUPPORTED"),
            (
                {"current_rows": [{"click_company": "x" * 257, "ap_cost": 1}]},
                "OPERATOR_RESOURCE_LIMIT",
            ),
            (
                {"current_rows": [{"click_company": "bytedance", "ap_cost": 10**40}]},
                "OPERATOR_RESOURCE_LIMIT",
            ),
            (
                {"current_rows": [{"click_company": "bytedance", "ap_cost": "1e1000"}]},
                "OPERATOR_RESOURCE_LIMIT",
            ),
            (
                {"current_rows": [{"click_company": "bytedance", "ap_cost": "1e-1000"}]},
                "OPERATOR_RESOURCE_LIMIT",
            ),
        )
        registry = OperatorRegistry()
        for override, reason in cases:
            with self.subTest(reason=reason):
                inputs = (
                    override
                    if override is None
                    else operator_input(**override)
                )
                result = registry.execute(
                    RETURNED_DIMENSION_CHANGE_URI, inputs
                )
                self.assertFalse(result["ok"])
                self.assertEqual([reason], result["reason_codes"])
                self.assertIsNone(result["result"])

    def test_fact_paths_reference_only_supplied_rows(self) -> None:
        result = OperatorRegistry().execute(
            RETURNED_DIMENSION_CHANGE_URI, operator_input()
        )["result"]
        self.assertEqual(
            [
                "/reference/0/ap_cost",
                "/reference/1/ap_cost",
                "/current/0/ap_cost",
                "/current/1/ap_cost",
                "/selected/reference",
                "/selected/current",
            ],
            [item["path"] for item in result["fact_references"]],
        )

    def test_contract_digest_is_order_independent_and_tamper_fails(self) -> None:
        registry = OperatorRegistry()
        contract = registry.artifact(RETURNED_DIMENSION_CHANGE_URI)["contract"]
        reordered = {key: copy.deepcopy(contract[key]) for key in reversed(contract)}
        self.assertEqual(
            compile_operator_contract(contract)["digest"],
            compile_operator_contract(reordered)["digest"],
        )
        self.assertEqual("valid", registry.validate(contract)["status"])

        invalid = copy.deepcopy(contract)
        invalid["claim_policy"]["forbidden"].append(
            invalid["claim_policy"]["allowed"][0]
        )
        self.assertEqual(
            ["OPERATOR_CLAIM_CONFLICT"], registry.validate(invalid)["reason_codes"]
        )

        unknown = copy.deepcopy(contract)
        unknown["uri"] = "operator://project/not-installed@1"
        unknown["method"]["method_id"] = "not-installed"
        self.assertEqual(
            ["OPERATOR_GOLDEN_INVALID"],
            registry.validate(unknown)["reason_codes"],
        )

    def test_unknown_revoked_and_output_drift_fail_closed(self) -> None:
        registry = OperatorRegistry()
        missing = registry.resolve("operator://gravity/missing@1")
        self.assertEqual(["OPERATOR_UNAVAILABLE"], missing["reason_codes"])

        registry._artifacts[RETURNED_DIMENSION_CHANGE_URI]["contract"]["lifecycle"] = "revoked"
        revoked = registry.execute(RETURNED_DIMENSION_CHANGE_URI, operator_input())
        self.assertEqual(["OPERATOR_REVOKED"], revoked["reason_codes"])

        registry = OperatorRegistry()
        with patch.dict(
            registry_module._RUNNERS,
            {RETURNED_DIMENSION_CHANGE_URI: lambda _inputs: {"schema_version": "bad"}},
        ):
            drift = registry.execute(RETURNED_DIMENSION_CHANGE_URI, operator_input())
        self.assertEqual(["OPERATOR_OUTPUT_INVALID"], drift["reason_codes"])

    def test_registry_startup_rejects_golden_drift(self) -> None:
        with patch.dict(
            registry_module._RUNNERS,
            {RETURNED_DIMENSION_CHANGE_URI: lambda _inputs: {"schema_version": "bad"}},
        ), self.assertRaisesRegex(OperatorContractError, "OPERATOR_GOLDEN_MISMATCH"):
            OperatorRegistry()

    def test_registry_never_constructs_network(self) -> None:
        with patch("socket.socket", side_effect=AssertionError("network attempted")):
            registry = OperatorRegistry()
            result = registry.execute(RETURNED_DIMENSION_CHANGE_URI, operator_input())
        self.assertTrue(result["ok"])
        self.assertFalse(result["network_called"])


if __name__ == "__main__":
    unittest.main()
