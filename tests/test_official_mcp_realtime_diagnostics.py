"""Real controlled reads prove realtime filters, metadata scope and privacy bounds."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gravity_insight import GravityInsightClient, GravitySDK, InputValidationError, cli
from gravity_insight.agents.realtime_event_catalog import REALTIME_EVENT_CATALOG_CAPABILITY, realtime_event_catalog_plan_request
from gravity_insight.compiler import ContractError, JsonSchemaValidator
from gravity_insight.field_policy import FieldPolicy
from gravity_insight.journey_service import JourneyService
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_realtime_event_catalog_adapter import execute_realtime_event_catalog_plan, project_realtime_event_catalog_result, safe_realtime_event_catalog_envelope
from gravity_insight.realtime_event_catalog import SCHEMA_VERSION
from gravity_insight.transport import TransportResponse


OPERATION = "analysis.realtime_event.list"
ROOT = Path(__file__).resolve().parents[1] / "src/gravity_insight/contracts/operations"
WINDOW = ["2026-01-12 00:00:00", "2026-01-12 01:00:00"]


class RealtimeTransport:
    is_test_transport = True

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/event_info/"):
            data = {"properties": {"common": [], "custom": [
                {"name": "score", "data_type": "INT"},
                {"name": "email", "data_type": "STRING"},
                {"name": "labels", "data_type": "LIST"},
            ], "preset": []}}
        elif path.endswith("/event_list/"):
            data = {"list": [{"name": "level_up"}], "page_info": {"total_page": 1}}
        elif kwargs["operation"].operation_id == "analysis.event_property.list":
            data = {"list": [{"name": "score", "data_type": "INT"}], "page_info": {"total_page": 1}}
        elif path.endswith("/realtime_event/list/"):
            data = {"list": deepcopy(self.rows)}
        else:
            raise AssertionError(path)
        return TransportResponse(200, {"code": 0, "data": data}, "2026-01-12T01:00:00Z")


def client_for(rows):
    operations = [json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))["operation"]
                  for name in ("app.list", OPERATION, "analysis.event.list", "analysis.event.info", "analysis.event_property.list")]
    transport = RealtimeTransport(rows)
    return GravityInsightClient._from_manifest_for_tests({"manifest_version": 1, "operations": operations}, transport=transport), transport


def inputs():
    return {"app_id": 7, "request_time": WINDOW, "page": 1, "page_size": 50,
            "filters": {"event_name": "level_up", "client_lib": "sdk", "client_lib_version": "1.2.3",
                        "properties": [{"field": "score", "datatype": "INT", "operator": "EQUALS", "values": [7]}]},
            "property_fields": ["score"]}


def test_typed_selected_properties_and_sdk_versions_use_one_native_request():
    row = {"event_name": "level_up", "request_time": "2026-01-12 00:30:00", "client_id": "existing-client",
           "request_id": "existing-request", "client_lib": "sdk", "client_lib_version": "1.2.3",
           "raw_properties": {"score": 7, "email": "private@example.invalid", "token": "private-token"},
           "request_ip": "private-ip", "request_ua": "private-agent"}
    client, transport = client_for([row])
    request = inputs()
    result = client.read(OPERATION, request)
    assert result["status"] == "success"
    item = result["data"]["list"][0]
    assert item["properties"] == {"score": 7}
    assert item["property_coverage"] == {"score": "returned"}
    assert (item["client_lib"], item["client_lib_version"], item["client_id"], item["request_id"]) == ("sdk", "1.2.3", "existing-client", "existing-request")
    assert "private" not in json.dumps(result)
    assert result["request"]["inputs"]["filters"] == "[REDACTED]"
    target = [call for call in transport.calls if call[1].endswith("/realtime_event/list/")]
    assert len(target) == 1
    assert dict(target[0][2]["body"]) == {key: value for key, value in request.items() if key != "property_fields"}
    assert len(transport.calls) == 3
    assert FieldPolicy.dependencies(client._registry.get(OPERATION), request) == ("analysis.event.list", "analysis.event.info")


@pytest.mark.parametrize("change", [
    {"property_fields": ["email"]},
    {"filters": {"event_name": "level_up", "properties": [{"field": "score", "datatype": "STRING", "operator": "EQUALS", "values": ["7"]}]}},
    {"filters": {"event_name": "level_up", "properties": [{"field": "score", "datatype": "INT", "operator": "EQUALS", "values": [7, 8]}]}},
    {"filters": {"event_name": "中文事件"}},
    {"request_time": ["2026-01-12 00:00:00", "2026-01-14 00:00:00"]},
])
def test_unsupported_semantics_never_dispatch_the_target_read(change):
    client, transport = client_for([])
    with pytest.raises(InputValidationError):
        client.read(OPERATION, {**inputs(), **change})
    assert not any(path.endswith("/realtime_event/list/") for _method, path, _kwargs in transport.calls)


def test_default_empty_read_has_no_metadata_or_ingestion_absence_claim():
    client, transport = client_for([])
    result = client.read(OPERATION, {"app_id": 7, "request_time": WINDOW, "filters": {"event_type": "profile"}})
    assert result["status"] == "empty"
    assert result["completeness"] == "unknown"
    assert len(transport.calls) == 1


def test_selected_property_type_drift_never_passes_raw_containers():
    client, _transport = client_for([{"event_name": "level_up", "request_time": "2026-01-12 00:30:00",
                                     "client_lib": "sdk", "client_lib_version": "1.2.3",
                                     "raw_properties": {"score": {"token": "private-token"}}}])
    request = inputs()
    request["filters"].pop("properties")
    result = client.read(OPERATION, request)
    assert result["status"] == "contract_changed"
    assert "private-token" not in json.dumps(result)
    assert result["data"]["list"][0]["property_coverage"] == {"score": "type_mismatch"}


@pytest.mark.parametrize("changed", [{"client_lib_version": "other"}, {"raw_properties": {"score": 8}}])
def test_ignored_native_filters_reject_the_whole_result(changed):
    row = {"event_name": "level_up", "request_time": "2026-01-12 00:30:00", "client_lib": "sdk", "client_lib_version": "1.2.3", "raw_properties": {"score": 7}, **changed}
    client, _transport = client_for([row])
    result = client.read(OPERATION, inputs())
    assert result["status"] == "contract_changed"
    assert result["data"]["list"] == []


def test_app_wide_property_selection_uses_same_app_metadata_without_event_discovery():
    client, transport = client_for([{"event_name": "level_up", "event_type": "profile", "request_time": "2026-01-12 00:30:00", "raw_properties": {"score": 7}}])
    result = client.read(OPERATION, {"app_id": 7, "request_time": WINDOW, "filters": {"event_type": "profile"}, "property_fields": ["score"]})
    assert result["status"] == "success"
    assert result["data"]["list"][0]["properties"] == {"score": 7}
    assert len(transport.calls) == 2
    metadata = [kwargs for _method, _path, kwargs in transport.calls if kwargs["operation"].operation_id == "analysis.event_property.list"]
    assert len(metadata) == 1
    assert metadata[0]["query"]["app_id"] == "7"


def test_native_rows_above_the_declared_bound_fail_without_trimming():
    row = {"event_name": "level_up", "event_type": "profile", "request_time": "2026-01-12 00:30:00"}
    client, transport = client_for([row] * 1001)
    result = client.read(OPERATION, {"app_id": 7, "request_time": WINDOW, "filters": {"event_type": "profile"}})
    assert result["status"] == "contract_changed"
    assert result["data"] == {}
    assert len(transport.calls) == 1


def test_agent_machine_grammar_accepts_the_real_condition_and_rejects_wrong_values():
    schema = REALTIME_EVENT_CATALOG_CAPABILITY["input_schema"]["properties"]["machine_schema"]
    validator = JsonSchemaValidator(schema, "realtime property filters")
    condition = inputs()["filters"]["properties"]
    validator.validate(condition)
    with pytest.raises(ContractError):
        validator.validate([{**condition[0], "values": ["wrong-type"]}])
    with pytest.raises(ContractError):
        validator.validate([*condition, *condition])


def test_sdk_cli_plan_agent_and_journey_preserve_the_same_diagnostic_inputs(tmp_path):
    row = {"event_name": "level_up", "event_type": "profile", "request_time": "2026-01-12 00:30:00",
           "client_lib": "sdk", "client_lib_version": "1.2.3", "raw_properties": {"score": 7}}
    client, transport = client_for([row])
    class Workspace:
        root, state_root = tmp_path, tmp_path / "state"
        def resolve_app(self, value):
            assert value == "main"
            return 7
    workspace = Workspace()
    sdk = GravitySDK(workspace=workspace, insight_factory=lambda: client)
    optional = {**inputs()["filters"], "property_fields": ["score"]}
    sdk_result = sdk.realtime_event_catalog("main", start=WINDOW[0], end=WINDOW[1], **optional)
    assert sdk_result["status"] == "success"
    assert sdk_result["diagnostic_scope"]["public_filters"] == {"event_type": "profile", "event_name": "level_up", "client_lib": "sdk", "client_lib_version": "1.2.3"}
    argv = ["analysis", "realtime-events", "--app", "main", "--start", WINDOW[0], "--end", WINDOW[1],
            "--event-name", "level_up", "--client-lib", "sdk", "--client-lib-version", "1.2.3",
            "--property-filter", json.dumps(optional["properties"][0]), "--property-field", "score"]
    parsed = cli.build_parser().parse_args(argv)
    with patch("gravity_insight.capability_cli.load_workspace", return_value=workspace), patch("gravity_insight.capability_cli.runtime.build_client", return_value=client):
        cli_result = parsed._gravity_handler(parsed, json.loads)
    request = realtime_event_catalog_plan_request({"app": "main", "start": WINDOW[0], "end": WINDOW[1], **optional})
    context = AdapterContext("realtime", "run", "composite", workspace, ("data",), (), 1, 1000)
    plan_result = execute_realtime_event_catalog_plan(sdk, request, context)
    assert plan_result["status"] == "success"
    assert sdk_result["data"] == cli_result["data"] == plan_result["data"]
    bodies = [dict(kwargs["body"]) for _method, path, kwargs in transport.calls if path.endswith("/realtime_event/list/")]
    assert len(bodies) == 3
    assert bodies[0] == bodies[1] == bodies[2]
    projected = project_realtime_event_catalog_result(plan_result, ("data",), context)
    assert projected["obligations"]["data_completeness"]["state"] == "unknown"
    before = len(transport.calls)
    readiness = JourneyService(sdk).can_run("analysis.realtime-event-catalog", {"app": "main", "start": WINDOW[0], "end": WINDOW[1], **optional})
    assert "JOURNEY_INPUT_INVALID" not in readiness["reason_codes"]
    assert len(transport.calls) == before
    for forged in ({**plan_result, "schema_version": "gravity-insight.realtime-event-catalog.v1"},
                   {**plan_result, "diagnostic_scope": {**plan_result["diagnostic_scope"], "public_filters": {**plan_result["diagnostic_scope"]["public_filters"], "client_lib_version": "other"}}},
                   {**plan_result, "diagnostic_scope": {**plan_result["diagnostic_scope"], "raw_properties": {"token": "private-token"}}}):
        rejected = safe_realtime_event_catalog_envelope(forged)
        assert rejected["schema_version"] == SCHEMA_VERSION
        assert rejected["status"] == "contract_changed"
        assert "private-token" not in json.dumps(rejected)
