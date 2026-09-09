from __future__ import annotations

import copy
from decimal import Decimal
import unittest
from unittest.mock import patch

from gravity_insight import ModelRegistry, OperatorRegistry
from gravity_insight.operator_ids import GOVERNED_METHOD_URIS, GOVERNED_METHOD_URIS_V2


class GovernedOperatorScopeTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("socket.socket", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.registry = OperatorRegistry()

    def inputs(self, method="campaign-outcome-evaluation", version=2):
        uri = f"operator://gravity/{method}@{version}"
        return copy.deepcopy(self.registry.artifact(uri)["golden"]["cases"][0]["input"])

    def execute(self, inputs, version=2):
        return self.registry.execute(f"operator://gravity/{inputs['method']}@{version}", inputs)

    def reject(self, inputs, reason, version=2):
        result = self.execute(inputs, version)
        self.assertEqual(("invalid", False, None, [reason]),
                         (result["status"], result["ok"], result["result"], result["reason_codes"]))
        self.assertIn(reason, self.registry.artifact(result["uri"])["contract"]["failure_reasons"])
        self.assertTrue(result["error"]["field"])
        self.assertTrue(result["error"]["next_action"])
        self.assertFalse(result["network_called"])
        return result

    def test_appendix_a_counterexamples_fail_through_public_registry(self):
        campaign = self.inputs(version=1)
        campaign.pop("mode")
        campaign.update(unit="UV", additivity="non_additive")
        for row in campaign["rows"]:
            row["values"] = {"current": 100, "reference": 80}
        self.reject(campaign, "OPERATOR_AGGREGATION_UNPROVEN", version=1)

        funnel = self.inputs("funnel-diagnosis", version=1)
        funnel.pop("mode")
        funnel["rows"][0]["values"] = {"order": 1, "entered": 10, "reached": 9}
        funnel["rows"][1]["values"] = {"order": 2, "entered": 100, "reached": 90}
        self.reject(funnel, "OPERATOR_FUNNEL_LINEAGE_UNPROVEN", version=1)

    def test_v1_has_no_implicit_upgrade_and_retains_explicit_rowwise_results(self):
        for method, uri in GOVERNED_METHOD_URIS_V2.items():
            with self.subTest(method=method):
                inputs = self.inputs(method, version=1)
                result = self.execute(inputs, version=1)
                self.assertTrue(result["ok"])
                self.assertEqual("gravity.operator-result.governed-method.v1", result["result"]["schema_version"])
                inputs.pop("mode")
                reason = "OPERATOR_FUNNEL_LINEAGE_UNPROVEN" if method == "funnel-diagnosis" else "OPERATOR_AGGREGATION_UNPROVEN"
                rejected = self.reject(inputs, reason, version=1)
                self.assertIn(uri, rejected["error"]["next_action"])
        self.reject(self.inputs(), "OPERATOR_INPUT_INVALID", version=1)
        self.reject(self.inputs(version=1), "OPERATOR_INPUT_INVALID", version=2)

    def test_additive_currency_totals_keep_each_comparison_window_separate(self):
        inputs = self.inputs()
        inputs["unit"] = "CNY"
        for row in inputs["rows"]:
            for scope in row["scopes"].values():
                scope["unit"] = "CNY"
            row["scopes"]["reference"]["window"].update(start="2026-08-25", end="2026-08-31")
        result = self.execute(inputs)
        self.assertEqual({"current_total": "200", "reference_total": "200", "absolute_change": "0"}, result["result"]["metrics"])
        inputs["rows"].reverse()
        self.assertEqual(result, self.execute(inputs))

    def test_nonadditive_ratios_compare_rowwise_without_normalized_shares(self):
        for version in (1, 2):
            with self.subTest(version=version):
                inputs = self.inputs("metric-decomposition", version)
                inputs.update(mode="rowwise", unit="ratio", additivity="non_additive")
                inputs.pop("aggregation", None)
                for row in inputs["rows"]:
                    row["values"] = {"current": 0.5, "reference": 0.25}
                    for scope in row.get("scopes", {}).values():
                        scope["unit"] = "ratio"
                result = self.execute(inputs, version)
                self.assertEqual({}, result["result"]["metrics"])
                self.assertEqual(["0.25", "0.25"], [r["contribution"] for r in result["result"]["ranked_rows"]])

    def test_all_summing_methods_reject_nonadditivity_but_keep_rowwise(self):
        for method in ("campaign-outcome-evaluation", "metric-decomposition", "scenario-projection", "sentiment-aggregation"):
            with self.subTest(method=method):
                inputs = self.inputs(method)
                inputs["additivity"] = "non_additive"
                self.reject(inputs, "OPERATOR_ADDITIVITY_UNSUPPORTED")
                inputs["mode"] = "rowwise"
                inputs.pop("aggregation")
                result = self.execute(inputs)
                self.assertTrue(result["ok"])
                self.assertFalse(any("total" in key for key in result["result"]["metrics"]))

    def test_semi_additive_axis_and_partition_evidence_are_required(self):
        inputs = self.inputs()
        inputs["additivity"] = "semi_additive"
        self.assertTrue(self.execute(inputs)["ok"])
        inputs["aggregation"]["axis"] = "time"
        self.reject(inputs, "OPERATOR_ADDITIVITY_UNSUPPORTED")
        inputs = self.inputs()
        inputs["aggregation"]["disjointness"]["members"].pop()
        self.reject(inputs, "OPERATOR_AGGREGATION_UNPROVEN")
        inputs.pop("aggregation")
        self.reject(inputs, "OPERATOR_AGGREGATION_UNPROVEN")

    def test_partition_assertion_cannot_omit_evidence_or_duplicate_components(self):
        inputs = self.inputs()
        inputs["aggregation"]["disjointness"].pop("evidence")
        self.reject(inputs, "OPERATOR_INPUT_INVALID")
        inputs = self.inputs()
        members = inputs["aggregation"]["disjointness"]["members"]
        members.append(members[0])
        self.reject(inputs, "OPERATOR_INPUT_INVALID")

    def test_mixed_units_windows_and_populations_fail_before_arithmetic(self):
        for field, value, reason in (
            ("unit", "USD", "OPERATOR_UNIT_MISMATCH"),
            ("population", "different-cohort", "OPERATOR_SCOPE_MISMATCH"),
            ("window", {"start": "2026-08-01", "end": "2026-08-07", "timezone": "UTC", "grain": "day"}, "OPERATOR_SCOPE_MISMATCH"),
        ):
            with self.subTest(field=field):
                inputs = self.inputs()
                inputs["rows"][1]["scopes"]["current"][field] = value
                self.reject(inputs, reason)

    def test_invalid_dates_and_funnel_within_step_window_mismatch_are_rejected(self):
        inputs = self.inputs()
        inputs["rows"][0]["scopes"]["current"]["window"]["start"] = "2026-02-30"
        self.reject(inputs, "OPERATOR_SCOPE_MISMATCH")
        inputs = self.inputs("funnel-diagnosis")
        inputs.update(mode="rowwise", topology="independent")
        inputs["rows"][0]["scopes"]["reached"]["window"]["end"] = "2026-09-08"
        self.reject(inputs, "OPERATOR_SCOPE_MISMATCH")

    def test_partial_unknown_and_empty_never_claim_a_complete_total(self):
        for state in ("prefix", "unknown"):
            with self.subTest(state=state):
                inputs = self.inputs()
                inputs["rows"][0]["scopes"]["current"]["completeness"] = state
                self.reject(inputs, "OPERATOR_COMPLETENESS_UNSUPPORTED")
                inputs["mode"] = "rowwise"
                inputs.pop("aggregation")
                result = self.execute(inputs)["result"]
                self.assertEqual((state, {}), (result["completeness"], result["metrics"]))
        inputs["rows"] = []
        self.reject(inputs, "OPERATOR_INPUT_INVALID")

    def test_real_linear_funnel_supports_evidenced_subset_boundaries(self):
        inputs = self.inputs("funnel-diagnosis")
        inputs["rows"][1]["values"]["entered"] = 60
        inputs["rows"][1]["lineage"]["relation"] = "subset"
        result = self.execute(inputs)["result"]
        self.assertEqual("0.4", result["metrics"]["cumulative_conversion"])
        self.assertEqual("0.666667", next(r["value"] for r in result["ranked_rows"] if r["key"] == "payment"))
        inputs["rows"].reverse()
        self.assertEqual(result, self.execute(inputs)["result"])

    def test_matching_counts_do_not_prove_membership_or_linear_topology(self):
        inputs = self.inputs("funnel-diagnosis")
        inputs["rows"][1].pop("lineage")
        self.reject(inputs, "OPERATOR_FUNNEL_LINEAGE_UNPROVEN")
        inputs = self.inputs("funnel-diagnosis")
        inputs["topology"] = "independent"
        self.reject(inputs, "OPERATOR_FUNNEL_LINEAGE_UNPROVEN")
        inputs["mode"] = "rowwise"
        inputs["rows"][0]["values"].update(entered=10, reached=9)
        inputs["rows"][1]["values"].update(entered=100, reached=90)
        result = self.execute(inputs)["result"]
        self.assertNotIn("cumulative_conversion", result["metrics"])
        self.assertEqual({"0.9"}, {r["value"] for r in result["ranked_rows"]})

    def test_cumulative_rejects_impossible_subset_and_partial_chain(self):
        inputs = self.inputs("funnel-diagnosis")
        inputs["rows"][1]["values"].update(entered=100, reached=90)
        inputs["rows"][1]["lineage"]["relation"] = "subset"
        self.reject(inputs, "OPERATOR_FUNNEL_LINEAGE_UNPROVEN")
        inputs = self.inputs("funnel-diagnosis")
        inputs["rows"][1]["scopes"]["reached"]["completeness"] = "prefix"
        self.reject(inputs, "OPERATOR_COMPLETENESS_UNSUPPORTED")

    def test_zero_denominators_and_zero_total_change_remain_undefined(self):
        inputs = self.inputs("funnel-diagnosis")
        for row in inputs["rows"]:
            row["values"].update(entered=0, reached=0)
        result = self.execute(inputs)["result"]
        self.assertIsNone(result["metrics"]["cumulative_conversion"])
        self.assertTrue(all(r["value"] is None for r in result["ranked_rows"]))
        decomposition = self.execute(self.inputs("metric-decomposition"))["result"]
        self.assertEqual("0", decomposition["metrics"]["returned_total_change"])
        self.assertTrue(all(r["contribution"] is None for r in decomposition["ranked_rows"]))

    def test_positive_decomposition_and_scenario_totals_are_preserved(self):
        inputs = self.inputs("metric-decomposition")
        inputs["rows"][1]["values"]["current"] = 60
        result = self.execute(inputs)["result"]
        self.assertEqual("30", result["metrics"]["returned_total_change"])
        self.assertEqual(["0.666667", "0.333333"], [r["contribution"] for r in result["ranked_rows"]])
        scenario = self.execute(self.inputs("scenario-projection"))["result"]
        self.assertEqual("165", scenario["metrics"]["scenario_total"])

    def test_unchanged_nonsum_methods_accept_nonadditive_inputs(self):
        for method in ("retention-curve", "price-elasticity", "churn-segment-profile", "ltv-payback-period"):
            with self.subTest(method=method):
                inputs = self.inputs(method, version=1)
                inputs["additivity"] = "non_additive"
                self.assertTrue(self.registry.execute(GOVERNED_METHOD_URIS[method], inputs)["ok"])

    def test_large_valid_numbers_are_bounded_and_do_not_leak_decimal_exceptions(self):
        inputs = self.inputs()
        for row in inputs["rows"]:
            row["values"]["current"] = 10 ** 36
        result = self.execute(inputs)
        self.assertEqual(Decimal(2 * 10 ** 36), Decimal(result["result"]["metrics"]["current_total"]))

    def test_model_successors_resolve_exact_operators_without_aliasing_legacy(self):
        models = ModelRegistry(operators=self.registry)
        for name in ("game-revenue-forecast", "ltv-curve", "segmented-ltv-curve"):
            with self.subTest(model=name):
                for version in (1, 2):
                    result = models.describe(f"model://gravity/{name}@{version}")
                    contract = result["model"]["contract"]
                    self.assertEqual(f"operator://gravity/scenario-projection@{version}", contract["operator_uri"])
                    self.assertTrue(models.evaluate(contract["uri"], at="2026-09-09")["ok"])
                self.assertNotEqual(models.describe(f"model://gravity/{name}@1")["model"]["digest"],
                                    models.describe(f"model://gravity/{name}@2")["model"]["digest"])
