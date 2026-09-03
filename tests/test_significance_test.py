from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from gravity_insight.operator_ids import SIGNIFICANCE_TEST_URI
from gravity_insight.operator_registry import OperatorRegistry


def significance_input(**overrides):
    value = copy.deepcopy(
        OperatorRegistry().artifact(SIGNIFICANCE_TEST_URI)["golden"]["cases"][0][
            "input"
        ]
    )
    value.update(overrides)
    return value


class SignificanceTestOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = OperatorRegistry()

    def test_valid_non_significant_observation_is_success_not_calculation_failure(self) -> None:
        result = self.registry.execute(SIGNIFICANCE_TEST_URI, significance_input())

        self.assertTrue(result["ok"])
        self.assertEqual("success", result["status"])
        self.assertEqual([], result["reason_codes"])
        self.assertEqual(
            "no_significant_observed_difference", result["result"]["verdict"]
        )
        self.assertFalse(result["result"]["metrics"][0]["significant"])
        self.assertFalse(result["network_called"])

    def test_significant_result_stays_an_observation_with_explicit_method(self) -> None:
        value = significance_input()
        value["metrics"][0]["treatment"]["successes"] = 150
        result = self.registry.execute(SIGNIFICANCE_TEST_URI, value)["result"]

        self.assertEqual("significant_observed_difference", result["verdict"])
        self.assertTrue(result["metrics"][0]["significant"])
        self.assertEqual("two-proportion-z-test", result["test_specification"]["method"])
        self.assertEqual("greater", result["metrics"][0]["alternative"])
        self.assertEqual("pooled-under-null", result["test_specification"]["null_variance"])
        self.assertTrue(result["assumptions"]["observational_only"])

    def test_causal_claim_request_fails_closed(self) -> None:
        result = self.registry.execute(
            SIGNIFICANCE_TEST_URI,
            significance_input(claim="causality-without-controlled-evidence"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(["OPERATOR_CAUSALITY_FORBIDDEN"], result["reason_codes"])
        self.assertEqual("claim", result["error"]["field"])
        self.assertIsNone(result["result"])

    def test_recommendation_self_validation_fails_closed(self) -> None:
        value = significance_input(evaluation_run_id="recommendation-run-1")
        result = self.registry.execute(SIGNIFICANCE_TEST_URI, value)

        self.assertFalse(result["ok"])
        self.assertEqual(
            ["OPERATOR_SELF_VALIDATION_FORBIDDEN"], result["reason_codes"]
        )
        self.assertEqual("evaluation_run_id", result["error"]["field"])
        self.assertIn("distinct", result["error"]["next_action"])

    def test_overlapping_evidence_window_fails_closed(self) -> None:
        value = significance_input()
        overlapping = {
            "start": "2026-08-07",
            "end": "2026-08-20",
            "timezone": "UTC",
        }
        value["observation"]["window"] = overlapping
        value["evidence_window"] = overlapping
        result = self.registry.execute(SIGNIFICANCE_TEST_URI, value)

        self.assertEqual(["OPERATOR_EVIDENCE_WINDOW_OVERLAP"], result["reason_codes"])
        self.assertEqual("evidence_window.start", result["error"]["field"])

    def test_missing_group_has_structured_actionable_error(self) -> None:
        value = significance_input()
        del value["metrics"][0]["control"]
        result = self.registry.execute(SIGNIFICANCE_TEST_URI, value)

        self.assertEqual(["OPERATOR_INPUT_INVALID"], result["reason_codes"])
        self.assertEqual("metrics[0].control", result["error"]["field"])
        self.assertTrue(result["error"]["next_action"])
        self.assertIsNone(result["result"])

    def test_insufficient_sample_and_degenerate_variance_fail_closed(self) -> None:
        insufficient = significance_input()
        insufficient["metrics"][0]["control"]["successes"] = 4
        degenerate = significance_input()
        degenerate["metrics"][0]["control"]["successes"] = 0
        degenerate["metrics"][0]["treatment"]["successes"] = 0

        insufficient_result = self.registry.execute(
            SIGNIFICANCE_TEST_URI, insufficient
        )
        degenerate_result = self.registry.execute(SIGNIFICANCE_TEST_URI, degenerate)

        self.assertEqual(
            ["OPERATOR_SAMPLE_INSUFFICIENT"], insufficient_result["reason_codes"]
        )
        self.assertEqual(
            ["OPERATOR_VARIANCE_DEGENERATE"], degenerate_result["reason_codes"]
        )
        self.assertEqual("metrics[0]", insufficient_result["error"]["field"])
        self.assertEqual("metrics[0]", degenerate_result["error"]["field"])
        self.assertTrue(insufficient_result["error"]["next_action"])
        self.assertTrue(degenerate_result["error"]["next_action"])

    def test_multi_metric_requires_and_reports_bonferroni_assumptions(self) -> None:
        value = significance_input()
        value["metrics"].append(
            {
                "metric_uri": "metric://project/error-rate@1",
                "role": "guardrail",
                "alternative": "greater",
                "control": {"successes": 50, "trials": 1000},
                "treatment": {"successes": 60, "trials": 1000},
            }
        )
        missing = self.registry.execute(SIGNIFICANCE_TEST_URI, value)
        value["test"]["multiplicity"] = "bonferroni"
        complete = self.registry.execute(SIGNIFICANCE_TEST_URI, value)

        self.assertEqual(
            ["OPERATOR_MULTIPLICITY_REQUIRED"], missing["reason_codes"]
        )
        self.assertTrue(complete["ok"])
        self.assertEqual("bonferroni", complete["result"]["test_specification"]["multiplicity"])
        self.assertEqual("0.025", complete["result"]["test_specification"]["per_comparison_alpha"])

    def test_operator_is_deterministic_and_never_constructs_network(self) -> None:
        value = significance_input()
        with patch("socket.socket", side_effect=AssertionError("network attempted")):
            first = self.registry.execute(SIGNIFICANCE_TEST_URI, value)
            second = self.registry.execute(SIGNIFICANCE_TEST_URI, copy.deepcopy(value))

        self.assertEqual(first, second)
        self.assertTrue(first["ok"])
        self.assertFalse(first["network_called"])


if __name__ == "__main__":
    unittest.main()
