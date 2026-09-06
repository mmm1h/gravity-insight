from __future__ import annotations
import copy, importlib, json, unittest

from gravity_insight.errors import InputValidationError, LocalIOError, PaginationError
from gravity_insight.material_performance import (
    MATERIAL_REPORT_OPERATION,
    material_performance,
)
from gravity_insight.material_performance_result import safe_component
from gravity_insight.material_performance_plan_result import sanitize_product_result
from gravity_insight.response_drift import ResponseDriftRecorder

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
    def test_component_contract_failures_identify_the_broken_invariant(self):
        wrong_identity = _failure("error", "CUSTOM_UPSTREAM", "upstream")
        wrong_identity["operation_id"] = "material.report.changed"
        status_type = _failure(None, "CUSTOM_UPSTREAM", "upstream")
        unsafe_error = _failure("error", "CUSTOM_UPSTREAM", [])
        mismatched_error = _failure(
            "parent_required", "CUSTOM_UPSTREAM", "upstream"
        )
        invalid_status = _success("tencent")
        invalid_status.update(ok=False, status="success")
        cases = (
            (None, "component_shape", "$"),
            (
                wrong_identity,
                "component_identity",
                "$.operation_id_or_request_id",
            ),
            (status_type, "component_status_type", "$.status"),
            (unsafe_error, "component_error_shape", "$.error"),
            (
                mismatched_error,
                "component_error_status",
                "$.status_or_error.code",
            ),
            (invalid_status, "component_status", "$.ok_or_status"),
        )
        for value, check, path in cases:
            with self.subTest(check=check):
                result = safe_component(value, "tencent", max_pages=3)
                self.assertEqual("contract_changed", result["status"])
                self.assertEqual(
                    {"check": check, "path": path},
                    result["drift_diagnostics"]["failures"][0],
                )

    def test_upstream_contract_drift_reaches_consumers_without_values(self):
        sentinel = "PRIVATE_MATERIAL_VALUE_MUST_NOT_LEAK"
        recorder = ResponseDriftRecorder()
        recorder.add_breaking_field(
            ("data", "list", "*", "remaining_field"),
            "json_scalar",
            [sentinel],
        )
        drift = recorder.to_contract()
        self.assertIsNotNone(drift)
        inner = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": MATERIAL_REPORT_OPERATION,
            "ok": False,
            "status": "contract_changed",
            "data": {"list": [{"remaining_field": [sentinel]}]},
            "error": {
                "code": "CONTRACT_CHANGED",
                "category": "upstream",
                "message": sentinel,
            },
            "result_audit": {
                "schema_version": "gravity.result-audit.v1",
                "fact_paths": {},
                "http_receipts": [],
                "response_drift": drift,
            },
        }
        raw = {
            "operation_id": MATERIAL_REPORT_OPERATION,
            "request_id": "kuaishou",
            "ok": False,
            "status": "contract_changed",
            "data": inner,
            "error": {
                "code": "CONTRACT_CHANGED",
                "category": "upstream",
                "message": sentinel,
            },
        }

        component = safe_component(raw, "kuaishou", max_pages=3)
        self.assertEqual(
            drift, component["result_audit"]["response_drift"]
        )
        self.assertNotIn("drift_diagnostics", component)
        self.assertNotIn(sentinel, json.dumps(component, sort_keys=True))

        class DriftClient:
            def batch(self, _requests, **_options):
                return [copy.deepcopy(raw)]

        product = material_performance(
            DriftClient(),
            [17],
            "2026-08-01",
            "2026-08-02",
            platforms=("kuaishou",),
            max_pages=3,
            max_items=1,
        )
        self.assertEqual(
            drift, product["results"][0]["result_audit"]["response_drift"]
        )
        self.assertEqual(drift, product["result_audit"]["response_drift"])
        self.assertNotIn(sentinel, json.dumps(product, sort_keys=True))
        plan_result = sanitize_product_result(product)
        self.assertEqual(drift, plan_result["result_audit"]["response_drift"])
        self.assertNotIn(sentinel, json.dumps(plan_result, sort_keys=True))

        poisoned = copy.deepcopy(raw)
        poisoned_drift = poisoned["data"]["result_audit"]["response_drift"]
        poisoned_drift["fields"][0]["value"] = sentinel
        rejected = safe_component(poisoned, "kuaishou", max_pages=3)
        self.assertNotIn("response_drift", rejected["result_audit"])
        self.assertNotIn(sentinel, json.dumps(rejected, sort_keys=True))

    def test_semantic_rejection_code_is_consistent_across_product_sanitizers(self):
        modules = ("advertiser_profile", "company_usage", "custom_audience", "material_performance_result", "order_trace_result", "promotion_performance_error", "title_package")
        policies = [importlib.import_module(f"gravity_insight.{name}")._FAILURE_CODES for name in modules]
        self.assertEqual([{"INPUT_INVALID"}] * 7,
                         [policy["semantic_error"] for policy in policies])
        directory = importlib.import_module("gravity_insight._order_directory_failure")
        self.assertEqual(("INPUT_INVALID", {"INPUT_INVALID"}),
                         (directory._STATUS_CODES["semantic_error"], directory._SPECIAL_STATUS_CODES["semantic_error"]))
        semantic = _failure("semantic_error", "INPUT_INVALID", "caller")
        self.assertEqual("semantic_error", safe_component(semantic, "tencent", max_pages=3)["status"])

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
