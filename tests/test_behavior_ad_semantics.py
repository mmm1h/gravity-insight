"""Native IAA observations never acquire invented monetary/calendar facts."""

from copy import deepcopy
import json

import pytest

from gravity_insight.agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from gravity_insight.agents.multidim import MULTIDIM_CAPABILITY
from gravity_insight.agents.unavailable_analysis import unavailable_analysis_gap
from gravity_insight.contracts.behavior_ad_semantics import GAP_CODE
from gravity_insight.executor import _shape_fingerprint
from gravity_insight.multidim_product import multidim_input_schema
from gravity_insight.output_projection import apply_output_fields
from gravity_insight.plan_multidim_result import sanitize_multidim_result
from gravity_insight.result_audit import add_result_audit
from tests.test_gravity_insight_analysis import client_for, page
from tests.test_semantic_compose import native_result


MULTIDIM = "report.multidim.query"
MONETIZATION = "report.get.query"


def read_native(operation, metrics, values):
    def handler(_method, path, _kwargs):
        if path.endswith("metric/list/"):
            return page([{"name": name, "cname": name, "data_type": "FLOAT", "exclusion_dims": []} for name in metrics])
        if path.endswith("custom_get/"):
            return page(values)
        raise AssertionError(path)
    client, transport = client_for(operation, "report.multidim.metric.list", handler=handler)
    inputs = {"date_list": ["2026-01-12", "2026-01-13"], "time_dims": "day", "metrics_list": metrics,
              "data_dims": ["app_id"], "filters": [{"field": "app_id", "operator": "EQUALS", "values": [101]}]}
    return client.read(operation, inputs), client, transport


@pytest.mark.parametrize("operation,amount", [(MULTIDIM, "reporting_ad_amount"), (MONETIZATION, "reporting_ad_revenue")])
def test_native_values_and_missing_dates_survive_without_currency_conversion_or_uv_sum(operation, amount):
    rows = [{"day": "2026-01-12", amount: 1.234567, "reporting_ad_uv": 7}, {"day": "2026-01-12", amount: 2.345678, "reporting_ad_uv": 7}]
    result, _client, transport = read_native(operation, [amount, "reporting_ad_uv"], rows)
    boundary = result["behavior_ad_semantics"]
    validate_schema(boundary, "behavior-ad-semantics-v1.schema.json", "Behavior advertising semantics")
    assert result["data"]["list"] == rows
    assert result["schema_fingerprint"] == _shape_fingerprint(result["data"])
    assert boundary["monetary_unit"] is boundary["currency"] is boundary["native_bucket_timezone"] is boundary["dataset_as_of"] is None
    assert boundary["settlement_status"] == "unverified"
    assert boundary["grouped_ad_uv"] == "non_additive"
    assert boundary["missing_dates"] == "unknown_not_zero"
    assert boundary["cross_family_amount_equivalence"] == "unverified"
    assert sum(path.endswith("custom_get/") for _method, path, _kwargs in transport.calls) == 1
    assert "101" not in json.dumps(boundary)


def test_selected_projection_and_plan_keep_only_the_closed_unknown_boundary():
    raw, client, _transport = read_native(MULTIDIM, ["reporting_ad_amount"], [{"reporting_ad_amount": 1.25}])
    selected = apply_output_fields(raw, client.schema(MULTIDIM), ["reporting_ad_amount"], request_inputs={"metrics_list": ["reporting_ad_amount"]})
    product = native_result()
    product["query"] = selected
    safe = sanitize_multidim_result(product, "17")
    assert safe["query"]["behavior_ad_semantics"] == raw["behavior_ad_semantics"]
    forged = deepcopy(raw)
    forged.pop("request")
    forged["behavior_ad_semantics"]["currency"] = "CNY"
    assert "behavior_ad_semantics" not in add_result_audit(forged, ())


def test_ordinary_metrics_and_empty_results_keep_their_prior_behavior():
    ordinary, _client, _transport = read_native(MULTIDIM, ["cost"], [{"cost": 1.25}])
    assert "behavior_ad_semantics" not in ordinary
    empty, _client, _transport = read_native(MULTIDIM, ["reporting_ad_amount"], [])
    assert empty["status"] == "empty"
    assert empty["behavior_ad_semantics"]["source_completeness"] == "unknown"


def test_discovery_and_financial_claim_requests_return_the_same_registered_gap():
    schema = multidim_input_schema()["x-native-behavior-ad-semantics"]
    assert schema == MULTIDIM_CAPABILITY["input_schema"]["inputs"]["machine_schema"]["x-native-behavior-ad-semantics"]
    assert schema["gap_code"] == GAP_CODE
    for query in ("确认 IAA 币种和结算现金", "reporting_ad_amount native timezone", "IAA收入公式和财务账精确合并", "IAA native monetary unit"):
        result = unavailable_analysis_gap(query)
        assert result["code"] == GAP_CODE
    assert unavailable_analysis_gap("查询 IAA 原生估算序列") is None
    boundary = schema["families"][0]
    with pytest.raises(AgentRuntimeContractError):
        validate_schema({**boundary, "currency": "CNY"}, "behavior-ad-semantics-v1.schema.json", "Behavior advertising semantics")
