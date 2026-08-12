from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from gravity_sdk.composite import CompositeService
from gravity_sdk.domains import PROMOTION_PRIMARY_OPERATIONS
from gravity_sdk.errors import (
    GravityInsightError, InputValidationError, LocalIOError, PaginationError)
from gravity_sdk.promotion_performance import (
    PROMOTION_PLATFORM_OPERATIONS,
    SUPPORTED_PLATFORMS,
    promotion_performance,
    promotion_performance_input_schema,
)
from gravity_sdk.promotion_performance_result import (
    PROMOTION_ROW_FIELDS,
    safe_component,
)


def _safe(value, metrics=("stat_cost",)):
    return safe_component(value, "tencent", metrics=metrics, expected_app_id="17", expected_window=("2026-08-01", "2026-08-07"), max_pages=3)


def _read_envelope(operation_id, rows, *, status="success", page=None):
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": operation_id,
        "status": status,
        "error": None,
        "data": {"list": rows},
        "page": page
        or {
            "number": 1,
            "size": 10,
            "item_count": len(rows),
            "total_pages": 1,
            "total_items": len(rows),
            "has_more": False,
            "pages_fetched": 1,
            "max_workers": 1,
        },
    }


def _success(platform, rows=None, *, status="success", page=None):
    operation_id = PROMOTION_PLATFORM_OPERATIONS[platform]
    return {
        "operation_id": operation_id,
        "request_id": platform,
        "ok": True,
        "status": status,
        "data": _read_envelope(
            operation_id,
            rows if rows is not None else [{"stat_cost": 1.5}],
            status=status,
            page=page,
        ),
        "error": None,
    }


class _BatchClient:
    def __init__(self, *, rows_per_platform=1):
        self.calls = []
        self.rows_per_platform = rows_per_platform

    def batch(self, requests, **options):
        self.calls.append((copy.deepcopy(requests), dict(options)))
        return [
            _success(
                request["request_id"],
                [
                    {
                        "advertiser_id": f"account-{index}",
                        "stat_cost": index + 0.5,
                    }
                    for index in range(self.rows_per_platform)
                ],
            )
            for request in reversed(requests)
        ]


class PromotionPerformanceTests(unittest.TestCase):
    def test_fans_out_real_operations_with_fair_bounds_and_order(self):
        client = _BatchClient()
        result = promotion_performance(
            client,
            "017",
            "2026-08-01",
            "2026-08-07",
            platforms=("tencent", "bytedance"),
            metrics=("stat_cost",),
            max_workers=6,
            max_pages=3,
            max_items=5,
        )
        requests, options = client.calls[0]
        self.assertEqual(
            {"max_workers": 2, "max_pages": 3, "max_total_items": 5},
            options,
        )
        self.assertEqual(
            ["tencent", "bytedance"],
            [item["request_id"] for item in requests],
        )
        self.assertEqual(
            [PROMOTION_PLATFORM_OPERATIONS["tencent"],
             PROMOTION_PLATFORM_OPERATIONS["bytedance"]],
            [item["operation_id"] for item in requests],
        )
        for request in requests:
            self.assertTrue(request["read_all"])
            self.assertEqual(
                {
                    "date_list": ["2026-08-01", "2026-08-07"],
                    "query_fields": ["stat_cost"],
                    "filters": [
                        {"field": "app_id", "operator": 1, "values": ["17"]}
                    ],
                    "page": 1,
                    "page_size": 10,
                },
                request["inputs"],
            )
        self.assertEqual(
            ["tencent", "bytedance"],
            [item["platform"] for item in result["results"]],
        )
        self.assertEqual("gravity-insight.promotion-performance.v1", result["schema_version"])
        self.assertEqual(("17", 2, 1, 2), (
            result["app_id"], result["platform_count"],
            result["metric_count"], result["returned_items"],
        ))
        self.assertNotIn("metrics", result)
        self.assertEqual(2, result["limits"]["max_items_per_platform"])
        self.assertEqual(1, result["limits"]["page_workers_per_platform"])

    def test_closed_platform_map_and_projection_match_stable_contracts(self):
        self.assertEqual(21, len(SUPPORTED_PLATFORMS))
        self.assertEqual(set(SUPPORTED_PLATFORMS), set(PROMOTION_PLATFORM_OPERATIONS))
        self.assertTrue(
            set(SUPPORTED_PLATFORMS).isdisjoint(
                {"bing", "xiaohongshu", "taptap", "wechat_video"}
            )
        )
        contracts = Path(__file__).parents[1] / "src" / "gravity_sdk" / "contracts" / "operations"
        for platform in SUPPORTED_PLATFORMS:
            operation_id = PROMOTION_PLATFORM_OPERATIONS[platform]
            with self.subTest(platform=platform):
                self.assertEqual(PROMOTION_PRIMARY_OPERATIONS[platform], operation_id)
                operation = json.loads(
                    (contracts / f"{operation_id}.json").read_text(encoding="utf-8")
                )["operation"]
                self.assertEqual(
                    set(operation["response_projection"]["item_keys"]),
                    set(PROMOTION_ROW_FIELDS[platform]),
                )
                self.assertEqual(
                    ["query_fields"],
                    operation["response_projection"]["dynamic_item_fields"],
                )
                self.assertEqual("page_info", operation["pagination"]["kind"])

    def test_all_local_rules_fail_before_batch(self):
        cases = (
            {"app_id": True},
            {"app_id": "0"},
            {"app_id": " 17 "},
            {"app_id": 1 << 20_000},
            {"app_id": "1" * 129},
            {"start": "2026-08-08", "end": "2026-08-07"},
            {"start": "20260801", "end": "20260802"},
            {"start": "2026-W31-6", "end": "2026-W31-7"},
            {"platforms": ("tencent", "tencent")},
            {"platforms": ("bing",)},
            {"metrics": ("app_id",)},
            {"metrics": ("phone",)},
            *({"metrics": (name,)} for name in (
                "authorization_header", "api_key", "access_key", "private_key",
                "client_secret", "session_cookie", "credentials", "credential_id",
                "session_key", "access_secret", "signing_key", "accessToken",
                "apiSecret", "clientPassword", "callbackUrl")),
            {"metrics": ("metric", "metric")},
            {"metrics": ()},
            {"max_workers": 25},
            {"max_pages": 0},
            {"max_items": 1, "platforms": ("tencent", "bytedance")},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                client = _BatchClient()
                request = dict(
                    app_id=17,
                    start="2026-08-01",
                    end="2026-08-07",
                    platforms=("tencent",),
                    metrics=("stat_cost",),
                    max_workers=6,
                    max_pages=3,
                    max_items=10,
                )
                request.update(overrides)
                with self.assertRaises(InputValidationError):
                    promotion_performance(client, **request)
                self.assertEqual([], client.calls)

    def test_result_contract_rejects_identity_rows_and_receipt_drift(self):
        mutations = []
        wrong_operation = _success("tencent")
        wrong_operation["operation_id"] = PROMOTION_PLATFORM_OPERATIONS["bytedance"]
        mutations.append(wrong_operation)
        injected = _success("tencent", [{"stat_cost": 1, "secret": "token"}])
        mutations.append(injected)
        missing_receipt = _success("tencent")
        del missing_receipt["data"]["page"]["max_workers"]
        mutations.append(missing_receipt)
        contradictory = _success("tencent")
        contradictory["data"]["page"].update(
            number=2, size=0, total_pages=0, total_items=0, has_more=True
        )
        mutations.append(contradictory)
        huge = _success("tencent")
        huge["data"]["page"]["total_items"] = 1 << 20_000
        mutations.append(huge)
        for field, bad_value in (
            ("size", 999), ("total_pages", 999), ("total_items", 999),
            ("total_items", []), ("total_items", {}), ("total_items", False)):
            malformed = _success("tencent")
            malformed["data"]["page"][field] = bad_value
            mutations.append(malformed)
        contradictory_empty = _success(
            "tencent", [], status="empty", page={
                "number": 1, "size": 10, "item_count": 0, "total_pages": 2,
                "total_items": 0, "has_more": False, "pages_fetched": 1,
                "max_workers": 1},
        )
        mutations.append(contradictory_empty)
        mutations.extend(
            (
                _success("tencent", [], status="success"),
                _success("tencent", [{"stat_cost": 1}], status="empty"),
                _success("tencent", [{"stat_cost": float("nan")}]), dict(_success("tencent"), error={"code": "CONTRACT_CHANGED"}),
            )
        )
        for value in mutations:
            with self.subTest(value=value):
                safe = _safe(value)
                self.assertEqual("contract_changed", safe["status"])
                self.assertFalse(safe["window_applied"])
        empty = _success("tencent", [], status="empty", page={
            "number": 1, "size": 10, "item_count": 0, "total_pages": 0,
            "total_items": 0, "has_more": False, "pages_fetched": 1,
            "max_workers": 1})
        self.assertEqual("empty", _safe(empty)["status"])
        optional_totals = _success("tencent")
        optional_totals["data"]["page"].update(total_pages=None, total_items=None)
        empty_one = copy.deepcopy(empty); empty_one["data"]["page"]["total_pages"] = 1
        two_pages = _success("tencent", [{"stat_cost": index} for index in range(11)], page={
            "number": 1, "size": 10, "item_count": 11, "total_pages": 2,
            "total_items": 11, "has_more": False, "pages_fetched": 2, "max_workers": 1})
        for expected, value in (("success", optional_totals), ("empty", empty_one),
                                ("success", two_pages)):
            self.assertEqual(expected, _safe(value)["status"])
        for field, value in (("app_id", "18"), ("date", "2026-08-08"), ("day", "20260801"), ("stat_date", "2026-07-31")):
            self.assertEqual("contract_changed", _safe(_success("tencent", [{"stat_cost": 1, field: value}]), ("stat_cost", field) if field == "stat_date" else ("stat_cost",))["status"])

        unknown_code = {"operation_id": PROMOTION_PLATFORM_OPERATIONS["tencent"], "request_id": "tencent",
            "ok": False, "status": "error", "data": None, "error": {
                "code": "SECRET_TOKEN_LEAK", "category": "local", "retryable": False}}
        safe = _safe(unknown_code)
        self.assertEqual("contract_changed", _safe(unknown_code)["status"])
        self.assertNotIn("SECRET_TOKEN_LEAK", repr(safe))

        missing = copy.deepcopy(unknown_code)
        missing["error"]["code"] = "BATCH_RESULT_MISSING"
        self.assertEqual("error", _safe(missing)["status"])

    def test_partial_error_is_sanitized_and_preserves_primary_exit(self):
        class PartialClient:
            def batch(self, requests, **_options):
                return [
                    _success("tencent"),
                    {
                        "operation_id": PROMOTION_PLATFORM_OPERATIONS["bytedance"],
                        "request_id": "bytedance",
                        "ok": False,
                        "status": "error",
                        "data": None,
                        "error": {
                            "code": "UPSTREAM_UNAVAILABLE",
                            "category": "upstream",
                            "message": "token=secret C:/private/request.json",
                            "field": "app_id",
                            "retryable": True,
                        },
                    },
                ]

        result = promotion_performance(
            PartialClient(),
            17,
            "2026-08-01",
            "2026-08-02",
            platforms=("tencent", "bytedance"),
            metrics=("stat_cost",),
            max_items=2,
        )
        self.assertEqual(("partial", 3, 1, 1), (
            result["status"], result["exit_code"],
            result["success_count"], result["failure_count"],
        ))
        self.assertIsNotNone(result["error"])
        self.assertNotIn("secret", repr(result))
        self.assertNotIn("C:/private", repr(result))
        self.assertEqual("result", result["results"][1]["error"]["field"])

    def test_budget_rechecks_compatible_clients_and_local_errors_are_safe(self):
        with self.assertRaises(PaginationError):
            promotion_performance(
                _BatchClient(rows_per_platform=2),
                17,
                "2026-08-01",
                "2026-08-02",
                platforms=("tencent",),
                metrics=("stat_cost",),
                max_items=1,
            )

        class UnfairClient:
            def batch(self, _requests, **_options):
                return [
                    _success("tencent", [{"stat_cost": index} for index in range(3)]),
                    _success("bytedance", [{"stat_cost": 1}]),
                ]

        with self.assertRaises(PaginationError):
            promotion_performance(
                UnfairClient(),
                17,
                "2026-08-01",
                "2026-08-02",
                platforms=("tencent", "bytedance"),
                metrics=("stat_cost",),
                max_items=4,
            )

        class BrokenClient:
            def batch(self, _requests, **_options):
                raise RuntimeError("token=secret C:/private/request.json")

        with self.assertRaises(LocalIOError) as raised:
            promotion_performance(
                BrokenClient(),
                17,
                "2026-08-01",
                "2026-08-02",
                platforms=("tencent",),
                metrics=("stat_cost",),
                max_items=1,
            )
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("C:/private", str(raised.exception))

        class ExtensionErrorClient:
            def batch(self, *_args, **_options):
                raise GravityInsightError("token=secret", code="SECRET_TOKEN_LEAK")

        with self.assertRaises(Exception) as raised:
            promotion_performance(ExtensionErrorClient(), 17, "2026-08-01", "2026-08-02",
                platforms=("tencent",), metrics=("stat_cost",), max_items=1)
        self.assertNotIn("SECRET_TOKEN_LEAK", repr(raised.exception))
        self.assertEqual("LOCAL_IO_ERROR", raised.exception.to_error_detail().code)

    def test_input_schema_is_closed_and_legacy_snapshot_stays_compatible(self):
        schema = promotion_performance_input_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(21, schema["properties"]["platforms"]["maxItems"])

        capabilities = {
            "taptap": ("group", "promotion.taptap.group.list"),
            "wechat_video": ("report", "promotion.wechat_video.report.list"),
        }

        class Client:
            def operations(self, **filters):
                resource, operation_id = capabilities[filters["platform"]]
                return [{
                    "operation_id": operation_id,
                    "domain": "promotion",
                    "platform": filters["platform"],
                    "resource": resource,
                    "action": "list",
                    "stability": "stable",
                }]

            def batch(self, requests, **_options):
                self.requests = list(requests)
                return [{
                    "operation_id": item["operation_id"],
                    "request_id": item["request_id"],
                    "ok": True,
                    "status": "success",
                } for item in requests]

            def schema(self, *_args, **_kwargs):
                return {}

            def read(self, *_args, **_kwargs):
                return {}

            def read_all(self, *_args, **_kwargs):
                return {}

        client = Client()
        result = CompositeService(client).promotion_snapshot(list(capabilities))
        self.assertEqual("gravity-insight.composite.promotion.v1", result["schema_version"])
        self.assertEqual("success", result["status"])
        self.assertEqual(
            list(capabilities), [item["platform"] for item in result["results"]]
        )


if __name__ == "__main__":
    unittest.main()
