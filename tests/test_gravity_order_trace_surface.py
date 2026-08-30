import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import gravity_insight
from gravity_insight import cli
from gravity_insight.onboarding import command_requires_credentials
from gravity_insight.order_trace_result import success_result
from gravity_insight.order_directory_result import success_result as directory_success
from gravity_insight.plan import AdapterContext, execute_plan
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.plan_order_trace_adapter import project_order_split_trace_result, validate_order_split_trace_plan
from gravity_insight.plan_order_directory_adapter import project_order_directory_result, validate_order_directory_plan
from gravity_insight.sdk import GravitySDK

BASE = ["analysis", "order", "trace", "--app", "main", "--date", "2026-08-08",
        "--trace-id", "trace-secret", "--max-pages", "5", "--max-items", "10"]
DIRECTORY_BASE = ["analysis", "order", "directory", "--app", "main", "--date", "2026-08-08", "--max-pages", "5", "--max-items", "10"]

class _Workspace:
    def resolve_app(self, value=None):
        if value in {7, "7", "main"}:
            return 7
        raise ValueError("unknown app")


class _Insight:
    @staticmethod
    def operations(**_kwargs):
        return []

def _result(app_id="7"):
    return success_result(
        app_id=app_id, date="2026-08-08",
        rows=[{"Amount": 2, "BackAmount": 0, "Status": "paid", "CreateTime": "now"}],
        scanned_items=2, split_id_count=1, max_pages=5, max_items=10,
        max_workers=1, parent_stage="success", child_stage="success")

class _SDK:
    workspace, insight = _Workspace(), _Insight()

    def __init__(self, result=None):
        self.result, self.calls = result or _result(), []

    def order_split_trace(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return copy.deepcopy(self.result)


def _directory_result(app="7", workers=1):
    row = {"CreateTime": "now", "Amount": 2, "BackAmount": 0, "Status": "paid"}
    row["CreateTime"] = "2026-08-08 01:00:00"
    page = {"number": 1, "size": 100, "item_count": 1, "total_pages": 1,
            "total_items": 1, "has_more": False, "pages_fetched": 1}
    return directory_success(app_id=app, date="2026-08-08", rows=[row], page=page,
                             max_pages=5, max_items=10, max_workers=workers)

class _DirectorySDK:
    workspace, insight = _Workspace(), _Insight()
    def __init__(self, result=None):
        self.result, self.calls = result or _directory_result(), []
    def order_directory(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return copy.deepcopy(self.result)

def _request():
    return {"name": "order_split_trace", "app": "main", "date": "2026-08-08",
            "trace_id": "trace-secret"}


def _context(dynamic=(), fields=()):
    return AdapterContext("trace", "trace", "composite", _Workspace(), tuple(fields),
                          tuple(dynamic), 5, 10)

class OrderTraceSurfaceTests(unittest.TestCase):
    def test_root_dry_run_is_not_an_order_preview(self):
        for base, module in ((BASE, "order_trace_cli"), (DIRECTORY_BASE, "order_directory_cli")):
            with self.subTest(command=base[2]), patch(f"gravity_insight.{module}.runtime.build_client") as factory:
                args = cli.build_parser().parse_args(["--dry-run", *base])
                self.assertFalse(command_requires_credentials(["--dry-run", *base], cli.build_parser))
                with self.assertRaisesRegex(ValueError, "--dry-run cannot be combined"):
                    args._gravity_handler(args, lambda _: {})
                factory.assert_not_called()

    def test_cli_json_only_preflight_and_sdk_lazy_delegate(self):
        parser, selected = cli.build_parser(), cli.build_parser().parse_args(BASE)
        self.assertEqual(("order", "trace", 6),
                         (selected.analysis_command, selected.order_command, selected.concurrency))
        for flag in ("--format", "--output"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                parser.parse_args([*BASE, flag, "ndjson"])
        invalid = [*BASE[:6], "bad", *BASE[7:]]
        with patch("gravity_insight.order_trace_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_insight.order_trace_cli.runtime.build_client") as factory:
            self.assertTrue(command_requires_credentials(BASE, cli.build_parser))
            self.assertFalse(command_requires_credentials(invalid, cli.build_parser))
            with self.assertRaises(ValueError):
                parser.parse_args(invalid)._gravity_handler(parser.parse_args(invalid), lambda _: {})
        factory.assert_not_called()
        client, factory = object(), Mock()
        with patch("gravity_insight.order_trace_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_insight.order_trace_cli.runtime.build_client", return_value=client), \
             patch("gravity_insight.order_trace.order_split_trace", return_value=_result()) as core:
            selected._gravity_handler(selected, lambda _: {})
        core.assert_called_once_with(client, "7", "2026-08-08", "trace-secret",
                                     max_workers=6, max_pages=5, max_items=10)
        sdk = GravitySDK(insight_factory=factory, workspace=_Workspace())
        with self.assertRaises(ValueError):
            sdk.order_split_trace("main", "bad", "trace-secret")
        factory.assert_not_called()
        factory.return_value = client
        with patch("gravity_insight.order_trace.order_split_trace", return_value=_result()) as core:
            sdk.order_split_trace("main", "2026-08-08", "trace-secret", max_pages=5, max_items=10)
        core.assert_called_once_with(client, "7", "2026-08-08", "trace-secret",
                                     max_workers=6, max_pages=5, max_items=10)

    def test_plan_scalar_targets_worker_one_receipts_and_dry_run(self):
        validate_order_split_trace_plan(_request(), _context(("/app", "/date", "/trace_id")), _Workspace())
        with self.assertRaises(ValueError):
            validate_order_split_trace_plan(_request(), _context(("/data",)), _Workspace())
        sdk = _SDK()
        adapter, context = build_plan_adapters(sdk).composite, _context(fields=("data",))
        safe = adapter.execute(_request(), context)
        self.assertEqual(("7", "2026-08-08", 1),
                         (safe["app_id"], safe["date"], sdk.calls[0][1]["max_workers"]))
        projected = adapter.project(safe, ("data",), context)
        self.assertEqual(("7", "2026-08-08", 1),
                         (projected["app_id"], projected["date"], len(projected["data"]["list"])))
        drift = build_plan_adapters(_SDK(_result("8"))).composite.execute(_request(), _context())
        fake = project_order_split_trace_result(_result(), (), _context())
        self.assertEqual(("contract_changed", [], "contract_changed"),
                         (drift["status"], drift["data"]["list"], fake["status"]))
        self.assertNotIn("trace-secret", str(drift))
        plan = {"schema_version": "gravity.plan.v1", "nodes": [{"id": "trace",
                "kind": "composite", "request": _request(),
                "limits": {"max_pages": 5, "max_items": 10}}]}
        dry_sdk = _SDK()
        result = execute_plan(plan, adapters={"composite": build_plan_adapters(dry_sdk).composite},
                              workspace=_Workspace(), dry_run=True)
        self.assertEqual(("validated", []), (result["status"], dry_sdk.calls))


class OrderDirectorySurfaceTests(unittest.TestCase):
    def test_cli_sdk_onboarding_and_public_surface_are_preflighted(self):
        parser, selected = cli.build_parser(), cli.build_parser().parse_args(DIRECTORY_BASE)
        self.assertEqual(("order", "directory", 6), (selected.analysis_command, selected.order_command, selected.concurrency))
        with self.assertRaises(ValueError): parser.parse_args([*DIRECTORY_BASE, "--format", "ndjson"])
        invalid = [*DIRECTORY_BASE[:6], "bad", *DIRECTORY_BASE[7:]]
        unknown = [*DIRECTORY_BASE]; unknown[4] = "missing"
        invalid_outputs = ([*DIRECTORY_BASE, "--output", "-"], [*DIRECTORY_BASE, "--output", "."],
                           [*DIRECTORY_BASE, "--output", "pyproject.toml/child.json"])
        with patch("gravity_insight.order_directory_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_insight.order_directory_cli.runtime.build_client") as client_factory:
            self.assertTrue(command_requires_credentials(DIRECTORY_BASE, cli.build_parser))
            self.assertFalse(command_requires_credentials(invalid, cli.build_parser)); self.assertFalse(command_requires_credentials(unknown, cli.build_parser))
            for argv in invalid_outputs: self.assertFalse(command_requires_credentials(argv, cli.build_parser))
            with self.assertRaises(ValueError):
                args = parser.parse_args(invalid); args._gravity_handler(args, lambda _: {})
            with self.assertRaises(ValueError):
                args = parser.parse_args(unknown); args._gravity_handler(args, lambda _: {})
        client_factory.assert_not_called()
        client = object()
        with patch("gravity_insight.order_directory_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_insight.order_directory_cli.runtime.build_client", return_value=client), \
             patch("gravity_insight.order_directory.order_directory", return_value=_directory_result()) as core:
            selected._gravity_handler(selected, lambda _: {})
        core.assert_called_once_with(client, "7", "2026-08-08", max_workers=6, max_pages=5, max_items=10)
        factory, workspace = Mock(return_value=client), Mock(wraps=_Workspace())
        sdk = GravitySDK(insight_factory=factory, workspace=workspace)
        with self.assertRaises(ValueError): sdk.order_directory("main", "bad")
        for app in (0, -1, 1 << 513):
            with self.subTest(app=app), self.assertRaises(ValueError): sdk.order_directory(app, "2026-08-08")
        with self.assertRaises(ValueError): sdk.order_directory("main", "2026-08-08", max_workers=25)
        factory.assert_not_called(); workspace.resolve_app.assert_not_called()
        with patch("gravity_insight.order_directory.order_directory", return_value=_directory_result()):
            sdk.order_directory("main", "2026-08-08", max_pages=5, max_items=10)
        self.assertLessEqual({"order_directory", "validate_order_directory_request"}, set(gravity_insight.__all__))
        self.assertNotIn("sanitize_order_directory_result", gravity_insight.__all__)

    def test_cli_json_file_preserves_more_than_stdout_row_limit(self):
        rows = [{"CreateTime": "2026-08-08", "Amount": i, "BackAmount": 0, "Status": "paid"} for i in range(201)]
        complete = _directory_result(); complete["data"]["list"] = rows; complete["returned_items"] = 201
        with tempfile.TemporaryDirectory() as folder:
            output = f"{folder}/orders.json"; argv = [*DIRECTORY_BASE, "--output", output]
            with patch("gravity_insight.order_directory_cli.load_workspace", return_value=_Workspace()), \
                 patch("gravity_insight.order_directory_cli.runtime.build_client", return_value=object()), \
                 patch("gravity_insight.order_directory.order_directory", return_value=complete):
                self.assertEqual(0, cli.main(argv))
            with open(output, encoding="utf-8") as stream: written = json.load(stream)
        self.assertEqual((201, 200), (len(written["data"]["list"]), written["data"]["list"][200]["Amount"]))

    def test_plan_revalidates_and_sanitizes_actual_core_receipts(self):
        request = {"name": "order_directory", "app": "main", "date": "2026-08-08"}
        validate_order_directory_plan(request, _context(("/app", "/date")), _Workspace())
        for missing in ("app", "date"):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_order_directory_plan({key: value for key, value in request.items() if key != missing}, _context((f"/{missing}",)), _Workspace())
        with self.assertRaises(ValueError): validate_order_directory_plan(request, _context(("/data",)), _Workspace())
        sdk, adapter = _DirectorySDK(), build_plan_adapters(_DirectorySDK()).composite
        bad = {**request, "date": "bad"}
        validate_order_directory_plan(bad, _context(("/date",)), _Workspace())
        with self.assertRaises(ValueError): adapter.execute(bad, _context(("/date",)))
        adapter = build_plan_adapters(sdk).composite
        safe = adapter.execute(request, _context(fields=("data",)))
        self.assertEqual(("7", 1), (safe["app_id"], sdk.calls[0][1]["max_workers"]))
        self.assertEqual(1, len(adapter.project(safe, ("data",), _context())["data"]["list"]))
        mutations = ({"app_id": "8"}, {"app_id": []}, {"date": {}}, {"status": []},
                     {"limits": []}, {"page": []}, {"schema_version": "unknown"},
                     {"limits": {"max_pages": 5, "max_items": 10, "max_workers": 6}})
        for mutation in mutations:
            forged = copy.deepcopy(_directory_result()); forged.update(mutation)
            with self.subTest(mutation=mutation):
                failed = build_plan_adapters(_DirectorySDK(forged)).composite.execute(request, _context())
                self.assertEqual(("contract_changed", "7", "2026-08-08", 1, None, []),
                                 (failed["status"], failed["app_id"], failed["date"],
                                  failed["limits"]["max_workers"], failed["page"], failed["data"]["list"]))
        malformed = project_order_directory_result({"app_id": [], "date": {}}, (), _context())
        self.assertEqual("contract_changed", malformed["status"])
        plan = {"schema_version": "gravity.plan.v1", "nodes": [{"id": "directory", "kind": "composite", "request": request,
                "limits": {"max_pages": 5, "max_items": 10}}]}
        dry = _DirectorySDK()
        receipt = execute_plan(plan, adapters={"composite": build_plan_adapters(dry).composite}, workspace=_Workspace(), dry_run=True)
        self.assertEqual(("validated", []), (receipt["status"], dry.calls))
        live = execute_plan(plan, adapters={"composite": adapter}, workspace=_Workspace())
        self.assertEqual(("success", 1), (live["status"], len(live["results"][0]["result"]["data"]["list"])))


if __name__ == "__main__":
    unittest.main()
