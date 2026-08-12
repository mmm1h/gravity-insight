import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk import cli
from gravity_sdk import plan_segment_snapshot_adapter as plan_subject
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.segment_snapshot import SCHEMA_VERSION
from gravity_sdk.segment_spec_cli import run_segment_command


class _Workspace:
    def __init__(self): self.calls = []
    def resolve_app(self, value):
        self.calls.append(value)
        if value != "main": raise KeyError(value)
        return 17


def _context(workspace, *, targets=(), fields=(), items=20):
    return AdapterContext("segment", "segment", "composite", workspace,
                          fields, targets, 5, items)


class SegmentSnapshotSurfaceTests(unittest.TestCase):
    def test_cli_and_sdk_bind_app_before_one_shared_product_call(self):
        parsed = cli.build_parser().parse_args([
            "analysis", "segment", "snapshot", "--app", "main",
            "--ref", "Buyers", "--date", "2026-08-12",
            "--concurrency", "2", "--max-pages", "3", "--max-items", "30",
            "--output", "result.json",
        ])
        self.assertEqual(("snapshot", "result.json"),
                         (parsed.segment_action, parsed.output))
        workspace = _Workspace()
        expected = {"schema_version": SCHEMA_VERSION, "ok": True}
        with (
            patch("gravity_sdk.segment_spec_cli.load_workspace", return_value=workspace),
            patch("gravity_sdk.segment_spec_cli.resolve_workspace_app", return_value=17) as resolve,
            patch("gravity_sdk.segment_spec_cli.segment_snapshot", return_value=expected) as snapshot,
        ):
            result = run_segment_command(parsed, lambda: object(), lambda _v: {}, lambda *_a, **_k: {})
        self.assertIs(expected, result)
        resolve.assert_called_once_with(workspace, "main")
        self.assertEqual((17, "Buyers"), snapshot.call_args.args[1:])
        self.assertEqual({"date": "2026-08-12", "max_workers": 2,
                          "max_pages": 3, "max_items": 30}, snapshot.call_args.kwargs)

        order = []
        sdk = GravitySDK(
            workspace=workspace,
            insight_factory=lambda: (order.append("insight"), object())[1],
        )
        with patch("gravity_sdk.segment_snapshot.segment_snapshot", return_value=expected) as facade:
            self.assertIs(expected, sdk.segment_snapshot(
                "main", 8, date="2026-08-12", max_workers=2,
                max_pages=3, max_items=30,
            ))
        self.assertEqual(["insight"], order)
        facade.assert_called_once_with(
            sdk.insight, 17, 8, date="2026-08-12", max_workers=2,
            max_pages=3, max_items=30,
        )

    def test_plan_preflight_is_offline_exact_and_execution_uses_one_worker(self):
        workspace = _Workspace()
        request = {"name": "segment_snapshot", "app": "main",
                   "ref": 8, "date": "2026-08-12"}
        plan_subject.validate_segment_snapshot_plan(request, _context(workspace), workspace)
        self.assertEqual(["main"], workspace.calls)
        plan_subject.validate_segment_snapshot_plan(
            {**request, "app": "<bound>"},
            _context(workspace, targets=("/app",)), workspace,
        )
        invalid = (
            ({**request, "extra": 1}, _context(workspace)),
            ({**request, "date": "2026-8-2"}, _context(workspace)),
            ({**request, "ref": ""}, _context(workspace)),
            (request, _context(workspace, targets=("/ref",))),
            (request, _context(workspace, items=3)),
            (request, _context(workspace, fields=("ref",))),
        )
        for value, context in invalid:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                plan_subject.validate_segment_snapshot_plan(value, context, workspace)

        calls = []
        native = {
            "schema_version": SCHEMA_VERSION, "ok": False, "status": "partial",
            "exit_code": 3, "total_count": 3, "success_count": 2,
            "failure_count": 1, "app_id": 17, "segment": {"id": "8"},
            "date": "2026-08-12", "results": [{"ok": False, "error": {
                "code": "UPSTREAM_UNAVAILABLE", "category": "upstream",
                "message": "C:/private/raw boom"}}], "scopes": ["segment"],
            "source_count": 3, "ref": "private-ref",
        }
        sdk = SimpleNamespace(segment_snapshot=lambda app, ref, **options:
                              (calls.append((app, ref, options)), native)[1])
        context = _context(workspace, fields=("segment", "results"), items=40)
        safe = plan_subject.execute_segment_snapshot_plan(sdk, request, context)
        self.assertEqual(1, calls[0][2]["max_workers"])
        self.assertEqual((5, 40), (calls[0][2]["max_pages"], calls[0][2]["max_items"]))
        self.assertEqual(("upstream", "UPSTREAM_UNAVAILABLE"),
                         (safe["error"]["category"], safe["error"]["code"]))
        projected = plan_subject.project_segment_snapshot_result(
            safe, context.output_fields, context
        )
        self.assertEqual({"segment", "results"},
                         set(projected) & plan_subject.SEGMENT_SNAPSHOT_OUTPUT_FIELDS)
        self.assertNotIn("private", str(projected).casefold())


if __name__ == "__main__":
    unittest.main()
