"""A valid workbook must pass its own immutable task scope before publication."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gravity_insight.blob import ArchivePolicy, AuthorizedBlobSource, BlobPolicy, MagicSignature, SafeBlobTransfer
from gravity_insight.agent_runtime_contracts import validate_schema
from gravity_insight.contracts.user_event_export_scope import OPERATION, SCHEMA_VERSION, UserEventExportScope, UserEventScopeError
from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_file import export_file_policies
from gravity_insight.export_models import ExportCreationRequest, ExportJobSnapshot, ExportRuntimeError, ExportState
from gravity_insight.export_results import export_result_envelope
from gravity_insight.export_state import ExportOrchestrator
from tests.test_export_condition_contract import Client
from tests.test_gravity_insight_blob import FakeResponse, FakeTransport
from tests.test_gravity_insight_export_integration import CONTRACT_PATH, NOW, _write_xlsx
from tests.test_gravity_insight_export_runtime import FakeGateway


BODY = {
    "app_id": 1, "client_id": "private-client", "date_list": ["2026-01-12", "2026-01-13"],
    "event_list": ["evt_a"], "query_item_list": [], "desc": False, "group_by": "day",
    "page_info": {"page": 1, "page_size": 50}, "task_name": "synthetic-scope",
}
EVENTS = [{"name": "evt_a", "cname": "Event A"}, {"name": "evt_b", "cname": "Event B"}]
HEADERS = ("客户(client_id)", "用户注册时间", "事件发生时间", "事件", "事件属性")
ROW = ("private-client", "2026-01-01 00:00:00", "2026-01-12T10:00:00", "Event A", "{}")
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JOB = "synthetic-job-294"


def transfer(tmp_path, rows, *, body=None, events=EVENTS, resume=False, tamper_during_status=False):
    request_body = deepcopy(body or BODY)
    scope = UserEventExportScope.capture(request_body, events).bind_job(JOB)
    source_path = tmp_path / "native.xlsx"
    _write_xlsx(source_path, HEADERS, tuple(rows))
    data = source_path.read_bytes()
    transport = FakeTransport([FakeResponse(headers={"Content-Type": MIME, "Content-Length": str(len(data))}, chunks=(data,))])
    source = AuthorizedBlobSource(
        url="https://files.example.test/exports/synthetic.xlsx", declared_path="/exports/synthetic.xlsx",
        expires_at=NOW + timedelta(minutes=5), authorization_scope="synthetic-export-294",
        job_id=JOB, declared_mime_type=MIME,
    )
    policy = BlobPolicy(
        allowed_extensions=frozenset({".xlsx"}), allowed_mime_types=frozenset({MIME}),
        mime_types_by_extension={".xlsx": (MIME,)},
        magic_signatures={".xlsx": (MagicSignature(0, b"PK\x03\x04"),)},
        allowed_hosts=frozenset({"files.example.test"}),
        allowed_path_prefixes={"files.example.test": ("/exports/",)},
        destination_root=tmp_path, temporary_root=tmp_path, overwrite_policy="replace",
        archive_policy=ArchivePolicy(enabled=True),
    )
    route = ExportContractRegistry.from_file(CONTRACT_PATH).get(OPERATION)
    _unused, privacy = export_file_policies(route, tmp_path)
    privacy = replace(privacy, scope_contract=SCHEMA_VERSION)
    snapshot = ExportJobSnapshot(JOB, ExportState.READY, source, completeness=scope.completeness())
    gateway = FakeGateway(create_snapshot=snapshot, statuses=(snapshot,))
    runner = ExportOrchestrator(gateway, SafeBlobTransfer(transport, wall_clock=lambda: NOW))
    if resume:
        external_receipt = scope.completeness()
        if tamper_during_status:
            original_status = gateway.status
            def mutating_status(job_id, *, timeout_seconds):
                external_receipt["scope"]["date_list"][0] = "2025-01-01"
                return original_status(job_id, timeout_seconds=timeout_seconds)
            gateway.status = mutating_status
        result = runner.resume(JOB, "result.xlsx", policy, privacy, completeness=external_receipt)
    else:
        request = ExportCreationRequest(request_body, HEADERS, "synthetic-export-scope-294", scope.completeness())
        result = runner.start(request, "result.xlsx", policy, privacy)
    return export_result_envelope(OPERATION, result), gateway, transport, scope


@pytest.mark.parametrize("resume", [False, True])
def test_clean_scope_preserves_tied_occurrences_and_separates_transfer_from_source_closure(tmp_path, resume):
    result, gateway, _transport, _scope = transfer(tmp_path, (ROW, ROW), resume=resume)
    assert result["state"] == "COMMITTED"
    assert result["file"]["rows"] == 2
    assert result["completion_status"] == "complete"
    assert result["obligations"]["data_completeness"]["state"] == "unknown"
    assert result["completeness"]["file_scope_verification"] == "verified"
    assert result["completeness"]["native_summary_reconciliation"] == "unavailable_without_snapshot_binding"
    assert len(gateway.create_calls) == (0 if resume else 1)
    assert (tmp_path / "result.xlsx").is_file()


@pytest.mark.parametrize("column,value,reason", [
    (0, "other-private-client", "client_mismatch"),
    (2, "2026-01-14T00:00:00", "date_out_of_scope"),
    (2, "invalid-private-time", "timestamp_unverifiable"),
    (3, "Event B", "event_out_of_scope"),
])
def test_wrong_scope_never_replaces_the_existing_destination(tmp_path, column, value, reason):
    destination = tmp_path / "result.xlsx"
    destination.write_bytes(b"previous-verified-file")
    row = list(ROW)
    row[column] = value
    result, gateway, _transport, _scope = transfer(tmp_path, (tuple(row),))
    assert result["state"] == "FAILED"
    assert result["diagnostics"]["reason"] == reason
    assert destination.read_bytes() == b"previous-verified-file"
    assert len(gateway.create_calls) == 1
    rendered = json.dumps(result)
    assert all(marker not in rendered for marker in (value, "private-client", "Event B"))


def test_ambiguous_display_name_is_unverifiable_and_conditions_are_not_inferred(tmp_path):
    events = [{"name": "evt_a", "cname": "shared label"}, {"name": "evt_b", "cname": "shared label"}]
    row = (*ROW[:3], "shared label", ROW[4])
    result, *_ = transfer(tmp_path, (row,), events=events)
    assert result["diagnostics"]["reason"] == "event_identity_unverifiable"
    body = deepcopy(BODY)
    body["query_item_list"] = [{"event_name": "evt_a", "conditions": [{"value": ["private-predicate"]}]}]
    result, *_ = transfer(tmp_path, (ROW,), body=body)
    assert result["state"] == "COMMITTED"
    assert result["completeness"]["conditions_verification"] == "unavailable"
    assert "private-predicate" not in json.dumps(result)


def test_receipt_is_task_bound_and_isolated_from_mutable_original_input():
    body = deepcopy(BODY)
    scope = UserEventExportScope.capture(body, EVENTS).bind_job(JOB)
    original = scope.receipt()
    validate_schema(original, "user-event-export-scope-v1.schema.json", "User-event export scope")
    request = ExportCreationRequest(body, HEADERS, "synthetic-export-scope-294", scope.completeness())
    body["date_list"][0] = "2025-01-01"
    assert scope.receipt() == original
    assert request.payload["date_list"] == original["date_list"]
    assert "private-client" not in json.dumps(original)
    forged = deepcopy(original)
    forged["date_list"][0] = "2025-01-01"
    with pytest.raises(UserEventScopeError):
        UserEventExportScope.from_receipt(forged, job_id=JOB)
    with pytest.raises(UserEventScopeError):
        UserEventExportScope.from_receipt(original, job_id="another-job")


def test_resume_freezes_the_original_receipt_before_status_or_download(tmp_path):
    result, *_ = transfer(tmp_path, (ROW,), resume=True, tamper_during_status=True)
    assert result["state"] == "COMMITTED"
    assert result["completeness"]["scope"]["date_list"] == BODY["date_list"]


def test_empty_verified_file_preserves_empty_transfer_and_unknown_source(tmp_path):
    result, *_ = transfer(tmp_path, ())
    assert result["state"] == "COMMITTED"
    assert result["completion_status"] == "empty"
    assert result["file"]["rows"] == 0
    assert result["obligations"]["data_completeness"]["state"] == "unknown"


@pytest.mark.parametrize("kind", ["missing", "other_task", "tampered"])
def test_download_rejects_a_missing_or_mismatched_receipt_before_any_network(tmp_path, kind):
    client = Client(ExportContractRegistry.from_file(CONTRACT_PATH))
    receipt = UserEventExportScope.capture(BODY, EVENTS).bind_job("another-job" if kind == "other_task" else JOB).completeness()
    if kind == "tampered":
        receipt["scope"]["client_fingerprint"] = "0" * 64
    with pytest.raises(ExportRuntimeError):
        client.export_download(OPERATION, JOB, tmp_path / "result.xlsx", completeness=None if kind == "missing" else receipt)
    assert client._export_runtime.calls == []


def test_start_captures_fresh_governed_event_names_and_returns_a_resumable_task_receipt():
    client = Client(ExportContractRegistry.from_file(CONTRACT_PATH), ({"code": 0, "data": {"task_id": JOB}},))
    metadata_calls = []
    def execute(operation, inputs):
        metadata_calls.append((operation, inputs))
        return SimpleNamespace(to_dict=lambda: {"ok": True, "status": "success", "data": {"list": EVENTS}, "page": {"has_more": False}})
    client._operation_catalog = SimpleNamespace(guard=lambda _operation: None)
    client._executor = SimpleNamespace(execute=execute)
    result = client.export_start(OPERATION, deepcopy(BODY), requested_columns=HEADERS, idempotency_key="synthetic-export-scope-294")
    scope = UserEventExportScope.from_receipt(result["completeness"]["scope"], job_id=JOB, payload=BODY)
    assert scope.job_id == JOB
    assert metadata_calls == [("analysis.event.list", {"app_id": "1", "page": 1, "page_size": 2000})]
    assert len(client._export_runtime.calls) == 1
    assert client._export_runtime.calls[0][3] == BODY
