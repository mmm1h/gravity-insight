from __future__ import annotations

import json
import unittest

from gravity_sdk.dashboard_analysis import (
    prepare_dashboard_analysis,
    run_dashboard_analysis,
)
from gravity_sdk.errors import (
    ContractChangedError,
    InputValidationError,
    PaginationError,
)


def _event_report(report_id: str = "10") -> dict:
    return {
        "report_id": report_id,
        "name": "Active users",
        "subject": "analysis_event",
        "config": {
            "calculateBody": {
                "query_item_list": [{
                    "cond_logic": "AND", "conditions": [], "custom_name": "login",
                    "event_index": 0, "event_label": "login", "event_name": "login",
                    "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
                }],
                "group_by_list": [{
                    "type": "default_event", "field": "create_time", "group_by": "day",
                }],
            },
            "groupByCreateTime": {"value": "day"},
            "tableShowType": "table",
            "aggregate_config": {},
        },
    }


def _tree() -> dict:
    return {"ok": True, "status": "success", "data": [{
        "id": 1, "name": "space", "folder_or_dashboard": [{
            "id": 3, "name": "Growth", "space_id": 1,
        }],
    }]}


class _Client:
    def __init__(self, reports=None, *, fail=False, duplicate=False):
        self.reports = reports if reports is not None else [
            _event_report(),
            {"report_id": "11", "name": "Web only", "subject": "analysis_cash", "config": {}},
        ]
        self.fail, self.duplicate = fail, duplicate
        self.batch_calls, self.read_calls = [], []

    def read(self, operation_id, inputs):
        self.read_calls.append((operation_id, inputs))
        if operation_id.endswith(".tree"):
            return _tree()
        return {"ok": True, "status": "success", "data": {
            "id": 3, "app_id": 17, "space_id": 1, "even_report": self.reports,
        }}

    def validate(self, operation_id, inputs):
        return {"ok": True, "status": "needs_live_metadata"}

    def batch(self, requests, *, max_workers, max_pages, max_total_items):
        self.batch_calls.append((requests, max_workers, max_pages, max_total_items))
        rows = []
        for request in reversed(requests):
            rows.append({
                "operation_id": request["operation_id"],
                "request_id": request["request_id"],
                "ok": not self.fail,
                "status": "error" if self.fail else "success",
                "data": None if self.fail else {
                    "schema_version": "gravity-insight.read.v1",
                    "operation_id": request["operation_id"],
                    "status": "success",
                    "data": {"list": [{"value": 1}]},
                    "request": {"token": "secret"},
                },
                "error": ({"code": "UPSTREAM_UNAVAILABLE", "category": "upstream",
                           "message": "C:/private/raw exception"} if self.fail else None),
            })
        if self.duplicate and rows:
            rows.append(dict(rows[0]))
        return rows


class DashboardAnalysisTests(unittest.TestCase):
    def test_prepare_compiles_supported_and_isolates_unsupported_without_query(self):
        client = _Client()
        result = prepare_dashboard_analysis(
            client, 17, "Growth", start="2026-08-01", end="2026-08-08", max_items=20
        )
        self.assertEqual((2, 1, 1), (
            result["chart_count"], result["supported_count"], result["unsupported_count"]
        ))
        self.assertEqual("prepared", result["status"])
        self.assertFalse(result["query_executed"])
        self.assertEqual([], client.batch_calls)
        encoded = json.dumps(result).casefold()
        for forbidden in ("calculatebody", "query_item_list", "login", "compiled_input"):
            self.assertNotIn(forbidden, encoded)

    def test_run_batches_supported_charts_in_order_and_sanitizes_failures(self):
        client = _Client([
            {"report_id": "11", "name": "Web only", "subject": "analysis_cash", "config": {}},
            _event_report(),
        ])
        result = run_dashboard_analysis(
            client, 17, 3, start="2026-08-01", end="2026-08-08", max_workers=4,
            max_items=20,
        )
        self.assertEqual(("partial", 1, 1), (
            result["status"], result["success_count"], result["failure_count"]
        ))
        self.assertEqual(4, result["exit_code"])
        self.assertEqual((4, 1), (client.batch_calls[0][1], client.batch_calls[0][2]))
        self.assertFalse(result["charts"][0]["query_executed"])
        self.assertTrue(result["charts"][1]["query_executed"])
        encoded = json.dumps(result).casefold()
        for forbidden in ("request_id", "token", "secret", "inputs", "calculatebody"):
            self.assertNotIn(forbidden, encoded)

        failed = run_dashboard_analysis(
            _Client(fail=True), 17, 3, start="2026-08-01", end="2026-08-08"
        )
        self.assertEqual(("partial", 4, None), (
            failed["status"], failed["exit_code"], failed["charts"][0]["result"]
        ))
        self.assertNotIn("private", json.dumps(failed).casefold())

    def test_identity_and_budget_drift_fail_before_chart_queries(self):
        duplicate = _Client([_event_report("10"), _event_report("10")])
        with self.assertRaises(ContractChangedError):
            run_dashboard_analysis(
                duplicate, 17, 3, start="2026-08-01", end="2026-08-08"
            )
        self.assertEqual([], duplicate.batch_calls)
        bounded = _Client([_event_report(str(index)) for index in range(10)])
        with self.assertRaises(PaginationError):
            prepare_dashboard_analysis(
                bounded, 17, 3, start="2026-08-01", end="2026-08-08",
                max_charts=5, max_items=30,
            )
        self.assertEqual([], bounded.batch_calls)
        capacity = _Client([_event_report(str(index)) for index in range(5)])
        with self.assertRaises(PaginationError):
            run_dashboard_analysis(
                capacity, 17, 3, start="2026-08-01", end="2026-08-08",
                max_items=7,
            )
        self.assertEqual([], capacity.batch_calls)
        with self.assertRaises(RuntimeError):
            run_dashboard_analysis(
                _Client(duplicate=True), 17, 3,
                start="2026-08-01", end="2026-08-08",
            )
        offline = _Client([])
        with self.assertRaises(InputValidationError):
            prepare_dashboard_analysis(
                offline, 17, 3, start="not-a-date", end="2026-08-08"
            )
        self.assertEqual([], offline.read_calls)


if __name__ == "__main__":
    unittest.main()
