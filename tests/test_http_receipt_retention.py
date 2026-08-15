import json, os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCRIPT = r"""
import json,logging,sys,time
from pathlib import Path
from gravity_sdk.receipt import perform_http_request,request_receipt_context
class Response: status_code=200
root=Path(sys.argv[1]); operation=sys.argv[2]
response=perform_http_request(lambda:Response(),http_receipt=request_receipt_context(operation_id=operation,method='GET',path='/synthetic'),receipt_root=root)
print(json.dumps({'status':response.status_code}))
"""
def _environment(**values: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(values, PYTHONPATH=str(ROOT / "src")); return environment
def _old_receipt(directory: Path, name: str, *, days: int = 0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name; path.write_text("{}", encoding="ascii")
    modified = time.time() - days * 86_400; os.utime(path, (modified, modified)); return path
def test_configured_count_and_age_limits_and_safe_defaults(tmp_path: Path) -> None:
    count_root = tmp_path / "count"; directory = count_root / "receipts" / "http"
    for number in range(3):
        _old_receipt(directory, f"old-{number}.json")
    completed = subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(count_root), "count.new"],
        env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="2", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500"), check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == {"status": 200}
    remaining = [json.loads(path.read_text()) for path in directory.glob("*.json")]
    assert len(remaining) == 2 and any(item.get("operation_id") == "count.new" for item in remaining)
    age_root = tmp_path / "age"; expired = _old_receipt(age_root / "receipts" / "http", "expired.json", days=2)
    subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(age_root), "age.new"],
        env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="100", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="1"), check=True, capture_output=True, text=True)
    assert not expired.exists()
    command = "import json;from gravity_sdk.receipt_retention import http_receipt_retention_policy as p;x=p();print(json.dumps([x.max_files,x.max_age_days]))"; environment = _environment()
    environment.pop("GRAVITY_HTTP_RECEIPT_MAX_FILES", None); environment.pop("GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS", None)
    defaults = subprocess.run([sys.executable, "-c", command], env=environment, check=True, capture_output=True, text=True)
    assert json.loads(defaults.stdout) == [10_000, 7]
    default_root = tmp_path / "default"; default_expired = _old_receipt(default_root / "receipts" / "http", "expired.json", days=8)
    subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(default_root), "default.new"],
        env=environment, check=True, capture_output=True, text=True)
    assert not default_expired.exists()
def test_undeletable_target_only_warns_and_keeps_request_result(tmp_path: Path) -> None:
    blocked = tmp_path / "receipts" / "http" / "blocked.json"
    blocked.mkdir(parents=True)
    script = "import logging;logging.basicConfig(level=logging.WARNING);" + REQUEST_SCRIPT
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), "blocked.new"],
        env=_environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="1", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500"), check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == {"status": 200}
    assert blocked.is_dir()
    assert "gravity_http_receipt_prune_failed" in completed.stderr
def test_concurrent_process_pruning_keeps_both_active_runs(tmp_path: Path) -> None:
    ready, release = tmp_path / "ready", tmp_path / "release"
    first_script = REQUEST_SCRIPT + r"""
Path(sys.argv[3]).write_text('ready',encoding='ascii')
deadline=time.time()+10
while not Path(sys.argv[4]).exists() and time.time()<deadline: time.sleep(.01)
"""
    environment = _environment(GRAVITY_HTTP_RECEIPT_MAX_FILES="1", GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS="36500")
    first = subprocess.Popen([sys.executable, "-c", first_script, str(tmp_path), "concurrent.first", str(ready), str(release)],
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 10
    while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert ready.is_file()
    second = subprocess.run([sys.executable, "-c", REQUEST_SCRIPT, str(tmp_path), "concurrent.second"],
        env=environment, check=True, capture_output=True, text=True)
    operations = {json.loads(path.read_text())["operation_id"] for path in (tmp_path / "receipts" / "http").glob("*.json")}
    assert operations == {"concurrent.first", "concurrent.second"}
    assert json.loads(second.stdout) == {"status": 200}
    release.write_text("release", encoding="ascii")
    stdout, stderr = first.communicate(timeout=10)
    assert first.returncode == 0, stderr
    assert json.loads(stdout) == {"status": 200}
