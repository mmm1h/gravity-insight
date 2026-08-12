import copy
import unittest
from unittest.mock import Mock, patch

from gravity_sdk.plan import AdapterContext


class _Workspace:
    def resolve_app(self, value=None):
        if value in {"main", 7, "7"}:
            return 7
        raise ValueError("unknown app")


def _context(*, dynamic=(), fields=(), max_pages=5, max_items=10):
    return AdapterContext(
        node_id="promotion",
        execution_id="promotion",
        kind="composite",
        workspace=_Workspace(),
        output_fields=tuple(fields),
        dynamic_targets=tuple(dynamic),
        max_pages=max_pages,
        max_items=max_items,
    )


def _request():
    return {
        "name": "promotion_performance",
        "app": "main",
        "start": "2026-08-01",
        "end": "2026-08-02",
        "platforms": ["bytedance"],
        "metrics": ["stat_cost"],
    }


def _product():
    from gravity_sdk.promotion_performance_result import (
        PROMOTION_PLATFORM_OPERATIONS,
        product_envelope,
        safe_component,
    )

    operation_id = PROMOTION_PLATFORM_OPERATIONS["bytedance"]
    component = safe_component(
        {
            "operation_id": operation_id,
            "request_id": "bytedance",
            "ok": True,
            "status": "success",
            "error": None,
            "data": {
                "schema_version": "gravity-insight.read.v1",
                "operation_id": operation_id,
                "status": "success",
                "error": None,
                "data": {
                    "list": [{"date": "2026-08-01", "stat_cost": 2.5}]
                },
                "page": {
                    "item_count": 1,
                    "pages_fetched": 1,
                    "max_workers": 1,
                    "number": 1,
                    "size": 10,
                    "total_pages": 1,
                    "total_items": 1,
                    "has_more": False,
                },
            },
        },
        "bytedance",
        metrics=("stat_cost",),
        max_pages=5,
    )
    return product_envelope(
        [component],
        app_id="7",
        window=("2026-08-01", "2026-08-02"),
        platforms=("bytedance",),
        metric_count=1,
        max_pages=5,
        max_items=10,
        max_workers=1,
        returned_items=1,
    )


class PromotionPerformanceSurfaceTests(unittest.TestCase):
    def test_cli_invalid_product_input_never_loads_workspace_or_client(self):
        from gravity_sdk import cli

        with (
            patch("gravity_sdk.promotion_cli.load_workspace") as workspace,
            patch("gravity_sdk.promotion_cli.runtime.build_client") as client,
        ):
            exit_code = cli.main(
                [
                    "promotion", "performance", "--app", "main",
                    "--start", "2026-08-01", "--end", "2026-08-02",
                    "--platform", "bing", "--metric", "cost",
                ]
            )
        self.assertEqual(2, exit_code)
        workspace.assert_not_called()
        client.assert_not_called()

    def test_cli_output_is_json_file_only_and_old_commands_remain(self):
        from gravity_sdk.cli import build_parser

        parser = build_parser()
        performance = parser.parse_args(
            [
                "promotion", "performance", "--app", "main",
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--platform", "bytedance,tencent",
                "--metric", "cost", "--metric", "register_count",
                "--output", "performance.json",
            ]
        )
        self.assertEqual("performance.json", performance.output)
        self.assertFalse(hasattr(performance, "format"))
        self.assertEqual(
            "query",
            parser.parse_args(
                ["promotion", "query", "--platform", "bytedance"]
            ).promotion_command,
        )
        with self.assertRaises(Exception):
            parser.parse_args(
                [
                    "promotion", "performance", "--app", "main",
                    "--start", "2026-08-01", "--end", "2026-08-02",
                    "--platform", "bytedance", "--metric", "cost",
                    "--output", "-",
                ]
            )

    def test_sdk_preflights_before_lazy_client_and_delegates_valid_request(self):
        from gravity_sdk.sdk import GravitySDK

        factory = Mock()
        sdk = GravitySDK(insight_factory=factory, workspace=_Workspace())
        with self.assertRaises(ValueError):
            sdk.promotion_performance(
                "main", "bad", "2026-08-02",
                platforms=("bytedance",), metrics=("stat_cost",),
            )
        factory.assert_not_called()

        insight = object()
        factory.return_value = insight
        expected = {"schema_version": "gravity-insight.promotion-performance.v1"}
        with patch(
            "gravity_sdk.promotion_performance.promotion_performance",
            return_value=expected,
        ) as core:
            result = sdk.promotion_performance(
                "main", "2026-08-01", "2026-08-02",
                platforms=("bytedance",), metrics=("stat_cost",),
                max_workers=3, max_pages=5, max_items=10,
            )
        self.assertIs(expected, result)
        core.assert_called_once_with(
            insight, 7, "2026-08-01", "2026-08-02",
            platforms=("bytedance",), metrics=("stat_cost",),
            max_workers=3, max_pages=5, max_items=10,
        )

    def test_plan_requires_literal_arrays_and_only_scalar_bindings(self):
        from gravity_sdk.plan_promotion_performance_adapter import (
            validate_promotion_performance_plan,
        )

        validate_promotion_performance_plan(
            _request(), _context(dynamic=("/app", "/start", "/end")),
            _Workspace(),
        )
        for field in ("platforms", "metrics"):
            request = _request()
            request[field] = "bytedance"
            with self.assertRaises(ValueError):
                validate_promotion_performance_plan(
                    request, _context(), _Workspace()
                )
        with self.assertRaises(ValueError):
            validate_promotion_performance_plan(
                _request(), _context(dynamic=("/metrics",)), _Workspace()
            )

    def test_plan_route_forces_inner_worker_one_and_rejects_fake_fields(self):
        from gravity_sdk.plan_adapters import build_plan_adapters

        class Insight:
            @staticmethod
            def operations(**_kwargs):
                return []

        class SDK:
            workspace = _Workspace()
            insight = Insight()

            def __init__(self, result):
                self.result = result
                self.calls = []

            def promotion_performance(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return copy.deepcopy(self.result)

        sdk = SDK(_product())
        adapter = build_plan_adapters(sdk).composite
        adapter.validate(_request(), _context())
        safe = adapter.execute(_request(), _context())
        self.assertEqual("success", safe["status"])
        self.assertEqual(1, sdk.calls[0][1]["max_workers"])
        self.assertEqual(
            {"schema_version", "ok", "status", "exit_code", "error",
             "next_action", "results"},
            set(adapter.project(safe, ("results",), _context(fields=("results",)))),
        )

        drift = _product()
        drift["results"][0]["data"]["list"][0]["secret_metric"] = 99
        rejected = build_plan_adapters(SDK(drift)).composite.execute(
            _request(), _context()
        )
        self.assertEqual("contract_changed", rejected["status"])
        self.assertNotIn("results", rejected)


if __name__ == "__main__":
    unittest.main()
