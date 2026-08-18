from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Mapping

from gravity_sdk._field_policy_analysis import (
    validate_analysis_date_list,
    validate_analysis_query,
    validate_analysis_segment_rule,
    validate_analysis_shape,
)
from gravity_sdk._field_policy_conditions import (
    validate_analysis_conditions,
    validate_analysis_filter_map,
    validate_analysis_group_by,
)
from gravity_sdk._field_policy_retention import validate_retention_before_after
from gravity_sdk._field_policy_segment_members import validate_segment_member_fields
from gravity_sdk._field_policy_shared import (
    new_analysis_references,
    parse_iso_calendar_date,
    require_exact_mapping,
    validate_optional_label,
    validate_scalar_list,
)
from gravity_sdk._order_read import canonical_app, canonical_date
from gravity_sdk.analysis_primitives import AnalysisFilter
from gravity_sdk.analysis_query_batch import (
    BATCH_SCHEMA_VERSION,
    MAX_QUERIES,
    _identity,
    validate_analysis_query_batch,
)
from gravity_sdk.analysis_query_multi_app import MAX_COMPONENTS, parse_multi_app_queries
from gravity_sdk.analysis_spec_cli import _spec_schema_result
from gravity_sdk.attribution import attribution_snapshot
from gravity_sdk.bilibili_account_performance import normalize_bilibili_account_window
from gravity_sdk.errors import InputValidationError, SqlValidationError
from gravity_sdk.material_performance import normalize_material_platforms
from gravity_sdk.models import InputField, _validate_date_range, _validate_filters
from gravity_sdk.monetization_detail import validate_monetization_operation_request
from gravity_sdk.monetization_detail_cli import dispatch_monetization_detail
from gravity_sdk.order_trace import _bounded_trace
from gravity_sdk.pagination_inputs import validate_page_inputs
from gravity_sdk.promotion_performance_request import normalize_promotion_platforms
from gravity_sdk.promotion_snapshot_compat import promotion_snapshot_compat
from gravity_sdk.sql.client import GravityClient as SqlClient
from gravity_sdk.workspace import load_workspace


QUERY_ID = "1700000000000AAAAAAAAAAAAAAAAAAA"


def _event_inputs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "query_id": QUERY_ID,
        "app_id": "101",
        "query_item_list": [
            {
                "event_name": "purchase",
                "custom_name": "purchase",
                "target": {"name": "PresetAllCount", "field": "PresetAllCount"},
                "conditions": [],
                "cond_logic": "AND",
            }
        ],
        "group_by_list": [
            {"type": "default_event", "field": "create_time", "group_by": "day"}
        ],
        "date_list": [
            {"start_date": "2026-08-07T00:00:00", "end_date": "2026-08-07T00:00:00"}
        ],
    }
    values.update(overrides)
    return values


class _NoPlanSDK:
    def __init__(self) -> None:
        self.workspace = load_workspace("examples/workspace")

    def validate_plan(self, _plan: Mapping[str, Any], **_options: Any) -> dict[str, Any]:
        return {"schema_version": "gravity.plan-result.v1", "results": []}


class ErrorGradeBActualTests(unittest.TestCase):
    def _assert_actual(self, error: BaseException, *needles: str) -> None:
        rendered = str(error)
        self.assertIn("actual value:", rendered)
        for needle in needles:
            self.assertIn(needle, rendered)

    def test_shared_mapping_date_and_label_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            require_exact_mapping({"extra": 1}, {"start_date", "end_date"}, "analysis date range")
        self._assert_actual(caught.exception, "extra")
        with self.assertRaises(InputValidationError) as caught:
            require_exact_mapping("nope", {"start_date"}, "analysis date range")
        self._assert_actual(caught.exception, "str")
        with self.assertRaises(InputValidationError) as caught:
            validate_optional_label(123, "custom_name")
        self._assert_actual(caught.exception, "123")
        with self.assertRaises(InputValidationError) as caught:
            validate_scalar_list({"a": 1}, "user_filtering")
        self._assert_actual(caught.exception, "dict")
        with self.assertRaises(InputValidationError) as caught:
            parse_iso_calendar_date("2026/08/07", "date")
        self._assert_actual(caught.exception, "2026/08/07")

    def test_analysis_identifier_and_date_window_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_query(
                "event",
                _event_inputs(app_id=123),
                lambda *_a: {"status": "success", "data": {"list": []}},
            )
        self._assert_actual(caught.exception, "123")
        self.assertEqual(caught.exception.field, "app_id")
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_segment_rule(
                {"app_id": "abc", "name": "n", "update_type": "Manual", "cond_logic": "AND"},
                lambda *_a: {"status": "success", "data": {"list": []}},
            )
        self.assertIn("actual value:", str(caught.exception))
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_shape("event", _event_inputs(query_id="not-an-id"))
        self._assert_actual(caught.exception, "not-an-id")
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_date_list([], "event")
        self._assert_actual(caught.exception, "list")

    def test_retention_control_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_retention_before_after(
                {"formula": "^", "name": "ok"}, new_analysis_references()
            )
        self._assert_actual(caught.exception, "^")
        self.assertEqual(caught.exception.field, "formula")

    def test_condition_and_group_shape_errors_include_type_not_values(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_conditions(
                "not-a-list", new_analysis_references(), "global_conditions"
            )
        self._assert_actual(caught.exception, "str")
        self.assertNotIn("token=secret", str(caught.exception))
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_group_by(["x"] * 21, new_analysis_references())
        self._assert_actual(caught.exception, "21")
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_filter_map(["not-object"], set(), "user_filtering")
        self._assert_actual(caught.exception, "list")

    def test_operation_input_field_errors_include_actual(self) -> None:
        required = InputField(name="kind", type="string", nullable=False, enum=("event",))
        with self.assertRaises(InputValidationError) as caught:
            required.validate(None)
        self._assert_actual(caught.exception, "null")
        with self.assertRaises(InputValidationError) as caught:
            required.validate("scatter")
        self._assert_actual(caught.exception, "scatter")
        bounded = InputField(name="tags", type="array", max_items=2, item_type="string")
        with self.assertRaises(InputValidationError) as caught:
            bounded.validate(["a", "b", "c"])
        self._assert_actual(caught.exception, "3")

    def test_pagination_and_attribution_errors_include_actual(self) -> None:
        pagination = SimpleNamespace(
            kind="page_info",
            page_field="page",
            page_size_field="page_size",
            max_page_size=100,
        )
        with self.assertRaises(InputValidationError) as caught:
            validate_page_inputs(
                {"page": 0, "page_size": 20},
                pagination,
                {"page": 0, "page_size": 20},
            )
        self._assert_actual(caught.exception, "0")
        with self.assertRaises(InputValidationError) as caught:
            attribution_snapshot(object(), app_id="abc")
        self._assert_actual(caught.exception, "abc")

    def test_bilibili_and_promotion_material_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            normalize_bilibili_account_window("2026-02-01", "2026-01-01")
        self._assert_actual(caught.exception, "2026-02-01")
        with self.assertRaises(InputValidationError) as caught:
            promotion_snapshot_compat(object(), [])
        self._assert_actual(caught.exception, "[]")
        with self.assertRaises(InputValidationError) as caught:
            normalize_material_platforms(["nope"])
        self._assert_actual(caught.exception, "nope")
        with self.assertRaises(InputValidationError) as caught:
            normalize_promotion_platforms(["nope"])
        self._assert_actual(caught.exception, "nope")

    def test_analysis_batch_and_filter_primitive_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            validate_analysis_query_batch(
                _NoPlanSDK(),
                {
                    "schema_version": BATCH_SCHEMA_VERSION,
                    "queries": [{}] * (MAX_QUERIES + 1),
                },
            )
        self._assert_actual(caught.exception, str(MAX_QUERIES + 1))
        with self.assertRaises(InputValidationError) as caught:
            _identity({"id": "1bad", "kind": "event"}, "queries[0]")
        self._assert_actual(caught.exception, "1bad")
        with self.assertRaises(InputValidationError) as caught:
            parse_multi_app_queries(
                [
                    {
                        "id": f"q{index}",
                        "kind": "event",
                        "apps": ["demo", "other"],
                        "spec": {},
                    }
                    for index in range((MAX_COMPONENTS // 2) + 1)
                ]
            )
        self._assert_actual(caught.exception, str(MAX_COMPONENTS + 2))
        with self.assertRaises(InputValidationError) as caught:
            AnalysisFilter(
                field="$os",
                operator="EQUALS",
                field_type="user",
                values="$os",
            )
        self._assert_actual(caught.exception, "str")

    def test_cli_sql_http_and_order_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            _spec_schema_result(
                SimpleNamespace(spec_schema=True, spec="{}", input=None, kind="event")
            )
        self._assert_actual(caught.exception, "{}")
        with self.assertRaises(SqlValidationError) as caught:
            SqlClient(runtime=object()).execute_batch(["select 1"], max_workers=0)
        self._assert_actual(caught.exception, "0")
        with self.assertRaises(SqlValidationError) as caught:
            SqlClient(runtime=object()).execute_sql("")
        self._assert_actual(caught.exception, '""')
        with self.assertRaises(InputValidationError) as caught:
            canonical_app("abc")
        self._assert_actual(caught.exception, "abc")
        with self.assertRaises(InputValidationError) as caught:
            canonical_date("2026/08/07")
        self._assert_actual(caught.exception, "2026/08/07")
        with self.assertRaises(InputValidationError) as caught:
            _bounded_trace(123)
        self._assert_actual(caught.exception, "123")

    def test_models_date_filter_and_monetization_errors_include_actual(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            _validate_date_range(["2026-02-01", "2026-01-01"])
        self._assert_actual(caught.exception, "2026-02-01")
        with self.assertRaises(InputValidationError) as caught:
            _validate_filters(["not-object"])
        self._assert_actual(caught.exception, "str")
        with self.assertRaises(InputValidationError) as caught:
            validate_monetization_operation_request(
                object(), {"fields": "not-a-list", "date": "2026-08-07"}
            )
        self._assert_actual(caught.exception, "str")
        with self.assertRaises(InputValidationError) as caught:
            dispatch_monetization_detail(SimpleNamespace(dry_run=True), None)
        self._assert_actual(caught.exception, "true")

    def test_segment_member_unknown_field_includes_actual_without_loader(self) -> None:
        operation = SimpleNamespace(
            response_projection=SimpleNamespace(item_keys=("id", "name"))
        )
        with self.assertRaises(InputValidationError) as caught:
            validate_segment_member_fields(
                operation, {"fields": "not-a-list"}, "101", lambda *_a: {}
            )
        self._assert_actual(caught.exception, '"str"')
        with self.assertRaises(InputValidationError) as caught:
            validate_segment_member_fields(
                operation,
                {"fields": ["unknown_field"]},
                "101",
                lambda *_a: {"status": "success", "data": {"list": []}},
            )
        self._assert_actual(caught.exception, "unknown_field")
