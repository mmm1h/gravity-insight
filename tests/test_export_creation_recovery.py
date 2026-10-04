"""A rejected user-event export creation is certified against stored requests (#248)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_models import ExportRuntimeError
from gravity_insight.export_recovery import reviewed_semantic_rejection
from gravity_insight.export_results import _failure_diagnostics
from tests.test_export_condition_contract import Client
from tests.test_gravity_insight_export_integration import CONTRACT_PATH

START = "export.analysis.user_event.start"
BODY = {
    "app_id": 1, "client_id": "SENSITIVE-CLIENT", "date_list": ["2026-01-01", "2026-01-02"],
    "desc": False, "group_by": "day", "event_list": [], "page_info": {"page": 1, "page_size": 1},
    "query_item_list": [], "task_name": "synthetic-248",
}
REJECTION = {"code": 1004, "msg": "参数错误", "extra": {"error": "PRIVATE_SENTINEL SENSITIVE-CLIENT"}}


def task(task_id, body, *, status=2, task_type="user_detail"):
    # Upstream rewrites task_name; args keeps the submitted body (key order may differ).
    args = json.dumps(dict(reversed(list(body.items()))), ensure_ascii=False)
    return {"id": task_id, "task_type": task_type, "status": status, "create_time": "2026-10-04 19:01:28",
            "task_name": "用户行为序列-SENSITIVE-CLIENT", "args": args}


def listing(*rows):
    return {"code": 0, "data": {"list": list(rows), "page_info": {"total_number": len(rows)}}}


def run(*responses):
    contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
    client = Client(contracts, [REJECTION, *responses])
    columns = tuple(contracts.get(START).privacy["allowed_columns"])
    with tempfile.TemporaryDirectory() as directory:
        result = client.export_run(START, dict(BODY), str(Path(directory) / "events.xlsx"),
                                   requested_columns=columns, idempotency_key="synthetic-export-248")
    return result, client._export_runtime.calls


OTHER = {**BODY, "client_id": "another-client"}


@pytest.mark.parametrize("responses,association,job_id,candidates,resume", [
    ((listing(task("a" * 32, OTHER), task("b" * 32, BODY)),), "existing_identical_task", "b" * 32, ["b" * 32], True),
    ((listing(task("a" * 32, OTHER), task("c" * 32, BODY, task_type="segment")),), "not_found", None, [], False),
    ((listing(task("a" * 32, BODY), task("b" * 32, BODY, status=3)),), "ambiguous", None, ["a" * 32, "b" * 32], True),
    ((listing(task("b" * 32, BODY, status=4)),), "existing_identical_task", "b" * 32, ["b" * 32], False),
    ((listing(task("b" * 32, BODY, status="2")),), "existing_identical_task", "b" * 32, ["b" * 32], True),
    (({"code": 1004, "msg": "参数错误"},), "unconfirmed", None, [], False),
])
def test_rejected_creation_reports_certified_association(responses, association, job_id, candidates, resume):
    result, calls = run(*responses)
    recovery = result["creation_recovery"]
    assert (recovery["association"], result["job_id"]) == (association, job_id)
    assert [item["job_id"] for item in recovery["candidates"]] == candidates
    assert result["resumable"] is (resume and job_id is not None)
    assert recovery["match_basis"] == "exact_submitted_args"
    assert [path.rsplit("/", 2)[-2] for _m, path, *_ in calls] == ["download", "list"]
    assert result["error"]["retryable"] is False
    # A dead (failed, cancelled, expired) match is never offered for resumption.
    assert ("export wait" in result["error"]["next_action"]) is resume
    dumped = json.dumps(result, ensure_ascii=False)
    assert "SENSITIVE-CLIENT" not in dumped and "PRIVATE_SENTINEL" not in dumped


def test_export_start_failure_envelope_carries_the_recovered_job_id():
    contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
    client = Client(contracts, [REJECTION, listing(task("b" * 32, BODY))])
    columns = tuple(contracts.get(START).privacy["allowed_columns"])
    with pytest.raises(ExportRuntimeError) as raised:
        client.export_start(START, dict(BODY), requested_columns=columns, idempotency_key="synthetic-start-248")
    recovery = _failure_diagnostics(raised.value)["creation_recovery"]
    assert recovery["candidates"] == [{"job_id": "b" * 32, "resumable": True, "created_at": "2026-10-04 19:01:28"}]


def test_invalid_parameter_message_is_not_an_unclassified_retryable_failure():
    result, _calls = run(listing())
    assert result["diagnostics"]["responsibility"] == "upstream_reported_invalid_parameter"
    assert result["diagnostics"]["semantic_code"] == "1004"
    assert result["creation_recovery"]["association"] == "not_found"
    assert result["creation_recovery"]["readback_complete"] is True


def test_reviewed_message_keeps_duplicate_safety_and_ignores_unhashable_messages():
    assert "inspect gravity export list" in reviewed_semantic_rejection("参数错误")["next_action"]
    assert reviewed_semantic_rejection(["参数错误"]) == {} == reviewed_semantic_rejection({"msg": "参数错误"})
