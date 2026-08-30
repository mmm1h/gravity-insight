import unittest
from types import SimpleNamespace

from gravity_insight import plan_dashboard_snapshot_adapter as subject
from gravity_insight.dashboard_snapshot import SCHEMA_VERSION
from gravity_insight.errors import InputValidationError
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_execution import detail_exit_code, safe_native_error


class _Workspace:
    def __init__(self): self.calls = []
    def resolve_app(self, value):
        self.calls.append(value)
        if value is None: return 17
        if value != "demo": raise KeyError(value)
        return 17


def _context(workspace, *, targets=(), fields=(), items=7):
    return AdapterContext("dash", "dash", "composite", workspace, fields, targets, 3, items)


class DashboardSnapshotPlanTests(unittest.TestCase):
    def test_preflight_is_local_bounded_and_binding_targets_are_exact(self):
        workspace = _Workspace()
        request = {"name": "dashboard_snapshot", "app": "demo", "ref": 8}
        subject.validate_dashboard_snapshot_plan(request, _context(workspace), workspace)
        self.assertEqual(["demo"], workspace.calls)
        subject.validate_dashboard_snapshot_plan(
            {"name": "dashboard_snapshot"}, _context(workspace, targets=("/app", "/ref")), workspace)
        invalid = [
            ({**request, "x": 1}, _context(workspace)),
            (request, _context(workspace, targets=("/name",))),
            (request, _context(workspace, items=6)),
            ({"name": "dashboard_snapshot", "ref": 8}, _context(workspace)),
            ({"name": "dashboard_snapshot", "app": "demo"}, _context(workspace)),
            ({**request, "app": None}, _context(workspace)),
            ({**request, "ref": ""}, _context(workspace)),
            (request, _context(workspace, fields=("ref",))),
        ]
        for value, context in invalid:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                subject.validate_dashboard_snapshot_plan(value, context, workspace)

    def test_execution_forces_one_worker_and_projection_is_safe(self):
        calls = []
        native = dict(schema_version=SCHEMA_VERSION, ok=True, status="success", exit_code=0,
                      total_count=5, success_count=5, failure_count=0, next_action="consume",
                      app_id=17, dashboard={"id": 8}, results=[{"source": "detail"}],
                      scopes=["dashboard", "app"], source_count=5, ref="private-ref", secret="token")
        def snapshot(app, ref, **options): calls.append((app, ref, options)); return native
        workspace = _Workspace()
        context = _context(workspace, fields=("dashboard", "results"), items=40)
        result = subject.execute_dashboard_snapshot_plan(SimpleNamespace(dashboard_snapshot=snapshot),
            {"name": "dashboard_snapshot", "app": "demo", "ref": 8}, context)
        self.assertEqual(("demo", 8), calls[0][:2])
        self.assertEqual({"max_workers": 1, "max_pages": 3, "max_items": 40, "workspace": workspace}, calls[0][2])
        projected = subject.project_dashboard_snapshot_result(result, context.output_fields, context)
        outputs = {"app_id", "dashboard", "results", "scopes", "source_count"}
        self.assertEqual({"dashboard", "results"}, set(projected) & outputs)
        self.assertNotIn("private-ref", str(projected)); self.assertNotIn("token", str(projected))

    def test_partial_and_contract_drift_expose_only_aggregate_error_identity(self):
        for category, code, exit_code in (
            ("upstream", "PERMISSION_UNAVAILABLE", 3),
            ("upstream", "UPSTREAM_UNAVAILABLE", 3),
            ("local", "LOCAL_IO_ERROR", 4),
        ):
            native = {"schema_version": SCHEMA_VERSION, "ok": False, "status": "partial",
                      "exit_code": exit_code, "results": [{"ok": False, "error": {
                          "category": category, "code": code,
                          "message": "C:/private/original boom"}}]}
            safe = subject.safe_dashboard_snapshot_envelope(native)
            self.assertEqual((category, code), (safe["error"]["category"], safe["error"]["code"]))
            self.assertEqual(exit_code, detail_exit_code(safe_native_error(safe)))
            self.assertNotIn("private", str(safe["error"]))
        drift = subject.safe_dashboard_snapshot_envelope({"schema_version": "breaking.v2"})
        self.assertEqual(("upstream", "CONTRACT_CHANGED"),
                         (drift["error"]["category"], drift["error"]["code"]))
        self.assertEqual(3, detail_exit_code(safe_native_error(drift)))
