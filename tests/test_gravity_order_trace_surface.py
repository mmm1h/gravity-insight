import copy
import unittest
from unittest.mock import Mock, patch

from gravity_sdk import cli
from gravity_sdk.onboarding import command_requires_credentials
from gravity_sdk.order_trace_result import success_result
from gravity_sdk.plan import AdapterContext, execute_plan
from gravity_sdk.plan_adapters import build_plan_adapters
from gravity_sdk.plan_order_trace_adapter import project_order_split_trace_result, validate_order_split_trace_plan
from gravity_sdk.sdk import GravitySDK

BASE = ["analysis", "order", "trace", "--app", "main", "--date", "2026-08-08",
        "--trace-id", "trace-secret", "--max-pages", "5", "--max-items", "10"]

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

def _request():
    return {"name": "order_split_trace", "app": "main", "date": "2026-08-08",
            "trace_id": "trace-secret"}


def _context(dynamic=(), fields=()):
    return AdapterContext("trace", "trace", "composite", _Workspace(), tuple(fields),
                          tuple(dynamic), 5, 10)

class OrderTraceSurfaceTests(unittest.TestCase):
    def test_cli_json_only_preflight_and_sdk_lazy_delegate(self):
        parser, selected = cli.build_parser(), cli.build_parser().parse_args(BASE)
        self.assertEqual(("order", "trace", 6),
                         (selected.analysis_command, selected.order_command, selected.concurrency))
        for flag in ("--format", "--output"):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                parser.parse_args([*BASE, flag, "ndjson"])
        invalid = [*BASE[:6], "bad", *BASE[7:]]
        with patch("gravity_sdk.order_trace_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_sdk.order_trace_cli.runtime.build_client") as factory:
            self.assertTrue(command_requires_credentials(BASE, cli.build_parser))
            self.assertFalse(command_requires_credentials(invalid, cli.build_parser))
            with self.assertRaises(ValueError):
                parser.parse_args(invalid)._gravity_handler(parser.parse_args(invalid), lambda _: {})
        factory.assert_not_called()
        client, factory = object(), Mock()
        with patch("gravity_sdk.order_trace_cli.load_workspace", return_value=_Workspace()), \
             patch("gravity_sdk.order_trace_cli.runtime.build_client", return_value=client), \
             patch("gravity_sdk.order_trace.order_split_trace", return_value=_result()) as core:
            selected._gravity_handler(selected, lambda _: {})
        core.assert_called_once_with(client, "7", "2026-08-08", "trace-secret",
                                     max_workers=6, max_pages=5, max_items=10)
        sdk = GravitySDK(insight_factory=factory, workspace=_Workspace())
        with self.assertRaises(ValueError):
            sdk.order_split_trace("main", "bad", "trace-secret")
        factory.assert_not_called()
        factory.return_value = client
        with patch("gravity_sdk.order_trace.order_split_trace", return_value=_result()) as core:
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


if __name__ == "__main__":
    unittest.main()
