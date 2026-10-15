"""Native first-day totals require the same query's registered base measures."""

from copy import deepcopy

import pytest

from gravity_insight.errors import ContractChangedError, InputValidationError
from gravity_insight.multidim_service import (
    MULTIDIM_QUERY_OPERATION as QUERY,
    MULTIDIM_TOTAL_OPERATION as TOTAL,
    STANDARD_METRIC_OPERATION as METADATA,
    MultidimService,
)


BASES = ("standard_1day_pay_amount", "ad_1day_amount")


class NativeDependencyClient:
    def __init__(self, *, available=("revenue_1day", *BASES), base_fault=None):
        self.available = available
        self.base_fault = base_fault
        self.target_calls = []
        self.metadata_calls = 0

    def schema(self, operation_id):
        if operation_id == METADATA:
            return {"domain": "report", "resource": "metric", "action": "list"}
        return {"input_fields": {"metrics_list": {}, "data_list": {}}}

    def read_all(self, operation_id, inputs, **limits):
        if operation_id == METADATA:
            self.metadata_calls += 1
            return {"status": "success", "data": {"list": [{"name": name, "exclusion_dims": []} for name in self.available]}}
        return self.read(operation_id, inputs)

    def read(self, operation_id, inputs):
        self.target_calls.append((operation_id, deepcopy(inputs)))
        if operation_id == QUERY:
            observed = {"revenue_1day": 5, BASES[0]: 2, BASES[1]: 3}
            row = {name: observed[name] for name in inputs["metrics_list"]}
            rows = [deepcopy(row)]
            if self.base_fault == "missing":
                row.pop(BASES[0], None)
                rows = [row]
            elif self.base_fault == "null_after_valid_row":
                row[BASES[0]] = None
                rows.append(row)
        else:
            # Characterize the native dependency behavior reported in #279;
            # the Runtime must supply source columns, not calculate the amount.
            row = {"revenue_1day": sum(item.get(BASES[0], 0) + item.get(BASES[1], 0) for item in inputs["data_list"])}
            rows = [row]
        return {"operation_id": operation_id, "ok": True, "status": "success", "data": {"list": rows}}


def test_first_day_total_uses_registered_bases_in_one_query_without_mutating_input():
    client = NativeDependencyClient()
    inputs = {"metrics_list": ["revenue_1day"], "data_dims": []}
    original = deepcopy(inputs)
    result = MultidimService(client).query(inputs, include_total=True)
    assert result["total"]["data"]["list"][0]["revenue_1day"] == result["query"]["data"]["list"][0]["revenue_1day"] == 5
    assert [operation for operation, _ in client.target_calls] == [QUERY, TOTAL]
    assert client.metadata_calls == 1
    assert inputs == original


def test_explicit_dependencies_are_preserved_without_duplicates():
    client = NativeDependencyClient()
    metrics = [BASES[1], "revenue_1day", BASES[0]]
    MultidimService(client).query({"metrics_list": metrics}, include_total=True)
    assert client.target_calls[0][1]["metrics_list"] == metrics


def test_missing_live_dependency_stops_target_calls_but_ordinary_read_remains_available():
    client = NativeDependencyClient(available=("revenue_1day",))
    with pytest.raises(InputValidationError):
        MultidimService(client).query({"metrics_list": ["revenue_1day"]}, include_total=True)
    assert client.target_calls == []
    result = MultidimService(client).query({"metrics_list": ["revenue_1day"]})
    assert result["query"]["data"]["list"] == [{"revenue_1day": 5}]
    assert client.target_calls[0][1]["metrics_list"] == ["revenue_1day"]


@pytest.mark.parametrize("base_fault", ["missing", "null_after_valid_row"])
def test_projected_dependency_gap_cannot_become_a_successful_total(base_fault):
    client = NativeDependencyClient(base_fault=base_fault)
    with pytest.raises(ContractChangedError):
        MultidimService(client).query({"metrics_list": ["revenue_1day"]}, include_total=True)
    assert [operation for operation, _ in client.target_calls] == [QUERY]
