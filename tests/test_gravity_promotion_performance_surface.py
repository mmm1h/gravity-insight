import copy
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

from gravity_sdk import cli
from gravity_sdk.__main__ import main as unified_main
from gravity_sdk.errors import ErrorCode, ErrorDetail
from gravity_sdk.onboarding import command_requires_credentials
from gravity_sdk.plan import AdapterContext, execute_plan
from gravity_sdk.plan_adapters import build_plan_adapters
from gravity_sdk.plan_promotion_performance_adapter import (
    project_promotion_performance_result,
    sanitize_product_result,
    validate_promotion_performance_plan,
)
from gravity_sdk.promotion_performance_result import (
    PROMOTION_PLATFORM_OPERATIONS,
    product_envelope,
    promotion_performance_item_count,
    safe_component,
)
from gravity_sdk.sdk import GravitySDK


WINDOW = ("2026-08-01", "2026-08-02")
METRICS = ("stat_cost",)
BASE = [
    "promotion", "performance", "--app", "main",
    "--start", WINDOW[0], "--end", WINDOW[1],
    "--platform", "bytedance", "--metric", METRICS[0],
]


class _Workspace:
    def resolve_app(self, value=None):
        if value in {"main", 7, "7"}:
            return 7
        raise ValueError("unknown app")


class _Insight:
    @staticmethod
    def operations(**_kwargs):
        return []


class _SDK:
    workspace = _Workspace()
    insight = _Insight()

    def __init__(self, result):
        self.result, self.calls = result, []

    def promotion_performance(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return copy.deepcopy(self.result)


def _context(*, dynamic=(), fields=(), max_items=10):
    return AdapterContext(
        "promotion", "promotion", "composite", _Workspace(),
        tuple(fields), tuple(dynamic), 5, max_items,
    )


def _request():
    return {
        "name": "promotion_performance", "app": "main",
        "start": WINDOW[0], "end": WINDOW[1],
        "platforms": ["bytedance"], "metrics": list(METRICS),
    }


def _component(platform):
    operation = PROMOTION_PLATFORM_OPERATIONS[platform]
    return safe_component({
        "operation_id": operation, "request_id": platform,
        "ok": True, "status": "success", "error": None,
        "data": {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": operation, "status": "success", "error": None,
            "data": {"list": [{"app_id": "7", "date": WINDOW[0], METRICS[0]: 2.5}]},
            "page": {
                "item_count": 1, "pages_fetched": 1, "max_workers": 1,
                "number": 1, "size": 10, "total_pages": 1,
                "total_items": 1, "has_more": False,
            },
        },
    }, platform, metrics=METRICS, expected_app_id="7", expected_window=WINDOW, max_pages=5)


def _failure(platform="tencent"):
    operation = PROMOTION_PLATFORM_OPERATIONS[platform]
    return safe_component({
        "operation_id": operation, "request_id": platform,
        "ok": False, "status": "error",
        "error": ErrorDetail.create(
            ErrorCode.UPSTREAM_UNAVAILABLE, "secret upstream diagnostic",
            operation_id=operation,
        ).to_dict(),
    }, platform, metrics=METRICS, expected_app_id="7", expected_window=WINDOW, max_pages=5)


def _product(platforms=("bytedance",), *, max_items=10, results=None):
    parts = list(results) if results is not None else [
        _component(platform) for platform in platforms
    ]
    returned = promotion_performance_item_count({"results": parts})
    return product_envelope(
        parts, app_id="7", window=WINDOW, platforms=tuple(platforms),
        metric_count=1, max_pages=5, max_items=max_items, max_workers=1,
        returned_items=returned,
    )


def _sanitize(value, **overrides):
    expected = {
        "expected_app_id": "7", "expected_window": WINDOW,
        "expected_platforms": ("bytedance", "tencent"),
        "expected_metrics": METRICS, "expected_max_pages": 5,
        "expected_max_items": 10, "expected_max_workers": 1,
    }
    expected.update(overrides)
    return sanitize_product_result(value, **expected)


def _inject_unhashable_error_code(value):
    failure = _failure("bytedance")
    failure["error"]["code"] = []
    value["results"][0] = failure


class PromotionPerformanceSurfaceTests(unittest.TestCase):
    def test_cli_preflight_owns_onboarding_output_and_legacy_compatibility(self):
        invalid = (
            [*BASE[:5], "bad", *BASE[6:]],
            [*BASE[:-3], "bing", *BASE[-2:]],
            [*BASE[:-1], "user_id"],
            [*BASE, "--max-items", "0"],
            [*BASE, "--output", "-"],
            [*BASE, "--output", "."],
        )
        with (
            patch("gravity_sdk.promotion_cli.load_workspace", return_value=_Workspace()),
            patch("gravity_sdk.promotion_cli.runtime.build_client") as client,
        ):
            self.assertTrue(command_requires_credentials(BASE, cli.build_parser))
            for argv in invalid:
                with self.subTest(argv=argv):
                    self.assertFalse(command_requires_credentials(argv, cli.build_parser))
                    with (
                        patch(
                            "gravity_sdk.__main__.ensure_first_run_credentials",
                            return_value=True,
                        ) as onboard,
                        redirect_stderr(io.StringIO()),
                    ):
                        self.assertEqual(2, unified_main(argv))
                    onboard.assert_called_once_with(requires_credentials=False)
        client.assert_not_called()

        parser = cli.build_parser()
        selected = parser.parse_args([*BASE, "--output", "performance.json"])
        self.assertEqual("performance.json", selected.output)
        self.assertFalse(hasattr(selected, "format"))
        legacy = parser.parse_args(["promotion", "query", "--platform", "bytedance"])
        self.assertEqual("query", legacy.promotion_command)

    def test_sdk_preflights_before_lazy_client_and_delegates(self):
        factory = Mock()
        sdk = GravitySDK(insight_factory=factory, workspace=_Workspace())
        with self.assertRaises(ValueError):
            sdk.promotion_performance(
                "main", "bad", WINDOW[1], platforms=("bytedance",), metrics=METRICS
            )
        factory.assert_not_called()

        insight, expected = object(), {"schema_version": "test"}
        factory.return_value = insight
        with patch(
            "gravity_sdk.promotion_performance.promotion_performance",
            return_value=expected,
        ) as core:
            result = sdk.promotion_performance(
                "main", *WINDOW, platforms=("bytedance",), metrics=METRICS,
                max_workers=3, max_pages=5, max_items=10,
            )
        self.assertIs(expected, result)
        core.assert_called_once_with(
            insight, 7, *WINDOW, platforms=("bytedance",), metrics=METRICS,
            max_workers=3, max_pages=5, max_items=10,
        )

    def test_plan_validation_route_and_fake_projection_fail_closed(self):
        validate_promotion_performance_plan(
            _request(), _context(dynamic=("/app", "/start", "/end")), _Workspace()
        )
        for field in ("platforms", "metrics"):
            request = _request()
            request[field] = "bytedance"
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_promotion_performance_plan(request, _context(), _Workspace())
        with self.assertRaises(ValueError):
            validate_promotion_performance_plan(
                _request(), _context(dynamic=("/metrics",)), _Workspace()
            )

        sdk = _SDK(_product())
        adapter = build_plan_adapters(sdk).composite
        safe = adapter.execute(_request(), _context())
        self.assertEqual(("success", 1), (
            safe["status"], sdk.calls[0][1]["max_workers"]
        ))
        projected = adapter.project(safe, ("results",), _context(fields=("results",)))
        self.assertEqual(["bytedance"], [item["platform"] for item in projected["results"]])

        fake = _product()
        fake["results"][0]["data"]["list"][0]["secret"] = "leak"
        rejected = project_promotion_performance_result(fake, (), _context())
        self.assertEqual("contract_changed", rejected["status"])
        self.assertNotIn("leak", str(rejected))

    def test_request_bound_sanitizer_rejects_receipt_drift_and_unfair_share(self):
        mutations = (
            lambda item: item.__setitem__("app_id", "8"),
            lambda item: item["date_range"].__setitem__("end", "2026-08-03"),
            lambda item: item["results"][0].__setitem__("platform", "tencent"),
            lambda item: item["results"].reverse(),
            lambda item: item["results"][0]["data"]["list"][0].__setitem__("app_id", "8"),
            lambda item: item["results"][0]["data"]["list"][0].__setitem__("date", "2026-08-03"),
            lambda item: item.__setitem__("metric_count", 2),
            lambda item: item["limits"].__setitem__("platform_workers", 2),
            lambda item: item.__setitem__("returned_items", 3),
            lambda item: item["results"][0].__setitem__("status", []),
            _inject_unhashable_error_code,
        )
        for mutate in mutations:
            value = _product(("bytedance", "tencent"))
            mutate(value)
            with self.subTest(mutate=mutate):
                self.assertEqual("contract_changed", _sanitize(value)["status"])

        unfair = _product(("bytedance", "tencent"), max_items=3)
        first = unfair["results"][0]
        first["data"]["list"].append(copy.deepcopy(first["data"]["list"][0]))
        first["returned_items"] = first["page"]["item_count"] = 2
        first["page"]["total_items"] = 2
        unfair["returned_items"] = 3
        self.assertEqual(
            "contract_changed",
            _sanitize(unfair, expected_max_items=3)["status"],
        )

    def test_partial_error_is_controlled_and_full_plan_keeps_verified_marker(self):
        partial = _product(
            ("bytedance", "tencent"), results=[_component("bytedance"), _failure()]
        )
        safe = _sanitize(partial)
        self.assertEqual("partial", safe["status"])
        self.assertNotIn("secret upstream diagnostic", str(safe))

        adapter = build_plan_adapters(_SDK(_product())).composite
        result = execute_plan({
            "schema_version": "gravity.plan.v1",
            "nodes": [{
                "id": "promotion", "kind": "composite", "request": _request(),
                "limits": {"max_pages": 5, "max_items": 10},
                "output_fields": ["results"],
            }],
        }, adapters={"composite": adapter}, workspace=_Workspace())
        item = result["results"][0]
        self.assertEqual(("success", 0, True), (
            result["status"], result["exit_code"], item["ok"]
        ))
        self.assertEqual(
            ["bytedance"],
            [part["platform"] for part in item["result"]["results"]],
        )


if __name__ == "__main__":
    unittest.main()
