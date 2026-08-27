from __future__ import annotations
import copy, unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK, InputValidationError
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agents.capabilities import (
    composite_capability_cards, composite_capability_inventory,
)
from gravity_sdk.agents.handoff import attach_plan_node
from gravity_sdk.material_performance_result import product_envelope, safe_component
from gravity_sdk.material_performance import MATERIAL_REPORT_OPERATION
from gravity_sdk.material_performance_plan_result import sanitize_product_result
from gravity_sdk.plan import AdapterContext, PlanAdapter, execute_plan
from gravity_sdk.plan_material_performance_adapter import (
    execute_material_performance_plan,
    validate_material_performance_plan,
)

def _success(platform):
    return {
        "operation_id": MATERIAL_REPORT_OPERATION, "request_id": platform,
        "ok": True, "status": "success", "error": None,
        "data": {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": MATERIAL_REPORT_OPERATION,
            "status": "success", "error": None,
            "data": {"list": [{"gravity_material_id": platform}]},
            "page": {
                "number": 1, "size": 10, "item_count": 1,
                "total_pages": 1, "total_items": 1, "has_more": False,
                "pages_fetched": 1, "max_workers": 1},
        },
    }

class _BatchClient:
    def batch(self, requests, **_options):
        return [_success(request["request_id"]) for request in requests]

class _Workspace:
    def resolve_app(self, value):
        if value in {"main", 17, "17"}:
            return 17
        if value in {"secondary", 23, "23"}:
            return 23
        raise ValueError("unknown private alias")

def _context(**overrides):
    values = {
        "node_id": "materials", "execution_id": "materials",
        "kind": "composite", "workspace": _Workspace(),
        "output_fields": (), "dynamic_targets": (),
        "max_pages": 2, "max_items": 10,
    }
    values.update(overrides)
    return AdapterContext(**values)

class MaterialPerformanceSurfaceTests(unittest.TestCase):
    def test_sdk_validates_before_lazy_client_and_executes_through_core(self):
        built = []

        def factory():
            built.append(True)
            return _BatchClient()
        sdk = GravitySDK(insight_factory=factory, workspace=_Workspace())
        invalid = (
            {"apps": b"1", "start": "2026-08-01", "end": "2026-08-02"},
            {"apps": ["main"], "start": "bad", "end": "2026-08-02"},
            {"apps": ["main"], "start": "2026-08-01",
             "end": "2026-08-02", "platforms": ("tencent", "tencent")},
            {"apps": ["main"], "start": "2026-08-01",
             "end": "2026-08-02", "max_items": 1},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(InputValidationError):
                sdk.material_performance(**kwargs)
        self.assertEqual([], built)
        result = sdk.material_performance(
            ["main", "secondary"], "2026-08-01", "2026-08-02",
            platforms=("tencent",), max_pages=2, max_items=10)
        self.assertEqual((1, 2), (len(built), result["app_count"]))

    def test_cli_keeps_catalogs_and_rejects_invalid_before_client(self):
        from gravity_sdk import cli

        for command in ("list", "tags", "reviews"):
            parsed = cli.build_parser().parse_args(["materials", command])
            self.assertEqual(command, parsed.materials_command)
        argv = [
            "materials", "performance", "--app", "main",
            "--start", "bad", "--end", "2026-08-02",
        ]
        with (
            patch("gravity_sdk.material_cli.load_workspace", return_value=_Workspace()),
            patch("gravity_sdk.material_cli.runtime.build_client") as build,
        ):
            args = cli.build_parser().parse_args(argv)
            with self.assertRaises(InputValidationError): cli.run(args)
        build.assert_not_called()
        with self.assertRaises(InputValidationError):
            cli.build_parser().parse_args([
                "materials", "performance", "--app", "main",
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--output", "-",
            ])
    def test_onboarding_requires_only_a_complete_local_request(self):
        from gravity_sdk import cli
        from gravity_sdk.onboarding import command_requires_credentials

        base = [
            "materials", "performance", "--app", "main",
            "--start", "2026-08-01", "--end", "2026-08-02",
            "--platform", "tencent",
        ]
        invalid = (
            [*base[:-3], "bad", *base[-2:]],
            [*base, "--platform", "tencent"],
            [*base, "--concurrency", "25"],
            [*base, "--max-items", "0"],
        )
        with patch("gravity_sdk.workspace.load_workspace", return_value=_Workspace()):
            self.assertTrue(command_requires_credentials(base, cli.build_parser))
            for argv in invalid:
                with self.subTest(argv=argv):
                    self.assertFalse(command_requires_credentials(argv, cli.build_parser))
    def test_plan_allows_only_scalar_dates_and_binds_exact_runtime_limits(self):
        request = {
            "name": "material_performance", "apps": ["main"],
            "start": "2026-08-01", "end": "2026-08-02",
            "platforms": ["tencent"],
        }
        validate_material_performance_plan(request, _context(), _Workspace())
        validate_material_performance_plan(
            request, _context(dynamic_targets=("/start", "/end")), _Workspace()
        )
        for target in ("/apps", "/platforms", "/platforms/0"):
            with self.subTest(target=target), self.assertRaises(InputValidationError):
                validate_material_performance_plan(
                    request, _context(dynamic_targets=(target,)), _Workspace()
                )
        with self.assertRaises(InputValidationError):
            validate_material_performance_plan(
                {**request, "apps": ["main", "17"]}, _context(), _Workspace()
            )
        for start, end in (
            ("20260801", "20260802"),
            ("2026-W31-6", "2026-W31-7"),
        ):
            with self.subTest(start=start), self.assertRaises(InputValidationError):
                validate_material_performance_plan(
                    {**request, "start": start, "end": end},
                    _context(), _Workspace())
        class SDK:
            def __init__(self, drift=False):
                self.calls = []
                self.drift = drift

            def material_performance(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                result = product_envelope(
                    [safe_component(_success("tencent"), "tencent", max_pages=2)],
                    app_count=1,
                    window=("2026-08-01", "2026-08-02"),
                    platforms=("tencent",), max_pages=2, max_items=10,
                    max_workers=1, returned_items=1,
                )
                if self.drift:
                    result = copy.deepcopy(result)
                    result["limits"]["max_pages_per_platform"] = 3
                return result
        sdk = SDK()
        safe = execute_material_performance_plan(sdk, request, _context())
        self.assertEqual("success", safe["status"])
        self.assertEqual((1, 2, 10), (
            sdk.calls[0][1]["max_workers"], sdk.calls[0][1]["max_pages"],
            sdk.calls[0][1]["max_items"]))
        drift = execute_material_performance_plan(SDK(drift=True), request, _context())
        self.assertEqual("contract_changed", drift["status"])
        boolean_receipt = product_envelope(
            [safe_component(_success("tencent"), "tencent", max_pages=2)],
            app_count=1, window=("2026-08-01", "2026-08-02"),
            platforms=("tencent",), max_pages=2, max_items=10,
            max_workers=1, returned_items=1,
        )
        boolean_receipt["limits"]["page_workers_per_platform"] = True
        with patch.object(SDK, "material_performance", return_value=boolean_receipt):
            result = execute_material_performance_plan(SDK(), request, _context())
            self.assertEqual("contract_changed", result["status"])
        for field, value in (
            ("ok", 1), ("exit_code", False),
            ("platform_count", True), ("returned_items", 1.0),
        ):
            drifted = copy.deepcopy(safe)
            drifted[field] = value
            with self.subTest(field=field), patch.object(
                SDK, "material_performance", return_value=drifted):
                result = execute_material_performance_plan(SDK(), request, _context())
                self.assertEqual("contract_changed", result["status"])

        swapped = product_envelope([
            safe_component(_success("bytedance"), "bytedance", max_pages=2),
            safe_component(_success("tencent"), "tencent", max_pages=2),
        ], app_count=1, window=("2026-08-01", "2026-08-02"),
            platforms=("tencent", "bytedance"), max_pages=2, max_items=10,
            max_workers=1, returned_items=2)
        self.assertEqual("contract_changed", sanitize_product_result(
            swapped, expected_platforms=("tencent", "bytedance"))["status"])
    def test_full_plan_preserves_upstream_exit_for_partial_platform_failure(self):
        class SDK:
            def material_performance(self, *_args, **_kwargs):
                failed = safe_component({
                    "operation_id": MATERIAL_REPORT_OPERATION,
                    "request_id": "bytedance", "ok": False,
                    "status": "error", "data": None,
                    "error": {
                        "code": "UPSTREAM_UNAVAILABLE", "category": "upstream",
                        "message": "opaque upstream message",
                        "field": None, "retryable": True, "retry_after_ms": None,
                    },
                }, "bytedance", max_pages=2)
                return product_envelope(
                    [safe_component(_success("tencent"), "tencent", max_pages=2), failed],
                    app_count=1, window=("2026-08-01", "2026-08-02"),
                    platforms=("tencent", "bytedance"), max_pages=2,
                    max_items=10, max_workers=1, returned_items=1,
                )
        adapter = PlanAdapter(
            execute=lambda request, context: execute_material_performance_plan(
                SDK(), request, context
            ),
            validate=lambda request, context: validate_material_performance_plan(
                request, context, _Workspace()
            ),
        )
        result = execute_plan(
            {
                "schema_version": "gravity.plan.v1",
                "nodes": [{
                    "id": "materials", "kind": "composite",
                    "request": {
                        "name": "material_performance", "apps": ["main"],
                        "start": "2026-08-01", "end": "2026-08-02",
                        "platforms": ["tencent", "bytedance"],
                    },
                    "limits": {"max_pages": 2, "max_items": 10},
                }],
            },
            adapters={"composite": adapter}, workspace=_Workspace(),
        )
        self.assertEqual(("error", 3, "UPSTREAM_UNAVAILABLE"), (
            result["status"], result["exit_code"],
            result["results"][0]["error"]["code"]))
    def test_agent_returns_one_authoritative_copyable_node(self):
        for query in (
            "素材表现", "material performance", "跨平台素材报表",
            "material performance 请查询", "请跑 material report",
        ):
            with self.subTest(query=query):
                cards = composite_capability_cards(
                    query, domain=None, platform=None
                )
                self.assertEqual(
                    ["material_performance"], [card["composite"] for card in cards]
                )
                card = attach_plan_node(cards[0], query)
                self.assertEqual(
                    ["apps", "start", "end"], card["missing_inputs"])
                self.assertIsInstance(card["plan_node"]["request"]["apps"], list)
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertEqual(
                    set(card["input_schema"]), set(card["input_template"])
                )
                self.assertNotIn("name", card["input_template"])
        discovered = discover_capabilities("Compare creative material performance across all supported ad platforms for yesterday.", client=None)
        self.assertEqual((1, 1), (discovered["count"], discovered["total"]))
        card = discovered["candidates"][0]
        self.assertEqual("material_performance", card["composite"])
        self.assertEqual(["apps"], card["missing_inputs"])
        self.assertIn("resolved_date_window", card)
        inventory = composite_capability_inventory()
        material = next(item for item in inventory if item["name"] == "material_performance")
        material["input_schema"]["platforms"]["enum"].append("evil")
        fresh = composite_capability_inventory()
        material = next(item for item in fresh if item["name"] == "material_performance")
        self.assertNotIn("evil", material["input_schema"]["platforms"]["enum"])
        for query in (
            "素材库", "material report export", "素材排名", "素材效果排名",
            "material performance ranking", "best material performance",
            "material analysis", "material metrics", "素材分析", "素材指标",
            "素材表现 export", "素材报表 ranking", "素材效果 dashboard",
            "not material performance", "no material report",
            "avoid material performance", "material report without apps",
            "不要素材表现", "无需素材报表", "不需要素材表现", "不必做素材表现",
            "别查素材表现", "别给我素材报表", "别展示素材表现", "不做素材表现",
            "无须素材报表", "避免素材表现", "don't 素材表现",
            "run saved material report", "运行已保存的素材报表",
            "运行已存素材报表", "business pulse material performance",
            "素材表现脉搏",
        ):
            cards = composite_capability_cards(query, domain=None, platform=None)
            self.assertNotIn("material_performance", [card["composite"] for card in cards])
