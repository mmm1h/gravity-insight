"""Decision-workbench follow-ups: silent Funnel grouping, misread grains, empty Retention."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from gravity_insight._field_policy_analysis import validate_analysis_shape
from gravity_insight.analysis_interpretation import RETENTION_EMPTY_WARNING, attach_analysis_interpretation
from gravity_insight.analysis_spec import compile_query_spec
from gravity_insight.errors import ErrorDetail, GravityInsightError, InputValidationError
from gravity_insight.find_metadata import search_metadata
from gravity_insight.semantic_rejection import classify_read_rejection, raise_read_rejection
from tests.test_gravity_analysis_query_batch import _issue_24_spec


def _funnel_inputs(*groups):
    spec = {**_issue_24_spec(0), "window": {"unit": "day", "value": 1}, "group_by": list(groups)}
    spec["steps"] = spec["steps"] * 2
    return compile_query_spec("funnel", spec, app=101).inputs


def test_funnel_rejects_a_second_grouping_dimension_before_dispatch():
    first, second = {"field": "pay_method", "source": "user"}, {"field": "ab_label", "source": "user"}
    validate_analysis_shape("funnel", _funnel_inputs(first))
    # Raw event/default create_time groups are time grains, as the field policy reads them.
    for time_type in ("event", "default"):
        raw = _funnel_inputs(first)
        raw["group_by_list"][0] = {"type": time_type, "field": "create_time", "group_by": "day"}
        validate_analysis_shape("funnel", raw)
    with pytest.raises(InputValidationError) as caught:
        validate_analysis_shape("funnel", _funnel_inputs(first, second))
    error = caught.value
    assert (error.field, error.to_error_detail().retryable) == ("group_by_list[2].field", False)
    assert error.unsupported_items == ({"field": "ab_label", "type": "unsupported_grouping"},)


def test_a_user_create_time_group_is_not_reported_as_the_time_grain():
    user_group = {"type": "user", "field": "create_time", "group_by": "create_time", "operator": "day"}
    payload = {"code": 1004, "extra": {"error": "unreviewed sentence"}}

    def classified(time_group):
        inputs = {"group_by_list": [time_group, user_group]}
        return classify_read_rejection(payload, operation_id="analysis.event.query", request_inputs=inputs)

    field, _message, next_action = classified({"type": "default_event", "field": "create_time", "group_by": "day"})
    assert field != "time_grain" and "time_grain" not in next_action
    assert classified({"type": "event", "field": "create_time", "group_by": "week"})[0] == "time_grain"
    event = _issue_24_spec(0)
    spec = {"start": event["start"], "end": event["end"], "steps": event["steps"][:1] * 2, "offset": 1,
            "period_calc_method": "SUM", "custom_before_method": "SUM", "total_calc_type": "DAY",
            "week_first_day": 1, "group_by": [{"field": "create_time", "source": "user"}]}
    compiled = compile_query_spec("retention", spec, app=101).inputs["group_by_list"]
    assert compiled[0] == {"type": "default_event", "field": "create_time", "group_by": "day"}


def test_a_sentence_sharing_only_the_prefix_stays_unreviewed():
    sentence = "处理事件属性分组错误：用户属性[vip_level]查询超时,请稍后重试"
    with pytest.raises(GravityInsightError) as caught:
        raise_read_rejection({"code": 1004, "extra": {"error": sentence}}, operation_id="analysis.event.query")
    assert (caught.value.code, caught.value.retryable) == ("UPSTREAM_UNAVAILABLE", True)


@pytest.mark.parametrize("result,kind,warned", [
    ({"status": "empty", "warnings": []}, "retention", True),
    ({"status": "success", "warnings": []}, "retention", False),
    ({"status": "empty", "warnings": []}, "event", False),
    # A period comparison with one empty window is partial at the top level.
    ({"status": "partial", "windows": {"baseline": {"status": "success"}, "current": {"status": "empty"}}}, "retention", True),
])
def test_only_empty_retention_warns_that_zero_is_unestablished(result, kind, warned):
    attached = attach_analysis_interpretation(result, kind, {})
    assert (RETENTION_EMPTY_WARNING in attached.get("warnings", ())) is warned


def test_missing_catalog_and_operationless_errors_name_an_executable_next_step():
    with tempfile.TemporaryDirectory() as raw:
        with pytest.raises(InputValidationError) as caught:
            search_metadata("first_pay", database=Path(raw) / "absent.sqlite3")
    assert "gravity metadata sync" in caught.value.next_action
    assert "<operation-id>" not in ErrorDetail.create("INPUT_INVALID", "bad spec").next_action
    assert "describe app.list" in ErrorDetail.create("INPUT_INVALID", "bad", operation_id="app.list").next_action
