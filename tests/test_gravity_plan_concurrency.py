from __future__ import annotations

import copy
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from gravity_sdk.analysis_context import ANALYSIS_CONTEXT_SOURCES, analysis_context
from gravity_sdk.credentials import Credential
from gravity_sdk.dashboard_analysis import run_dashboard_analysis
from gravity_sdk.http_runtime import GravityHttpRuntime, HostRateLimiter, SQL_PROFILE
from gravity_sdk.plan import PlanAdapter, PlanAdapters, execute_plan
from gravity_sdk.plan_dashboard_analysis_adapter import execute_dashboard_analysis_plan
from gravity_sdk.plan_fixed_composite_adapter import execute_fixed_composite
from gravity_sdk.plan_promotion_performance_adapter import execute_promotion_performance_plan
from gravity_sdk.promotion_performance import (
    PROMOTION_PLATFORM_OPERATIONS,
    SUPPORTED_PLATFORMS,
    promotion_performance,
)


def _plan(request, *, workers, max_items):
    return {
        "schema_version": "gravity.plan.v1",
        "budget": {"max_workers": workers, "max_total_items": max_items},
        "nodes": [{
            "id": "subject", "kind": "composite", "request": request,
            "limits": {"max_pages": 5, "max_items": max_items},
        }],
    }


def _read(operation_id, rows, *, status="success"):
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": operation_id,
        "status": status,
        "error": None,
        "data": {"list": rows},
        "page": {
            "number": 1, "size": 10, "item_count": len(rows),
            "total_pages": 1, "total_items": len(rows), "has_more": False,
            "pages_fetched": 1, "max_workers": 1,
        },
    }


class PeakTransport:
    def __init__(self, response):
        self.response = response
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.request_ids = []

    def batch(self, requests, *, max_workers, **_options):
        def send(request):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
                self.request_ids.append(request["request_id"])
            time.sleep(0.01)
            try:
                return self.response(request)
            finally:
                with self.lock:
                    self.active -= 1

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(send, requests))


class Workspace:
    def resolve_app(self, _value):
        return 17


def _event_report(index):
    return {
        "report_id": str(index), "name": f"chart-{index}",
        "subject": "analysis_event",
        "config": {"calculateBody": {
            "query_item_list": [{
                "cond_logic": "AND", "conditions": [], "custom_name": "login",
                "event_index": 0, "event_label": "login", "event_name": "login",
                "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
            }],
            "group_by_list": [{
                "type": "default_event", "field": "create_time", "group_by": "day",
            }],
        }, "groupByCreateTime": {"value": "day"}, "tableShowType": "table",
        "aggregate_config": {}},
    }


class DashboardTransport(PeakTransport):
    def __init__(self, chart_count):
        super().__init__(lambda request: {
            "operation_id": request["operation_id"], "request_id": request["request_id"],
            "ok": True, "status": "success",
            "data": _read(request["operation_id"], []), "error": None,
        })
        self.chart_count = chart_count
        self.read_ids = []

    def read(self, operation_id, _inputs):
        self.read_ids.append(operation_id)
        if operation_id.endswith(".tree"):
            return {"ok": True, "status": "success", "data": [{
                "id": 1, "name": "space", "folder_or_dashboard": [{
                    "id": 3, "name": "Growth", "space_id": 1,
                }],
            }]}
        if operation_id.endswith("default_to_me.get"):
            return {"ok": True, "status": "success", "data": {
                "object": {"config": {"filter": []}}
            }}
        return {"ok": True, "status": "success", "data": {
            "id": 3, "app_id": 17, "space_id": 1,
            "even_report": [_event_report(index) for index in range(self.chart_count)],
        }}

    def validate(self, _operation_id, _inputs):
        return {"ok": True, "status": "needs_live_metadata"}


class PlanBorrowedConcurrencyTests(unittest.TestCase):
    def run_case(self, sdk, execute, request, *, workers, max_items):
        adapter = PlanAdapter(execute, lambda _request, _context: None, preserve_partial=True)
        return execute_plan(
            _plan(request, workers=workers, max_items=max_items),
            adapters=PlanAdapters(composite=adapter), workspace=Workspace(),
        )

    def test_nested_borrow_is_nonblocking_and_reentrant(self):
        barrier = threading.Barrier(2)
        observed = []

        def execute(_request, context):
            barrier.wait(timeout=1)
            with context.borrow_workers(2) as outer:
                with context.borrow_workers(2) as inner:
                    observed.append((outer, inner))
            return {"ok": True, "status": "success"}

        adapter = PlanAdapter(execute, lambda *_args: None)
        plan = {
            "schema_version": "gravity.plan.v1", "budget": {"max_workers": 2},
            "nodes": [
                {"id": "a", "kind": "run", "request": {}},
                {"id": "b", "kind": "run", "request": {}},
            ],
        }
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                execute_plan, plan, adapters=PlanAdapters(run=adapter), workspace=object()
            ).result(timeout=2)
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(observed))
        self.assertTrue(all(1 <= outer == inner <= 2 for outer, inner in observed))

    def test_same_layer_adapters_cannot_multiply_borrowed_peak(self):
        transport = PeakTransport(lambda request: request)

        def execute(_request, context):
            with context.borrow_workers(6) as workers:
                requests = [
                    {"request_id": f"{context.node_id}-{index}"} for index in range(6)
                ]
                transport.batch(requests, max_workers=workers)
            return {"ok": True, "status": "success"}

        adapter = PlanAdapter(execute, lambda *_args: None)
        plan = {
            "schema_version": "gravity.plan.v1", "budget": {"max_workers": 6},
            "nodes": [
                {"id": "a", "kind": "run", "request": {}},
                {"id": "b", "kind": "run", "request": {}},
            ],
        }
        result = execute_plan(
            plan, adapters=PlanAdapters(run=adapter), workspace=object()
        )
        self.assertTrue(result["ok"])
        self.assertEqual(12, len(transport.request_ids))
        self.assertLessEqual(transport.peak, 6)

    def test_promotion_21_platform_peak_request_count_and_partial_envelope(self):
        failed = {
            "apple": ("error", "UPSTREAM_UNAVAILABLE", "upstream", True),
            "baidu": ("permission_unavailable", "PERMISSION_UNAVAILABLE", "upstream", False),
            "bilibili": ("unavailable", "NOT_IMPLEMENTED", "local", False),
        }

        def response(request):
            platform, operation = request["request_id"], request["operation_id"]
            if platform in failed:
                status, code, category, retryable = failed[platform]
                return {
                    "operation_id": operation, "request_id": platform, "ok": False,
                    "status": status, "data": None,
                    "error": {"code": code, "category": category, "retryable": retryable},
                }
            empty = platform == "alipay"
            return {
                "operation_id": operation, "request_id": platform, "ok": True,
                "status": "empty" if empty else "success",
                "data": _read(operation, [] if empty else [{"spend": 1}],
                              status="empty" if empty else "success"), "error": None,
            }

        def execute_for(transport):
            class SDK:
                def promotion_performance(self, app, start, end, **options):
                    options.pop("workspace")
                    return promotion_performance(
                        transport, Workspace().resolve_app(app), start, end, **options
                    )
            return lambda request, context: execute_promotion_performance_plan(
                SDK(), request, context
            )

        request = {
            "name": "promotion_performance", "app": "demo",
            "start": "2026-08-01", "end": "2026-08-02",
            "platforms": list(SUPPORTED_PLATFORMS), "metrics": ["spend"],
        }
        serial, concurrent = PeakTransport(response), PeakTransport(response)
        self.run_case(None, execute_for(serial), request, workers=1, max_items=42)
        result = self.run_case(None, execute_for(concurrent), request, workers=6, max_items=42)
        envelope = result["results"][0]["result"]
        item = result["results"][0]
        self.assertEqual((1, 6), (serial.peak, concurrent.peak))
        self.assertEqual(
            (21, sorted(serial.request_ids)),
            (len(concurrent.request_ids), sorted(concurrent.request_ids)),
        )
        self.assertEqual(("partial", 18, 3), (
            envelope["status"], envelope["success_count"], envelope["failure_count"]
        ))
        self.assertEqual((False, "partial", 4, False, "partial"), (
            result["ok"], result["status"], result["exit_code"],
            item["ok"], item["status"],
        ))
        components = {item["platform"]: item for item in envelope["results"]}
        self.assertEqual("empty", components["alipay"]["status"])
        self.assertEqual(
            {platform: (values[0], values[1], PROMOTION_PLATFORM_OPERATIONS[platform])
             for platform, values in failed.items()},
            {platform: (components[platform]["status"], components[platform]["error"]["code"],
                        components[platform]["operation_id"]) for platform in failed},
        )

    def test_dashboard_64_charts_and_context_13_sources_share_plan_peak(self):
        def run_dashboard(workers, chart_count):
            transport = DashboardTransport(chart_count)

            class SDK:
                def run_dashboard_analysis(self, app, ref, **options):
                    options.pop("workspace")
                    return run_dashboard_analysis(
                        transport, Workspace().resolve_app(app), ref, **options
                    )
            request = {
                "name": "dashboard_analysis", "app": "demo", "ref": 3,
                "mode": "run", "start": "2026-08-01", "end": "2026-08-02",
                "max_charts": chart_count,
            }
            result = self.run_case(
                None,
                lambda value, context: execute_dashboard_analysis_plan(SDK(), value, context),
                request, workers=workers, max_items=200,
            )
            return transport, result

        for chart_count in (32, 64):
            with self.subTest(chart_count=chart_count):
                serial_dashboard, _ = run_dashboard(1, chart_count)
                concurrent_dashboard, dashboard_result = run_dashboard(6, chart_count)
                self.assertEqual((1, 6), (serial_dashboard.peak, concurrent_dashboard.peak))
                self.assertEqual(
                    chart_count + 3,
                    len(serial_dashboard.read_ids) + len(serial_dashboard.request_ids),
                )
                self.assertEqual(
                    sorted(serial_dashboard.read_ids + serial_dashboard.request_ids),
                    sorted(concurrent_dashboard.read_ids + concurrent_dashboard.request_ids),
                )
                self.assertEqual(
                    chart_count,
                    dashboard_result["results"][0]["result"]["success_count"],
                )

        def run_context(workers):
            transport = PeakTransport(lambda request: {
                "operation_id": request["operation_id"], "request_id": request["request_id"],
                "ok": True, "status": "empty",
                "data": _read(request["operation_id"], [], status="empty"), "error": None,
            })

            class SDK:
                def analysis_context(self, app, **options):
                    options.pop("workspace")
                    return analysis_context(transport, Workspace().resolve_app(app), **options)
            request = {"name": "analysis_context", "app": "demo"}
            result = self.run_case(
                None, lambda value, context: execute_fixed_composite(SDK(), value, context),
                request, workers=workers, max_items=13,
            )
            return transport, result

        serial_context, _ = run_context(1)
        concurrent_context, context_result = run_context(6)
        self.assertEqual((1, 6), (serial_context.peak, concurrent_context.peak))
        self.assertEqual(13, len(serial_context.request_ids))
        self.assertEqual(sorted(serial_context.request_ids), sorted(concurrent_context.request_ids))
        self.assertEqual(
            [source.source for source in ANALYSIS_CONTEXT_SOURCES],
            [item["source"] for item in context_result["results"][0]["result"]["results"]],
        )

    def test_concurrent_429_publishes_cooldown_to_waiting_request(self):
        now = [0.0]
        first_http = threading.Event()
        return_429 = threading.Event()
        waiting = threading.Event()
        release = threading.Event()
        delays = []
        case = self

        class Response:
            def __init__(self, status, headers=None):
                self.status_code, self.headers = status, dict(headers or {})

            def json(self):
                return {}

        class Session:
            def __init__(self):
                self.calls = 0
                self.lock = threading.Lock()

            def request(self, *_args, **_options):
                with self.lock:
                    self.calls += 1
                    call = self.calls
                if call == 1:
                    first_http.set()
                    case.assertTrue(return_429.wait(1))
                    return Response(429, {"Retry-After": "3"})
                return Response(200)

        class Credentials:
            def get(self):
                return Credential("opaque")

        limiter = HostRateLimiter(
            clock=lambda: now[0], random_source=lambda: 0.0, interval_jitter_ratio=0.0
        )
        session = Session()

        def sleep(delay):
            delays.append(delay)
            if len(delays) == 1:
                waiting.set()
                self.assertTrue(release.wait(1))
            now[0] += delay

        runtime = GravityHttpRuntime(
            session=session, credentials=Credentials(), limiter=limiter,
            requests_per_second=10, attempts=1, sleeper=sleep,
            rate_clock=lambda: now[0], random_source=lambda: 0.0,
            interval_jitter_ratio=0.0,
            wall_clock=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            business_slots=threading.BoundedSemaphore(2),
            sql_slots=threading.BoundedSemaphore(2),
        )

        def request():
            return runtime.request(
                SQL_PROFILE, "POST", "/custom_sql/api/sql/execute",
                json_body={"sql": "SELECT 1", "tabId": "1"}, attempts=1,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            self.assertTrue(first_http.wait(1))
            second = pool.submit(request)
            self.assertTrue(waiting.wait(1))
            return_429.set()
            self.assertEqual(429, first.result(timeout=2).status_code)
            release.set()
            self.assertEqual(200, second.result(timeout=2).status_code)
        self.assertGreaterEqual(sum(delays), 3.0)
        self.assertEqual(2, len(delays))
        self.assertEqual(2, session.calls)


if __name__ == "__main__":
    unittest.main()
