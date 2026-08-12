from __future__ import annotations

import copy
import unittest
from pathlib import Path

from gravity_sdk._field_policy_detail import validate_analysis_detail
from gravity_sdk.models import load_operation_manifest
from gravity_sdk.order_trace import (
    CHILD_OPERATION_ID,
    PARENT_FIELDS,
    PARENT_OPERATION_ID,
    order_split_trace,
    sanitize_order_split_trace_result,
    validate_order_split_trace_request,
)


ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-08-08"


def _parent(rows, *, workers=3, status=None):
    selected = status or ("empty" if not rows else "success")
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": PARENT_OPERATION_ID,
        "status": selected,
        "error": None,
        "data": {"list": copy.deepcopy(rows)},
        "page": {
            "number": 1, "size": 100, "item_count": len(rows),
            "total_pages": 1, "total_items": len(rows), "has_more": False,
            "pages_fetched": 1, "max_workers": workers,
        },
    }


def _child(rows, *, status=None):
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": CHILD_OPERATION_ID,
        "status": status or ("empty" if not rows else "success"),
        "error": None,
        "data": copy.deepcopy(rows),
    }


def _row(trace="parent-1", splits=None):
    return {
        "TraceID": trace,
        "PayEventTime": "2026-08-08 12:00:00",
        "ClientID": "private-client",
        "$split_trace_id_list": splits or ["split-1"],
    }


class _Client:
    def __init__(self, parent, child=None):
        self.parent = parent
        self.child = child or _child([])
        self.calls = []

    def read_all(self, operation_id, inputs=None, **options):
        self.calls.append((operation_id, copy.deepcopy(inputs), dict(options)))
        return copy.deepcopy(self.parent)

    def read(self, operation_id, inputs=None):
        self.calls.append((operation_id, copy.deepcopy(inputs), {}))
        return copy.deepcopy(self.child)


class _ExplodingClient(_Client):
    def read_all(self, operation_id, inputs=None, **options):
        raise RuntimeError("parent-secret client-secret")


class OrderSplitTraceTests(unittest.TestCase):
    def test_success_derives_child_once_and_drops_every_identifier(self):
        client = _Client(
            _parent([_row()], workers=3),
            _child([{
                "TraceID": "split-1", "Amount": 9, "BackAmount": 2,
                "Status": "paid", "CreateTime": "2026-08-08 12:01:00",
            }]),
        )
        result = order_split_trace(
            client, 7, DAY, "parent-1", max_workers=3,
            max_pages=5, max_items=10,
        )
        self.assertTrue(result["ok"])
        self.assertEqual([{
            "Amount": 9, "BackAmount": 2, "Status": "paid",
            "CreateTime": "2026-08-08 12:01:00",
        }], result["data"]["list"])
        child = client.calls[1][1]
        self.assertEqual("private-client", child["client_id"])
        self.assertEqual(["split-1"], child["split_trace_ids"])
        rendered = repr(result)
        for secret in ("parent-1", "private-client", "split-1", "PayEventTime"):
            self.assertNotIn(secret, rendered)

    def test_empty_ambiguous_and_budget_paths_never_call_child(self):
        cases = (
            (_parent([], workers=1), "missing", 10, True),
            (_parent([_row(), _row()], workers=1), "parent-1", 10, False),
            (_parent([_row(splits=["a", "b"])], workers=1), "parent-1", 2, False),
        )
        for parent, trace, items, expected_ok in cases:
            with self.subTest(trace=trace, items=items):
                client = _Client(parent)
                result = order_split_trace(
                    client, "7", DAY, trace, max_workers=1,
                    max_pages=5, max_items=items,
                )
                self.assertEqual(expected_ok, result["ok"])
                self.assertEqual(1, len(client.calls))

    def test_parent_and_child_contract_drift_fail_closed(self):
        malformed_parent = _parent([_row()], workers=1)
        malformed_parent["page"]["has_more"] = True
        first = _Client(malformed_parent)
        self.assertEqual(
            "contract_changed",
            order_split_trace(first, 7, DAY, "parent-1", max_workers=1)["status"],
        )
        self.assertEqual(1, len(first.calls))

        second = _Client(
            _parent([_row()], workers=1),
            _child([{
                "TraceID": "wrong", "Amount": 1, "BackAmount": 0,
                "Status": "paid", "CreateTime": DAY,
            }]),
        )
        result = order_split_trace(second, 7, DAY, "parent-1", max_workers=1)
        self.assertEqual("contract_changed", result["status"])
        self.assertNotIn("wrong", repr(result))

        for status in ([], "mystery", "contract_changed_additive"):
            with self.subTest(status=status):
                malformed = _parent([_row()], workers=1)
                malformed["status"] = status
                result = order_split_trace(
                    _Client(malformed), 7, DAY, "parent-1", max_workers=1,
                )
                self.assertEqual("contract_changed", result["status"])

        incomplete = _child([{
            "TraceID": "split-1", "Amount": 1, "BackAmount": 0,
            "Status": "paid", "CreateTime": DAY,
        }])
        incomplete["truncated"] = True
        incomplete["next_page_input"] = {"private": "split-1"}
        result = order_split_trace(
            _Client(_parent([_row()], workers=1), incomplete),
            7, DAY, "parent-1", max_workers=1,
        )
        self.assertEqual("contract_changed", result["status"])
        self.assertNotIn("split-1", repr(result))

    def test_known_native_failure_status_keeps_safe_builtin_semantics(self):
        parent = _parent([], workers=1)
        parent.update({"status": "parent_required", "error": {}})
        result = order_split_trace(
            _Client(parent), 7, DAY, "parent-1", max_workers=1,
        )
        self.assertEqual("PARENT_REQUIRED", result["error"]["code"])
        self.assertEqual(2, result["exit_code"])
        local = order_split_trace(
            _ExplodingClient(_parent([], workers=1)),
            7, DAY, "parent-1", max_workers=1,
        )
        self.assertEqual("LOCAL_IO_ERROR", local["error"]["code"])
        self.assertNotIn("secret", repr(local).lower())
        mismatch = _parent([], workers=1)
        mismatch.update({
            "status": "parent_required",
            "error": {"code": "RATE_LIMITED"},
        })
        self.assertEqual(
            "contract_changed",
            order_split_trace(
                _Client(mismatch), 7, DAY, "parent-1", max_workers=1,
            )["status"],
        )

    def test_parent_inputs_and_child_values_are_never_normalized_or_echoed(self):
        bad_time, bad_split = _row(), _row()
        bad_time["PayEventTime"] = "not-a-time"
        bad_split["$split_trace_id_list"] = [1]
        leaking_child = _child([{
            "TraceID": "split-1", "Amount": 1, "BackAmount": 0,
            "Status": "parent-1", "CreateTime": DAY,
        }])
        cases = (
            (_parent([_row(trace=" parent-1 ")], workers=1), _child([])),
            (_parent([bad_time], workers=1), _child([])),
            (_parent([bad_split], workers=1), _child([])),
            (_parent([_row()], workers=1), leaking_child),
        )
        for parent, child in cases:
            result = order_split_trace(
                _Client(parent, child), 7, DAY, "parent-1", max_workers=1,
            )
            self.assertEqual("contract_changed", result["status"])
            self.assertNotIn("parent-1", repr(result))

    def test_request_and_plan_resanitizer_are_strict(self):
        for values in (
            (True, DAY, "x"), (7, "20260808", "x"), (7, DAY, "\n"),
            (7, DAY, " x "),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_order_split_trace_request(*values)
        valid = order_split_trace(
            _Client(_parent([], workers=1)), 7, DAY, "x", max_workers=1,
            max_pages=5, max_items=10,
        )
        valid["app_id"] = "8"
        safe = sanitize_order_split_trace_result(
            valid, "7", DAY, max_pages=5, max_items=10, max_workers=1,
        )
        self.assertEqual("contract_changed", safe["status"])

        forged = order_split_trace(
            _Client(_parent([_row()], workers=1), _child([])),
            7, DAY, "parent-1", max_workers=1, max_pages=5, max_items=10,
        )
        forged["split_id_count"] = 10
        self.assertEqual(
            "contract_changed",
            sanitize_order_split_trace_result(
                forged, "7", DAY, max_pages=5, max_items=10, max_workers=1,
            )["status"],
        )
        valid_failure = order_split_trace(
            _ExplodingClient(_parent([], workers=1)),
            7, DAY, "x", max_workers=1, max_pages=5, max_items=10,
        )
        valid_failure["stages"] = {"parent": "success", "child": "success"}
        self.assertEqual(
            "contract_changed",
            sanitize_order_split_trace_result(
                valid_failure, "7", DAY,
                max_pages=5, max_items=10, max_workers=1,
            )["status"],
        )

    def test_exact_static_parent_skips_metadata_but_nearby_request_does_not(self):
        operation = next(
            item for item in load_operation_manifest(
                ROOT / "src" / "gravity_sdk" / "manifests" / "analysis.json"
            ) if item.operation_id == PARENT_OPERATION_ID
        )
        calls = []
        exact = {
            "app_id": "7", "date": DAY, "fields": list(PARENT_FIELDS),
            "page": 1, "page_size": 100,
        }
        validate_analysis_detail(operation, exact, lambda *args: calls.append(args))
        self.assertEqual([], calls)
        validate_analysis_detail(
            operation, {**exact, "page": 2}, lambda *args: calls.append(args)
        )
        self.assertEqual([], calls)
        nearby = {**exact, "fields": [*PARENT_FIELDS, "Amount"]}
        validate_analysis_detail(
            operation, nearby,
            lambda *args: calls.append(args) or {"status": "empty", "data": {"list": []}},
        )
        self.assertTrue(calls)
        with self.assertRaises(ValueError):
            validate_analysis_detail(
                operation, {**exact, "date": "2026-99-99"},
                lambda *args: calls.append(args),
            )


if __name__ == "__main__":
    unittest.main()
