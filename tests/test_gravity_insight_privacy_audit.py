from __future__ import annotations

import unittest

import json


from gravity_insight.models import ResponseProjection
from gravity_insight.prober.privacy import (
    build_projection,
    candidate_fields,
    classify_candidate_field,
    classify_field,
    projection_exposes_path,
    response_schema_sketch,
)
from gravity_insight.prober.privacy_stats import profile_named_fields
from gravity_insight.projection_validation import validate_projection_bindings



class GravityInsightPrivacyAuditTests(unittest.TestCase):
    def test_only_credentials_remain_sensitive(self):
        for field in [
        "password",
        "access_token",
        "cookie",
        "private_key",
    ]:
            with self.subTest(field=field):
                assert classify_field(f"data.list[].{field}")[0] == "sensitive"


    def test_upstream_authorized_identity_and_person_fields_are_exposable(self):
        for field in [
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
        "account_name",
        "advertiser_name",
        "company_name",
        "creator_id",
        "department_id",
        "public_key",
        "before_value",
        "after_value",
        "gender",
    ]:
            with self.subTest(field=field):
                assert classify_field(f"data.list[].{field}")[0] == "non_sensitive"


    def test_clear_business_objects_time_state_and_counts_are_non_sensitive(self):
        for field in [
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
    ]:
            with self.subTest(field=field):
                assert classify_field(f"data.list[].{field}")[0] == "non_sensitive"


    def test_reviewed_ambiguous_fields_use_evidence_based_decisions(self):
        for (field, expected) in [
        ("condition", "manual_review"),
        ("content", "manual_review"),
        ("data_topic", "non_sensitive"),
        ("description", "manual_review"),
        ("file_md5", "non_sensitive"),
        ("message", "manual_review"),
        ("params_md5", "non_sensitive"),
        ("remark", "manual_review"),
        ("target", "non_sensitive"),
        ("thumbnail", "manual_review"),
        ("value", "non_sensitive"),
    ]:
            with self.subTest(field=field, expected=expected):
                assert classify_field(f"data.list[].{field}")[0] == expected


    def test_cid_is_reviewed_as_a_tenant_identifier(self):
        assert classify_field("data.list[].cid") == (
            "non_sensitive",
            "tenant_company_identifier_review",
        )


    def test_cid_and_person_or_client_identifiers_are_exposable(self):
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
            "client_id": "non_sensitive",
            "user_id": "non_sensitive",
        }
        assert projection["item_keys"] == [
            "campaign_id",
            "cid",
            "client_id",
            "user_id",
        ]
        assert "known_omitted_item_keys" not in projection


    def test_aggregate_metric_review_is_route_and_path_scoped(self):
        path = "data.today[].AppRevenueReco"

        assert classify_field(path)[0] == "manual_review"
        assert classify_candidate_field(
            path, operation_id="report.hour_comparison.query"
        ) == ("non_sensitive", "aggregate_metric_field_review")
        assert classify_candidate_field(
            path, operation_id="promotion.history.list"
        )[0] == "manual_review"


    def test_account_company_selector_reviews_are_route_scoped(self):
        path = "data.list[]"

        assert classify_field(path)[0] == "manual_review"
        for operation_id in (
            "promotion.kuaishou.account_company.list",
            "promotion.tencent.account_company.list",
        ):
            assert classify_candidate_field(path, operation_id=operation_id) == (
                "non_sensitive",
                "route_specific_field_review",
            )
        assert classify_candidate_field(
            path, operation_id="promotion.company.list"
        )[0] == "manual_review"


    def test_aggregate_mapping_and_series_receive_nested_allowlists(self):
        payload = {
            "data": {
                "columns": {
                    "AppRevenueReco": "revenue",
                    "remark": "not persisted",
                },
                "today": [
                    {"AppRevenueReco": 12, "hour": "10", "remark": "not persisted"}
                ],
            }
        }
        fields = candidate_fields(
            response_schema_sketch(payload),
            operation_id="report.hour_comparison.query",
        )

        projection = build_projection(payload, fields)

        assert projection["data_keys"] == ["columns", "today"]
        assert projection["data_item_keys"] == {
            "columns": ["AppRevenueReco"],
            "today": ["AppRevenueReco", "hour"],
        }
        assert projection["known_omitted_data_item_keys"] == {
            "columns": ["remark"],
            "today": ["remark"],
        }


    def test_nested_object_projection_is_recursive_and_fail_closed(self):
        payload = {
            "data": {
                "data": {
                    "capacity": {
                        "status": "active",
                        "total_count": 10,
                        "create_user_name": "not persisted",
                        "relation_package": [
                            {"id": 1, "name": "standard", "remark": "not persisted"}
                        ],
                    },
                    "product": {"id": 2, "status": 1, "remark": "not persisted"},
                }
            }
        }
        fields = candidate_fields(response_schema_sketch(payload))

        projection = build_projection(payload, fields)

        assert projection["data_keys"] == ["data"]
        assert projection["data_item_keys"] == {"data": ["capacity", "product"]}
        assert projection["nested_item_keys"] == {
            "capacity": [
                "create_user_name",
                "relation_package",
                "status",
                "total_count",
            ],
            "product": ["id", "status"],
            "relation_package": ["id", "name"],
        }
        assert projection["known_omitted_nested_item_keys"] == {
            "product": ["remark"],
            "relation_package": ["remark"],
        }
        assert projection_exposes_path("data.data.capacity.total_count", projection)
        assert projection_exposes_path(
            "data.data.capacity.relation_package[].name", projection
        )
        assert projection_exposes_path(
            "data.data.capacity.create_user_name", projection
        )
        assert not projection_exposes_path("data.data.product.remark", projection)
        validate_projection_bindings(ResponseProjection.from_dict(projection), ())


    def test_metadata_dictionary_context_allows_authorized_user_names(self):
        safe_path = "data.list[].name_en_cn_dict.item_price"
        sensitive_path = "data.list[].name_en_cn_dict.user_name"

        assert classify_candidate_field(
            safe_path, operation_id="metadata.version.list"
        ) == ("non_sensitive", "metadata_dictionary_field_review")
        assert classify_candidate_field(
            sensitive_path, operation_id="metadata.version.list"
        )[0] == "non_sensitive"


    def test_user_count_is_an_authorized_data_field(self):
        path = "data.list[].user_count"

        assert classify_field(path)[0] == "non_sensitive"
        assert (
            classify_candidate_field(
                path, operation_id="report.company_amount.query"
            )[0]
            == "non_sensitive"
        )


    def test_bytedance_text_title_metrics_are_reviewed_by_operation_family(self):
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
        )[0] == "non_sensitive"


    def test_ai_trusteeship_metrics_are_reviewed_by_operation_family(self):
        path = "data.list[].check_fre"

        assert classify_field(path)[0] == "manual_review"
        assert classify_candidate_field(
            path, operation_id="promotion.ai_trusteeship.future_list"
        ) == ("non_sensitive", "route_specific_field_review")
        assert classify_candidate_field(
            path, operation_id="material.ai_trusteeship.future_list"
        )[0] == "manual_review"


    def test_bytedance_promotion_material_review_exposes_registered_fields(self):
        payload = {
            "data": {
                "list": [
                    {
                        "filename": "synthetic.mp4",
                        "stat_cost": 1.0,
                        "cpc_platform": 0.5,
                        "labels": ["synthetic"],
                        "material_info": {
                            "filename": "synthetic.mp4",
                            "signature": "synthetic-signature",
                            "star_author_id": "synthetic-author",
                            "url": "https://example.invalid/video",
                        },
                    },
                    {"labels": "synthetic"},
                ]
            }
        }

        fields = candidate_fields(
            response_schema_sketch(payload),
            operation_id="material.bytedance.promotion_material.list",
        )
        by_path = {item["path"]: item for item in fields}

        for path in (
            "data.list[].filename",
            "data.list[].stat_cost",
            "data.list[].cpc_platform",
            "data.list[].material_info.filename",
        ):
            assert by_path[path]["privacy_classification"] == "non_sensitive"
            assert by_path[path]["expose"] is True
        for path in (
            "data.list[].labels",
            "data.list[].material_info.signature",
            "data.list[].material_info.star_author_id",
            "data.list[].material_info.url",
        ):
            assert by_path[path]["privacy_classification"] == "non_sensitive"
            assert by_path[path]["expose"] is True
        assert not {
            item["path"]
            for item in fields
            if item["privacy_classification"] == "manual_review"
        }


    def test_credentials_alone_stay_out_of_generated_projection(self):
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

        assert projection["item_keys"] == [
            "advertiser_name",
            "campaign_id",
            "company_name",
        ]
        assert projection["known_omitted_item_keys"] == [
            "callback_url",
            "private_key",
        ]


    def test_value_shape_profile_contains_statistics_but_no_values(self):
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


    def test_value_shape_profile_counts_business_name_markers_without_values(self):
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
