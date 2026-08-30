from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from gravity_insight import GravityInsightClient
from gravity_insight._field_policy_detail import validate_analysis_detail
from gravity_insight.models import load_operation_manifest
from gravity_insight.order_directory import (
    OPERATION_ID,
    SAFE_ROW_FIELDS,
    order_directory,
    order_directory_item_count,
    sanitize_order_directory_result,
    validate_order_directory_request,
)
from gravity_insight.order_trace import PARENT_FIELDS
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-08-08"
ROW = {
    "CreateTime": "2026-08-08 12:00:00",
    "Amount": 9,
    "BackAmount": 2,
    "Status": "paid",
}


def _read(rows, *, workers=3, status=None):
    selected = status or ("empty" if not rows else "success")
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": OPERATION_ID,
        "status": selected,
        "error": None,
        "data": {"list": copy.deepcopy(rows)},
        "page": {
            "number": 1,
            "size": 100,
            "item_count": len(rows),
            "total_pages": 1,
            "total_items": len(rows),
            "has_more": False,
            "pages_fetched": 1,
            "fetch_strategy": "single_page",
            "max_workers": workers,
        },
    }


class _Client:
    def __init__(self, result):
        self.result, self.calls = result, []

    def read_all(
        self, operation_id, inputs=None, *, max_pages, max_items, max_workers
    ):
        self.calls.append(
            (operation_id, copy.deepcopy(inputs), max_pages, max_items, max_workers)
        )
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class _KwargsClient:
    def __init__(self):
        self.options = None

    def read_all(self, operation_id, inputs=None, **kwargs):
        self.options = kwargs
        return _read([ROW], workers=kwargs["max_workers"])


class _Transport:
    is_test_transport = True

    def __init__(self):
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if not path.endswith("/user/pay_event/list/"):
            raise AssertionError(path)
        body = kwargs["body"]
        self.assert_wire(body)
        page = body["page"]
        row = {**ROW, "Amount": page}
        return TransportResponse(200, {
            "code": 0,
            "data": {"list": [row], "page_info": {
                "page": page, "page_size": 100, "total_page": 2,
                "total_number": 2,
            }},
        }, "2026-08-08T06:00:00Z")

    @staticmethod
    def assert_wire(body):
        if body["field_map"] != list(SAFE_ROW_FIELDS):
            raise AssertionError(body["field_map"])
        expected = [{
            "operator": "RANGE_IN", "field": "create_time", "type": "event",
            "value": [f"{DAY} 00:00:00", f"{DAY} 23:59:59"],
        }]
        if body["global_conditions"] != expected:
            raise AssertionError(body["global_conditions"])


class OrderDirectoryTests(unittest.TestCase):
    def test_real_client_reads_all_pages_with_no_metadata_or_child(self):
        operations = [
            operation
            for path in (ROOT / "src" / "gravity_insight" / "manifests").glob("*.json")
            for operation in json.loads(path.read_text(encoding="utf-8"))["operations"]
        ]
        transport = _Transport()
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": operations}, transport=transport
        )
        result = order_directory(
            client, 7, DAY, max_workers=3, max_pages=5, max_items=10
        )
        self.assertEqual("success", result["status"])
        self.assertEqual([1, 2], [row["Amount"] for row in result["data"]["list"]])
        self.assertEqual(2, result["page"]["pages_fetched"])
        self.assertEqual(2, len(transport.calls))

    def test_page_strategy_receipt_must_be_reachable(self):
        def receipt(rows, strategy, fetched, total_pages, workers):
            value = _read(rows, workers=workers)
            value["page"].update({
                "fetch_strategy": strategy,
                "pages_fetched": fetched,
                "total_pages": total_pages,
            })
            return value

        valid = (
            ([ROW], "single_page", 1, 1, 6),
            ([ROW], "serial_known_total", 2, 2, 6),
            ([ROW], "serial_known_total", 3, 3, 1),
            ([ROW], "parallel_known_total", 3, 3, 6),
            ([ROW], "serial_unknown_total", 1, None, 6),
            ([ROW] * 100, "serial_unknown_total", 2, None, 6),
            ([ROW] * 100, "serial_unknown_total", 2, 2, 6),
        )
        invalid = (
            ([ROW], None, 1, 1, 1),
            ([ROW], "parallel_known_total", 1, 1, 1),
            ([ROW], "single_page", 2, 2, 1),
            ([ROW], "single_page", 1, None, 1),
            ([ROW], "serial_known_total", 3, 3, 6),
            ([ROW], "parallel_known_total", 2, 2, 6),
            ([ROW], "serial_unknown_total", 1, 1, 1),
            ([ROW] * 100, "serial_unknown_total", 1, None, 1),
            ([ROW], "serial_unknown_total", 2, None, 1),
            ([ROW] * 101, "single_page", 1, 1, 1),
            ([ROW] * 100, "serial_unknown_total", 5, None, 1),
        )
        for rows, strategy, fetched, total_pages, workers in valid:
            with self.subTest(valid=strategy, fetched=fetched, workers=workers):
                result = order_directory(
                    _Client(receipt(rows, strategy, fetched, total_pages, workers)),
                    7, DAY, max_workers=workers, max_pages=5, max_items=200,
                )
                self.assertEqual("success", result["status"])
        for rows, strategy, fetched, total_pages, workers in invalid:
            with self.subTest(invalid=strategy, fetched=fetched, workers=workers):
                value = receipt(rows, strategy, fetched, total_pages, workers)
                if strategy is None:
                    value["page"].pop("fetch_strategy")
                result = order_directory(
                    _Client(value), 7, DAY, max_workers=workers,
                    max_pages=5, max_items=200,
                )
                self.assertEqual("contract_changed", result["status"])

        safe = order_directory(
            _Client(_read([ROW], workers=1)), 7, DAY,
            max_workers=1, max_pages=5, max_items=200,
        )
        safe["page"].update({"total_pages": None, "pages_fetched": 2})
        rebuilt = sanitize_order_directory_result(
            safe, "7", DAY, max_pages=5, max_items=200, max_workers=1,
        )
        self.assertEqual("contract_changed", rebuilt["status"])

    def test_exact_request_success_empty_and_validation(self):
        for rows, expected in (([ROW], "success"), ([], "empty")):
            with self.subTest(rows=rows):
                client = _Client(_read(rows, workers=3))
                result = order_directory(
                    client, "007", DAY, max_workers=3, max_pages=5, max_items=10
                )
                self.assertEqual(expected, result["status"])
                self.assertEqual("7", result["app_id"])
                self.assertEqual(len(rows), order_directory_item_count(result))
                call = client.calls[0]
                self.assertEqual(OPERATION_ID, call[0])
                self.assertEqual(list(SAFE_ROW_FIELDS), call[1]["fields"])
                self.assertEqual((5, 10, 3), call[2:])
        invalid = ((True, DAY), (7, "20260808"), (0, DAY))
        for app, day in invalid:
            with self.subTest(app=app, day=day), self.assertRaises(ValueError):
                validate_order_directory_request(app, day)

    def test_var_kwargs_facade_receives_canonical_complete_read_limits(self):
        client = _KwargsClient()
        result = order_directory(
            client, 7, DAY, max_workers=1, max_pages=5, max_items=10
        )
        self.assertEqual("success", result["status"])
        self.assertEqual(
            {"max_workers": 1, "max_pages": 5, "max_items": 10},
            client.options,
        )

    def test_read_contract_drift_and_sensitive_rows_fail_closed(self):
        cases = []
        for field, value in (
            ("schema_version", "other"),
            ("operation_id", "analysis.user_detail.list"),
            ("status", "mystery"),
            ("truncated", True),
            ("truncated", 0),
            ("error", {}),
            ("next_page_input", {}),
            ("next_page_input", {"TraceID": "secret"}),
        ):
            candidate = _read([ROW], workers=1)
            candidate[field] = value
            cases.append(candidate)
        for key, value in (
            ("has_more", True), ("item_count", 2), ("total_items", 2),
            ("max_workers", 2),
            ("fetch_strategy", []),
        ):
            candidate = _read([ROW], workers=1)
            candidate["page"][key] = value
            cases.append(candidate)
        for row in (
            {**ROW, "TraceID": "secret"},
            {**ROW, "Amount": math.inf},
            {**ROW, "Status": "x" * 8_193},
            {**ROW, "CreateTime": "2026-09-01 00:00:00"},
            {**ROW, "CreateTime": f"{DAY} nonsense"},
            {**ROW, "CreateTime": None},
            {key: value for key, value in ROW.items() if key != "Status"},
        ):
            cases.append(_read([row], workers=1))
        for candidate in cases:
            with self.subTest(candidate=candidate):
                result = order_directory(
                    _Client(candidate), 7, DAY, max_workers=1,
                    max_pages=5, max_items=10,
                )
                self.assertEqual("contract_changed", result["status"])
                self.assertEqual([], result["data"]["list"])
                self.assertNotIn("secret", repr(result))

    def test_native_failures_are_fixed_and_value_free(self):
        class BrokenDetail(RuntimeError):
            def to_error_detail(self):
                raise RuntimeError("TraceID secondary-secret")

        local = order_directory(
            _Client(RuntimeError("TraceID secret")), 7, DAY, max_workers=1
        )
        self.assertEqual("LOCAL_IO_ERROR", local["error"]["code"])
        self.assertNotIn("secret", repr(local))
        broken = order_directory(_Client(BrokenDetail("primary-secret")), 7, DAY)
        self.assertEqual("LOCAL_IO_ERROR", broken["error"]["code"])
        self.assertNotIn("secret", repr(broken))
        unavailable = _read([], workers=1)
        unavailable.update({
            "status": "permission_unavailable",
            "error": {"code": "PERMISSION_UNAVAILABLE", "message": "secret"},
        })
        result = order_directory(_Client(unavailable), 7, DAY, max_workers=1)
        self.assertEqual("PERMISSION_UNAVAILABLE", result["error"]["code"])
        mismatch = copy.deepcopy(unavailable)
        mismatch["error"]["code"] = "RATE_LIMITED"
        self.assertEqual(
            "contract_changed",
            order_directory(_Client(mismatch), 7, DAY, max_workers=1)["status"],
        )

    def test_request_bound_sanitizer_rebuilds_or_rejects(self):
        valid = order_directory(
            _Client(_read([ROW], workers=1)), 7, DAY, max_workers=1,
            max_pages=5, max_items=10,
        )
        sanitized = lambda value: sanitize_order_directory_result(
            value, "7", DAY, max_pages=5, max_items=10, max_workers=1
        )
        self.assertEqual(valid, sanitized(valid))
        mutations = []
        for path, value in (
            (("app_id",), "8"),
            (("limits", "max_items"), 11),
            (("returned_items",), 2),
            (("page", "pages_fetched"), 6),
            (("page", "total_items"), 2),
        ):
            forged = copy.deepcopy(valid)
            target = forged
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            mutations.append(forged)
        extra = copy.deepcopy(valid)
        extra["request"] = {"TraceID": "secret"}
        mutations.append(extra)
        for forged in mutations:
            with self.subTest(forged=forged):
                rebuilt = sanitized(forged)
                self.assertEqual("contract_changed", rebuilt["status"])
                self.assertNotIn("secret", repr(rebuilt))

        failed = order_directory(_Client(RuntimeError("secret")), 7, DAY,
                                 max_workers=1, max_pages=5, max_items=10)
        for path, value in (
            (("status",), []),
            (("returned_items",), False),
            (("error", "field"), []),
            (("error", "field"), "contract"),
            (("error", "retry_after_ms"), []),
            (("error", "retry_after_ms"), 1 << 40),
        ):
            forged = copy.deepcopy(failed)
            target = forged
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path, value=value):
                self.assertEqual("contract_changed", sanitized(forged)["status"])

        for status in ([], {}, ["success"]):
            forged = copy.deepcopy(valid)
            forged["status"] = status
            with self.subTest(item_count_status=status):
                self.assertEqual(0, order_directory_item_count(forged))

    def test_field_policy_fast_path_is_exact_and_data_driven(self):
        operation = next(
            item for item in load_operation_manifest(
                ROOT / "src" / "gravity_insight" / "manifests" / "analysis.json"
            ) if item.operation_id == OPERATION_ID
        )
        calls = []
        base = {"app_id": "7", "date": DAY, "page": 2, "page_size": 100}
        for fields in (SAFE_ROW_FIELDS, PARENT_FIELDS):
            validate_analysis_detail(
                operation, {**base, "fields": list(fields)},
                lambda *args: calls.append(args),
            )
        self.assertEqual([], calls)
        for fields in (
            [*SAFE_ROW_FIELDS, "TraceID"],
            [*SAFE_ROW_FIELDS, SAFE_ROW_FIELDS[0]],
        ):
            validate_analysis_detail(
                operation, {**base, "fields": fields},
                lambda *args: calls.append(args)
                or {"status": "empty", "data": {"list": []}},
            )
        self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
