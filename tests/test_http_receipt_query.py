from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gravity_insight.receipt_query import get_http_receipt, list_http_receipts
from gravity_insight.cli import build_parser
from gravity_insight.sdk import GravitySDK
from gravity_insight.workspace import Workspace, WorkspaceDefaults


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "0" * 32


def _receipt(identifier: str, completed_at: str, operation: str = "app.list") -> dict:
    return {
        "schema_version": "gravity.http-receipt.v1",
        "receipt_id": identifier,
        "completed_at": completed_at,
        "operation_id": operation,
        "method": "GET",
        "path": "/account_center/api/v1/app/list/",
        "http_status": 200,
        "page_number": 1,
        "attempt": 1,
        "retry": False,
        "request_shape_fingerprint": "a" * 64,
    }


def _write(root: Path, value: dict, *, pid: int = 999_999) -> None:
    directory = root / "receipts" / "http"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{pid}-{RUN_ID}-{value['receipt_id']}.json"
    (directory / name).write_text(json.dumps(value), encoding="utf-8")


def _workspace(root: Path) -> Workspace:
    return Workspace(
        path=None,
        root=root,
        state_root=root,
        apps={},
        defaults=WorkspaceDefaults(app=None, timezone="UTC", time_window=None),
        datasources={},
        products={},
        recipes={},
    )


class HttpReceiptQueryTests(unittest.TestCase):
    def test_three_gap_kinds_are_mechanically_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            identifier = "1" * 32
            pruned = get_http_receipt(
                root, {"receipt_id": identifier, "storage_status": "stored"}
            )
            failed = get_http_receipt(
                root, {"receipt_id": identifier, "storage_status": "write_failed"}
            )

            ready, release = root / "ready", root / "release"
            script = r"""
import sys,time
from pathlib import Path
from gravity_insight.receipt import record_completed_http_response,request_receipt_context
class Response: status_code=200
root,ready,release=map(Path,sys.argv[1:])
record_completed_http_response(Response(),request_receipt_context(operation_id='app.list',method='GET',path='/account_center/api/v1/app/list/'),root)
ready.write_text('ready',encoding='ascii')
deadline=time.time()+10
while not release.exists() and time.time()<deadline: time.sleep(.01)
"""
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(root), str(ready), str(release)],
                env=environment,
            )
            for _ in range(1_000):
                if ready.exists() or process.poll() is not None:
                    break
                import time

                time.sleep(0.01)
            active = list_http_receipts(root)
            release.write_text("release", encoding="ascii")
            process.wait(timeout=10)

        self.assertEqual("retention_pruned", pruned["gaps"][0]["kind"])
        self.assertEqual("write_failed", failed["gaps"][0]["kind"])
        self.assertEqual("run_in_progress", active["gaps"][0]["kind"])
        self.assertEqual("run_in_progress", active["items"][0]["run_status"])

    def test_empty_unreadable_and_corrupt_storage_do_not_collapse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            empty = list_http_receipts(root)
            directory = root / "receipts" / "http"
            directory.mkdir(parents=True)
            with mock.patch(
                "gravity_insight.receipt_query.os.scandir", side_effect=PermissionError
            ):
                unreadable = list_http_receipts(root)
            _write(root, _receipt("2" * 32, "2026-01-16T00:00:00.000001Z"))
            (directory / "broken.json").write_text("{", encoding="ascii")
            corrupt = list_http_receipts(root)

        self.assertEqual((True, "empty"), (empty["ok"], empty["status"]))
        self.assertEqual("storage_unreadable", unreadable["gaps"][0]["kind"])
        self.assertEqual((False, "partial", 1), (corrupt["ok"], corrupt["status"], len(corrupt["items"])))
        self.assertEqual("corrupt_receipt", corrupt["gaps"][0]["kind"])

    def test_cursor_snapshot_is_stable_while_another_process_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            timestamp = "2026-08-15T00:00:00.000001Z"
            for digit in "123":
                _write(root, _receipt(digit * 32, timestamp))
            first = list_http_receipts(root, limit=2)
            script = r"""
import sys
from pathlib import Path
from gravity_insight.receipt import record_completed_http_response,request_receipt_context
class Response: status_code=200
record_completed_http_response(Response(),request_receipt_context(operation_id='app.list',method='GET',path='/account_center/api/v1/app/list/'),Path(sys.argv[1]))
"""
            subprocess.run(
                [sys.executable, "-c", script, str(root)],
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                check=True,
            )
            second = list_http_receipts(
                root, limit=2, cursor=first["page"]["next_cursor"]
            )

        self.assertEqual(["3" * 32, "2" * 32], [item["receipt_id"] for item in first["items"]])
        self.assertEqual(["1" * 32], [item["receipt_id"] for item in second["items"]])
        self.assertFalse(second["page"]["has_more"])
        self.assertNotIn("snapshot_changed", {gap["kind"] for gap in second["gaps"]})

    def test_sdk_and_plan_use_the_same_local_query_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write(root, _receipt("4" * 32, "2026-01-16T00:00:00.000001Z"))
            sdk = GravitySDK(insight_factory=lambda: self.fail("Insight was constructed"), workspace=_workspace(root))
            direct = sdk.list_http_receipts(limit=1)
            plan = sdk.execute_plan(
                {
                    "schema_version": "gravity.plan.v1",
                    "nodes": [
                        {
                            "id": "audit",
                            "kind": "receipt_query",
                            "request": {"action": "list", "limit": 1},
                            "limits": {"max_pages": 1, "max_items": 1},
                        }
                    ],
                }
            )
            missing = sdk.execute_plan(
                {
                    "schema_version": "gravity.plan.v1",
                    "nodes": [{
                        "id": "missing", "kind": "receipt_query",
                        "request": {
                            "action": "get",
                            "reference": {
                                "receipt_id": "5" * 32,
                                "storage_status": "stored",
                            },
                        },
                    }],
                }
            )

        nested = plan["results"][0]["result"]
        self.assertEqual("gravity.http-receipt-query.v1", direct["schema_version"])
        self.assertEqual(direct["items"], nested["items"])
        self.assertEqual("local_audit", plan["results"][0]["result_source"]["tier"])
        self.assertEqual(
            "retention_pruned",
            missing["results"][0]["result"]["gaps"][0]["kind"],
        )
        parsed = build_parser().parse_args(["receipts", "list", "--limit", "1"])
        self.assertFalse(parsed.network_required)


if __name__ == "__main__":
    unittest.main()
