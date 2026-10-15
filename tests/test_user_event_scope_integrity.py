"""Timeline filters, native summary scope and content closure are separate facts."""

from copy import deepcopy
import json

import pytest

from gravity_insight.output_projection import apply_output_fields
from gravity_insight.agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from gravity_insight.executor import _shape_fingerprint
from gravity_insight.plan_adapter_support import identity_projection
from gravity_insight.result_audit import add_result_audit
from tests.test_gravity_insight_analysis import client_for, page


OPERATION = "analysis.user_event.list"
DAY = "2026-01-12"


def event(name):
    return {"事件名称": name, "事件英文名": name, "事件时间": f"{DAY} 10:00:00"}


def read_native(data, *, conditions=False):
    properties = [{"name": "source_tag", "cname": "来源", "data_type": "STRING", "visible": True}]

    def handler(_method, path, _kwargs):
        if path.endswith("event_list/"):
            return page([{"name": name, "cname": name, "visible": True} for name in ("evt_a", "evt_b")])
        if path.endswith("event_property_list/"):
            return page(properties)
        if path.endswith("event_info/"):
            return {"code": 0, "data": {"properties": {"common": [], "preset": [], "custom": properties}}}
        if path.endswith(("user_property_list/", "segment/list/")):
            return page([])
        if path.endswith("user/event/list/"):
            return {"code": 0, "data": deepcopy(data)}
        raise AssertionError(path)

    client, transport = client_for(
        OPERATION, "analysis.event.list", "analysis.event.info",
        "analysis.event_property.list", "analysis.user_property.list", "analysis.segment.list",
        handler=handler,
    )
    inputs = {
        "app_id": "101", "client_id": "private-client", "date_list": [DAY, DAY],
        "event_list": ["evt_a", "evt_b"], "fields": [], "page": 1, "page_size": 50,
    }
    if conditions:
        inputs["query_item_list"] = [{
            "event_name": "evt_a", "conditions": [{
                "field": "source_tag", "operator": "EQUALS", "type": "event", "value": ["private-predicate"],
            }], "cond_logic": "AND",
        }]
    return client.read(OPERATION, inputs), client, transport


def test_filtered_timeline_does_not_gain_the_unfiltered_summary_total():
    native = {
        "event_timeline": [{"timeline": DAY, "list": [event("evt_a")]}],
        "summary": [{"timeline": DAY, "cnt": 7, "list": [{"event": "evt_a", "cnt": 7}]}],
    }
    result, _client, transport = read_native(native, conditions=True)
    scope = result["user_event_scope"]
    validate_schema(scope, "user-event-result-scope-v1.schema.json", "User-event result scope")
    assert scope["summary_scope"] == "unfiltered_event_window"
    assert scope["query_item_conditions"] == "present"
    assert scope["summary_reconciliation"] == "not_comparable"
    assert scope["filtered_matching_record_total"] is None
    assert result["data"]["summary"] == native["summary"]
    assert result["data"]["field_coverage"]["row_count"] == 1
    assert sum(path.endswith("user/event/list/") for _m, path, _k in transport.calls) == 1
    assert all(value not in json.dumps(scope) for value in ("private-client", "private-predicate", DAY))


def test_matching_total_and_same_time_rows_do_not_certify_event_distribution():
    rows = [event("evt_a"), event("evt_a"), event("evt_b")]
    native = {
        "event_timeline": [{"timeline": DAY, "list": rows}],
        "summary": [{"timeline": DAY, "cnt": 3, "list": [{"event": "evt_a", "cnt": 1}, {"event": "evt_b", "cnt": 2}]}],
    }
    result, _client, _transport = read_native(native)
    assert result["data"]["event_timeline"][0]["list"] == rows
    assert len(rows) == result["data"]["summary"][0]["cnt"]
    scope = result["user_event_scope"]
    assert scope["content_completeness"] == "unknown"
    assert scope["content_gap_code"] == "USER_EVENT_CONTENT_CLOSURE_UNPROVEN"
    assert scope["equal_total_proves_content_closure"] is False
    assert scope["empty_terminator_proves_content_closure"] is False


def test_metadata_preserves_empty_status_and_requires_same_scope_without_conditions():
    result, _client, _transport = read_native({"event_timeline": [], "summary": []})
    assert result["status"] == "empty"
    assert result["user_event_scope"]["query_item_conditions"] == "not_requested"
    assert result["user_event_scope"]["summary_reconciliation"] == "requires_identical_scope"
    assert result["schema_fingerprint"] == _shape_fingerprint(result["data"])


def test_metadata_cannot_mask_a_native_projection_failure():
    result, _client, _transport = read_native({"event_timeline": "invalid", "summary": []})
    assert result["status"] == "contract_changed"
    assert result["ok"] is False
    assert result["completeness"] == "unknown"
    assert result["schema_fingerprint"] == _shape_fingerprint(result["data"])


def test_scope_survives_data_selection_and_plan_identity_projection():
    result, client, _transport = read_native({"event_timeline": [], "summary": []}, conditions=True)
    selected = apply_output_fields(result, client.schema(OPERATION), ["summary"])
    planned = identity_projection(selected, ("summary",), None)
    assert planned["user_event_scope"] == result["user_event_scope"]
    assert planned["status"] == "empty"


def test_unavailable_request_evidence_and_forged_closure_stay_unknown():
    result, _client, _transport = read_native({"event_timeline": [], "summary": []})
    result.pop("request")
    result["user_event_scope"]["content_completeness"] = "complete"
    result["user_event_scope"]["private-value"] = "private-marker"
    safe = add_result_audit(result, ())
    scope = safe["user_event_scope"]
    assert scope["query_item_conditions"] == "unavailable"
    assert scope["content_completeness"] == "unknown"
    assert "private-" not in json.dumps(scope)


def test_scope_schema_rejects_contradictory_comparison_and_content_certification():
    result, _client, _transport = read_native({"event_timeline": [], "summary": []}, conditions=True)
    for change in ({"summary_reconciliation": "requires_identical_scope"}, {"content_completeness": "complete"}):
        with pytest.raises(AgentRuntimeContractError):
            validate_schema({**result["user_event_scope"], **change}, "user-event-result-scope-v1.schema.json", "User-event result scope")
