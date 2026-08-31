from __future__ import annotations

import unittest

from collections import Counter
from pathlib import Path


from gravity_insight._field_policy_conditions import validate_analysis_conditions
from gravity_insight._field_policy_shared import new_analysis_references
from gravity_insight.errors import InputValidationError
from scripts.audit_actionable_errors import inventory


ROOT = Path(__file__).resolve().parents[1]


class ActionableErrorAuditTests(unittest.TestCase):
    def test_actionable_error_inventory_is_complete_and_reproducible(self):
        """The aggregate product adds bounded, actionable validation sites."""

        rows = inventory(ROOT / "src" / "gravity_insight")
        counts = Counter(item["grade"] for item in rows)
        assert len(rows) == 1368
        assert counts["A"] == 1185
        assert counts["B"] == 183
        assert counts.get("C", 0) == 0
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
        from gravity_insight.analysis_query_batch import run_analysis_query_batch
        from gravity_insight.plan import PlanValidationError
        from gravity_insight.plan_validation import validate_plan

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

    def test_plan_adapter_errors_describe_safe_actual_shape(self):
        from gravity_insight.plan import AdapterContext
        from gravity_insight.plan_custom_audience_adapter import validate_custom_audience_plan

        context = AdapterContext(
            node_id="audiences", execution_id="audiences", kind="composite",
            workspace=object(), output_fields=(), dynamic_targets=(),
            max_pages=1, max_items=1,
        )
        with self.assertRaises(InputValidationError) as caught:
            validate_custom_audience_plan(
                {"name": "custom_audience", "unexpected": "business-value"},
                context,
                frozenset(),
            )
        self.assertIn('actual value: ["name","unexpected"]', str(caught.exception))
        self.assertNotIn("business-value", str(caught.exception))

    def test_representative_sites_now_carry_path_and_remedy(self):
        from types import SimpleNamespace

        from gravity_insight.attribution import attribution_snapshot
        from gravity_insight.bilibili_account_performance import (
            normalize_bilibili_account_window,
        )
        from gravity_insight.pagination_inputs import validate_page_inputs
        from gravity_insight.plan import PlanValidationError
        from gravity_insight.plan_validation import validate_plan

        with self.assertRaises(PlanValidationError) as kind_error:
            validate_plan(
                {
                    "schema_version": "gravity.plan.v1",
                    "nodes": [{"id": "n1", "kind": "nope", "request": {}}],
                }
            )
        self.assertEqual(kind_error.exception.field, "nodes[0].kind")
        self.assertIn("actual value:", str(kind_error.exception))
        self.assertIn("must be one of", str(kind_error.exception))

        pagination = SimpleNamespace(
            kind="page_info",
            page_field="page",
            page_size_field="page_size",
            max_page_size=100,
        )
        with self.assertRaises(InputValidationError) as page_error:
            validate_page_inputs(
                {"page": object(), "page_size": object()},
                pagination,
                {"page": 0, "page_size": 20},
            )
        self.assertEqual(page_error.exception.field, "page")
        self.assertIn("must be a positive integer", str(page_error.exception))

        with self.assertRaises(InputValidationError) as date_error:
            normalize_bilibili_account_window("2026-02-01", "2026-01-01")
        self.assertEqual(date_error.exception.field, "start/end")
        self.assertIn("must not follow end", str(date_error.exception))

        with self.assertRaises(InputValidationError) as app_error:
            attribution_snapshot(object(), app_id="abc")
        self.assertEqual(app_error.exception.field, "app_id")
        self.assertIn("must be a positive integer", str(app_error.exception))
