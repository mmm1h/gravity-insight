from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

from gravity_insight.analysis_bootstrap import bootstrap_event_analysis
from gravity_insight.errors import AuthenticationError, InputValidationError
from gravity_insight.field_metadata_override import selected_metadata_loader
from gravity_insight.metadata_catalog_snapshot import create_metadata_snapshot
from gravity_insight.metadata_sync import (
    _create_schema,
    _utc_now,
    _write_apps,
    _write_catalog_metadata,
    _write_rows,
)
from gravity_insight.plan import execute_plan
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.result_audit import error_receipt_references
from gravity_insight.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]


def _catalog(database: Path, *, event: str = "open") -> None:
    synced_at = _utc_now()
    with closing(sqlite3.connect(database)) as connection:
        _create_schema(connection)
        _write_apps(connection, [("101", {"id": 101, "name": "Game"})], synced_at)
        _write_rows(
            connection,
            "101",
            "analysis.event.list",
            [{"name": event, "cname": "Open"}],
            synced_at,
        )
        _write_catalog_metadata(
            connection,
            synced_at=synced_at,
            status="success",
            app_count=1,
            rows_written=1,
            failure_count=0,
        )
        connection.commit()


class Insight:
    def __init__(self, apps: list[dict[str, Any]] | None = None) -> None:
        self.apps = [{"id": 101, "name": "Game"}] if apps is None else apps
        self.read_calls = 0

    def read(self, operation_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self.read_calls += 1
        return {
            "ok": True,
            "status": "success" if self.apps else "empty",
            "operation_id": operation_id,
            "data": {"list": list(self.apps)},
            "result_audit": {
                "schema_version": "gravity.result-audit.v1",
                "fact_paths": {},
                "http_receipts": [
                    {"receipt_id": "a" * 32, "storage_status": "stored"}
                ],
            },
        }


class BootstrapSDK:
    def __init__(self, insight: Insight | None = None) -> None:
        self.insight = insight or Insight()
        self.workspace = load_workspace(ROOT / "examples" / "workspace")
        self.validated_plan: dict[str, Any] | None = None

    def execute_plan(self, plan: dict[str, Any], **options: Any) -> dict[str, Any]:
        self.validated_plan = plan
        assert options["dry_run"] is True
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": True,
            "status": "validated",
            "dry_run": True,
        }


class AnalysisBootstrapTests(unittest.TestCase):
    def test_ready_catalog_emits_exact_decisions_and_pinned_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            _catalog(database)
            sdk = BootstrapSDK()
            result = bootstrap_event_analysis(
                sdk,
                app="101",
                start="2026-08-01",
                end="2026-08-02",
                target="open",
                database=database,
            )

        request = result["plan"]["nodes"][0]["request"]
        self.assertEqual(("101", "open"), (request["app"], request["spec"]["steps"][0]["event"]))
        self.assertEqual("2026-08-01", request["spec"]["start"])
        self.assertEqual("gravity.metadata-snapshot.v1", request["metadata_snapshot"]["schema_version"])
        self.assertEqual((False, 1), (result["metadata"]["sync_performed"], result["request_budget"]["http_requests_observed"]))
        self.assertIs(sdk.validated_plan, result["plan"])

    def test_missing_catalog_runs_one_existing_bounded_sync(self):
        sdk = BootstrapSDK()
        missing = {"status": "missing"}
        ready = {"status": "ready"}
        sync = {"ok": True, "status": "success"}
        found = {"results": [{"name": "open"}]}
        snapshot = {
            "schema_version": "gravity.metadata-snapshot.v1",
            "app_id": "101",
            "synced_at": "2026-08-17T00:00:00Z",
            "fingerprint": "b" * 64,
            "database": "fixture.sqlite3",
        }
        with tempfile.TemporaryDirectory() as temporary, patch(
            "gravity_insight.analysis_bootstrap.metadata_status",
            side_effect=[missing, ready],
        ), patch(
            "gravity_insight.analysis_bootstrap.sync_app", return_value=sync
        ) as sync_app, patch(
            "gravity_insight.analysis_bootstrap.search_metadata", return_value=found
        ), patch(
            "gravity_insight.analysis_bootstrap.create_metadata_snapshot",
            return_value=snapshot,
        ):
            database = Path(temporary) / "metadata.sqlite3"
            result = bootstrap_event_analysis(
                sdk, app="101", start="2026-08-01", end="2026-08-02",
                target="open", database=database, max_pages=1, concurrency=4,
            )

        sync_app.assert_called_once_with(
            sdk.insight, "101", database=database.resolve(), max_pages=1,
            concurrency=4,
        )
        self.assertTrue(result["metadata"]["sync_performed"])

    def test_page_cap_cannot_expand_seven_request_journey(self):
        sdk = BootstrapSDK()
        with self.assertRaises(InputValidationError) as raised:
            bootstrap_event_analysis(
                sdk, app="101", start="2026-08-01", end="2026-08-02",
                target="open", max_pages=2,
            )
        self.assertEqual(("max_pages", 0), (raised.exception.field, sdk.insight.read_calls))
        self.assertIn("seven HTTP requests", str(raised.exception.next_action))

    def test_metadata_page_bound_returns_one_explicit_larger_sync_action(self):
        sdk = BootstrapSDK()
        sync = {
            "ok": False,
            "status": "partial",
            "failures": [{
                "operation_id": "analysis.event.list",
                "status": "partial",
                "category": "caller",
                "code": "PAGE_BOUND_REACHED",
            }],
        }
        with patch(
            "gravity_insight.analysis_bootstrap.metadata_status",
            return_value={"status": "missing"},
        ), patch("gravity_insight.analysis_bootstrap.sync_app", return_value=sync):
            with self.assertRaises(InputValidationError) as raised:
                bootstrap_event_analysis(
                    sdk, app="101", start="2026-08-01", end="2026-08-02",
                    target="open", max_pages=1,
                )
        self.assertEqual("metadata.sync.failures", raised.exception.field)
        self.assertIn("--max-pages 2", str(raised.exception.next_action))

    def test_no_readable_app_returns_one_discovery_action(self):
        with self.assertRaises(InputValidationError) as raised:
            bootstrap_event_analysis(
                BootstrapSDK(Insight([])), app="101", start="2026-08-01",
                end="2026-08-02", target="open",
            )
        self.assertEqual("app.list.data.list", raised.exception.field)
        self.assertIn("actual value: 0", str(raised.exception))
        self.assertIn("owner", str(raised.exception.next_action))
        self.assertEqual(1, len(error_receipt_references(raised.exception)))

    def test_invalid_window_fails_before_app_discovery(self):
        sdk = BootstrapSDK()
        with self.assertRaises(InputValidationError) as raised:
            bootstrap_event_analysis(
                sdk, app="101", start="2026-08-02", end="2026-08-01",
                target="open",
            )
        self.assertEqual(("start/end", 0), (raised.exception.field, sdk.insight.read_calls))
        self.assertIn("actual value", str(raised.exception))
        self.assertIn("Replace --start", str(raised.exception.next_action))

    def test_unknown_event_returns_one_offline_discovery_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            _catalog(database)
            with self.assertRaises(InputValidationError) as raised:
                bootstrap_event_analysis(
                    BootstrapSDK(), app="101", start="2026-08-01",
                    end="2026-08-02", target="missing", database=database,
                )
        self.assertEqual("target", raised.exception.field)
        self.assertIn('actual value: "missing"', str(raised.exception))
        self.assertIn("gravity metadata events", str(raised.exception.next_action))
        self.assertEqual(1, len(error_receipt_references(raised.exception)))

    def test_rejected_credentials_keep_path_observation_and_action(self):
        class Rejected(Insight):
            def read(self, _operation_id, _inputs):
                raise AuthenticationError("secret upstream response")

        with self.assertRaises(AuthenticationError) as raised:
            bootstrap_event_analysis(
                BootstrapSDK(Rejected()), app="101", start="2026-08-01",
                end="2026-08-02", target="open",
            )
        self.assertEqual("credentials", raised.exception.field)
        self.assertIn('observed value: "AUTH_REJECTED"', str(raised.exception))
        self.assertIn("auth refresh", str(raised.exception.next_action))

    def test_plan_uses_pinned_catalog_and_fails_closed_after_drift(self):
        class PlanInsight:
            def operations(self, **_options): return []
            def validate(self, _operation_id, _inputs): return {"ok": True}

        class PlanSDK:
            insight = PlanInsight()
            calls = 0

            def analysis_query(self, kind, _spec, **_options):
                self.calls += 1
                fallback = lambda *_args: self.fail("live metadata loader was used")
                loader = selected_metadata_loader(fallback)
                rows = loader("analysis.event.list", {"app_id": "101"})
                return {
                    "ok": True, "status": "success",
                    "operation_id": f"analysis.{kind}.query",
                    "data": {"list": rows["data"]["list"]},
                }

            @staticmethod
            def fail(message):
                raise AssertionError(message)

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            _catalog(database)
            snapshot = create_metadata_snapshot("101", database=database)
            request = {
                "name": "analysis_query", "kind": "event", "app": "101",
                "spec": {"start": "2026-08-01", "end": "2026-08-02",
                         "steps": [{"event": "open", "metric": {
                             "field": "PresetAllCount",
                             "aggregation": "PresetAllCount"}}]},
                "metadata_snapshot": snapshot,
            }
            plan = {"schema_version": "gravity.plan.v1", "nodes": [{
                "id": "first", "kind": "composite", "request": request,
                "limits": {"max_pages": 1, "max_items": 200},
            }]}
            sdk = PlanSDK()
            adapters = build_plan_adapters(sdk, workspace=load_workspace())
            first = execute_plan(plan, adapters=adapters, workspace=load_workspace())
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE metadata_rows SET payload_json = ? WHERE app_id = ?",
                    ('{"name":"changed"}', "101"),
                )
                connection.commit()
            drift = execute_plan(plan, adapters=adapters, workspace=load_workspace())

        self.assertTrue(first["ok"])
        self.assertEqual((False, 2, 1), (drift["ok"], drift["exit_code"], sdk.calls))


if __name__ == "__main__":
    unittest.main()
