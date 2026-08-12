from __future__ import annotations
import copy, unittest

from gravity_sdk.errors import InputValidationError, LocalIOError, PaginationError
from gravity_sdk.material_performance import (
    MATERIAL_REPORT_OPERATION,
    material_performance,
)
from gravity_sdk.material_performance_result import safe_component

def _read_envelope(rows, *, status="success", page=None):
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": MATERIAL_REPORT_OPERATION,
        "status": status,
        "error": None,
        "data": {"list": rows},
        "page": page or {
            "number": 1, "size": 10, "item_count": len(rows),
            "total_pages": 1, "total_items": len(rows), "has_more": False,
            "pages_fetched": 1, "max_workers": 1,
        },
    }

def _success(platform, rows=None, *, status="success", page=None):
    return {
        "operation_id": MATERIAL_REPORT_OPERATION,
        "request_id": platform,
        "ok": True,
        "status": status,
        "data": _read_envelope(
            rows if rows is not None else [{"gravity_material_id": platform}],
            status=status, page=page,
        ),
        "error": None,
    }

def _failure(status, code, category):
    return {
        "operation_id": MATERIAL_REPORT_OPERATION, "request_id": "tencent",
        "ok": False, "status": status, "data": None,
        "error": {"code": code, "category": category},
    }

class _BatchClient:
    def __init__(self, *, rows_per_platform=1):
        self.calls = []
        self.rows_per_platform = rows_per_platform

    def batch(self, requests, **options):
        self.calls.append((copy.deepcopy(requests), dict(options)))
        return [_success(request["request_id"], [{
            "gravity_material_id": f"{request['request_id']}-{index}",
            "file_name": f"asset-{index}.png", "cost": index + 0.5,
        } for index in range(self.rows_per_platform)])
            for request in reversed(requests)]

class MaterialPerformanceTests(unittest.TestCase):
    def test_fans_out_by_platform_with_canonical_bounds_and_order(self):
        client = _BatchClient()
        result = material_performance(
            client, [17, 23], "2026-08-01", "2026-08-07",
            platforms=("tencent", "bytedance"),
            max_workers=6, max_pages=3, max_items=5,
        )
        requests, options = client.calls[0]
        self.assertEqual({
            "max_workers": 2, "max_pages": 3, "max_total_items": 5,
        }, options)
        self.assertEqual(["tencent", "bytedance"], [
            item["request_id"] for item in requests])
        self.assertTrue(all(item["read_all"] for item in requests))
        self.assertEqual(["17", "23"], requests[0]["inputs"]["app_list"])
        self.assertEqual(["tencent", "bytedance"], [
            item["platform"] for item in result["results"]])
        self.assertEqual((2, 2, 1), (
            result["platform_count"], result["returned_items"],
            result["limits"]["page_workers_per_platform"]))

    def test_all_local_rules_fail_before_batch(self):
        cases = (
            {"app_ids": memoryview(b"1")},
            {"app_ids": [17, "017"]},
            {"start": "2026-08-08", "end": "2026-08-07"},
            {"start": "20260801", "end": "20260802"},
            {"start": "2026-W31-6", "end": "2026-W31-7"},
            {"platforms": ("tencent", "tencent")},
            {"max_workers": 25},
            {"max_pages": 0},
            {"max_items": 1, "platforms": ("tencent", "bytedance")},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                client = _BatchClient()
                request = dict(
                    app_ids=[17], start="2026-08-01", end="2026-08-07",
                    platforms=("tencent",), max_workers=6, max_pages=3,
                    max_items=10,
                )
                request.update(overrides)
                with self.assertRaises(InputValidationError):
                    material_performance(client, **request)
                self.assertEqual([], client.calls)

    def test_result_contract_rejects_missing_receipts_status_drift_and_huge_values(self):
        mutations = []
        missing_receipt = _success("tencent")
        del missing_receipt["data"]["page"]["max_workers"]
        mutations.append(missing_receipt)
        contradictory_receipt = _success("tencent")
        contradictory_receipt["data"]["page"].update(
            number=99, size=0, total_pages=0, total_items=0, has_more=True)
        mutations.append(contradictory_receipt)
        huge_receipt = _success("tencent")
        huge_receipt["data"]["page"]["total_items"] = 1 << 20_000
        mutations.append(huge_receipt)
        mutations.extend((
            _success("tencent", [], status="success"),
            _success("tencent", [{"gravity_material_id": "x"}], status="empty"),
            _success("tencent", [{"file_name": "x" * 8_193}]),
            _success("tencent", [{"cost": 1 << 257}]),
            _failure("error", "UPSTREAM_UNAVAILABLE", []),
            _failure("parent_required", "RATE_LIMITED", "upstream"),
            _failure("error", "CONTRACT_CHANGED", "upstream"),
        ))
        for value in mutations:
            with self.subTest(value=value):
                safe = safe_component(value, "tencent", max_pages=3)
                self.assertEqual("contract_changed", safe["status"])
        empty = _success("tencent", [], status="empty", page={
            "number": 1, "size": 10, "item_count": 0,
            "total_pages": 0, "total_items": 0, "has_more": False,
            "pages_fetched": 1, "max_workers": 1,
        })
        self.assertEqual("empty", safe_component(
            empty, "tencent", max_pages=3)["status"])
        empty["data"]["page"]["total_pages"] = False
        self.assertEqual("contract_changed", safe_component(
            empty, "tencent", max_pages=3)["status"])

    def test_builtin_error_categories_cannot_change_plan_exit_semantics(self):
        for status, code, category in (
            ("error", "PARENT_REQUIRED", "upstream"),
            ("error", "LOCAL_IO_ERROR", "caller"),
            ("error", "PARENT_REQUIRED", "caller"),
            ("error", "PERMISSION_UNAVAILABLE", "caller"),
            ("error", "UNSUPPORTED", "caller"),
        ):
            with self.subTest(status=status, code=code, category=category):
                result = safe_component(
                    _failure(status, code, category), "tencent", max_pages=3
                )
                self.assertEqual("contract_changed", result["status"])
        for code, category, retryable, retry_after in (
            ("LOCAL_IO_ERROR", "local", True, None),
            ("RATE_LIMITED", "upstream", False, None),
            ("LOCAL_IO_ERROR", "local", False, 10),
        ):
            value = _failure("error", code, category)
            value["error"].update(
                retryable=retryable, retry_after_ms=retry_after)
            with self.subTest(code=code, retryable=retryable):
                self.assertEqual("contract_changed", safe_component(
                    value, "tencent", max_pages=3)["status"])

    def test_failure_is_safe_and_aggregate_budget_is_rechecked(self):
        class PartialClient:
            def batch(self, requests, **_options):
                return [
                    _success("tencent"),
                    {
                        "operation_id": MATERIAL_REPORT_OPERATION,
                        "request_id": "bytedance",
                        "ok": False,
                        "status": "error",
                        "data": None,
                        "error": {
                            "code": "UPSTREAM_UNAVAILABLE",
                            "category": "upstream",
                            "message": "token=secret C:/private/request.json",
                            "field": "app",
                            "retryable": True,
                        },
                    },
                ]
        result = material_performance(
            PartialClient(), [17], "2026-08-01", "2026-08-02",
            platforms=("tencent", "bytedance"), max_items=2)
        self.assertEqual(("partial", 1, 1), (
            result["status"], result["success_count"], result["failure_count"]))
        self.assertNotIn("secret", repr(result))
        self.assertNotIn("C:/private", repr(result))
        with self.assertRaises(PaginationError):
            material_performance(
                _BatchClient(rows_per_platform=2), [17],
                "2026-08-01", "2026-08-02",
                platforms=("tencent",), max_items=1,
            )
        class UnfairClient:
            def batch(self, _requests, **_options):
                return [
                    _success("tencent", [{"gravity_material_id": str(index)}
                        for index in range(3)]),
                    _success("bytedance", [{"gravity_material_id": "only"}]),
                ]
        with self.assertRaises(PaginationError):
            material_performance(
                UnfairClient(), [17], "2026-08-01", "2026-08-02",
                platforms=("tencent", "bytedance"), max_items=4)

    def test_compatible_batch_exceptions_never_expose_raw_details(self):
        class BrokenClient:
            def batch(self, _requests, **_options):
                raise RuntimeError("token=secret C:/private/request.json")
        with self.assertRaises(LocalIOError) as raised:
            material_performance(
                BrokenClient(), [17], "2026-08-01", "2026-08-02",
                platforms=("tencent",), max_items=1)
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("C:/private", str(raised.exception))
