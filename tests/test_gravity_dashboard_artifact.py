from __future__ import annotations

import unittest

from gravity_sdk.dashboard_artifact import compile_dashboard_chart
from gravity_sdk.errors import InputValidationError, UnsupportedOperationError


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
                "week_first_day": 1,
                "is_total_calc": False,
            },
            "analysis_funnel": {
                "calculateBody": {
                    "query_item_list": [_event("one"), _event("two")],
                    "stat_time_window": {"type": "day", "val": 1},
                },
                "seriesType": "funnel_line",
            },
            "analysis_scatter": {
                "calculateBody": {
                    "query_item_list": [{**_event(), "calc_zone": {"zone_type": "default"}, "prop_to_calc": "PresetAllCount", "prop_to_calc_sub": ""}],
                    "group_by_list": [
                        {"type": "default_event", "field": "create_time", "group_by": "day"}
                    ],
                },
                "seriesType": "table",
                "groupByCreateTime": {"value": "total"},
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
        self.assertNotIn("inputs", compiled[0].safe_summary())

    def test_unknown_web_semantics_and_bad_window_fail_before_validation(self) -> None:
        client = _Client()
        report = {
            "report_id": "1",
            "name": "private chart",
            "subject": "analysis_event",
            "config": {"calculateBody": {"query_item_list": [_event()]}, "commonFilter": ["secret"]},
        }
        with self.assertRaises(UnsupportedOperationError):
            compile_dashboard_chart(client, report, app_id=1, start="2026-08-01", end="2026-08-02")
        with self.assertRaises(InputValidationError):
            compile_dashboard_chart(client, {**report, "config": {"calculateBody": {"query_item_list": [_event()]}}}, app_id=1, start="2026-08-03", end="2026-08-02")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
