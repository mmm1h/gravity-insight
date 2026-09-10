from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gravity_insight._field_policy_detail import (
    _static_detail_product_request,
    validate_analysis_detail,
)
from gravity_insight._field_policy_operations import (
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_MONETIZATION_DETAIL,
    ANALYSIS_SEGMENT,
    ANALYSIS_USER_PROPERTY,
)
from gravity_insight.errors import ContractChangedError, GravityInsightError, InputValidationError
from gravity_insight.material_game_contract import normalize_request
from gravity_insight.material_game_performance import _read_days, _report_rows
from gravity_insight.material_game_result import safe_failure
from gravity_insight.material_performance_result import MATERIAL_REPORT_OPERATION
from gravity_insight.models import load_operation_manifest
from gravity_insight.monetization_detail import SAFE_ROW_FIELDS
from gravity_insight.user_detail_aggregate_contract import (
    CONDITION_TYPE_MISMATCH,
    FIELD_PRIVACY_EXCLUDED,
    FIELD_UNSUPPORTED,
    METADATA_OPERATION_ID,
    MIXED_TYPE,
    SOURCE_OPERATION_ID,
)
from gravity_insight.user_detail_aggregate_service import UserDetailAggregateService
from gravity_insight.user_detail_registered_aggregate import aggregate_registered_day


DAY = "2026-09-01"
NEXT_DAY = "2026-09-02"
SOURCE = {"app_id": "101", "date": DAY}
LEVEL = "usercurrent_level_user"
PAYMENT = "user$pay_count"
DURATION = "usertotal_session_time"
SENTINEL = "SYNTHETIC-PRIVATE-USER-223"
RECEIPT = {"receipt_id": "a" * 32, "storage_status": "stored"}
METADATA_OPERATIONS = [ANALYSIS_USER_PROPERTY, ANALYSIS_EVENT_PROPERTY, ANALYSIS_SEGMENT]


@pytest.fixture(scope="module")
def operations():
    root = Path(__file__).resolve().parents[1]
    return {
        item.operation_id: item
        for item in load_operation_manifest(root / "src/gravity_insight/manifests/analysis.json")
    }


@pytest.fixture
def operation(operations):
    return operations[SOURCE_OPERATION_ID]


def _group(key="video", field="bytedanceMid3", value="10101"):
    return {
        "key": key,
        "condition": {
            "field": field,
            "operator": "EQUALS",
            "values": [value],
        },
    }


def _metric(name="level", field=LEVEL, operator="GTE", values=None):
    return {
        "name": name,
        "op": "count_if",
        "condition": {
            "field": field,
            "operator": operator,
            "values": [3] if values is None else values,
        },
    }


def _row(**overrides):
    return {
        "CreateTime": f"{DAY} 12:00:00",
        "bytedanceMid3": "10101",
        "bytedanceMid1": None,
        LEVEL: 4,
        PAYMENT: 1,
        DURATION: 120,
        "ClientID": SENTINEL,
        "useraccount_id": SENTINEL,
        "unused_private_value": SENTINEL,
        **overrides,
    }


def _native(rows, *, completeness="unknown", has_more=False, total_pages=1):
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": SOURCE_OPERATION_ID,
        "ok": True,
        "status": "success" if rows else "empty",
        "data": {"list": copy.deepcopy(rows)},
        "page": {
            "number": 1,
            "size": 100,
            "item_count": len(rows),
            "pages_fetched": 1,
            "total_pages": total_pages,
            "total_items": len(rows) if has_more is False else None,
            "has_more": has_more,
            "fetch_strategy": "single_page",
        },
        "completeness": completeness,
        "pagination_evidence": "wire",
        "truncated": has_more is True,
        "next_page_input": {**SOURCE, "page": 2} if has_more is True else None,
        "result_audit": {
            "schema_version": "gravity.result-audit.v1",
            "http_receipts": [dict(RECEIPT)],
        },
    }


class _Client:
    def __init__(self, operation, native):
        self.operation, self.native = operation, native
        self.calls, self.metadata_calls = [], []

    def schema(self, operation_id):
        assert operation_id == SOURCE_OPERATION_ID
        return self.operation.schema()

    def read_all(self, *args, **kwargs):
        pytest.fail("registered-day aggregation must not call read_all or metadata")

    def _metadata(self, operation_id, inputs):
        self.metadata_calls.append((operation_id, inputs))
        pytest.fail("static registered-day fields must not load metadata")

    def read_limited(self, operation_id, inputs, **options):
        assert operation_id == SOURCE_OPERATION_ID
        self.calls.append((operation_id, copy.deepcopy(inputs), options))
        validate_analysis_detail(self.operation, inputs, self._metadata)
        return copy.deepcopy(self.native)


class _OriginalClient(_Client):
    def read_all(self, operation_id, inputs, **options):
        if operation_id == METADATA_OPERATION_ID:
            return {"status": "empty", "data": {"list": []}}
        assert operation_id == SOURCE_OPERATION_ID
        return copy.deepcopy(self.native)


def _run(client, *, groups=None, metrics=None, day=DAY):
    return aggregate_registered_day(
        client,
        {**SOURCE, "date": day},
        [_group()] if groups is None else groups,
        {} if metrics is None else metrics,
        max_pages=2,
        max_items=200,
        max_workers=3,
    )


def test_one_static_read_shares_material_groups_and_metrics_without_raw_output(
    operation,
    capsys,
    caplog,
):
    rows = [
        _row(),
        _row(**{LEVEL: 1, PAYMENT: 0, DURATION: 10}),
        _row(bytedanceMid3=None, bytedanceMid1="20202"),
        _row(bytedanceMid3="99999"),
    ]
    native = _native(rows)
    original = copy.deepcopy(native)
    client = _Client(operation, native)
    metrics = {
        "level": _metric(),
        "payment": _metric("payment", PAYMENT, "GT", [0]),
        "duration": _metric("duration", DURATION, "GTE", [60]),
    }
    result = _run(
        client,
        groups=[_group(), _group("image", "bytedanceMid1", "20202")],
        metrics=metrics,
    )

    assert {key: cell["value"] for key, cell in result["cells"].items()} == {
        "video:matched_users": 2,
        "video:level": 1,
        "video:payment": 1,
        "video:duration": 1,
        "image:matched_users": 1,
        "image:level": 1,
        "image:payment": 1,
        "image:duration": 1,
    }
    assert all(cell["status"] == "obtained" for cell in result["cells"].values())
    assert client.calls == [
        (
            SOURCE_OPERATION_ID,
            {
                **SOURCE,
                "fields": sorted(
                    [
                        "CreateTime",
                        "bytedanceMid1",
                        "bytedanceMid3",
                        LEVEL,
                        PAYMENT,
                        DURATION,
                    ]
                ),
                "page": 1,
                "page_size": 100,
            },
            {"max_pages": 2, "max_items": 200, "max_workers": 3},
        )
    ]
    assert client.metadata_calls == []
    assert result["http_receipts"] == [RECEIPT]
    assert set(result) == {"cells", "scan", "http_receipts"}
    assert native == original
    captured = capsys.readouterr()
    assert SENTINEL not in json.dumps(result) + captured.out + captured.err + caplog.text


@pytest.mark.parametrize(
    "completeness,has_more,total_pages,next_page,remaining",
    [("prefix", True, 3, 2, 2), ("unknown", None, None, None, None)],
)
def test_partial_scan_preserves_unknowns_and_continuation(
    operation,
    completeness,
    has_more,
    total_pages,
    next_page,
    remaining,
):
    client = _Client(
        operation,
        _native(
            [_row()],
            completeness=completeness,
            has_more=has_more,
            total_pages=total_pages,
        ),
    )
    result = _run(client)

    assert result["cells"]["video:matched_users"] == {"status": "obtained", "value": 1}
    assert result["scan"] == {
        "pages_scanned": 1,
        "items_scanned": 1,
        "last_page": 1,
        "next_page": next_page,
        "total_pages": total_pages,
        "remaining_pages": remaining,
        "has_more": has_more,
        "completeness": completeness,
        "pagination_finished": False,
    }
    assert len(client.calls) == 1


def test_all_null_metric_is_unavailable_only_for_its_selected_cohort(operation):
    missing = _row()
    del missing[LEVEL]
    client = _Client(
        operation,
        _native(
            [
                _row(**{LEVEL: None}),
                missing,
                _row(bytedanceMid3="20202"),
                _row(CreateTime=f"{NEXT_DAY} 00:00:00"),
            ]
        ),
    )
    result = _run(
        client,
        groups=[_group(), _group("other", value="20202")],
        metrics={"level": _metric()},
    )

    assert result["cells"]["video:level"] == {
        "status": "unavailable",
        "value": None,
        "reason": "METRIC_VALUES_UNAVAILABLE",
    }
    assert result["cells"]["video:matched_users"]["value"] == 2
    assert result["cells"]["other:level"] == {
        "status": "obtained",
        "value": 1,
        "definition": _metric(),
    }


@pytest.mark.parametrize(
    "values,code,category",
    [
        ([SENTINEL, SENTINEL], CONDITION_TYPE_MISMATCH, "caller"),
        ([4, SENTINEL], MIXED_TYPE, "upstream"),
        ([{SENTINEL: 4}], MIXED_TYPE, "upstream"),
    ],
    ids=["condition-type-mismatch", "mixed-native-types", "non-scalar"],
)
def test_type_errors_match_original_classification_and_do_not_expose_values(
    operation,
    values,
    code,
    category,
    capsys,
    caplog,
):
    # Original type validation also considers unrelated and out-of-day rows.
    rows = [_row(**{LEVEL: values[0]})]
    rows.extend(
        _row(
            CreateTime=f"{NEXT_DAY} 00:00:00",
            bytedanceMid3="99999",
            **{LEVEL: value},
        )
        for value in values[1:]
    )
    native = _native(rows)
    original_inputs = {
        "source": dict(SOURCE),
        "filters": [_group()["condition"]],
        "group_by": [],
        "measures": [_metric()],
        "bounds": {"max_pages": 2, "max_items": 200, "max_cells": 200},
    }
    with pytest.raises(GravityInsightError) as raised:
        UserDetailAggregateService(_OriginalClient(operation, native)).aggregate(original_inputs)

    result = _run(_Client(operation, native), metrics={"level": _metric()})
    failed = result["cells"]["video:level"]
    assert failed["reason"] == code
    assert failed["error"] == raised.value.to_error_detail().to_dict()
    assert failed["error"]["category"] == category
    assert failed["status"] == "unavailable" and failed["value"] is None
    assert result["cells"]["video:matched_users"] == {"status": "obtained", "value": 1}
    captured = capsys.readouterr()
    assert SENTINEL not in json.dumps(result) + str(raised.value) + captured.out + captured.err + caplog.text


def test_join_condition_does_not_coerce_string_identifiers(operation):
    result = _run(_Client(operation, _native([_row()])), groups=[_group(value=10101)])
    assert result["cells"]["video:matched_users"]["reason"] == CONDITION_TYPE_MISMATCH
    assert result["cells"]["video:matched_users"]["value"] is None


def test_registration_days_remain_disjoint_when_source_repeats_snapshots(operation):
    client = _Client(
        operation,
        _native(
            [
                _row(CreateTime=f"{DAY} 00:00:00"),
                _row(CreateTime=f"{DAY} 23:59:59"),
                _row(CreateTime=f"{NEXT_DAY} 00:00:00"),
                _row(CreateTime="2026-08-31 23:59:59"),
            ]
        ),
    )
    results = [_run(client, day=day) for day in (DAY, NEXT_DAY)]

    assert [item["cells"]["video:matched_users"]["value"] for item in results] == [2, 1]
    assert [call[1]["date"] for call in client.calls] == [DAY, NEXT_DAY]


@pytest.mark.parametrize("created", [None, f"{DAY} invalid-{SENTINEL}"])
def test_unprovable_creation_date_invalidates_cells_without_raw_values(operation, created):
    result = _run(
        _Client(operation, _native([_row(CreateTime=created)])),
        metrics={"level": _metric()},
    )
    assert {cell["reason"] for cell in result["cells"].values()} == {"MATERIAL_COHORT_DATE_UNAVAILABLE"}
    assert all(cell["status"] == "unavailable" and cell["value"] is None for cell in result["cells"].values())
    assert SENTINEL not in json.dumps(result)


@pytest.mark.parametrize(
    "measure,reason",
    [
        ({"name": "level", "op": "sum", "field": LEVEL}, FIELD_UNSUPPORTED),
        (_metric(field="ClientID", operator="WITH_VAL", values=[]), FIELD_PRIVACY_EXCLUDED),
        (_metric(field="userunregistered_metric"), FIELD_UNSUPPORTED),
    ],
    ids=["sum-requires-metadata", "private-field", "unregistered-field"],
)
def test_unsupported_metrics_are_not_requested_and_do_not_disable_counts(operation, measure, reason):
    client = _Client(operation, _native([_row()]))
    result = _run(client, metrics={"level": measure})
    assert result["cells"]["video:level"]["reason"] == reason
    assert result["cells"]["video:level"]["value"] is None
    assert result["cells"]["video:matched_users"] == {"status": "obtained", "value": 1}
    assert client.calls[0][1]["fields"] == ["CreateTime", "bytedanceMid3"]
    assert SENTINEL not in json.dumps(result)


def test_private_group_is_rejected_before_any_source_read(operation):
    client = _Client(operation, _native([_row()]))
    result = _run(client, groups=[_group(field="ClientID", value=SENTINEL)])
    assert result["cells"]["video:matched_users"]["reason"] == FIELD_PRIVACY_EXCLUDED
    assert result["scan"] is None and result["http_receipts"] == []
    assert client.calls == []
    assert SENTINEL not in json.dumps(result)


def _detail_inputs(**overrides):
    return {
        **SOURCE,
        "fields": ["CreateTime", "bytedanceMid3", LEVEL],
        "page": 1,
        "page_size": 100,
        **overrides,
    }


def _metadata_loader(calls, *, dynamic=False):
    def load(operation_id, inputs):
        assert operation_id in METADATA_OPERATIONS
        assert inputs["app_id"] == SOURCE["app_id"]
        calls.append(operation_id)
        rows = []
        if dynamic and operation_id == ANALYSIS_USER_PROPERTY:
            rows = [{"name": "synthetic_dynamic_level", "data_type": "INT"}]
        return {"status": "success" if rows else "empty", "data": {"list": rows}}

    return load


@pytest.mark.parametrize("page_size", [1, 37, 100])
def test_static_user_fields_skip_metadata_with_clamped_page_sizes(operation, page_size):
    def forbidden_loader(*args):
        pytest.fail("static scalar user fields must not load metadata")

    validate_analysis_detail(operation, _detail_inputs(page_size=page_size), forbidden_loader)
    with pytest.raises(InputValidationError):
        validate_analysis_detail(
            operation,
            _detail_inputs(date="2026-02-30", page_size=page_size),
            forbidden_loader,
        )


def test_smaller_page_fast_path_is_exclusive_to_static_user_fields(operations):
    operation = operations[ANALYSIS_MONETIZATION_DETAIL]
    inputs = _detail_inputs(fields=list(SAFE_ROW_FIELDS))
    assert _static_detail_product_request(operation, inputs)
    assert not _static_detail_product_request(operation, {**inputs, "page_size": 37})


@pytest.mark.parametrize("registered", [True, False])
def test_dynamic_user_fields_retain_live_metadata_membership_validation(operation, registered):
    calls = []
    inputs = _detail_inputs(fields=["usersynthetic_dynamic_level"], page_size=37)
    loader = _metadata_loader(calls, dynamic=registered)
    if registered:
        validate_analysis_detail(operation, inputs, loader)
    else:
        with pytest.raises(InputValidationError, match="absent from live metadata"):
            validate_analysis_detail(operation, inputs, loader)
    assert calls == METADATA_OPERATIONS


@pytest.mark.parametrize("condition_key", ["global_conditions", "postback_conditions"])
def test_conditions_retain_metadata_and_condition_validation(operation, condition_key):
    condition = {
        "field": "bytedanceMid3",
        "operator": "EQUALS",
        "type": "default_user",
        "value": ["10101"],
    }
    calls = []
    validate_analysis_detail(
        operation,
        _detail_inputs(page_size=37, **{condition_key: [condition]}),
        _metadata_loader(calls),
    )
    assert calls == METADATA_OPERATIONS

    calls.clear()
    with pytest.raises(InputValidationError) as raised:
        validate_analysis_detail(
            operation,
            _detail_inputs(**{condition_key: [{**condition, "operator": "UNSUPPORTED"}]}),
            _metadata_loader(calls),
        )
    assert raised.value.to_error_detail().field == f"{condition_key}[].operator"
    assert calls == METADATA_OPERATIONS


def test_nested_projection_and_sorting_do_not_enter_static_fast_path(operation):
    calls = []
    validate_analysis_detail(operation, _detail_inputs(fields=["device_info"]), _metadata_loader(calls))
    assert calls == METADATA_OPERATIONS

    calls.clear()
    with pytest.raises(InputValidationError) as raised:
        validate_analysis_detail(
            operation,
            _detail_inputs(order_by_list=[{"field": LEVEL, "sort": "UNSUPPORTED"}]),
            _metadata_loader(calls),
        )
    assert raised.value.to_error_detail().field == "order_by_list[].sort"
    assert calls == METADATA_OPERATIONS


def _source_failure():
    return GravityInsightError(
        f"source response contains {SENTINEL}",
        code="UPSTREAM_UNAVAILABLE",
        next_action=f"private remedy {SENTINEL}",
    )


def test_source_gravity_error_formats_without_attribute_error_or_private_details(capsys, caplog):
    error = _source_failure()
    detail = error.to_error_detail()
    result = safe_failure(error)

    assert result["status"] == "unavailable" and result["value"] is None
    assert result["reason"] == "UPSTREAM_UNAVAILABLE"
    assert result["error"] == {
        "code": detail.code,
        "category": "upstream",
        "retryable": detail.retryable,
        "message": "The bounded source read failed.",
    }
    captured = capsys.readouterr()
    assert SENTINEL not in json.dumps(result) + captured.out + captured.err + caplog.text


def test_empty_report_accepts_one_fetched_page_with_zero_total_pages():
    native = _native([], completeness="complete", has_more=False, total_pages=0)
    native["operation_id"] = MATERIAL_REPORT_OPERATION
    native["page"]["size"] = 10
    rows, scan = _report_rows(native, max_pages=1)

    assert rows == []
    assert scan == {
        "pages_scanned": 1,
        "items_scanned": 0,
        "last_page": 1,
        "next_page": None,
        "total_pages": 0,
        "remaining_pages": 0,
        "has_more": False,
        "completeness": "complete",
        "pagination_finished": True,
    }

    nonempty = copy.deepcopy(native)
    nonempty["status"] = "success"
    nonempty["data"]["list"] = [{"material_id": "10101"}]
    nonempty["page"].update(item_count=1, total_items=1)
    with pytest.raises(ContractChangedError, match="total page count"):
        _report_rows(nonempty, max_pages=1)


class _FailingDayClient(_Client):
    def __init__(self, operation, failed_date):
        super().__init__(operation, _native([_row()]))
        self.failed_date = failed_date

    def read_limited(self, operation_id, inputs, **options):
        if inputs["date"] == self.failed_date:
            assert operation_id == SOURCE_OPERATION_ID
            self.calls.append((operation_id, copy.deepcopy(inputs), options))
            raise _source_failure()
        return super().read_limited(operation_id, inputs, **options)


@pytest.mark.parametrize("failed_date,successful_days", [(DAY, 0), (NEXT_DAY, 1)])
def test_source_failure_counts_attempt_but_keeps_failed_day_pending(
    operation,
    failed_date,
    successful_days,
    capsys,
    caplog,
):
    request = normalize_request(
        "101",
        ["10101"],
        "bytedance",
        start=DAY,
        end="2026-09-03",
        metrics={"level": _metric()},
        max_user_pages=3,
        max_user_items=250,
        max_days=3,
        max_workers=3,
    )
    budget = {
        **request["bounds"],
        "user_pages_used": 0,
        "user_items_used": 0,
        "attempted_days": 0,
        "remaining_days": 0,
        "remaining_pages": None,
        "stopped_reason": None,
    }
    client = _FailingDayClient(operation, failed_date)
    days, receipts = [], []
    _read_days(
        client,
        request,
        [_group(key="0")],
        [{"window": request["window"]}],
        days,
        budget,
        receipts,
    )

    assert len(client.calls) == successful_days + 1
    assert client.metadata_calls == []
    assert [day["date"] for day in days] == ([DAY] if successful_days == 0 else [DAY, NEXT_DAY])
    assert days[-1]["scan"] is None
    assert days[-1]["error"] == safe_failure(_source_failure())
    assert days[-1]["cells"] == {
        "0:matched_users": safe_failure(_source_failure()),
        "0:level": safe_failure(_source_failure()),
    }
    assert receipts == [RECEIPT] * successful_days
    if successful_days:
        assert days[0]["cells"]["0:matched_users"] == {"status": "obtained", "value": 1}
    assert budget["total_days"] == 3
    assert budget["stopped_reason"] == "USER_SOURCE_FAILED"
    assert budget["failed_date"] == budget["next_date"] == failed_date
    assert budget["remaining_days"] == 3 - successful_days
    # Usage is receipt-backed; the failed read's reservation is not a measured count.
    assert budget["user_pages_used"] == budget["user_items_used"] == successful_days
    assert budget["failed_read_page_reservation"] == 3 - successful_days
    assert budget["failed_read_item_reservation"] == 250 - successful_days
    assert budget["remaining_pages"] is None
    captured = capsys.readouterr()
    assert (
        SENTINEL
        not in json.dumps({"days": days, "budget": budget}) + captured.out + captured.err + caplog.text
    )
    assert budget["attempted_days"] == successful_days + 1
