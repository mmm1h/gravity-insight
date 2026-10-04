"""Batch components carry their own HTTP receipt references (#245)."""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import gravity_insight.receipt as receipt
from gravity_insight.result_audit import STORED, receipt_reference
from tests.test_gravity_analysis_query_batch import _event_result, _issue_24_spec, _transport_sdk


def _receipt_id(day: str, attempt: int) -> str:
    return hashlib.md5(f"{day}#{attempt}".encode()).hexdigest()


def _sdk(*, fail_first: set[str] = frozenset(), parties: int = 1):
    attempts: dict[str, int] = {}

    def response(_method, _path, kwargs):
        # Stand-in for the HTTP layer: record one receipt in the active result context.
        day = kwargs["body"]["date_list"][0]["start_date"]
        attempts[day] = attempts.get(day, 0) + 1
        receipt._ACTIVE_RESULT_RECEIPTS.get().append(receipt_reference(_receipt_id(day, attempts[day]), STORED))
        if day in fail_first and attempts[day] == 1:
            return {"code": 1004, "extra": {"error": "unreviewed capacity sentence"}}
        return _event_result()

    return _transport_sdk(response, rendezvous_parties=parties)[0]


def _run(sdk, specs, **extra):
    payload = {"schema_version": "gravity.analysis-query-batch.v1", "queries": [
        {"id": f"q{index}", "kind": "event", "app": "demo", "spec": spec, **extra}
        for index, spec in enumerate(specs)
    ]}
    with patch("gravity_insight.analysis_query_batch_retry.time.sleep"):
        return sdk.analysis_queries(payload, max_workers=len(specs))


def _receipts(item):
    return [ref["receipt_id"] for ref in item["result"]["result_audit"]["http_receipts"]]


def test_concurrent_components_reference_only_their_own_receipts():
    specs = [_issue_24_spec(index) for index in range(3)]
    result = _run(_sdk(parties=3), specs)
    for item, spec in zip(result["results"], specs):
        assert _receipts(item) == [_receipt_id(spec["start"], 1)]
        assert set(item["result"]["result_audit"]["http_receipts"][0]) == {"receipt_id", "storage_status"}


def test_retried_component_references_the_execution_that_produced_its_result():
    specs = [_issue_24_spec(index) for index in range(2)]
    result = _run(_sdk(fail_first={specs[1]["start"]}), specs)
    assert result["results"][1]["status"] == "success"
    assert _receipts(result["results"][1]) == [_receipt_id(specs[1]["start"], 2)]
    assert _receipts(result["results"][0]) == [_receipt_id(specs[0]["start"], 1)]


def test_selected_output_fields_keep_the_audit_surface():
    spec = _issue_24_spec(0)
    result = _run(_sdk(), [spec], output_fields=["target_list"])
    item = result["results"][0]
    assert item["status"] == "success" and item["result"]["output_fields"] == ["target_list"]
    assert _receipts(item) == [_receipt_id(spec["start"], 1)]
