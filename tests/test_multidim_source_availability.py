"""Missing spend dates cannot acquire zero/current provenance from row totals."""

from copy import deepcopy
import json

import pytest

from gravity_insight import GravitySDK
from gravity_insight.agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from gravity_insight.agents.multidim import MULTIDIM_CAPABILITY
from gravity_insight.contracts.multidim_availability import GAP_CODE
from gravity_insight.multidim_product import multidim_input_schema, run_multidim_query
from gravity_insight.output_projection import apply_output_fields
from gravity_insight.plan_multidim_result import sanitize_multidim_result
from gravity_insight.result_audit import add_result_audit
from tests.test_gravity_insight_analysis import client_for


QUERY = "report.multidim.query"
TOTAL = "report.multidim.calc_total"
INPUTS = {
    "date_list": ["2026-01-12", "2026-01-15"],
    "time_dims": "day",
    "metrics_list": ["ap_cost"],
}


def native_client(rows, *, total_failure=False):
    def handler(_method, path, kwargs):
        if path.endswith("metric/list/"):
            return {"code": 0, "data": {"list": [
                {"name": "ap_cost", "exclusion_dims": []},
            ]}}
        if path.endswith("custom_get/"):
            return {"code": 0, "data": {
                "list": deepcopy(rows), "page_info": {"total": len(rows)},
            }}
        if path.endswith("calc_total/"):
            if total_failure:
                return {"code": 500, "msg": "unavailable"}
            # The fake upstream receives exactly the query's returned rows.
            assert kwargs["body"]["data_list"] == [rows]
            return {"code": 0, "data": {"list": [{"ap_cost": 13}]}}
        raise AssertionError(path)

    return client_for(QUERY, TOTAL, "report.multidim.metric.list", handler=handler)


def test_empty_include_total_skips_native_total_and_keeps_unknown_calendar():
    client, transport = native_client([])
    result = run_multidim_query(client, INPUTS, app_id=17, include_total=True)
    assert (result["status"], result["query"]["status"], result["total"]) == ("empty", "empty", None)
    assert result["completeness"] == "unknown"
    boundary = result["source_availability"]
    assert boundary["gap_code"] == GAP_CODE
    assert boundary["composite_total"]["empty_query_behavior"] == "skip_calc_total_and_return_null"
    assert boundary["missing_dates"] == "unknown_not_zero"
    assert boundary["source_through"] is None
    assert not any(path.endswith("calc_total/") for _, path, _ in transport.calls)
    assert sum(path.endswith("custom_get/") for _, path, _ in transport.calls) == 1
    validate_schema(boundary, "multidim-source-availability-v1.schema.json", "Multidim source availability")


def test_reconciled_total_and_explicit_zero_rows_do_not_close_trailing_dates():
    rows = [{"day": "2026-01-12", "ap_cost": 0}, {"day": "2026-01-13", "ap_cost": 13}]
    client, transport = native_client(rows)
    result = GravitySDK(insight=client).multidim_query(INPUTS, app=17, include_total=True)
    assert result["query"]["data"]["list"] == rows
    assert result["total"]["data"]["list"] == [{"ap_cost": 13}]
    assert result["completeness"] == "unknown"
    boundary = result["source_availability"]
    assert boundary["composite_total"]["basis"] == "returned_query_rows"
    assert "complete-requested-window-spend" in boundary["forbidden_claims"]
    assert boundary["source_through"] is boundary["native_calendar"] is None
    assert boundary["zero_suppression"] == "unverified"
    assert len(transport.calls) == 3  # metadata, query, native returned-row total


def test_projection_keeps_the_boundary_and_replaces_forged_source_claims():
    client, _transport = native_client([])
    native = run_multidim_query(client, INPUTS, app_id=17, include_total=True)
    raw = client.read(QUERY, {**INPUTS, "filters": []})
    selected = apply_output_fields(raw, client.schema(QUERY), ["ap_cost"], request_inputs=INPUTS)
    expected = raw["source_availability"]
    assert raw["fetched_at"]
    assert expected["source_through"] is None
    assert selected["source_availability"] == expected
    forged = deepcopy(native)
    forged["source_availability"].update(source_through="private-calendar-value", arbitrary="private-value")
    forged["query"]["source_availability"] = forged["source_availability"]
    safe = sanitize_multidim_result(forged, "17", fields=("query",))
    assert safe["source_availability"] == safe["query"]["source_availability"] == expected
    assert "private-" not in json.dumps(safe)
    raw["source_availability"] = forged["source_availability"]
    assert add_result_audit(raw, ())["source_availability"] == expected


def test_failed_total_preserves_its_failure_without_certifying_calendar():
    client, transport = native_client([{"ap_cost": 13}], total_failure=True)
    result = run_multidim_query(client, INPUTS, app_id=17, include_total=True)
    assert result["ok"] is False
    assert result["exit_code"] != 0
    assert result["error"]["stage"] == "total"
    assert result["source_availability"]["availability"] == "unavailable"
    assert len(transport.calls) == 3


def test_schema_and_agent_discovery_publish_an_immutable_unavailable_contract():
    declaration = multidim_input_schema()["x-source-availability"]
    advertised = MULTIDIM_CAPABILITY["input_schema"]["inputs"]["machine_schema"]["x-source-availability"]
    assert advertised == declaration
    declaration["source_through"] = "2026-01-15"
    with pytest.raises(AgentRuntimeContractError):
        validate_schema(declaration, "multidim-source-availability-v1.schema.json", "Multidim source availability")
    assert multidim_input_schema()["x-source-availability"]["source_through"] is None
