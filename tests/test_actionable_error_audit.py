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
        assert len(rows) == 1061
        assert counts == {"A": 257, "B": 434, "C": 370}
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
