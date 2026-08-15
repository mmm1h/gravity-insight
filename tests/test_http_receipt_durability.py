from __future__ import annotations

import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

from gravity_sdk import Credential, GravityInsightClient
from gravity_sdk.composite import CompositeService
from gravity_sdk.http_runtime import GravityHttpRuntime, SQL_PROFILE


class Response:
    def __init__(self, payload, status=200): self.payload, self.status_code, self.headers = payload, status, {}
    def json(self): return self.payload


class Session:
    def __init__(self, responses): self.responses = list(responses)
    def request(self, *_args, **_kwargs):
        response = self.responses.pop(0)
        if isinstance(response, BaseException): raise response
        return response


class Credentials:
    def get(self): return Credential("synthetic-token")


def client_for(root: Path, responses) -> GravityInsightClient:
    runtime = GravityHttpRuntime(session=Session(responses), credentials=Credentials(), attempts=1,
                                 requests_per_second=100, sleeper=lambda _delay: None,
                                 interval_jitter_ratio=0, receipt_root=root)
    return GravityInsightClient.from_env(runtime=runtime, attempts=1)


def app_page(number: int, total: int = 1) -> Response:
    return Response({"code": 0, "data": {"list": [{"id": number, "name": "synthetic"}],
                                          "page_info": {"page": number, "page_size": 1,
                                                        "total_page": total, "total_number": total}}})


def receipts(root: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in (root / "receipts/http").glob("*.json")]


class HttpReceiptDurabilityTests(unittest.TestCase):
    def test_projection_and_contract_failures_keep_completed_response_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            for stage in ("_project", "_enforce_semantic_rules"):
                with self.subTest(stage=stage):
                    root = Path(folder, stage); client = client_for(root, [app_page(1)])
                    with mock.patch(f"gravity_sdk.executor.{stage}", side_effect=RuntimeError(f"injected {stage} failure")):
                        with self.assertRaisesRegex(RuntimeError, f"injected {stage} failure"): client.read("app.list", {"page": 1, "page_size": 1})
                    [item] = receipts(root)
                    self.assertEqual(("app.list", "GET", 200, 1, False), (item["operation_id"], item["method"], item["http_status"], item["page_number"], item["retry"]))
                    self.assertNotIn("synthetic", json.dumps(item))

    def test_receipt_write_failure_reports_but_keeps_original_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder, "unavailable"); root.write_text("not a directory", encoding="ascii")
            client = client_for(root, [app_page(1), app_page(1)])
            with self.assertLogs("gravity_sdk", "WARNING") as logs:
                client.read("app.list", {"page": 1, "page_size": 1})
                with mock.patch("gravity_sdk.executor._project", side_effect=RuntimeError("original failure")):
                    with self.assertRaisesRegex(RuntimeError, "original failure"): client.read("app.list", {"page": 1, "page_size": 1})
            self.assertIn("gravity_http_receipt_write_failed", "".join(logs.output))

    def test_page_three_transport_failure_keeps_first_two_page_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); client = client_for(root, [app_page(1, 3), app_page(2, 3), OSError("page three")])
            with self.assertRaises(Exception): client.read_all("app.list", {"page": 1, "page_size": 1}, max_workers=1)
            self.assertEqual([(1, 200), (2, 200)], sorted((item["page_number"], item["http_status"]) for item in receipts(root)))

    def test_each_retry_response_has_its_own_attempt_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); runtime = GravityHttpRuntime(session=Session([Response({}, 503), Response({"status": "success"})]), credentials=Credentials(), attempts=2, requests_per_second=100, sleeper=lambda _delay: None, interval_jitter_ratio=0, receipt_root=root)
            runtime.request(SQL_PROFILE, "POST", "/custom_sql/api/sql/execute", json_body={"sql": "SELECT 1", "tabId": "1"})
            self.assertEqual([(1, 503, False), (2, 200, True)], sorted((item["attempt"], item["http_status"], item["retry"]) for item in receipts(root)))

    def test_composite_component_failure_keeps_its_http_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); client = client_for(root, [Response({"code": 0, "data": []}), Response({}, 503)])
            result = CompositeService(client).metadata_snapshot(
                ["promotion.metric.list", "material.metric.list"], inputs_by_operation={name: {"media_type": "bytedance"} for name in ("promotion.metric.list", "material.metric.list")}, max_workers=1)
            self.assertEqual("partial", result["status"])
            self.assertEqual([("material.metric.list", 503), ("promotion.metric.list", 200)], sorted((item["operation_id"], item["http_status"]) for item in receipts(root)))

    def test_terminate_process_after_response_keeps_fsynced_receipt(self):
        script = """import sys,time
from pathlib import Path
from gravity_sdk import Credential
from gravity_sdk.http_runtime import GravityHttpRuntime,SQL_PROFILE
from gravity_sdk.prober.transport import RecordingSession,RequestDiscipline
class C:
 def get(self):return Credential('synthetic-token')
class R:
 status_code=200;headers={}
 def json(self):
  Path(sys.argv[2]).write_text('ready',encoding='ascii')
  while True:time.sleep(.1)
class S:
 def request(self,*a,**k):return R()
session=RecordingSession(S(),RequestDiscipline(interval_seconds=.3,sleeper=lambda _delay:None))
GravityHttpRuntime(session=session,credentials=C(),attempts=1,requests_per_second=100,interval_jitter_ratio=0,receipt_root=Path(sys.argv[1])).request(SQL_PROFILE,'POST','/custom_sql/api/sql/execute',json_body={'sql':'SELECT 1','tabId':'1'},attempts=1)
"""
        with tempfile.TemporaryDirectory() as folder:
            root, marker = Path(folder, "state"), Path(folder, "response-returned")
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
            process = subprocess.Popen([sys.executable, "-c", script, str(root), str(marker)], env=env)
            deadline = time.monotonic() + 10
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(marker.is_file()); process.kill(); process.wait(timeout=10)
            [item] = receipts(root); self.assertEqual(("sql.query", 200, False), (item["operation_id"], item["http_status"], item["retry"]))
