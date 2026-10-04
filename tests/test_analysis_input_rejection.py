"""Deterministic Event input failures must not become capacity retries."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from gravity_insight._field_policy_analysis import validate_analysis_shape
from gravity_insight._field_policy_shared import ANALYSIS_CONDITION_OPERATORS
from gravity_insight.analysis_spec import analysis_query_spec_schema, compile_query_spec
from gravity_insight.analysis_spec_cli import _spec_schema_result
from gravity_insight.cli import build_parser
from gravity_insight.errors import InputValidationError, SemanticRejectedError
from gravity_insight.semantic_rejection import raise_read_rejection
from tests.test_gravity_analysis_query_batch import _event_result, _issue_24_spec, _transport_sdk


def event_spec(condition=None):
    spec = _issue_24_spec(0)
    spec["global_filters"] = [condition] if condition else []
    return spec


def condition(operator, **extra):
    return {"type": "event", "field": "level", "operator": operator, **extra}


@pytest.mark.parametrize("short,long", [
    ("GT", "GREATER"), ("GTE", "GREATER_EQUALS"), ("LT", "LESS"), ("LTE", "LESS_EQUALS"),
])
def test_event_alias_rejection_preserves_other_dsl_and_gives_exact_remedy(short, long):
    spec = event_spec(condition(short, value=[123456789]))
    with pytest.raises(InputValidationError) as caught:
        compile_query_spec("event", spec, app=101)
    error = caught.value
    assert (error.code, error.field, error.to_error_detail().retryable) == ("INPUT_INVALID", "global_conditions[0].operator", False)
    assert f"Replace {short} with {long}" in error.next_action
    assert "123456789" not in str(error) + error.next_action
    schema = analysis_query_spec_schema()["definitions"]
    assert short not in schema["event_condition"]["properties"]["operator"]["enum"]
    assert short in ANALYSIS_CONDITION_OPERATORS & set(schema["condition"]["properties"]["operator"]["enum"])
    spec["window"] = {"unit": "day", "value": 1}
    assert compile_query_spec("funnel", spec, app=101).inputs["global_conditions"][0]["operator"] == short


def test_raw_event_custom_step_cannot_bypass_operator_policy():
    inputs = compile_query_spec("event", event_spec(), app=101).inputs
    item = deepcopy(inputs["query_item_list"][0])
    item["conditions"] = [condition("GT", value=[0])]
    inputs["custom_query_item_list"] = [{"formula": "x", "query_item_list": [item]}]
    with pytest.raises(InputValidationError) as caught:
        validate_analysis_shape("event", inputs)
    assert caught.value.field == "custom_query_item_list[0].query_item_list[0].conditions[0].operator"


def test_valueless_conditions_compile_without_changing_spec():
    spec = event_spec(condition("WITH_VAL"))
    spec["steps"][0]["conditions"] = [condition("WITHOUT_VAL")]
    original = deepcopy(spec)
    compiled = compile_query_spec("event", spec, app=101)
    assert compiled.inputs["global_conditions"][0]["value"] == []
    assert compiled.inputs["query_item_list"][0]["conditions"][0]["value"] == []
    assert spec == original
    # The compiler also owns Property's distinct condition slot.
    prop = compile_query_spec("property", {
        "property": {"field": "level", "aggregation": "SumCount", "data_type": "INT"},
        "conditions": [condition("WITH_VAL")],
    }, app=101)
    assert prop.inputs["query_item"]["conditions"][0]["value"] == []


def test_value_bearing_condition_missing_value_stops_before_batch_transport():
    sdk, transport = _transport_sdk(_event_result(), disable_field_validation=False)
    payload = {"schema_version": "gravity.analysis-query-batch.v1", "queries": [{
        "id": "missing", "kind": "event", "app": "demo", "spec": event_spec(condition("EQUALS")),
    }]}
    with pytest.raises(InputValidationError) as caught:
        sdk.analysis_queries(payload, max_workers=4)
    assert caught.value.field == "global_conditions[0].value"
    assert "explicit scalar array" in caught.value.next_action
    assert transport.calls == []


def test_event_quantile_compiles_proven_wire_and_rejects_ambiguous_percentile():
    spec = event_spec()
    spec["steps"][0]["metric"] = {"field": "level", "aggregation": "Quantile_50"}
    target = compile_query_spec("event", spec, app=101).inputs["query_item_list"][0]["target"]
    assert target == {"field": "level", "name": "Quantile", "quantile_level": 50}
    spec["steps"][0]["metric"]["quantile"] = 75
    with pytest.raises(InputValidationError, match="conflicting quantile"):
        compile_query_spec("event", spec, app=101)
    spec["steps"][0]["metric"] = {"field": "level", "aggregation": "Quantile"}
    with pytest.raises(InputValidationError) as caught:
        compile_query_spec("event", spec, app=101)
    assert caught.value.field == "steps[0].metric.quantile"
    spec["steps"][0]["metric"]["quantile"] = 50
    assert compile_query_spec("event", spec, app=101).inputs["query_item_list"][0]["target"] == target


def test_cli_publishes_the_same_kind_scoped_input_contract():
    args = build_parser().parse_args(["analysis", "query", "--kind", "event", "--spec-schema"])
    published = _spec_schema_result(args)
    assert published.pop("requested_kind") == "event"
    assert published == analysis_query_spec_schema()
    definitions = published["definitions"]
    assert definitions["condition"]["allOf"][0]["else"] == {"required": ["value"]}
    assert definitions["event_query_step"]["properties"]["conditions"]["items"]["$ref"] == "#/definitions/event_condition"
    assert definitions["event_metric"]["allOf"][0]["then"] == {"required": ["quantile"]}


REJECTIONS = [
    ("operator:GT非法", "conditions[].operator", "GREATER"),
    ("operator:GTE非法", "conditions[].operator", "GREATER_EQUALS"),
    ("operator:LT非法", "conditions[].operator", "LESS"),
    ("operator:LTE非法", "conditions[].operator", "LESS_EQUALS"),
    ("参数缺失,value:{'private': 'sensitive-marker'}", "conditions[].value", "value=[]"),
    ("统计指标不正确: Quantile_50", "target.name", "quantile_level=N"),
    ("处理事件属性分组错误：该事件未绑定属性[$pay_reason]", "group_by_list[].field", "unknown"),
    # The sentence embeds the caller's property name, so the prefix must generalize.
    ("处理事件属性分组错误：该事件未绑定属性[other_property]", "group_by_list[].field", "unknown"),
    ("处理事件属性分组错误：用户属性[create_time]已经被删除", "group_by_list[].field", "default_user create_time"),
    # The DATETIME sentence starts with the caller's property name, so it matches by suffix.
    ("$first_pay_time属性格式不正确,需传递[yyyy-MM-dd HH:mm:ss]格式", "conditions[].value", "YYYY-MM-DD 00:00:00"),
]


@pytest.mark.parametrize("sentence,field,remedy", REJECTIONS)
def test_reviewed_rejections_have_nonretryable_value_safe_remedies(sentence, field, remedy):
    with pytest.raises(SemanticRejectedError) as caught:
        raise_read_rejection({"code": 1004, "extra": {"error": sentence}}, operation_id="analysis.event.query")
    error = caught.value
    assert (error.category, error.to_error_detail().retryable, error.field) == ("caller", False, field)
    assert remedy in error.next_action
    assert sentence not in str(error) + error.next_action
    assert "sensitive-marker" not in str(error) + error.next_action


def test_batch_retries_only_the_unreviewed_sentence_not_deterministic_components():
    sentences = [row[0] for row in REJECTIONS] + ["unreviewed capacity sentence"]
    specs = [_issue_24_spec(index) for index in range(len(sentences))]
    by_day = {spec["start"]: index for index, spec in enumerate(specs)}
    attempts = [0] * len(specs)

    def response(_method, _path, kwargs):
        index = by_day[kwargs["body"]["date_list"][0]["start_date"]]
        attempts[index] += 1
        if index == len(specs) - 1 and attempts[index] > 1:
            return _event_result()
        return {"code": 1004, "extra": {"error": sentences[index]}}

    sdk, transport = _transport_sdk(response)
    payload = {"schema_version": "gravity.analysis-query-batch.v1", "queries": [
        {"id": f"q{index}", "kind": "event", "app": "demo", "spec": spec}
        for index, spec in enumerate(specs)
    ]}
    with patch("gravity_insight.analysis_query_batch_retry.time.sleep"):
        result = sdk.analysis_queries(payload, max_workers=4)
    assert attempts == [1] * len(REJECTIONS) + [2]
    assert result["adaptive_execution"]["total_component_attempts"] == len(transport.calls) == len(specs) + 1
    assert "sensitive-marker" not in str(result)


def test_similar_but_unreviewed_operator_sentence_is_not_silently_registered():
    with pytest.raises(SemanticRejectedError) as caught:
        raise_read_rejection({"code": 1004, "extra": {"error": "operator:UNKNOWN非法"}}, operation_id="analysis.event.query")
    assert (caught.value.code, caught.value.retryable) == ("UPSTREAM_UNAVAILABLE", True)
