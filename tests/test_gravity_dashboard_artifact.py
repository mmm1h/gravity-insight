from __future__ import annotations

import json
import unittest

from gravity_insight.dashboard_artifact import compile_dashboard_chart
from gravity_insight.errors import (
    InputValidationError,
    UnsupportedOperationError,
    error_envelope,
)


def _event(name: str = "event") -> dict:
    return {
        "cond_logic": "AND",
        "conditions": [],
        "custom_name": name,
        "event_index": 0,
        "event_label": name,
        "event_name": name,
        "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
    }


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def validate(self, operation_id: str, inputs: dict) -> dict:
        self.calls.append((operation_id, inputs))
        return {"ok": True, "status": "needs_live_metadata"}


class _RejectingClient(_Client):
    def validate(self, operation_id: str, inputs: dict) -> dict:
        self.calls.append((operation_id, inputs))
        return {
            "ok": False,
            "status": "invalid",
            "error": {
                "field": "query_item_list",
                "message": "opaque-validation-value",
            },
        }


class DashboardArtifactTests(unittest.TestCase):
    def test_five_subjects_compile_to_exact_stable_inputs(self) -> None:
        reports = {
            "analysis_event": {
                "calculateBody": {
                    "query_item_list": [_event()],
                    "group_by_list": [
                        {"type": "default_event", "field": "create_time", "group_by": "day"}
                    ],
                },
                "groupByCreateTime": {"value": 5},
                "tableShowType": "table",
                "aggregate_config": {},
                "date_list": [{"start_date": "2026-07-01", "end_date": "2026-07-02"}],
                "queryItemList": [],
            },
            "analysis_user_property": {
                "calculateBody": {
                    "query_item": {
                        "conditions": [],
                        "custom_name": "",
                        "target": {
                            "cname": "",
                            "data_type": "INT",
                            "field": "PresetUserCount",
                            "name": "PresetUserCount",
                        },
                    }
                },
                "seriesType": "table",
            },
            "analysis_retention": {
                "calculateBody": {"query_item_list": [_event("before"), _event("after")]},
                "cascaderValue": ["day", 7],
                "cascaderInput": 7,
                "seriesType": "table",
                "groupByCreateTime": {"value": "day"},
                "compareList": [],
                "date_list": [{"start_date": "2026-07-01", "end_date": "2026-07-02"}],
                "checkIndexList": [],
                "week_first_day": 1,
                "is_total_calc": False,
            },
            "analysis_funnel": {
                "calculateBody": {
                    "query_item_list": [_event("one"), _event("two")],
                    "stat_time_window": {"type": "day", "val": 1},
                },
                "seriesType": "line",
                "cascaderValue": ["day", 7],
                "cascaderInput": 7,
                "groupByCreateTime": {"value": "day"},
                "compareList": [],
                "date_list": [{"start_date": "2026-07-01", "end_date": "2026-07-02"}],
            },
            "analysis_scatter": {
                "calculateBody": {
                    "query_item_list": [{**_event(), "calc_zone": {"zone_type": "default"}, "prop_to_calc": "PresetAllCount", "prop_to_calc_sub": ""}],
                    "group_by_list": [
                        {"type": "default_event", "field": "create_time", "group_by": "day"}
                    ],
                },
                "seriesType": "scatter_bar",
                "groupByCreateTime": {"value": "week"},
            },
        }
        client = _Client()
        compiled = [
            compile_dashboard_chart(
                client,
                {"report_id": str(index), "name": subject, "subject": subject, "config": config},
                app_id=17,
                start="2026-08-01",
                end="2026-08-02",
            )
            for index, (subject, config) in enumerate(reports.items(), 1)
        ]
        self.assertEqual(
            [item.kind for item in compiled],
            ["event", "property", "retention", "funnel", "scatter"],
        )
        self.assertEqual(len(client.calls), 5)
        self.assertEqual(client.calls[0][1]["group_by_list"][0]["granularity"], 5)
        self.assertFalse(compiled[1].date_override_applied)
        self.assertEqual(client.calls[2][1]["offset"], 7)
        self.assertTrue(client.calls[3][1]["to_calc_each_day"])
        self.assertEqual(client.calls[4][1]["group_by_list"][-1]["group_by"], "day")
        self.assertFalse(any(
            "dashboard conditions" in limitation
            for item in compiled for limitation in item.limitations
        ))
        self.assertNotIn("inputs", compiled[0].safe_summary())

    def test_unknown_web_semantics_and_bad_window_fail_before_validation(self) -> None:
        client = _Client()
        report = {
            "report_id": "1",
            "name": "private chart",
            "subject": "analysis_event",
            "config": {"calculateBody": {"query_item_list": [_event()]}, "commonFilter": ["secret"]},
        }
        with self.assertRaises(UnsupportedOperationError) as captured:
            compile_dashboard_chart(client, report, app_id=1, start="2026-08-01", end="2026-08-02")
        detail = error_envelope(captured.exception)["error"]
        self.assertEqual(
            [{"field": "report.config.commonFilter", "type": "array"}],
            detail["unsupported_items"],
        )
        self.assertFalse(detail["unsupported_items_truncated"])
        self.assertNotIn("secret", json.dumps(detail))
        with self.assertRaises(InputValidationError):
            compile_dashboard_chart(client, {**report, "config": {"calculateBody": {"query_item_list": [_event()]}}}, app_id=1, start="2026-08-03", end="2026-08-02")
        drift = {**report, "config": {
            "calculateBody": {"query_item_list": [_event()]},
            "groupByCreateTime": {"value": "day", "future_semantic": True},
        }}
        with self.assertRaises(UnsupportedOperationError) as nested:
            compile_dashboard_chart(client, drift, app_id=1, start="2026-08-01", end="2026-08-02")
        self.assertEqual(
            [
                {
                    "field": "report.config.groupByCreateTime.future_semantic",
                    "type": "boolean",
                }
            ],
            nested.exception.to_error_detail().to_dict()["unsupported_items"],
        )
        retention = {
            "report_id": "2", "name": "retention", "subject": "analysis_retention",
            "config": {
                "calculateBody": {
                    "query_item_list": [_event("before"), _event("after")],
                    "user_re_attribute_filtering": {"channel": "private"},
                },
                "cascaderValue": ["day", 7], "is_total_calc": "false",
            },
        }
        with self.assertRaises(UnsupportedOperationError) as semantic:
            compile_dashboard_chart(client, retention, app_id=1, start="2026-08-01", end="2026-08-02")
        semantic_detail = semantic.exception.to_error_detail().to_dict()
        self.assertEqual(
            [
                {
                    "field": "report.config.calculateBody.user_re_attribute_filtering",
                    "type": "object",
                }
            ],
            semantic_detail["unsupported_items"],
        )
        self.assertNotIn("private", json.dumps(semantic_detail))
        self.assertEqual(client.calls, [])

    def test_unknown_field_diagnostics_are_deterministic_and_bounded(self) -> None:
        client = _Client()
        config = {
            "calculateBody": {"query_item_list": [_event()]},
            **{
                f"future_{index:02d}": {
                    "opaque": f"tenant-secret-value-{index:02d}"
                }
                for index in range(25)
            },
        }

        with self.assertRaises(UnsupportedOperationError) as captured:
            compile_dashboard_chart(
                client,
                {
                    "report_id": "bounded",
                    "name": "bounded",
                    "subject": "analysis_event",
                    "config": config,
                },
                app_id=1,
                start="2026-08-01",
                end="2026-08-02",
            )

        detail = error_envelope(captured.exception)["error"]
        self.assertEqual(20, len(detail["unsupported_items"]))
        self.assertTrue(detail["unsupported_items_truncated"])
        self.assertEqual(
            [f"report.config.future_{index:02d}" for index in range(20)],
            [item["field"] for item in detail["unsupported_items"]],
        )
        self.assertEqual(
            {"object"}, {item["type"] for item in detail["unsupported_items"]}
        )
        self.assertNotIn("tenant-secret-value", json.dumps(detail))
        self.assertEqual([], client.calls)

    def test_contract_validation_rejection_stays_value_free_and_fail_closed(self) -> None:
        client = _RejectingClient()
        report = {
            "report_id": "invalid",
            "name": "invalid",
            "subject": "analysis_event",
            "config": {
                "calculateBody": {"query_item_list": [_event()]},
                "aggregate_config": {},
            },
        }

        with self.assertRaises(UnsupportedOperationError) as captured:
            compile_dashboard_chart(
                client,
                report,
                app_id=1,
                start="2026-08-01",
                end="2026-08-02",
            )

        detail = captured.exception.to_error_detail().to_dict()
        self.assertEqual(
            [{"field": "report.config", "type": "object"}],
            detail["unsupported_items"],
        )
        self.assertNotIn("opaque-validation-value", json.dumps(detail))
        self.assertEqual(1, len(client.calls))


if __name__ == "__main__":
    unittest.main()
