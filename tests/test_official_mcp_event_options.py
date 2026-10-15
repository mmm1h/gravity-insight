"""Risk coverage for the official Event options on the governed Runtime owner."""

from copy import deepcopy
from dataclasses import replace

import pytest

from gravity_insight._field_policy_analysis import validate_analysis_query, validate_analysis_shape
from gravity_insight import AnalysisFormula, AnalysisMetric, AnalysisSpec, AnalysisStep
from gravity_insight.analysis_spec import analysis_query_spec_schema, compile_query_spec
from gravity_insight.errors import InputValidationError
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_analysis_adapter import execute_analysis_query_plan, validate_analysis_query_plan
from gravity_insight.sdk import GravitySDK
from tests.test_gravity_analysis_spec import FakeInsight, step


QUERY_ID = "1700000000000AAAAAAAAAAAAAAAAAAA"


def formula_spec():
    return {
        "app": "101",
        "query_id": QUERY_ID,
        "date_ranges": [{"start": "2026-08-01", "end": "2026-08-02"}] * 10,
        "formulas": [{"name": "ratio", "formula": "x1/x2", "steps": [step("open"), step("pay")]}],
        "user_filters": {"country": ["CN"]},
        "calculate_y": True,
        "calculate_layer_y": True,
        "return_hierarchy_list": True,
        "page_size": 500,
    }


def test_formula_only_controls_share_the_direct_plan_wire_and_row_budget():
    spec = formula_spec()
    original = deepcopy(spec)
    insight = FakeInsight()
    sdk = GravitySDK(insight=insight)
    sdk._analysis_query_direct("event", spec)
    direct_input = insight.reads[-1]
    context = AdapterContext("event", "test", "composite", sdk.workspace, (), (), 1, 500)
    result = execute_analysis_query_plan(
        sdk, {"name": "analysis_query", "kind": "event", "app": "101", "spec": spec}, context
    )
    assert insight.reads[-1] == direct_input
    inputs = direct_input[1]
    assert (inputs["query_item_list"], len(inputs["date_list"]), inputs["user_filtering"], inputs["page_size"]) == ([], 10, {"country": ["CN"]}, 500)
    assert inputs["calc_y"] and inputs["calc_layer_y"] and inputs["return_hierarchy_list"]
    assert result["interpretation"]["metrics"] == [{"field": "ratio", "aggregation": "formula", "additivity": "unknown"}]
    assert spec == original
    assert compile_query_spec("event", spec).plan_node()["limits"]["max_items"] == 500
    with pytest.raises(InputValidationError, match="max_items"):
        validate_analysis_query_plan(
            insight, sdk.workspace,
            {"name": "analysis_query", "kind": "event", "app": "101", "spec": spec},
            replace(context, max_items=200),
        )


def test_user_filters_require_same_app_live_metadata_before_query_dispatch():
    inputs = compile_query_spec("event", formula_spec()).inputs
    calls = []

    def loader(operation, request):
        calls.append((operation, request))
        names = ["open", "pay"] if operation == "analysis.event.list" else []
        return {"ok": True, "status": "success", "data": {"list": [{"name": name} for name in names]}}

    with pytest.raises(InputValidationError):
        validate_analysis_query("event", inputs, loader)
    assert any(operation == "analysis.user_property.list" and request["app_id"] == "101" for operation, request in calls)


@pytest.mark.parametrize("change", [
    {"start": "2026-08-01", "end": "2026-08-02"},
    {"date_ranges": [{"start": "2026-08-01", "end": "2026-08-02"}] * 11},
    {"page_size": True},
    {"page_size": 10001},
    {"user_filters": {"country": {"unchecked": "object"}}},
    {"formulas": [{"name": "ratio", "formula": "x1/x2", "steps": [step("open")]}]},
    {"formulas": [], "steps": []},
])
def test_invalid_extended_spec_fails_before_client_validation(change):
    insight = FakeInsight()
    with pytest.raises(InputValidationError):
        GravitySDK(insight=insight).compile_analysis_query("event", {**formula_spec(), **change})
    assert insight.validated == []
    assert insight.reads == []


def test_typed_formula_and_event_only_higher_bounds_preserve_other_kinds():
    metric = AnalysisMetric("PresetAllCount", "PresetAllCount")
    typed = AnalysisSpec.event(
        "2026-08-01", "2026-08-02", app="101",
        formulas=[AnalysisFormula("total", "x1", (AnalysisStep("open", metric),))],
    )
    assert compile_query_spec("event", typed).inputs["query_item_list"] == []
    ordinary = {"app": "101", "start": "2026-08-01", "end": "2026-08-02", "steps": [step("open")] * 100}
    assert len(compile_query_spec("event", ordinary).inputs["query_item_list"]) == 100
    with pytest.raises(InputValidationError):
        compile_query_spec("funnel", ordinary)
    funnel = compile_query_spec("funnel", {**ordinary, "steps": [step("open"), step("pay")], "window": {"unit": "day", "value": 1}}).inputs
    funnel["query_item_list"][0]["event_index"] = 99
    with pytest.raises(InputValidationError, match="0 through 49"):
        validate_analysis_shape("funnel", funnel)
    schema = analysis_query_spec_schema()
    assert schema["kind_schemas"]["event"]["properties"]["date_ranges"]["maxItems"] == 10
