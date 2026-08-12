import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import GravitySDK, cli
from gravity_sdk import plan_saved_analysis_adapter as subject
from gravity_sdk.errors import (
    InputValidationError,
    PaginationError,
    UnsupportedOperationError,
)
from gravity_sdk.onboarding import command_requires_credentials
from gravity_sdk.plan import AdapterContext
from gravity_sdk.saved_analysis import REPLAY_SCHEMA_VERSION
from gravity_sdk.saved_analysis_cli import dispatch_saved_analysis


class _Workspace:
    def __init__(self): self.calls = []
    def resolve_app(self, value):
        self.calls.append(value)
        if value != "main": raise KeyError(value)
        return 17


def _context(workspace, *, targets=(), fields=(), max_items=200):
    return AdapterContext("saved", "saved", "composite", workspace,
                          fields, targets, 5, max_items)


class SavedAnalysisSurfaceTests(unittest.TestCase):
    def test_cli_and_sdk_validate_then_forward_explicit_window(self):
        argv = ["analysis", "saved", "run", "--app", "main", "--ref", "Daily",
                "--start", "2026-08-01", "--end", "2026-08-07",
                "--max-pages", "5", "--max-items", "200"]
        args, workspace, client = cli.build_parser().parse_args(argv), _Workspace(), object()
        expected = {"schema_version": REPLAY_SCHEMA_VERSION, "ok": True}
        with (patch("gravity_sdk.saved_analysis_cli.load_workspace", return_value=workspace),
              patch("gravity_sdk.saved_analysis_cli.runtime.build_client", return_value=client),
              patch("gravity_sdk.saved_analysis_cli.execute_saved_analysis",
                    return_value=expected) as run):
            self.assertIs(expected, dispatch_saved_analysis(args, lambda _value: {}))
        self.assertEqual((client,), run.call_args.args)
        self.assertEqual(("Daily", "2026-08-01", "2026-08-07"), tuple(
            run.call_args.kwargs[key] for key in ("reference", "start", "end")))

        incomplete = cli.build_parser().parse_args(
            ["analysis", "saved", "run", "--app", "main", "--ref", ""])
        with (patch("gravity_sdk.saved_analysis_cli.runtime.build_client",
                    side_effect=AssertionError("must stay local")),
              self.assertRaises(InputValidationError)):
            dispatch_saved_analysis(incomplete, lambda _value: {})
        excessive = cli.build_parser().parse_args(
            ["analysis", "saved", "list", "--app", "main", "--max-pages", "1001"])
        with (patch("gravity_sdk.saved_analysis_cli.runtime.build_client",
                    side_effect=AssertionError("must stay local")),
              self.assertRaises(InputValidationError)):
            dispatch_saved_analysis(excessive, lambda _value: {})
        self.assertTrue(command_requires_credentials(
            ["analysis", "saved", "run", "--app", "17", "--ref", "Daily"],
            cli.build_parser))
        self.assertTrue(command_requires_credentials(
            [value if value != "main" else "17" for value in argv], cli.build_parser))
        self.assertFalse(command_requires_credentials(
            ["analysis", "saved", "run", "--app", "main", "--ref", "Daily",
             "--start", "bad", "--end", "2026-08-07"], cli.build_parser))
        self.assertFalse(command_requires_credentials(
            ["analysis", "saved", "list", "--app", "main", "--output", "-"],
            cli.build_parser))
        self.assertFalse(command_requires_credentials(
            ["analysis", "saved", "list", "--app", ""], cli.build_parser))
        self.assertFalse(command_requires_credentials(
            ["analysis", "saved", "list", "--app", "bad-alias"], cli.build_parser))
        for invalid_definition in ("{}", '{"subject":"analysis_cash","config":{}}'):
            self.assertFalse(command_requires_credentials(
                ["analysis", "saved", "run", "--app", "main", "--definition",
                 invalid_definition], cli.build_parser))
            invalid = cli.build_parser().parse_args(
                ["analysis", "saved", "run", "--app", "main", "--definition",
                 invalid_definition])
            with (patch("gravity_sdk.saved_analysis_cli.runtime.build_client",
                        side_effect=AssertionError("must stay local")),
                  self.assertRaises((InputValidationError, UnsupportedOperationError))):
                dispatch_saved_analysis(invalid, json.loads)

        order = []
        sdk = GravitySDK(workspace=workspace,
                         insight_factory=lambda: (order.append("insight"), client)[1])
        with patch("gravity_sdk.saved_analysis.execute_saved_analysis",
                   return_value=expected) as facade:
            self.assertIs(expected, sdk.run_saved_analysis(
                "main", "Daily", start="2026-08-01", end="2026-08-07",
                max_pages=5, max_items=200))
        self.assertEqual((17, "2026-08-01", ["insight"]),
                         (facade.call_args.kwargs["app"],
                          facade.call_args.kwargs["start"], order))
        lazy = GravitySDK(workspace=workspace,
                          insight_factory=lambda: self.fail("must stay local"))
        with self.assertRaises(InputValidationError):
            lazy.run_saved_analysis("main", "Daily", start="2026-08-01")
        with self.assertRaises(InputValidationError):
            lazy.saved_analyses("main", max_items=100_001)

    def test_plan_is_literal_except_app_and_scrubs_artifact_inputs(self):
        workspace, request = _Workspace(), {
            "name": "saved_analysis", "app": "main", "ref": "Daily", "mode": "run",
            "start": "2026-08-01", "end": "2026-08-07"}
        subject.validate_saved_analysis(request, _context(workspace), workspace, frozenset())
        subject.validate_saved_analysis(
            {**request, "app": "<bound>"}, _context(workspace, targets=("/app",)),
            workspace, frozenset())
        invalid = (({**request, "end": "2026-11-30"}, _context(workspace)),
                   (request, _context(workspace, targets=("/ref",))),
                   (request, _context(workspace, fields=("config",))))
        for value, context in invalid:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                subject.validate_saved_analysis(value, context, workspace, frozenset())

        native = {
            "schema_version": REPLAY_SCHEMA_VERSION, "ok": True, "status": "success",
            "exit_code": 0, "source": "catalog", "network_called": True,
            "definition_network_called": True, "query_executed": True,
            "saved_analysis": {"id": "8", "name": "Daily", "subject": "analysis_event",
                               "app_id": "17", "kind": "event",
                               "subject_supported": True, "replay_supported": True,
                               "config": "private"},
            "artifact_mode": "web_artifact", "kind": "event",
            "operation_id": "analysis.event.query",
            "date_range": {"start": "2026-08-01", "end": "2026-08-07"},
            "limitations": ["dashboard conditions are not applied"],
            "validation": {"status": "needs_live_metadata",
                           "live_metadata_dependencies": ["analysis.event.list"]},
            "result": {"schema_version": "gravity-insight.read.v1", "ok": True,
                       "status": "success", "operation_id": "analysis.event.query",
                       "data": {"list": [{"count": 3}]},
                       "request": {"token": "private-token"}},
            "request": {"calculateBody": "private"}}
        context = _context(workspace, fields=("saved_analysis", "result", "limitations"))
        safe = subject.execute_saved_analysis_plan(
            SimpleNamespace(run_saved_analysis=lambda *args, **kwargs: native),
            request, context)
        projected = subject.project_saved_analysis_result(
            safe, context.output_fields, context)
        self.assertEqual(("gravity-insight.read.v1", 3),
                         (projected["result"]["schema_version"],
                          projected["result"]["data"]["list"][0]["count"]))
        self.assertNotIn("private", str(projected).casefold())
        self.assertNotIn("calculatebody", str(projected).casefold())

        retention = {**native, "kind": "retention",
            "operation_id": "analysis.retention.query",
            "saved_analysis": {**native["saved_analysis"], "kind": "retention",
                               "subject": "analysis_retention"},
            "result": {**native["result"], "operation_id": "analysis.retention.query",
                       "data": {"total": [{}, {}]}}}
        with self.assertRaises(PaginationError):
            subject.execute_saved_analysis_plan(
                SimpleNamespace(run_saved_analysis=lambda *args, **kwargs: retention),
                request, _context(workspace, max_items=1))

        poisoned = {**native, "result": {**native["result"],
            "status": "C:/private/status", "retryable": {"secret": "x"},
            "retry_after_ms": "D:/private/raw", "operation_id": "analysis.funnel.query"}}
        rejected = subject.safe_saved_analysis_envelope(poisoned)
        self.assertEqual((False, "contract_changed", 3),
                         (rejected["ok"], rejected["status"], rejected["exit_code"]))
        self.assertNotIn("private", str(rejected).casefold())
        drifted = {**native, "saved_analysis": {
            **native["saved_analysis"], "id": "9", "name": "Other", "app_id": "99"
        }, "date_range": {"start": "2026-09-01", "end": "2026-09-07"}}
        bound = subject.execute_saved_analysis_plan(
            SimpleNamespace(run_saved_analysis=lambda *args, **kwargs: drifted),
            request, context)
        self.assertEqual((False, "contract_changed"), (bound["ok"], bound["status"]))

    def test_saved_catalog_ndjson_writes_every_item(self):
        catalog = {
            "schema_version": "gravity-insight.saved-analysis-catalog.v1",
            "status": "success", "count": 201,
            "items": [{"id": str(index)} for index in range(201)],
        }
        lines = list(cli._iter_ndjson_lines(catalog))
        terminal = json.loads(lines[-1])["_gravity_insight"]
        self.assertEqual((202, 201, False), (
            len(lines), terminal["rows_written"], terminal["truncated"]
        ))


if __name__ == "__main__": unittest.main()
