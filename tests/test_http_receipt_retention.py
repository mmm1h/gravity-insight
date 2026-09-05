import tempfile
import unittest

import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCRIPT = r"""
import json,logging,sys,time
from pathlib import Path
from gravity_insight.receipt import PRODUCTION_HTTP_KIND,perform_http_request,request_receipt_context
class Response: status_code=200
root=Path(sys.argv[1]); operation=sys.argv[2]
response=perform_http_request(lambda:Response(),kind=PRODUCTION_HTTP_KIND,http_receipt=request_receipt_context(operation_id=operation,method='GET',path='/synthetic'),receipt_root=root)
print(json.dumps({'status':response.status_code}))
"""
def _environment(**values: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(values, PYTHONPATH=str(ROOT / "src")); return environment
def _old_receipt(directory: Path, name: str, *, days: int = 0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name; path.write_text("{}", encoding="ascii")
    modified = time.time() - days * 86_400; os.utime(path, (modified, modified)); return path

class HttpReceiptRetentionTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_configured_count_and_age_limits_and_safe_defaults(self):
        count_root = self.tmp_path / "count"; directory = count_root / "receipts" / "http"
        for number in range(3):
            _old_receipt(directory, f"old-{number}.json")
        completed = subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(count_root), "count.new"],
            env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="2", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500"), check=True, capture_output=True, text=True, encoding="utf-8")
        assert json.loads(completed.stdout) == {"status": 200}
        remaining = [json.loads(path.read_text()) for path in directory.glob("*.json")]
        assert len(remaining) == 2 and any(item.get("operation_id") == "count.new" for item in remaining)
        age_root = self.tmp_path / "age"; expired = _old_receipt(age_root / "receipts" / "http", "expired.json", days=2)
        subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(age_root), "age.new"],
            env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="100", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="1"), check=True, capture_output=True, text=True, encoding="utf-8")
        assert not expired.exists()
        command = "import json;from gravity_insight.receipt_retention import http_receipt_retention_policy as p;x=p();print(json.dumps([x.max_files,x.max_age_days]))"; environment = _environment()
        environment.pop("GRAVITY_HTTP_RECEIPT_MAX_FILES", None); environment.pop("GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS", None)
        defaults = subprocess.run([sys.executable, "-c", command], env=environment, check=True, capture_output=True, text=True, encoding="utf-8")
        assert json.loads(defaults.stdout) == [10_000, 7]
        default_root = self.tmp_path / "default"; default_expired = _old_receipt(default_root / "receipts" / "http", "expired.json", days=8)
        subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(default_root), "default.new"],
            env=environment, check=True, capture_output=True, text=True, encoding="utf-8")
        assert not default_expired.exists()
    def test_undeletable_target_only_warns_and_keeps_request_result(self):
        blocked = self.tmp_path / "receipts" / "http" / "blocked.json"
        blocked.mkdir(parents=True)
        script = "import logging;logging.basicConfig(level=logging.WARNING);" + REQUEST_SCRIPT
        completed = subprocess.run([sys.executable, "-c", script, str(self.tmp_path), "blocked.new"],
            env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="1", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500"), check=True, capture_output=True, text=True, encoding="utf-8")
        assert json.loads(completed.stdout) == {"status": 200}
        assert blocked.is_dir()
        assert "gravity_http_receipt_prune_failed" in completed.stderr
    def test_concurrent_process_pruning_keeps_both_active_runs(self):
        ready, release = self.tmp_path / "ready", self.tmp_path / "release"
        first_script = REQUEST_SCRIPT + r"""
Path(sys.argv[3]).write_text('ready',encoding='ascii')
deadline=time.time()+10
while not Path(sys.argv[4]).exists() and time.time()<deadline: time.sleep(.01)
"""
        environment = _environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="1", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500")
        first = subprocess.Popen([sys.executable, "-c", first_script, str(self.tmp_path), "concurrent.first", str(ready), str(release)],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        deadline = time.monotonic() + 10
        while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.is_file()
        second = subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(self.tmp_path), "concurrent.second"],
            env=environment, check=True, capture_output=True, text=True, encoding="utf-8")
        operations = {json.loads(path.read_text())["operation_id"] for path in (self.tmp_path / "receipts" / "http").glob("*.json")}
        assert operations == {"concurrent.first", "concurrent.second"}
        assert json.loads(second.stdout) == {"status": 200}
        release.write_text("release", encoding="ascii")
        stdout, stderr = first.communicate(timeout=10)
        assert first.returncode == 0, stderr
        assert json.loads(stdout) == {"status": 200}

    def test_windows_liveness_probe_does_not_deliver_console_events(self):
        from unittest import mock
        from gravity_insight import receipt_retention
        from gravity_insight.receipt_query import list_http_receipts
        from gravity_insight.receipt_retention import _process_is_alive
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: child.terminate() or child.wait(timeout=5))
        identifier = "a" * 32
        stale = _old_receipt(self.tmp_path / "receipts" / "http", f"{child.pid}-{'0'*32}-{identifier}.json")
        stale.write_text(json.dumps({"schema_version":"gravity.http-receipt.v1","receipt_id":identifier,"completed_at":"2026-01-16T00:00:00.000001Z","operation_id":"app.list","method":"GET","path":"/account_center/api/v1/app/list/","http_status":200,"page_number":1,"attempt":1,"retry":False,"request_shape_fingerprint":"a"*64}), encoding="utf-8")
        listed = list_http_receipts(self.tmp_path)
        completed = subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(self.tmp_path), "alive.new"],
            env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="1", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500"), check=True, capture_output=True, text=True, encoding="utf-8")
        assert json.loads(completed.stdout) == {"status": 200} and stale.exists() and child.poll() is None
        assert listed["items"][0]["run_status"] == "run_in_progress"
        if os.name != "nt":
            return
        import signal
        calls = []
        def record_kill(pid, sig):
            calls.append((pid, sig)); raise AssertionError("Windows liveness must not call os.kill")
        with mock.patch.object(receipt_retention.os, "kill", side_effect=record_kill):
            assert _process_is_alive(os.getpid()) and _process_is_alive(child.pid)
            list_http_receipts(self.tmp_path)
        assert calls == [] and signal.CTRL_C_EVENT == 0
