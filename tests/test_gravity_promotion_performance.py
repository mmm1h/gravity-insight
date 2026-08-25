from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from gravity_sdk.composite import CompositeService
from gravity_sdk.composite_result import bounded_structural_drift_diagnostics
from gravity_sdk.domains import PROMOTION_PLATFORMS, PROMOTION_PRIMARY_OPERATIONS
from gravity_sdk.errors import (
    GravityInsightError, InputValidationError, LocalIOError, PaginationError)
from gravity_sdk.promotion_performance import (
    PROMOTION_PLATFORM_OPERATIONS,
    SUPPORTED_PLATFORMS,
    promotion_performance,
    promotion_performance_input_schema,
)
from gravity_sdk.promotion_performance_result import (
    PROMOTION_OPAQUE_JSON_FIELDS,
    PROMOTION_ROW_FIELDS,
    safe_component,
)
from gravity_sdk.promotion_performance_snapshot import (
    PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS,
    promotion_component_binding,
)
from gravity_sdk.promotion_performance_rows import (
    MAX_JSON_STRING_LENGTH,
    MAX_OPAQUE_JSON_DEPTH,
    MAX_OPAQUE_JSON_ELEMENTS,
)
from gravity_sdk.promotion_snapshot_compat import _compatibility_snapshot


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


def _bytedance_26_success(row_count=246):
    rows = [
        {
            "app_id": "17",
            "date": "2026-08-01",
            "advertiser_id": f"advertiser-{index}",
            "stat_cost": index + 0.5,
            "delay": 0,
            "operator_id": "operator-id-value",
            "operator_name": "operator-name-value",
            "project_list": [
                {"project_id": f"project-{index}", "labels": ["active"]}
            ],
        }
        for index in range(row_count)
    ]
    pages = max(1, (row_count + 9) // 10)
    result = _success(
        "bytedance",
        rows,
        page={
            "number": 1,
            "size": 10,
            "item_count": row_count,
            "total_pages": pages,
            "total_items": row_count,
            "has_more": False,
            "pages_fetched": pages,
            "max_workers": 1,
        },
    )
    result["data"].update(
        completeness="complete",
        pagination_evidence="production",
        schema_fingerprint="0" * 64,
    )
    return result


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


class _CompatBatchClient(_BatchClient):
    def operations(self, **_filters):
        return []

    def schema(self, *_args, **_kwargs):
        return {}

    def read(self, *_args, **_kwargs):
        return {}

    def read_all(self, *_args, **_kwargs):
        return {}


class _InventoryBatchClient(_CompatBatchClient):
    def __init__(self, operations):
        super().__init__()
        self.inventory = list(operations)

    def operations(self, **filters):
        return [
            item
            for item in self.inventory
            if all(item.get(key) == value for key, value in filters.items())
        ]

    def batch(self, requests, **options):
        self.calls.append((copy.deepcopy(requests), dict(options)))
        return [
            {
                "operation_id": request["operation_id"],
                "request_id": request["request_id"],
                "ok": True,
                "status": "success",
                "data": {"list": [{"row": request["request_id"]}]},
            }
            for request in reversed(requests)
        ]


class _BoundInventoryBatchClient(_InventoryBatchClient):
    def __init__(self, operations, *, app_id="17", row=None):
        super().__init__(operations)
        self.app_id = app_id
        self.row = row

    def batch(self, requests, **options):
        self.calls.append((copy.deepcopy(requests), dict(options)))
        return [
            {
                "operation_id": request["operation_id"],
                "request_id": request["request_id"],
                "ok": True,
                "status": "success",
                "data": _read_envelope(
                    request["operation_id"],
                    [copy.deepcopy(self.row) if self.row is not None else {
                        "app_id": self.app_id,
                        "date": "2026-08-01",
                        "stat_cost": 1.5,
                    }],
                ),
                "error": None,
            }
            for request in reversed(requests)
        ]


def _inventory_operation(platform, resource, operation_id):
    return {
        "operation_id": operation_id,
        "domain": "promotion",
        "platform": platform,
        "resource": resource,
        "action": "list",
        "stability": "stable",
    }


def _registered_operation_row(operation_id):
    contract = (
        Path(__file__).parents[1]
        / "src"
        / "gravity_sdk"
        / "contracts"
        / "operations"
        / f"{operation_id}.json"
    )
    operation = json.loads(contract.read_text(encoding="utf-8"))["operation"]
    projection = operation["response_projection"]
    row = {field: f"{field}-value" for field in projection["item_keys"]}
    for field in ("date", "day", "stat_date"):
        if field in row:
            row[field] = "2026-08-01"
    if "app_id" in row:
        row["app_id"] = "17"
    for field in projection.get("opaque_json_item_keys", []):
        row[field] = [{"registered": ["value"]}]
    row["stat_cost"] = 1.5
    return row


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
                    set(
                        operation["response_projection"].get(
                            "opaque_json_item_keys", []
                        )
                    ),
                    set(PROMOTION_OPAQUE_JSON_FIELDS[platform]),
                )
                self.assertEqual(
                    ["query_fields"],
                    operation["response_projection"]["dynamic_item_fields"],
                )
                self.assertEqual("page_info", operation["pagination"]["kind"])

    def test_formal_snapshot_resources_match_stable_contracts(self):
        expected = {
            "project": {
                "bytedance": "promotion.bytedance.project.list",
            },
            "ad_group": {
                "honor": "promotion.honor.ad_group.list",
            },
            "campaign": {
                "honor": "promotion.honor.campaign.list",
            },
            "ad_unit": {
                "kuaishou": "promotion.kuaishou.ad_unit.list",
            },
            "group": {
                "ubix": "promotion.ubix.group.list",
            },
        }
        self.assertEqual(
            expected,
            {
                resource: dict(operations)
                for resource, operations in PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS.items()
            },
        )
        contracts = (
            Path(__file__).parents[1]
            / "src"
            / "gravity_sdk"
            / "contracts"
            / "operations"
        )
        for resource, operations in expected.items():
            for platform, operation_id in operations.items():
                with self.subTest(platform=platform, resource=resource):
                    operation = json.loads(
                        (contracts / f"{operation_id}.json").read_text(
                            encoding="utf-8"
                        )
                    )["operation"]
                    self.assertEqual(
                        {
                            "date_list", "filtering", "filters", "order_by",
                            "page", "page_size", "query_fields",
                        },
                        set(operation["input_fields"]),
                    )
                    self.assertEqual(
                        ["date_list"],
                        [
                            name
                            for name, field in operation["input_fields"].items()
                            if field.get("required")
                        ],
                    )
                    self.assertEqual(
                        ["query_fields"],
                        operation["response_projection"]["dynamic_item_fields"],
                    )
                    self.assertEqual(
                        ["list", "page_info", "total", "update_at"],
                        operation["response_projection"]["data_keys"],
                    )
                    self.assertEqual("page_info", operation["pagination"]["kind"])
                    self.assertEqual(
                        "internal_business",
                        operation["privacy_policy"]["classification"],
                    )
                    binding = promotion_component_binding(
                        platform, resource, operation_id
                    )
                    self.assertEqual(
                        set(operation["response_projection"]["item_keys"]),
                        set(binding.row_fields),
                    )
                    self.assertEqual(
                        PROMOTION_PLATFORMS[platform][resource],
                        binding.operation_id,
                    )

    def test_all_remaining_snapshot_pairs_lack_dynamic_result_binding(self):
        formal_pairs = {
            (platform, resource)
            for resource, operations in PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS.items()
            for platform in operations
        }
        remaining = []
        for platform, resources in PROMOTION_PLATFORMS.items():
            for resource, operation_id in resources.items():
                formal_primary = (
                    platform in SUPPORTED_PLATFORMS
                    and operation_id == PROMOTION_PRIMARY_OPERATIONS[platform]
                )
                if not formal_primary and (platform, resource) not in formal_pairs:
                    remaining.append((platform, resource, operation_id))
        self.assertEqual(32, len(remaining))
        contracts = (
            Path(__file__).parents[1]
            / "src"
            / "gravity_sdk"
            / "contracts"
            / "operations"
        )
        for platform, resource, operation_id in remaining:
            with self.subTest(platform=platform, resource=resource):
                operation = json.loads(
                    (contracts / f"{operation_id}.json").read_text(encoding="utf-8")
                )["operation"]
                self.assertEqual("stable", operation["stability"])
                self.assertNotIn(
                    "query_fields",
                    operation["response_projection"]["dynamic_item_fields"],
                )

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

    def test_bytedance_26_success_crosses_component_and_top_level_product(self):
        component = _bytedance_26_success()
        safe = safe_component(
            component,
            "bytedance",
            metrics=("stat_cost",),
            expected_app_id="17",
            expected_window=("2026-08-01", "2026-08-07"),
            max_pages=100,
        )
        self.assertEqual(("success", 246), (safe["status"], safe["returned_items"]))
        self.assertEqual(
            component["data"]["data"]["list"][0]["project_list"],
            safe["data"]["list"][0]["project_list"],
        )
        self.assertIsNot(
            component["data"]["data"]["list"][0]["project_list"],
            safe["data"]["list"][0]["project_list"],
        )

        class CurrentComponentClient:
            def batch(self, _requests, **_options):
                return [copy.deepcopy(component)]

        product = promotion_performance(
            CurrentComponentClient(),
            17,
            "2026-08-01",
            "2026-08-07",
            platforms=("bytedance",),
            metrics=("stat_cost",),
            max_pages=100,
            max_items=1_000,
        )
        self.assertEqual((True, "success", 246), (
            product["ok"], product["status"], product["returned_items"]
        ))
        self.assertEqual(
            component["data"]["data"]["list"][0]["project_list"],
            product["results"][0]["data"]["list"][0]["project_list"],
        )

    def test_opaque_json_is_bounded_and_ordinary_row_drift_stays_closed(self):
        cases = []
        too_deep = 0
        for _ in range(MAX_OPAQUE_JSON_DEPTH + 2):
            too_deep = [too_deep]
        cases.append((too_deep, "row_field_opaque_json_bounds"))
        cases.append((
            [0] * MAX_OPAQUE_JSON_ELEMENTS,
            "row_field_opaque_json_bounds",
        ))
        cases.append((
            ["x" * MAX_JSON_STRING_LENGTH] * 5,
            "row_field_opaque_json_bounds",
        ))
        cases.append(({1: "invalid-key"}, "row_field_opaque_json_rule"))
        for project_list, expected_check in cases:
            with self.subTest(expected_check=expected_check):
                component = _bytedance_26_success(1)
                component["data"]["data"]["list"][0]["project_list"] = project_list
                safe = safe_component(
                    component,
                    "bytedance",
                    metrics=("stat_cost",),
                    expected_app_id="17",
                    expected_window=("2026-08-01", "2026-08-07"),
                    max_pages=100,
                )
                self.assertEqual("contract_changed", safe["status"])
                self.assertEqual(
                    expected_check,
                    safe["drift_diagnostics"]["failures"][0]["check"],
                )

        destructive = _bytedance_26_success(1)
        del destructive["data"]["data"]["list"]
        changed_type = _bytedance_26_success(1)
        changed_type["data"]["data"]["list"][0]["operator_name"] = {
            "nested": "private-operator-value"
        }
        unregistered = _bytedance_26_success(1)
        unregistered["data"]["data"]["list"][0][
            "private-business-value-as-field"
        ] = "private-business-value"
        for component, expected_check in (
            (destructive, "read_data_required"),
            (changed_type, "row_field_scalar_rule"),
            (unregistered, "row_field_registration"),
        ):
            safe = safe_component(
                component,
                "bytedance",
                metrics=("stat_cost",),
                expected_app_id="17",
                expected_window=("2026-08-01", "2026-08-07"),
                max_pages=100,
            )
            self.assertEqual("contract_changed", safe["status"])
            self.assertEqual(
                expected_check,
                safe["drift_diagnostics"]["failures"][0]["check"],
            )
            rendered = repr(safe["drift_diagnostics"])
            self.assertNotIn("private-operator-value", rendered)
            self.assertNotIn("private-business-value", rendered)

    def test_diagnostics_are_bounded_value_free_and_binding_stays_closed(self):
        component = _bytedance_26_success(1)
        component["data"]["data"]["list"][0]["operator_name"] = {
            "private-nested-key": "private-operator-name"
        }
        safe = safe_component(
            component,
            "bytedance",
            metrics=("stat_cost",),
            expected_app_id="17",
            expected_window=("2026-08-01", "2026-08-07"),
            max_pages=100,
        )
        diagnostics = safe["drift_diagnostics"]
        self.assertEqual(
            {
                "check": "row_field_scalar_rule",
                "path": "$.data.data.list[0].operator_name",
            },
            diagnostics["failures"][0],
        )
        self.assertNotIn("private-nested-key", repr(diagnostics))
        self.assertNotIn("private-operator-name", repr(diagnostics))

        class ChangedComponentClient:
            def batch(self, _requests, **_options):
                return [copy.deepcopy(component)]

        product = promotion_performance(
            ChangedComponentClient(),
            17,
            "2026-08-01",
            "2026-08-07",
            platforms=("bytedance",),
            metrics=("stat_cost",),
            max_pages=100,
            max_items=10,
        )
        self.assertEqual("contract_changed", product["status"])
        self.assertEqual(
            diagnostics, product["results"][0]["drift_diagnostics"]
        )
        self.assertNotIn("private-operator-name", repr(product))

        many = bounded_structural_drift_diagnostics(
            PROMOTION_PLATFORM_OPERATIONS["bytedance"],
            [(f"check_{index}", f"$.data.list[{index}]") for index in range(12)],
        )
        self.assertEqual(8, len(many["failures"]))
        self.assertTrue(all(
            len(item["check"]) <= 160 and len(item["path"]) <= 160
            for item in many["failures"]
        ))

        for field, private_value in (
            ("app_id", "999"),
            ("date", "2026-09-09"),
        ):
            bound = _bytedance_26_success(1)
            bound["data"]["data"]["list"][0][field] = private_value
            rejected = safe_component(
                bound,
                "bytedance",
                metrics=("stat_cost",),
                expected_app_id="17",
                expected_window=("2026-08-01", "2026-08-07"),
                max_pages=100,
            )
            self.assertEqual("contract_changed", rejected["status"])
            failure = rejected["drift_diagnostics"]["failures"][0]
            self.assertEqual("request_binding", failure["check"])
            self.assertTrue(failure["path"].endswith(field))
            self.assertNotIn(private_value, repr(rejected["drift_diagnostics"]))

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

    def test_input_schema_is_closed_and_legacy_snapshot_matches_formal_product(self):
        schema = promotion_performance_input_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(21, schema["properties"]["platforms"]["maxItems"])

        formal_client, legacy_client = _BatchClient(), _CompatBatchClient()
        expected = promotion_performance(
            formal_client, 17, "2026-08-01", "2026-08-07",
            platforms=("tencent", "bytedance"), metrics=("stat_cost",),
        )
        actual = CompositeService(legacy_client).promotion_snapshot(
            ("tencent", "bytedance"),
            common_inputs={
                "app_id": 17,
                "date_list": ["2026-08-01", "2026-08-07"],
                "query_fields": ["stat_cost"],
            },
        )
        self.assertEqual(expected, actual)
        self.assertEqual(formal_client.calls, legacy_client.calls)

    def test_legacy_snapshot_reads_non_primary_resource_with_compatibility_marker(self):
        operation_id = "promotion.bytedance.account.list"
        client = _InventoryBatchClient([
            _inventory_operation("bytedance", "account", operation_id)
        ])
        result = CompositeService(client).promotion_snapshot(
            ("bytedance",),
            resource="account",
            common_inputs={"page": 1, "page_size": 10},
        )
        requests, options = client.calls[0]
        self.assertEqual(operation_id, requests[0]["operation_id"])
        self.assertEqual({"page": 1, "page_size": 10}, requests[0]["inputs"])
        self.assertEqual({"max_workers": 6}, options)
        self.assertEqual(
            [{"row": "bytedance"}], result["results"][0]["data"]["list"]
        )
        self.assertEqual(
            {"mode": "inventory", "formal_binding_validation": "not_performed"},
            result["compatibility"],
        )

    def test_non_primary_resources_keep_rows_when_formally_bound(self):
        common_inputs = {
            "date_list": ["2026-08-01", "2026-08-07"],
            "query_fields": ["stat_cost"],
            "filters": [
                {"field": "app_id", "operator": 1, "values": ["17"]}
            ],
            "page": 1,
            "page_size": 10,
        }
        for resource, operations in PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS.items():
            platform, operation_id = next(iter(operations.items()))
            inventory = [_inventory_operation(platform, resource, operation_id)]
            expected_row = _registered_operation_row(operation_id)
            compatibility_client = _BoundInventoryBatchClient(
                inventory, row=expected_row
            )
            formal_client = _BoundInventoryBatchClient(inventory, row=expected_row)
            with self.subTest(platform=platform, resource=resource):
                compatibility = _compatibility_snapshot(
                    compatibility_client,
                    [platform],
                    resource=resource,
                    shared=copy.deepcopy(common_inputs),
                    platform_inputs={},
                    read_all=True,
                    max_workers=6,
                )
                formal = CompositeService(formal_client).promotion_snapshot(
                    (platform,),
                    resource=resource,
                    common_inputs=copy.deepcopy(common_inputs),
                    read_all=True,
                )
                self.assertEqual(
                    compatibility_client.calls[0][0], formal_client.calls[0][0]
                )
                self.assertEqual(
                    compatibility["results"][0]["data"]["data"]["list"],
                    formal["results"][0]["data"]["list"],
                )
                self.assertEqual([expected_row], formal["results"][0]["data"]["list"])
                self.assertEqual(
                    compatibility["results"][0]["data"]["page"],
                    formal["results"][0]["page"],
                )
                self.assertEqual(
                    (
                        compatibility["results"][0]["operation_id"],
                        compatibility["results"][0]["status"],
                    ),
                    (
                        formal["results"][0]["operation_id"],
                        formal["results"][0]["status"],
                    ),
                )
                self.assertEqual(
                    "gravity-insight.promotion-performance.v1",
                    formal["schema_version"],
                )
                self.assertEqual(
                    (resource, operation_id),
                    (
                        formal["results"][0]["resource"],
                        formal["results"][0]["operation_id"],
                    ),
                )
                self.assertNotIn("compatibility", formal)

    def test_formal_non_primary_result_rejects_wrong_app_binding(self):
        operation_id = PROMOTION_SNAPSHOT_RESOURCE_OPERATIONS["project"][
            "bytedance"
        ]
        client = _BoundInventoryBatchClient(
            [_inventory_operation("bytedance", "project", operation_id)],
            app_id="18",
        )
        result = CompositeService(client).promotion_snapshot(
            ("bytedance",),
            resource="project",
            common_inputs={
                "app_id": 17,
                "date_list": ["2026-08-01", "2026-08-07"],
                "query_fields": ["stat_cost"],
            },
        )
        self.assertEqual("contract_changed", result["status"])
        failure = result["results"][0]["drift_diagnostics"]["failures"][0]
        self.assertEqual(
            ("request_binding", "$.data.data.list[0].app_id"),
            (failure["check"], failure["path"]),
        )

    def test_legacy_snapshot_reads_four_heterogeneous_primary_platforms(self):
        capabilities = {
            "bing": ("advertiser", "promotion.bing.advertiser.list"),
            "xiaohongshu": ("advertiser", "promotion.xiaohongshu.advertiser.list"),
            "taptap": ("group", "promotion.taptap.group.list"),
            "wechat_video": ("report", "promotion.wechat_video.report.list"),
        }
        client = _InventoryBatchClient([
            _inventory_operation(platform, resource, operation_id)
            for platform, (resource, operation_id) in capabilities.items()
        ])
        result = CompositeService(client).promotion_snapshot(tuple(capabilities))
        requests, _ = client.calls[0]
        self.assertEqual(
            [value[1] for value in capabilities.values()],
            [request["operation_id"] for request in requests],
        )
        self.assertEqual(list(capabilities), [item["platform"] for item in result["results"]])
        self.assertTrue(all(item["data"]["list"] for item in result["results"]))
        self.assertEqual("not_performed", result["compatibility"]["formal_binding_validation"])

    def test_legacy_snapshot_rejects_ambiguous_inventory_without_executing(self):
        client = _InventoryBatchClient([
            _inventory_operation("bytedance", "site", operation_id)
            for operation_id in (
                "promotion.bytedance.site.list",
                "promotion.bytedance.site.query",
            )
        ])
        with self.assertRaises(InputValidationError) as raised:
            CompositeService(client).promotion_snapshot(
                ("bytedance",), resource="site"
            )
        self.assertEqual("resource", raised.exception.field)
        self.assertIn("actual value:", str(raised.exception))
        self.assertIn("promotion.bytedance.site.list", str(raised.exception))
        self.assertIn("promotion.bytedance.site.query", str(raised.exception))
        self.assertTrue(raised.exception.next_action)
        self.assertEqual([], client.calls)

    def test_legacy_snapshot_uses_formal_input_error_classification(self):
        cases = (
            ({"app_id": "0"}, {}, {}),
            ({"start": "bad"}, {}, {}),
            ({"platforms": ("unknown",)}, {"platforms": ("unknown",)}, {}),
            ({"metrics": ("app_id",)}, {}, {"query_fields": ["app_id"]}),
        )
        base = dict(
            app_id=17, start="2026-08-01", end="2026-08-07",
            platforms=("tencent",), metrics=("stat_cost",),
        )
        for formal_overrides, legacy_overrides, input_overrides in cases:
            formal = {**base, **formal_overrides}
            inputs = {
                "app_id": formal["app_id"],
                "date_list": [formal["start"], formal["end"]],
                "query_fields": list(formal["metrics"]),
                **input_overrides,
            }
            with self.subTest(overrides=formal_overrides):
                with self.assertRaises(InputValidationError) as formal_error:
                    promotion_performance(_BatchClient(), **formal)
                with self.assertRaises(InputValidationError) as legacy_error:
                    CompositeService(_CompatBatchClient()).promotion_snapshot(
                        legacy_overrides.get("platforms", formal["platforms"]),
                        common_inputs=inputs,
                    )
                self.assertEqual(
                    (
                        formal_error.exception.code,
                        formal_error.exception.field,
                        formal_error.exception.next_action,
                    ),
                    (
                        legacy_error.exception.code,
                        legacy_error.exception.field,
                        legacy_error.exception.next_action,
                    ),
                )


if __name__ == "__main__":
    unittest.main()
