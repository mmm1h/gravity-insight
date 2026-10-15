"""Order diagnostics retain safe rejection evidence across product boundaries."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from gravity_insight.order_directory import order_directory, sanitize_order_directory_result
from gravity_insight.errors import ContractChangedError
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_order_directory_adapter import execute_order_directory_plan, project_order_directory_result
from gravity_insight.response_drift import ResponseDriftRecorder
from gravity_insight.result_audit import add_result_audit
from tests.test_gravity_order_directory import DAY, ROW, _Client, _read


LIMITS = {"max_workers": 1, "max_pages": 5, "max_items": 10}


def directory(value):
    return order_directory(_Client(value), 7, DAY, **LIMITS)


def test_rejected_row_identifies_field_and_types_without_native_values():
    result = directory(_read([{**ROW, "Amount": {"private-marker": "private-value"}}], workers=1))
    diagnostic = result["contract_diagnostic"]
    assert diagnostic["layer"] == "row"
    assert diagnostic["response_drift"]["fields"] == [{
        "classification": "breaking", "path": "/data/list/*/Amount",
        "expected_type": "json_scalar", "observed_type": "object",
    }]
    assert result["status"] == "contract_changed" and result["data"]["list"] == []
    assert "private-" not in json.dumps(result)


def test_invalid_envelope_and_incomplete_pagination_remain_distinct():
    envelope = _read([ROW], workers=1)
    envelope["schema_version"] = []
    result = directory(envelope)
    diagnostic = result["contract_diagnostic"]
    assert diagnostic["layer"] == "envelope"
    assert diagnostic["response_drift"]["fields"][0]["path"] == "/schema_version"
    page = _read([ROW], workers=1)
    page["page"]["has_more"] = True
    result = directory(page)
    assert result["contract_diagnostic"]["layer"] == "pagination"
    assert result["error"]["code"] == "CONTRACT_CHANGED"


@pytest.mark.parametrize("with_drift", [True, False])
def test_native_projection_evidence_is_preserved_only_when_observed(with_drift):
    native = _read([], workers=1, status="contract_changed")
    if with_drift:
        recorder = ResponseDriftRecorder()
        recorder.add_breaking_field(("data", "list", "*", "Amount"), "json_scalar", {})
        native = add_result_audit(native, (), response_drift=recorder.to_contract())
    result = directory(native)
    diagnostic = result["contract_diagnostic"]
    assert diagnostic["layer"] == "leaf_projection"
    assert diagnostic["field_evidence"] == ("observed" if with_drift else "unavailable")
    assert bool(diagnostic["response_drift"]) is with_drift
    assert diagnostic["product_schema_version"] == result["schema_version"]
    assert diagnostic["operation_contract_version"]


def test_native_unknown_paths_cannot_leak_through_diagnostics():
    recorder = ResponseDriftRecorder()
    recorder.add_breaking_field(("data", "private-marker"), "object", "private-value")
    native = add_result_audit(_read([], workers=1, status="contract_changed"), (), response_drift=recorder.to_contract())
    result = directory(native)
    assert result["contract_diagnostic"]["field_evidence"] == "unavailable"
    assert "private-" not in json.dumps(result)


def test_additive_native_projection_stays_rejected_with_a_success_marker():
    native = _read([ROW], workers=1, status="contract_changed_additive")
    native["ok"] = True
    result = directory(native)
    assert result["status"] == "contract_changed"
    assert result["contract_diagnostic"]["layer"] == "leaf_projection"
    assert result["contract_diagnostic"]["field_evidence"] == "unavailable"


def test_result_reconstruction_preserves_safe_diagnostic_and_rejects_forgery():
    result = directory(_read([{**ROW, "Amount": {}}], workers=1))
    safe = sanitize_order_directory_result(result, 7, DAY, **LIMITS)
    assert safe["contract_diagnostic"] == result["contract_diagnostic"]
    legacy = {key: value for key, value in result.items() if key not in {"contract_diagnostic", "obligations"}}
    restored = sanitize_order_directory_result(legacy, 7, DAY, **LIMITS)
    assert all(restored[key] == value for key, value in legacy.items())
    assert "contract_diagnostic" not in restored
    forged = deepcopy(result)
    forged["contract_diagnostic"]["response_drift"]["fields"][0]["path"] = "/private-marker"
    rejected = sanitize_order_directory_result(forged, 7, DAY, **LIMITS)
    assert rejected["status"] == "contract_changed"
    assert "private-marker" not in json.dumps(rejected)
    forged_facts = deepcopy(result)
    forged_facts["obligations"]["data_completeness"]["state"] = "complete"
    rejected = sanitize_order_directory_result(forged_facts, 7, DAY, **LIMITS)
    assert rejected["obligations"]["data_completeness"]["state"] == "unknown"


def test_plan_execution_and_field_projection_keep_the_verified_failure_diagnostic():
    result = directory(_read([{**ROW, "Amount": {}}], workers=1))
    workspace = SimpleNamespace(resolve_app=lambda _alias: "7")
    context = AdapterContext("orders", "test", "composite", workspace, ("data",), (), 5, 10)
    sdk = SimpleNamespace(order_directory=lambda *_args, **_kwargs: deepcopy(result))
    verified = execute_order_directory_plan(sdk, {"name": "order_directory", "app": "demo", "date": DAY}, context)
    projected = project_order_directory_result(verified, ("data",), context)
    assert projected["contract_diagnostic"] == result["contract_diagnostic"]
    assert projected["status"] == "contract_changed" and projected["data"]["list"] == []
    assert projected["obligations"]["execution_status"]["state"] == "failed"
    assert projected["obligations"]["data_completeness"]["state"] == "unknown"


def test_native_exception_does_not_claim_unobserved_projection_evidence():
    result = directory(ContractChangedError("private-marker"))
    assert result["contract_diagnostic"]["layer"] == "native_read"
    assert result["contract_diagnostic"]["field_evidence"] == "unavailable"
    assert "private-marker" not in json.dumps(result)
