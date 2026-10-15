"""Plan JSON publication preserves complete bounded node results before preview."""

import contextlib
from copy import deepcopy
import hashlib
import io
import json
from unittest.mock import patch

import pytest

from gravity_insight import cli
from gravity_insight.plan import PlanAdapter, PlanAdapters
from gravity_insight.plan_cli import run_plan_command


PLAN = {
    "schema_version": "gravity.plan.v1",
    "budget": {"max_workers": 1, "max_total_items": 100},
    "nodes": [
        {"id": "first", "kind": "run", "request": {"selector": "analysis.user_event.list"}, "limits": {"max_pages": 1, "max_items": 50}},
        {"id": "second", "kind": "run", "request": {"selector": "analysis.user_event.list"}, "depends_on": ["first"], "limits": {"max_pages": 1, "max_items": 50}},
    ],
}
TEXT = "观测" * 9000
VALUES = list(range(350))


def native():
    return {
        "schema_version": "gravity-insight.read.v1", "ok": True, "status": "success",
        "operation_id": "analysis.user_event.list", "completeness": "unknown",
        "page": {"item_count": 1},
        "request": {"inputs": {"page": 1, "page_size": 50}},
        "data": {"list": [{"note": TEXT, "measurements": VALUES}]},
        "result_audit": {"schema_version": "gravity.result-audit.v1", "http_receipts": [{"receipt_id": "a" * 32, "storage_status": "stored"}]},
        "obligations": {
            "schema_version": "gravity.envelope-obligations.v1",
            "execution_status": {"state": "complete", "evidence_code": "SYNTHETIC_READ_RETURNED"},
            "data_completeness": {"state": "unknown", "evidence_code": "USER_EVENT_CONTENT_CLOSURE_UNPROVEN", "facts": {}},
            "semantic_validity": {"state": "unknown", "evidence_codes": ["SYNTHETIC_SCOPE_ONLY"]},
            "diagnostic_evidence": {"state": "none", "evidence_codes": []},
            "mutation_certainty": {"state": "not_applicable", "evidence_code": "SYNTHETIC_READ_ONLY"},
        },
    }


def invoke(tmp_path, *, dry_run=False, returned=None, output=True):
    calls, checks, captured = [], [], []
    def execute(_request, context):
        calls.append((context.node_id, context.max_pages, context.max_items))
        value = returned(context.node_id) if callable(returned) else returned
        return deepcopy(value if value is not None else native())
    adapters = PlanAdapters(run=PlanAdapter(execute=execute, validate=lambda _r, context: checks.append(context.node_id)))
    def handler(args, _object_input):
        result = run_plan_command(args, adapters=adapters, workspace=object(), resolved_plan=PLAN)
        captured.append(result)
        return result
    argv = ["plan", "run", "--input", json.dumps(PLAN)]
    if output:
        argv += ["--output", str(tmp_path / "plan.json")]
    if dry_run:
        argv += ["--dry-run"]
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(cli, "dispatch_plan", handler), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue(), calls, checks, captured


def test_complete_plan_file_keeps_nested_values_provenance_and_native_unknown(tmp_path):
    code, stdout, stderr, calls, checks, _captured = invoke(tmp_path)
    assert code == 0, stderr
    encoded = (tmp_path / "plan.json").read_bytes()
    saved, receipt = json.loads(encoded), json.loads(stdout)
    assert receipt["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert receipt["size_bytes"] == len(encoded)
    assert receipt["preview_applied"] is False
    assert calls == [("first", 1, 50), ("second", 1, 50)]
    assert checks == ["first", "second"]
    for node in saved["results"]:
        result = node["result"]
        assert result["data"]["list"][0] == {"note": TEXT, "measurements": VALUES}
        assert result["request"]["inputs"] == {"page": 1, "page_size": 50}
        assert result["completeness"] == result["obligations"]["data_completeness"]["state"] == "unknown"
        assert result["result_audit"]["http_receipts"][0]["receipt_id"] == "a" * 32
    _code, preview, _stderr, *_ = invoke(tmp_path, output=False)
    assert json.loads(preview)["truncated"] is True
    assert len(preview) < len(encoded)


def test_dry_run_file_is_guarded_and_does_not_execute_adapters(tmp_path):
    code, stdout, stderr, calls, checks, _captured = invoke(tmp_path, dry_run=True)
    assert code == 0, stderr
    assert calls == []
    assert checks == ["first", "second"]
    assert json.loads((tmp_path / "plan.json").read_bytes())["dry_run"] is True
    assert json.loads(stdout)["preview_applied"] is False


@pytest.mark.parametrize("status", ["error", "capability_gap"])
def test_terminal_plan_failure_preserves_the_existing_file(tmp_path, status):
    target = tmp_path / "plan.json"
    target.write_bytes(b"previous-verified-plan")
    terminal = {"ok": False, "status": status, "error": {"category": "upstream", "code": "UPSTREAM_UNAVAILABLE", "message": "synthetic rejection", "retryable": False}}
    code, stdout, stderr, calls, _checks, captured = invoke(tmp_path, returned=terminal)
    assert code != 0
    assert stdout == ""
    assert json.loads(stderr)["ok"] is False
    assert len(calls) == len(captured) == 1
    assert json.loads(stderr)["schema_version"] == captured[0]["schema_version"]
    assert target.read_bytes() == b"previous-verified-plan"


def test_partial_plan_file_preserves_successful_nodes_and_nonzero_exit(tmp_path):
    failure = {"ok": False, "status": "error", "error": {"category": "upstream", "code": "UPSTREAM_UNAVAILABLE", "message": "synthetic rejection", "retryable": False}}
    code, stdout, stderr, calls, _checks, _captured = invoke(tmp_path, returned=lambda node: native() if node == "first" else failure)
    assert code != 0
    assert stderr == ""
    saved = json.loads((tmp_path / "plan.json").read_bytes())
    assert saved["status"] == "partial"
    assert saved["results"][0]["result"]["data"]["list"][0]["note"] == TEXT
    assert saved["results"][1]["ok"] is False
    assert json.loads(stdout)["sha256"] == hashlib.sha256((tmp_path / "plan.json").read_bytes()).hexdigest()
    assert len(calls) == 2
