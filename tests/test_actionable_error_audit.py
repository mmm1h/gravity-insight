from __future__ import annotations

import unittest

from collections import Counter
from pathlib import Path


from gravity_sdk._field_policy_conditions import validate_analysis_conditions
from gravity_sdk._field_policy_shared import new_analysis_references
from gravity_sdk.errors import InputValidationError
from scripts.audit_actionable_errors import inventory


ROOT = Path(__file__).resolve().parents[1]


class ActionableErrorAuditTests(unittest.TestCase):
    def test_actionable_error_inventory_is_complete_and_reproducible(self):
        rows = inventory(ROOT / "src" / "gravity_sdk")
        counts = Counter(item["grade"] for item in rows)
        assert len(rows) == 1225
        assert counts == {"A": 833, "B": 23, "C": 369}
        assert sum(counts.values()) == len(rows)


    def test_condition_error_sanitizes_value_and_bounds_authoritative_candidates(self):
        condition = {
            "operator": "token=do-not-log-this",
            "field": "country",
            "type": "user",
            "value": [],
        }
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_conditions(
                [condition], new_analysis_references(), "global_conditions"
            )
        error = caught.exception
        assert error.field == "conditions[].operator"
        assert "do-not-log-this" not in str(error)
        assert "token=[REDACTED]" in str(error)
        assert "showing 20 of 25" in str(error)
        assert "gravity analysis query --kind event --spec-schema" in str(error)


    def test_condition_collection_error_does_not_echo_filter_values(self):
        condition = {
            "operator": "EQUALS",
            "field": "account_id",
            "type": "user",
            "value": ["user-level-value-must-not-spread"],
        }
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_conditions(
                [condition] * 101, new_analysis_references(), "global_conditions"
            )
        assert caught.exception.field == "global_conditions"
        assert "user-level-value-must-not-spread" not in str(caught.exception)


    def test_plan_and_batch_errors_include_sanitized_actual_values(self):
        from gravity_sdk.analysis_query_batch import run_analysis_query_batch
        from gravity_sdk.plan import PlanValidationError
        from gravity_sdk.plan_validation import validate_plan

        with self.assertRaises(PlanValidationError) as plan_error:
            validate_plan("token=credential-value")
        self.assertIn("actual value:", str(plan_error.exception))
        self.assertIn("[REDACTED]", str(plan_error.exception))
        self.assertNotIn("credential-value", str(plan_error.exception))
        with self.assertRaises(PlanValidationError) as schema_error:
            validate_plan({"schema_version": "nope", "nodes": []})
        self.assertIn('actual value: "nope"', str(schema_error.exception))
        with self.assertRaises(InputValidationError) as batch_error:
            run_analysis_query_batch(object(), {"schema_version": "bad"}, dry_run="yes")
        self.assertIn('actual value: "yes"', str(batch_error.exception))
        self.assertEqual(batch_error.exception.field, "dry_run")
