import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gravity_sdk import GravitySDK, cli
from gravity_sdk.agent_capabilities import composite_capability_cards
from gravity_sdk.agent_handoff import attach_plan_node
from gravity_sdk.dashboard_snapshot_cli import dispatch_dashboard_analysis
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk import plan_dashboard_analysis_adapter as plan_adapter


class _Workspace:
    def __init__(self):
        self.calls = []

    def resolve_app(self, value):
        self.calls.append(value)
        if value != "main":
            raise KeyError(value)
        return 17


def _context(workspace, *, targets=(), fields=(), items=40):
    return AdapterContext(
        "dash", "dash", "composite", workspace, fields, targets, 1, items
    )


def _core_module(calls, result=None):
    module = types.ModuleType("gravity_sdk.dashboard_analysis")

    def prepare(*args, **kwargs):
        calls.append(("prepare", args, kwargs))
        return result or {"mode": "prepare"}

    def run(*args, **kwargs):
        calls.append(("run", args, kwargs))
        return result or {"mode": "run"}

    module.prepare_dashboard_analysis = prepare
    module.run_dashboard_analysis = run
    return module


class DashboardAnalysisSurfaceTests(unittest.TestCase):
    def test_cli_parser_and_dispatch_preserve_modes_and_bounds(self):
        base = [
            "analysis", "dashboard", "run", "--app", "main", "--ref", "Overview",
            "--start", "2026-08-01", "--end", "2026-08-08",
            "--concurrency", "4", "--max-charts", "12", "--max-items", "90",
        ]
        args = cli.build_parser().parse_args(base)
        self.assertTrue(args.network_required)
        calls, workspace, client = [], object(), object()
        with (
            patch.dict(sys.modules, {"gravity_sdk.dashboard_analysis": _core_module(calls)}),
            patch("gravity_sdk.dashboard_snapshot_cli.load_workspace", return_value=workspace),
            patch("gravity_sdk.dashboard_snapshot_cli.resolve_workspace_app", return_value=17),
            patch("gravity_sdk.dashboard_snapshot_cli.runtime.build_client", return_value=client),
        ):
            result = dispatch_dashboard_analysis(args, None)
        self.assertEqual({"mode": "run"}, result)
        self.assertEqual((client, 17, "Overview"), calls[0][1])
        self.assertEqual(
            {"start": "2026-08-01", "end": "2026-08-08", "max_workers": 4,
             "max_charts": 12, "max_items": 90}, calls[0][2]
        )
        with self.assertRaises(InputValidationError):
            cli.build_parser().parse_args([*base[:-4], "--max-charts", "65"])

    def test_sdk_resolves_app_before_lazy_client_for_prepare_and_run(self):
        order, calls = [], []

        class Workspace(_Workspace):
            def resolve_app(self, value):
                order.append(("app", value))
                return 17

        insight = object()
        sdk = GravitySDK(
            insight_factory=lambda: (order.append(("insight", None)), insight)[1],
            workspace=Workspace(),
        )
        with patch.dict(sys.modules, {"gravity_sdk.dashboard_analysis": _core_module(calls)}):
            sdk.prepare_dashboard_analysis(
                "main", 8, start="2026-08-01", end="2026-08-08", max_charts=9
            )
            sdk.run_dashboard_analysis(
                "main", 8, start="2026-08-01", end="2026-08-08",
                max_workers=4, max_charts=9,
            )
        self.assertEqual([("app", "main"), ("insight", None), ("app", "main")], order)
        self.assertEqual(["prepare", "run"], [call[0] for call in calls])
        self.assertEqual(4, calls[1][2]["max_workers"])

    def test_plan_preflight_is_offline_literal_and_budgeted(self):
        workspace = _Workspace()
        request = {
            "name": "dashboard_analysis", "app": "main", "ref": "Overview",
            "mode": "run", "start": "2026-08-01", "end": "2026-08-08",
        }
        plan_adapter.validate_dashboard_analysis_plan(
            request, _context(workspace), workspace
        )
        self.assertEqual(["main"], workspace.calls)
        plan_adapter.validate_dashboard_analysis_plan(
            {**request, "app": None},
            _context(workspace, targets=("/app",)),
            workspace,
        )
        invalid = (
            ({**request, "x": 1}, _context(workspace)),
            ({**request, "mode": "guess"}, _context(workspace)),
            ({**request, "end": "2026-07-01"}, _context(workspace)),
            ({**request, "end": "2026-11-01"}, _context(workspace)),
            (request, _context(workspace, targets=("/ref",))),
            (request, _context(workspace, items=2)),
            (request, _context(workspace, fields=("config",))),
        )
        for value, context in invalid:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                plan_adapter.validate_dashboard_analysis_plan(value, context, workspace)

    def test_plan_execution_forces_one_worker_and_scrubs_artifacts(self):
        native = {
            "schema_version": "gravity-insight.dashboard-analysis.v1",
            "ok": True, "status": "success", "exit_code": 0, "app_id": 17,
            "dashboard": {"id": 8}, "mode": "run", "chart_count": 1,
            "charts": [{"index": 0, "name": "Revenue", "supported": True,
                        "query_executed": True, "result": {"data": []},
                        "date_override_applied": False,
                        "limitations": ["property analysis has no date window"],
                        "error": {"code": "X", "category": "local",
                                  "message": "C:/private/original exception"},
                        "config": "private", "request": {"token": "secret"}}],
            "config": "private", "request": {"token": "secret"},
        }
        run = Mock(return_value=native)
        workspace = _Workspace()
        context = _context(workspace, fields=("dashboard", "charts"), items=18)
        result = plan_adapter.execute_dashboard_analysis_plan(
            SimpleNamespace(run_dashboard_analysis=run),
            {"name": "dashboard_analysis", "app": "main", "ref": 8, "mode": "run",
             "start": "2026-08-01", "end": "2026-08-08"},
            context,
        )
        self.assertEqual(1, run.call_args.kwargs["max_workers"])
        self.assertEqual(16, run.call_args.kwargs["max_charts"])
        projected = plan_adapter.project_dashboard_analysis_result(
            result, context.output_fields, context
        )
        self.assertEqual({"dashboard", "charts"}, set(projected) - {
            "schema_version", "ok", "status", "exit_code"
        })
        self.assertNotIn("private", str(projected))
        self.assertNotIn("secret", str(projected))
        self.assertFalse(projected["charts"][0]["date_override_applied"])
        self.assertEqual(1, len(projected["charts"][0]["limitations"]))

    def test_agent_routes_chart_replay_without_colliding_with_snapshot(self):
        cases = (
            ("run dashboard charts", "dashboard_analysis", ["app", "ref", "start", "end"]),
            ("重放看板图表", "dashboard_analysis", ["app", "ref", "start", "end"]),
            ("inspect dashboard members and filters", "dashboard_snapshot", ["app", "ref"]),
        )
        for query, expected, missing in cases:
            with self.subTest(query=query):
                cards = composite_capability_cards(query, domain=None, platform=None)
                self.assertEqual(1, len(cards))
                card = attach_plan_node(cards[0], query)
                self.assertEqual(expected, card["composite"])
                self.assertEqual(missing, card["missing_inputs"])
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertEqual(expected, card["plan_node"]["request"]["name"])


if __name__ == "__main__":
    unittest.main()
