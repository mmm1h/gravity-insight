from __future__ import annotations

import json
import unittest
from pathlib import Path

from gravity_insight import GravitySDK, InputValidationError
from gravity_insight.agent_runtime_contracts import validate_schema
from gravity_insight.multidim_contract import (
    STANDARD_RETENTION_DENOMINATOR_GAP_CODE,
    reconcile_standard_retention_denominators,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/retention_denominator_reconciliation.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA = "retention-denominator-reconciliation-v1.schema.json"


class RetentionDenominatorReconciliationTests(unittest.TestCase):
    def test_matching_denominators_keep_both_source_names(self) -> None:
        result = reconcile_standard_retention_denominators(**FIXTURES["match"])

        self.assertEqual(("match", 0, "observed"), (
            result["status"], result["drift"], result["cohort_status"]
        ))
        self.assertEqual(
            ("standard_activate_cnt", "init_num"),
            (
                result["sources"]["multidim"]["field"],
                result["sources"]["analysis"]["field"],
            ),
        )
        self.assertEqual("unknown", result["semantic_equivalence"])
        validate_schema(result, SCHEMA, "retention denominator reconciliation")

    def test_nonzero_registration_activation_drift_is_signed_and_provenanced(self) -> None:
        result = reconcile_standard_retention_denominators(**FIXTURES["drift"])

        self.assertEqual(("drift", 7), (result["status"], result["drift"]))
        self.assertEqual(
            ("2026-08-02", 7, "2026-08-10T02:00:00Z", "2026-08-10T02:03:00Z"),
            (
                result["cohort_date"],
                result["offset"],
                result["sources"]["multidim"]["fetched_at"],
                result["sources"]["analysis"]["fetched_at"],
            ),
        )
        negative = reconcile_standard_retention_denominators(
            **{
                **FIXTURES["drift"],
                "multidim": {**FIXTURES["drift"]["multidim"], "value": 113},
            }
        )
        self.assertEqual(("drift", -7), (negative["status"], negative["drift"]))
        validate_schema(result, SCHEMA, "positive retention denominator drift")
        validate_schema(negative, SCHEMA, "negative retention denominator drift")

    def test_successful_empty_cohort_is_unknown_without_zero_substitution(self) -> None:
        result = reconcile_standard_retention_denominators(**FIXTURES["empty"])

        self.assertEqual(
            ("unknown", "empty", None, ["EMPTY_COHORT"]),
            (
                result["status"],
                result["cohort_status"],
                result["drift"],
                result["reason_codes"],
            ),
        )
        self.assertFalse(result["sources"]["multidim"]["value_present"])
        self.assertFalse(result["sources"]["analysis"]["value_present"])
        validate_schema(result, SCHEMA, "empty retention denominator cohort")

    def test_missing_evidence_does_not_collapse_to_match(self) -> None:
        result = reconcile_standard_retention_denominators(**FIXTURES["missing"])

        self.assertEqual(
            ("unknown", None, ["DENOMINATOR_VALUE_MISSING"]),
            (result["status"], result["drift"], result["reason_codes"]),
        )
        self.assertEqual(0, result["sources"]["multidim"]["value"])
        self.assertIsNone(result["sources"]["analysis"]["value"])
        self.assertNotEqual("match", result["status"])
        validate_schema(result, SCHEMA, "missing retention denominator evidence")

    def test_sdk_surface_is_local_and_returns_the_named_bounded_gap(self) -> None:
        built: list[bool] = []
        sdk = GravitySDK(insight_factory=lambda: built.append(True))

        result = sdk.reconcile_standard_retention_denominators(**FIXTURES["drift"])
        gap = result["capability_gap"]

        self.assertEqual([], built)
        self.assertFalse(result["network_called"])
        self.assertEqual(STANDARD_RETENTION_DENOMINATOR_GAP_CODE, gap["code"])
        self.assertEqual(
            {
                "kind", "code", "journey", "query", "reason", "next_action",
                "weak_matches", "network_called",
            },
            set(gap),
        )
        for requirement in (
            "source event", "inclusion and exclusion", "timezone/day boundary",
            "attribution or re-attribution", "late-event/backfill",
        ):
            self.assertIn(requirement, gap["next_action"])

    def test_input_is_closed_to_aggregate_readings(self) -> None:
        private = dict(FIXTURES["match"]["multidim"])
        private["app_id"] = "must-not-pass-through"
        with self.assertRaises(InputValidationError) as raised:
            reconcile_standard_retention_denominators(
                **{**FIXTURES["match"], "multidim": private}
            )
        self.assertEqual("multidim", raised.exception.to_error_detail().field)
        self.assertNotIn("must-not-pass-through", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
