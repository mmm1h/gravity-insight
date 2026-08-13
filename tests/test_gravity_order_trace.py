from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from gravity_sdk._field_policy_detail import validate_analysis_detail
from gravity_sdk import GravityInsightClient
from gravity_sdk.models import load_operation_manifest
from gravity_sdk.order_trace import (
    CHILD_OPERATION_ID,
    PARENT_FIELDS,
    PARENT_OPERATION_ID,
    order_split_trace,
    sanitize_order_split_trace_result,
    validate_order_split_trace_request,
)
from gravity_sdk.transport import TransportResponse


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
            "pages_fetched": 1, "fetch_strategy": "single_page",
            "max_workers": workers,
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


class _RoutingTransport:
    is_test_transport = True

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return TransportResponse(
            200, self.handler(path, kwargs), "2026-08-08T06:00:00Z"
        )


class OrderSplitTraceTests(unittest.TestCase):
    def test_real_client_reads_every_parent_page_then_one_child_without_metadata(self):
        def handler(path, kwargs):
            if path.endswith("/pay_event/list/"):
                page = kwargs["body"]["page"]
                row = _row("other" if page == 1 else "parent-1")
                return {"code": 0, "data": {"list": [row], "page_info": {
                    "page": page, "page_size": 100, "total_page": 2,
                    "total_number": 2,
                }}}
            if path.endswith("/split_order_detail/"):
                return {"code": 0, "data": [{
                    "TraceID": "split-1", "Amount": 9, "BackAmount": 0,
                    "Status": "paid", "CreateTime": f"{DAY} 12:01:00",
                }]}
            raise AssertionError(path)
        operations = [operation for path in (ROOT / "src" / "gravity_sdk" / "manifests").glob("*.json")
                      for operation in json.loads(path.read_text(encoding="utf-8"))["operations"]]
        transport = _RoutingTransport(handler)
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": operations}, transport=transport,
        )
        result = order_split_trace(client, 7, DAY, "parent-1", max_workers=3,
                                   max_pages=5, max_items=10)
        self.assertEqual("success", result["status"])
        self.assertEqual(3, len(transport.calls))
        self.assertEqual(2, sum(path.endswith("/pay_event/list/") for _, path, _ in transport.calls))

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

        for strategy, fetched, total_pages, workers in (
            (None, 1, 1, 1),
            ("parallel_known_total", 1, 1, 1),
            ("single_page", 2, 2, 1),
            ("serial_known_total", 3, 3, 6),
        ):
            with self.subTest(strategy=strategy):
                parent = _parent([_row()], workers=workers)
                parent["page"].update({
                    "fetch_strategy": strategy,
                    "pages_fetched": fetched,
                    "total_pages": total_pages,
                })
                if strategy is None:
                    parent["page"].pop("fetch_strategy")
                client = _Client(parent)
                result = order_split_trace(
                    client, 7, DAY, "parent-1", max_workers=workers,
                    max_pages=5, max_items=10,
                )
                self.assertEqual("contract_changed", result["status"])
                self.assertEqual(1, len(client.calls))

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

        for truncated in (0, 0.0):
            with self.subTest(truncated=truncated):
                malformed = _parent([_row()], workers=1)
                malformed["truncated"] = truncated
                self.assertEqual(
                    "contract_changed",
                    order_split_trace(
                        _Client(malformed), 7, DAY, "parent-1", max_workers=1,
                    )["status"],
                )

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
        def sanitized(value, items=10):
            return sanitize_order_split_trace_result(
                value, "7", DAY, max_pages=5, max_items=items, max_workers=1,
            )
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
        self.assertEqual("contract_changed", sanitized(valid)["status"])

        forged = order_split_trace(
            _Client(_parent([_row()], workers=1), _child([])),
            7, DAY, "parent-1", max_workers=1, max_pages=5, max_items=10,
        )
        unreachable = {**forged, "scanned_items": 0}
        self.assertEqual("contract_changed", sanitized(unreachable)["status"])
        forged["split_id_count"] = 10
        self.assertEqual(
            "contract_changed",
            sanitized(forged)["status"],
        )
        valid_failure = order_split_trace(
            _ExplodingClient(_parent([], workers=1)),
            7, DAY, "x", max_workers=1, max_pages=5, max_items=10,
        )
        valid_failure["stages"] = {"parent": "success", "child": "success"}
        self.assertEqual(
            "contract_changed",
            sanitized(valid_failure)["status"],
        )
        for scanned, split_ids in ((0, 1), (9, 10)):
            forged_failure = copy.deepcopy(valid_failure)
            forged_failure.update({"scanned_items": scanned, "split_id_count": split_ids,
                                   "stages": {"parent": "success", "child": "error"}})
            forged_failure["error"]["field"] = "child"
            self.assertEqual("contract_changed", sanitized(forged_failure)["status"])
        budget_failure = order_split_trace(
            _Client(_parent([_row(splits=["a", "b"])], workers=1)),
            7, DAY, "parent-1", max_workers=1, max_pages=5, max_items=2,
        )
        self.assertEqual(
            "PAGINATION_LIMIT",
            sanitized(budget_failure, 2)["error"]["code"],
        )
        unreachable_budget = copy.deepcopy(budget_failure)
        unreachable_budget.update({"scanned_items": 0, "limits": {**budget_failure["limits"], "max_items": 1}})
        self.assertEqual("contract_changed", sanitized(unreachable_budget, 1)["status"])
        for malformed_status in ([], {}):
            malformed = copy.deepcopy(budget_failure)
            malformed["status"] = malformed_status
            self.assertEqual(
                "contract_changed",
                sanitized(malformed, 2)["status"],
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
