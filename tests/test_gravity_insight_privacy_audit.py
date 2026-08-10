from __future__ import annotations

import json

import pytest

from gravity_sdk.prober.privacy import (
    build_projection,
    candidate_fields,
    classify_candidate_field,
    classify_field,
    response_schema_sketch,
)
from gravity_sdk.prober.privacy_stats import profile_named_fields


@pytest.mark.parametrize(
    "field",
    [
        "uid",
        "user_id",
        "device_id",
        "phone",
        "mobile",
        "email",
        "idfa",
        "idfv",
        "imei",
        "oaid",
        "android_id",
        "order_id",
        "ip",
        "ip_address",
        "openid",
        "open_id",
        "unionid",
        "client_id",
        "trace_id",
        "session_id",
        "operator_id",
        "operator_name",
        "password",
        "access_token",
        "cookie",
    ],
)
def test_known_sensitive_fields_remain_sensitive(field: str) -> None:
    assert classify_field(f"data.list[].{field}")[0] == "sensitive"


@pytest.mark.parametrize(
    "field",
    [
        "account_name",
        "advertiser_name",
        "company_name",
        "creator_id",
        "department_id",
        "private_key",
        "public_key",
        "before_value",
        "after_value",
        "download_url",
        "callback_url",
        "latitude",
        "longitude",
        "gender",
    ],
)
def test_strict_identity_security_and_person_fields_are_sensitive(field: str) -> None:
    assert classify_field(f"data.list[].{field}")[0] == "sensitive"


@pytest.mark.parametrize(
    "field",
    [
        "campaign_id",
        "adgroup_id",
        "creative_id",
        "company_id",
        "campaign_name",
        "converted_time_duration",
        "create_at",
        "hide_if_converted",
        "marketing_goal",
        "update_at",
        "version",
        "is_deleted",
        "plan_num",
    ],
)
def test_clear_business_objects_time_state_and_counts_are_non_sensitive(
    field: str,
) -> None:
    assert classify_field(f"data.list[].{field}")[0] == "non_sensitive"


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("condition", "sensitive"),
        ("content", "manual_review"),
        ("data_topic", "non_sensitive"),
        ("description", "sensitive"),
        ("file_md5", "non_sensitive"),
        ("message", "sensitive"),
        ("params_md5", "non_sensitive"),
        ("remark", "sensitive"),
        ("target", "non_sensitive"),
        ("thumbnail", "sensitive"),
        ("value", "non_sensitive"),
    ],
)
def test_reviewed_ambiguous_fields_use_evidence_based_decisions(
    field: str, expected: str
) -> None:
    assert classify_field(f"data.list[].{field}")[0] == expected


def test_cid_is_reviewed_as_a_tenant_identifier() -> None:
    assert classify_field("data.list[].cid") == (
        "non_sensitive",
        "tenant_company_identifier_review",
    )


def test_cid_review_does_not_weaken_person_or_client_identifiers() -> None:
    payload = {
        "data": {
            "list": [
                {
                    "campaign_id": 1,
                    "cid": 2,
                    "client_id": "not persisted",
                    "user_id": "not persisted",
                }
            ]
        }
    }

    fields = candidate_fields(response_schema_sketch(payload))
    classifications = {
        item["path"].rsplit(".", 1)[-1]: item["privacy_classification"]
        for item in fields
    }
    projection = build_projection(payload, fields)

    assert classifications == {
        "campaign_id": "non_sensitive",
        "cid": "non_sensitive",
        "client_id": "sensitive",
        "user_id": "sensitive",
    }
    assert projection["item_keys"] == ["campaign_id", "cid"]
    assert projection["known_omitted_item_keys"] == ["client_id", "user_id"]


def test_aggregate_metric_review_is_route_and_path_scoped() -> None:
    path = "data.today[].AppRevenueReco"

    assert classify_field(path)[0] == "manual_review"
    assert classify_candidate_field(
        path, operation_id="report.hour_comparison.query"
    ) == ("non_sensitive", "aggregate_metric_field_review")
    assert classify_candidate_field(
        path, operation_id="promotion.history.list"
    )[0] == "manual_review"


def test_metadata_dictionary_context_does_not_override_sensitive_names() -> None:
    safe_path = "data.list[].name_en_cn_dict.item_price"
    sensitive_path = "data.list[].name_en_cn_dict.user_name"

    assert classify_candidate_field(
        safe_path, operation_id="metadata.version.list"
    ) == ("non_sensitive", "metadata_dictionary_field_review")
    assert classify_candidate_field(
        sensitive_path, operation_id="metadata.version.list"
    )[0] == "sensitive"


def test_route_context_does_not_weaken_sensitive_user_count_rule() -> None:
    path = "data.list[].user_count"

    assert classify_field(path)[0] == "sensitive"
    assert (
        classify_candidate_field(
            path, operation_id="report.company_amount.query"
        )[0]
        == "sensitive"
    )


def test_bytedance_text_title_metrics_are_reviewed_by_operation_family() -> None:
    path = "data.list[].history_click_rate"

    assert classify_field(path)[0] == "manual_review"
    assert classify_candidate_field(
        path, operation_id="material.bytedance_future_text_title.list"
    ) == ("non_sensitive", "route_specific_field_review")
    assert classify_candidate_field(
        path, operation_id="promotion.bytedance_future_text_title.list"
    )[0] == "manual_review"
    assert classify_candidate_field(
        "data.list[].create_user_id",
        operation_id="material.bytedance_future_text_title.list",
    )[0] == "sensitive"


def test_strict_sensitive_fields_never_enter_generated_projection() -> None:
    payload = {
        "data": {
            "list": [
                {
                    "advertiser_name": "not persisted",
                    "callback_url": "not persisted",
                    "campaign_id": "not persisted",
                    "company_name": "not persisted",
                    "private_key": "not persisted",
                }
            ]
        }
    }

    fields = candidate_fields(response_schema_sketch(payload))
    projection = build_projection(payload, fields)

    assert projection["item_keys"] == ["campaign_id"]
    assert projection["known_omitted_item_keys"] == [
        "advertiser_name",
        "callback_url",
        "company_name",
        "private_key",
    ]


def test_value_shape_profile_contains_statistics_but_no_values() -> None:
    payload = {
        "data": {
            "list": [
                {"remark": "private sample@example.com", "target": "ENUM_A"},
                {"remark": "13800138000", "target": "ENUM_B"},
            ],
            "condition": {"field": "private_field", "value": 7},
        }
    }

    profile = profile_named_fields(
        payload, ["condition", "remark", "target", "value"]
    )
    rendered = json.dumps(profile, ensure_ascii=False, sort_keys=True)

    assert profile["remark"]["occurrences"] == 2
    assert profile["remark"]["pii_shape_matches"]["phone"] == 1
    assert profile["target"]["distinct_count"] == 2
    assert profile["condition"]["object_keys"] == ["field", "value"]
    assert "sample@example.com" not in rendered
    assert "13800138000" not in rendered
    assert "private_field" not in rendered


def test_value_shape_profile_counts_business_name_markers_without_values() -> None:
    payload = {
        "data": {
            "list": [
                {"advertiser_name": "synthetic technology company"},
                {"advertiser_name": "\u6d4b\u8bd5\u5de5\u4f5c\u5ba4"},
            ]
        }
    }

    profile = profile_named_fields(payload, ["advertiser_name"])
    rendered = json.dumps(profile, ensure_ascii=False, sort_keys=True)

    assert profile["advertiser_name"]["string_patterns"][
        "organization_marker"
    ]["count"] == 1
    assert profile["advertiser_name"]["string_patterns"][
        "individual_business_marker"
    ]["count"] == 1
    assert "\u6d4b\u8bd5\u5de5\u4f5c\u5ba4" not in rendered
