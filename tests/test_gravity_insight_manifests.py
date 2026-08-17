from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from gravity_sdk.models import load_operation_manifest
from gravity_sdk.registry import Registry
from gravity_sdk.runtime import validate_manifest_json


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_sdk" / "manifests"
MANIFEST_NAMES = {
    "analysis.json",
    "analysis_auxiliary.json",
    "analysis_dashboard.json",
    "analysis_directory.json",
    "analysis_segment_rule.json",
    "analysis_values.json",
    "report.json",
    "promotion.json",
    "material.json",
    "other.json",
    "candidates.json",
}

REQUIRED_OPERATION_FIELDS = {
    "operation_id",
    "domain",
    "resource",
    "action",
    "contract_version",
    "upstream_method",
    "path_template",
    "auth_profile",
    "stability",
    "input_fields",
    "request",
    "response_projection",
    "pagination",
    "semantic_error_rules",
    "privacy_policy",
    "required_parent",
    "live_probe",
}
REQUEST_FIELDS = {
    "path_fields",
    "query_fields",
    "body_fields",
    "defaults",
    "fixed_query",
    "fixed_body",
}
PAGINATION_FIELDS = {
    "kind",
    "page_field",
    "page_size_field",
    "list_path",
    "page_info_path",
    "total_page_field",
}
PAGINATION_LIMIT_FIELDS = {"default_page_size", "max_page_size"}
STABILITIES = {
    "stable",
    "experimental",
    "permission_unavailable",
    "blocked_privacy",
    "blocked_write",
    "deprecated",
}
INPUT_TYPES = {
    "any",
    "string",
    "integer",
    "number",
    "boolean",
    "array",
    "object",
    "date",
    "datetime",
}
PRIVACY_CLASSES = {
    "internal_business",
    "aggregate",
    "configuration",
    "material",
    "user_level",
}
PLATFORMS = {
    "bytedance",
    "tencent",
    "kuaishou",
    "oppo",
    "bilibili",
    "baidu",
    "vivo",
    "iqiyi",
    "weibo",
    "apple",
    "uc",
    "huawei",
    "huawei_store",
    "honor",
    "ubix",
    "xiaohongshu",
    "xiaomi",
    "qihu360",
    "sigmob",
    "youdao",
    "huya",
    "alipay",
    "bing",
    "wechat_video",
    "taptap",
}
MAIN_LEVEL = {
    "bytedance": "advertiser",
    "tencent": "advertiser",
    "kuaishou": "advertiser",
    "oppo": "advertiser",
    "bilibili": "advertiser",
    "baidu": "advertiser",
    "vivo": "advertiser",
    "iqiyi": "advertiser",
    "weibo": "advertiser",
    "apple": "advertiser",
    "uc": "advertiser",
    "huawei": "advertiser",
    "huawei_store": "advertiser",
    "honor": "advertiser",
    "ubix": "group",
    "xiaohongshu": "advertiser",
    "xiaomi": "advertiser",
    "qihu360": "advertiser",
    "sigmob": "advertiser",
    "youdao": "advertiser",
    "huya": "advertiser",
    "alipay": "advertiser",
    "bing": "advertiser",
    "wechat_video": "report",
    "taptap": "group",
}
SENSITIVE_REDACTIONS = {
    "authorization",
    "access_token",
    "token",
    "cookie",
    "password",
}
SESSION_REDACTIONS = SENSITIVE_REDACTIONS
ALLOWED_BUSINESS_NAMES = {
    "account_name",
    "app_name",
    "object_name",
}
WRITE_SEGMENTS = {
    "authorize",
    "create",
    "delete",
    "download",
    "export",
    "grant",
    "remove",
    "save",
    "subscribe",
    "undelete",
    "upload",
}


def load_documents() -> dict[str, dict[str, object]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(MANIFEST_DIR.glob("*.json"))
    }


def operations(documents: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    return [
        operation
        for document in documents.values()
        for operation in document["operations"]
    ]


class GravityInsightManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = load_documents()
        cls.operations = operations(cls.documents)
        cls.by_id = {item["operation_id"]: item for item in cls.operations}

    def test_exact_versioned_manifest_set_is_json_loadable(self) -> None:
        self.assertEqual(MANIFEST_NAMES, set(self.documents))
        loaded = []
        for name, document in self.documents.items():
            with self.subTest(name=name):
                self.assertEqual(1, document["manifest_version"])
                self.assertIsInstance(document["operations"], list)
                self.assertTrue(document["operations"])
                loaded.extend(load_operation_manifest(document))
        self.assertEqual(len(self.operations), len(Registry(loaded).all()))
        summary = validate_manifest_json()
        self.assertEqual(11, summary["manifest_files"])
        self.assertEqual(len(self.operations), summary["operations"])

    def test_operation_ids_are_unique_and_well_formed(self) -> None:
        ids = [item["operation_id"] for item in self.operations]
        self.assertEqual(len(ids), len(set(ids)))
        for operation_id in ids:
            self.assertRegex(operation_id, r"^[a-z][a-z0-9_.-]{2,127}$")

    def test_all_25_promotion_platforms_have_a_stable_main_query(self) -> None:
        promotion = [
            item
            for item in self.documents["promotion.json"]["operations"]
            if item["stability"] == "stable" and item.get("platform")
        ]
        self.assertEqual(PLATFORMS, {item["platform"] for item in promotion})
        for platform, level in MAIN_LEVEL.items():
            operation_id = f"promotion.{platform}.{level}.list"
            with self.subTest(platform=platform):
                self.assertIn(operation_id, self.by_id)
                self.assertEqual("stable", self.by_id[operation_id]["stability"])

    def test_stable_contracts_are_decision_complete(self) -> None:
        all_ids = set(self.by_id)
        for item in self.operations:
            with self.subTest(operation_id=item["operation_id"]):
                self.assertTrue(REQUIRED_OPERATION_FIELDS <= set(item))
                self.assertIn(item["stability"], STABILITIES)
                self.assertIn(item["upstream_method"], {"GET", "POST"})
                self.assertTrue(item["path_template"].startswith("/"))
                self.assertTrue(item["path_template"].endswith("/"))
                self.assertEqual("gravity_authorization", item["auth_profile"])

                request = item["request"]
                self.assertEqual(REQUEST_FIELDS, set(request))
                declared = set(item["input_fields"])
                referenced = (
                    set(request["path_fields"])
                    | set(request["query_fields"])
                    | set(request["body_fields"])
                    | set(request["defaults"])
                )
                self.assertTrue(referenced <= declared)
                self.assertFalse(
                    set(request["fixed_query"]) & set(request["query_fields"])
                )
                self.assertFalse(
                    set(request["fixed_body"]) & set(request["body_fields"])
                )
                for field_name, field in item["input_fields"].items():
                    self.assertIn(field["type"], INPUT_TYPES, field_name)
                    if "enum" in field:
                        self.assertIsInstance(field["enum"], list)
                    if "item_enum" in field:
                        self.assertEqual("array", field["type"])
                        self.assertIsInstance(field["item_enum"], list)
                        self.assertTrue(field["item_enum"])

                projection = item["response_projection"]
                base_projection_fields = {
                    "data_keys",
                    "required_data_keys",
                    "item_keys",
                    "dynamic_item_fields",
                }
                self.assertTrue(base_projection_fields <= set(projection))
                self.assertTrue(
                    set(projection)
                    <= base_projection_fields
                    | {
                        "data_shape",
                        "nested_item_keys",
                        "known_omitted_nested_item_keys",
                        "data_item_keys",
                        "data_path_item_keys",
                        "scalar_list_item_types",
                        "data_scalar_list_types",
                        "numeric_paths",
                        "data_dynamic_item_fields",
                        "numeric_suffix_item_fields",
                        "data_numeric_suffix_item_fields",
                        "known_omitted_item_keys",
                        "known_omitted_data_keys",
                        "known_omitted_data_item_keys",
                        "recursive_data_item_keys",
                        "empty_object_as_empty_page",
                        "empty_object_as_empty_result",
                        "opaque_json_item_keys",
                    }
                )
                self.assertIsInstance(projection["data_keys"], list)
                self.assertIsInstance(projection["required_data_keys"], list)
                self.assertIsInstance(projection["item_keys"], list)
                self.assertIsInstance(projection["dynamic_item_fields"], list)
                self.assertTrue(
                    set(projection["required_data_keys"])
                    <= set(projection["data_keys"])
                )
                self.assertTrue(set(projection["dynamic_item_fields"]) <= declared)
                nested_item_keys = projection.get("nested_item_keys", {})
                self.assertIsInstance(nested_item_keys, dict)
                nested_parent_keys = set(projection["item_keys"])
                for fields in projection.get("data_item_keys", {}).values():
                    nested_parent_keys.update(fields)
                for fields in projection.get("data_path_item_keys", {}).values():
                    nested_parent_keys.update(fields)
                pending = list(nested_parent_keys)
                while pending:
                    parent = pending.pop()
                    for child in nested_item_keys.get(parent, []):
                        if child not in nested_parent_keys:
                            nested_parent_keys.add(child)
                            pending.append(child)
                self.assertTrue(set(nested_item_keys) <= nested_parent_keys)
                self.assertTrue(
                    all(
                        isinstance(fields, list)
                        and fields
                        and all(isinstance(field, str) and field for field in fields)
                        for fields in nested_item_keys.values()
                    )
                )
                known_omitted_nested_item_keys = projection.get(
                    "known_omitted_nested_item_keys", {}
                )
                self.assertIsInstance(known_omitted_nested_item_keys, dict)
                self.assertTrue(
                    set(known_omitted_nested_item_keys) <= set(nested_item_keys)
                )
                data_item_keys = projection.get("data_item_keys", {})
                self.assertIsInstance(data_item_keys, dict)
                self.assertTrue(set(data_item_keys) <= set(projection["data_keys"]))
                self.assertTrue(
                    all(
                        isinstance(fields, list)
                        and all(isinstance(field, str) and field for field in fields)
                        for fields in data_item_keys.values()
                    )
                )
                scalar_list_item_types = projection.get("scalar_list_item_types", {})
                self.assertIsInstance(scalar_list_item_types, dict)
                self.assertTrue(
                    set(scalar_list_item_types) <= set(projection["item_keys"])
                )
                self.assertTrue(
                    all(
                        item_type in {"string", "integer", "number", "boolean"}
                        for item_type in scalar_list_item_types.values()
                    )
                )
                data_scalar_list_types = projection.get("data_scalar_list_types", {})
                self.assertIsInstance(data_scalar_list_types, dict)
                self.assertTrue(
                    set(data_scalar_list_types) <= set(projection["data_keys"])
                )
                self.assertFalse(set(data_scalar_list_types) & set(data_item_keys))
                self.assertTrue(
                    all(
                        item_type in {"string", "integer", "number", "boolean"}
                        for item_type in data_scalar_list_types.values()
                    )
                )
                data_path_item_keys = projection.get("data_path_item_keys", {})
                self.assertIsInstance(data_path_item_keys, dict)
                self.assertTrue(
                    all(
                        isinstance(path, str)
                        and len(path.split(".")) == 2
                        and path.split(".")[0] in projection["data_keys"]
                        and isinstance(fields, list)
                        and fields
                        and all(isinstance(field, str) and field for field in fields)
                        for path, fields in data_path_item_keys.items()
                    )
                )
                data_dynamic_item_fields = projection.get(
                    "data_dynamic_item_fields", {}
                )
                self.assertIsInstance(data_dynamic_item_fields, dict)
                self.assertTrue(
                    set(data_dynamic_item_fields) <= set(projection["data_keys"])
                )
                self.assertTrue(
                    all(
                        isinstance(fields, list) and fields and set(fields) <= declared
                        for fields in data_dynamic_item_fields.values()
                    )
                )
                recursive_data_item_keys = projection.get(
                    "recursive_data_item_keys", {}
                )
                self.assertIsInstance(recursive_data_item_keys, dict)
                self.assertTrue(
                    set(recursive_data_item_keys) <= set(projection["data_keys"])
                )
                self.assertTrue(
                    all(
                        isinstance(fields, list)
                        and fields
                        and all(isinstance(field, str) and field for field in fields)
                        for fields in recursive_data_item_keys.values()
                    )
                )
                self.assertIsInstance(
                    projection.get("empty_object_as_empty_page", False), bool
                )
                self.assertIsInstance(
                    projection.get("empty_object_as_empty_result", False), bool
                )
                if (
                    item["stability"] == "stable"
                    and item["effect"] == "read"
                    and not projection["data_keys"]
                ):
                    self.assertEqual("list", projection.get("data_shape"))

                pagination = item["pagination"]
                self.assertIn(pagination["kind"], {"none", "page_info"})
                if pagination["kind"] == "none":
                    self.assertEqual(PAGINATION_FIELDS, set(pagination))
                    self.assertTrue(
                        all(
                            pagination[key] == ""
                            for key in PAGINATION_FIELDS - {"kind"}
                        )
                    )
                else:
                    self.assertTrue(pagination["list_path"].startswith("data."))
                    self.assertTrue(
                        pagination["page_info_path"] == "data"
                        or pagination["page_info_path"].startswith("data.")
                    )
                    if item["stability"] == "stable":
                        self.assertEqual(
                            PAGINATION_FIELDS | PAGINATION_LIMIT_FIELDS,
                            set(pagination),
                        )
                        default_page_size = pagination["default_page_size"]
                        max_page_size = pagination["max_page_size"]
                        self.assertIsInstance(default_page_size, int)
                        self.assertNotIsInstance(default_page_size, bool)
                        self.assertGreater(default_page_size, 0)
                        self.assertIsInstance(max_page_size, int)
                        self.assertNotIsInstance(max_page_size, bool)
                        self.assertGreaterEqual(max_page_size, default_page_size)
                        self.assertGreater(item["input_fields"]["page"]["default"], 0)
                        self.assertGreater(
                            item["input_fields"]["page_size"]["default"], 0
                        )
                        self.assertEqual(
                            default_page_size,
                            item["input_fields"]["page_size"]["default"],
                        )
                        self.assertEqual(
                            default_page_size,
                            request["defaults"]["page_size"],
                        )
                        self.assertTrue(
                            projection["item_keys"] or projection["dynamic_item_fields"]
                        )
                    else:
                        self.assertIn(
                            frozenset(pagination),
                            {
                                frozenset(PAGINATION_FIELDS),
                                frozenset(PAGINATION_FIELDS | PAGINATION_LIMIT_FIELDS),
                            },
                        )

                self.assertIsInstance(item["semantic_error_rules"], list)
                self.assertTrue(item["semantic_error_rules"])
                privacy = item["privacy_policy"]
                self.assertIn(privacy["classification"], PRIVACY_CLASSES)
                required_redactions = (
                    SESSION_REDACTIONS
                    if privacy["classification"] == "user_level"
                    else SENSITIVE_REDACTIONS
                )
                self.assertTrue(required_redactions <= set(privacy["redact_keys"]))
                self.assertFalse(ALLOWED_BUSINESS_NAMES & set(privacy["redact_keys"]))
                parent_ids = {
                    parent["operation_id"]
                    if isinstance(parent, dict)
                    else parent
                    for parent in item["required_parent"]
                }
                self.assertTrue(parent_ids <= all_ids)
                for parent in item["required_parent"]:
                    if isinstance(parent, dict):
                        self.assertIn(parent.get("input_field"), declared)

                probe = item["live_probe"]
                self.assertEqual({"enabled", "input"}, set(probe))
                self.assertTrue(set(probe["input"]) <= declared)
                if item["stability"] == "stable" and probe["enabled"]:
                    for name, field in item["input_fields"].items():
                        if field.get("required") and "default" not in field:
                            self.assertIn(name, probe["input"])

    def test_unverified_candidates_are_not_stable(self) -> None:
        for item in self.documents["candidates.json"]["operations"]:
            if item["operation_id"].startswith("candidate."):
                self.assertNotEqual("stable", item["stability"])
                self.assertFalse(item["live_probe"]["enabled"])
        openapi = [
            item
            for item in self.documents["candidates.json"]["operations"]
            if item["operation_id"].startswith("candidate.openapi.")
        ]
        self.assertEqual([], openapi)
        recycle = self.by_id["material.recycle.list"]
        self.assertEqual("stable", recycle["stability"])
        self.assertTrue(recycle["live_probe"]["enabled"])
        self.assertEqual(1, recycle["live_probe"]["input"]["page_size"])
        favorites = self.by_id["material.favorites.list"]
        self.assertEqual("stable", favorites["stability"])
        self.assertTrue(favorites["live_probe"]["enabled"])
        self.assertEqual(5000, favorites["live_probe"]["input"]["page_size"])
        department = self.by_id["account.department.list"]
        self.assertEqual("experimental", department["stability"])
        self.assertEqual("response_schema_unverified", department["block_reason"])
        blocked = [
            item
            for item in self.operations
            if item["stability"]
            in {
                "permission_unavailable",
                "blocked_privacy",
                "blocked_write",
                "deprecated",
            }
        ]
        self.assertTrue(blocked)
        self.assertTrue(all(item["executable"] is False for item in blocked))
        self.assertTrue(
            all(
                isinstance(item["block_reason"], str) and item["block_reason"]
                for item in blocked
            )
        )
        self.assertEqual(
            "request_and_response_contract_unverified",
            self.by_id["candidate.account.user_operation_log.list"]["block_reason"],
        )
        self.assertFalse(department["live_probe"]["enabled"])

    def test_stable_descriptions_are_not_draft_catalog_placeholders(self) -> None:
        for operation in self.operations:
            if operation["stability"] != "stable":
                continue
            with self.subTest(operation_id=operation["operation_id"]):
                self.assertFalse(
                    operation["description"].startswith("Draft catalog entry")
                )

    def test_every_stable_operation_has_a_repeatable_minimum_live_probe(self) -> None:
        downgraded_for_context: set[str] = set()
        for operation_id in downgraded_for_context:
            with self.subTest(operation_id=operation_id):
                operation = self.by_id[operation_id]
                self.assertEqual("experimental", operation["stability"])
                self.assertFalse(operation["live_probe"]["enabled"])
                self.assertIn("故保持 experimental", operation["description"])

        stable = [item for item in self.operations if item["stability"] == "stable"]
        self.assertTrue(stable)
        for operation in stable:
            with self.subTest(operation_id=operation["operation_id"]):
                probe = operation["live_probe"]
                inputs = probe["input"]
                declared = operation["input_fields"]
                if operation.get("effect") == "mutation":
                    self.assertFalse(probe["enabled"])
                    self.assertEqual({}, inputs)
                    continue
                self.assertTrue(probe["enabled"])
                self.assertIsInstance(inputs, dict)
                self.assertTrue(set(inputs) <= set(declared))

                required = {
                    name for name, field in declared.items() if field.get("required")
                }
                self.assertTrue(
                    required <= set(inputs) | set(operation["request"]["defaults"])
                )
                if "date_list" in required:
                    if declared["date_list"].get("item_type") == "object":
                        self.assertEqual(
                            [
                                {
                                    "start_date": "$yesterday",
                                    "end_date": "$yesterday",
                                }
                            ],
                            inputs["date_list"],
                        )
                    else:
                        self.assertEqual(["$today", "$today"], inputs["date_list"])
                if operation["pagination"]["kind"] == "page_info":
                    self.assertEqual(1, inputs["page"])
                    self.assertEqual(
                        5000
                        if operation["operation_id"] == "material.favorites.list"
                        else 1,
                        inputs["page_size"],
                    )
                if "query_fields" in declared:
                    self.assertEqual([], inputs["query_fields"])

        for operation_id in {
            "report.multidim.query",
            "report.multidim.calc_total",
            "promotion.object.list",
            "attribution.post_backtrack.list",
            "attribution.postback_mode.list",
            "attribution.postback_map_collect.list",
        }:
            probe = self.by_id[operation_id]["live_probe"]
            self.assertTrue(probe["enabled"])
            if "app_id" in probe["input"]:
                self.assertEqual("$first_app_id", probe["input"]["app_id"])
            else:
                self.assertEqual(
                    "$first_app_id", probe["input"]["filters"][0]["values"][0]
                )

    def test_direct_data_lists_have_row_allowlists(self) -> None:
        for operation_id in {
            "promotion.metric.list",
            "report.business.metric.list",
            "material.metric.list",
        }:
            with self.subTest(operation_id=operation_id):
                projection = self.by_id[operation_id]["response_projection"]
                self.assertEqual("list", projection["data_shape"])
                self.assertTrue(
                    projection["item_keys"] or projection["dynamic_item_fields"]
                )

    def test_material_examine_user_projection_exposes_registered_user_fields(self) -> None:
        operation = self.by_id["material.material_examine_user.list"]
        projection = operation["response_projection"]

        self.assertEqual("user_level", operation["privacy_policy"]["classification"])
        self.assertEqual(
            {"cid", "id", "name", "company", "dept", "email", "is_superuser", "role"},
            set(projection["item_keys"]),
        )
        self.assertNotIn("known_omitted_item_keys", projection)
        self.assertEqual({}, operation["input_fields"])

    def test_user_and_monetization_detail_register_the_full_observed_profiles(self) -> None:
        user_projection = self.by_id["analysis.user_detail.list"]["response_projection"]
        self.assertEqual(153, len(user_projection["item_keys"]))
        self.assertNotIn("known_omitted_item_keys", user_projection)
        self.assertNotIn("known_omitted_nested_item_keys", user_projection)
        self.assertEqual(14, len(user_projection["nested_item_keys"]["device_info"]))

        monetization = self.by_id["analysis.monetization_detail.list"]
        projection = monetization["response_projection"]
        self.assertEqual(26, len(projection["item_keys"]))
        self.assertEqual(["fields"], projection["dynamic_item_fields"])
        self.assertNotIn("item_enum", monetization["input_fields"]["fields"])
        self.assertNotIn("known_omitted_item_keys", projection)
        self.assertNotIn("known_omitted_data_item_keys", projection)

    def test_verified_nested_projection_contracts_are_exact(self) -> None:
        expected = {
            "app.testing_tool.list": {
                "device_info": ["android_id", "imei", "oaid"]
            },
            "attribution.attribution_detail.query": {
                "device_info": ["android_id", "imei", "oaid"]
            },
            "app.capacity.get": {
                "capacity": [
                    "ad_create_amount",
                    "ad_create_amount_usage",
                    "advertiser_amount",
                    "advertiser_amount_usage",
                    "app_limit_amount",
                    "app_limit_amount_usage",
                    "capacity_type",
                    "click_amount_million",
                    "click_amount_million_usage",
                    "company_id",
                    "company_type",
                    "contact_status",
                    "create_time",
                    "end_time",
                    "event_amount_million",
                    "event_amount_million_usage",
                    "id",
                    "material_transmit_g",
                    "material_transmit_g_usage",
                    "modify_time",
                    "package_total_million",
                    "package_total_million_opt_usage",
                    "package_total_million_usage",
                    "relation_package",
                    "snapshot_id",
                    "start_time",
                    "storage_amount_g",
                    "storage_amount_g_usage",
                    "update_usage_time",
                    "company_position",
                    "create_user_name",
                    "modify_user_name",
                    "our_salesman_id",
                    "our_salesman_remark",
                ],
                "product": [
                    "company_id",
                    "create_time",
                    "end_time",
                    "id",
                    "modify_time",
                    "product_id",
                    "start_time",
                    "status",
                    "version",
                ],
                "relation_package": [
                    "end_time",
                    "formula_name",
                    "name",
                    "package_id",
                    "package_total_million",
                    "start_time",
                ],
            },
            "app.capacity.list": {
                "relation_package": [
                    "end_time",
                    "formula_name",
                    "name",
                    "package_id",
                    "package_total_million",
                    "start_time",
                ]
            },
            "app.permission_menu.list": {
                "children": ["id", "name", "parent_id", "person_num"]
            },
            "app.template.list": {
                "data_config": ["child_module", "effect_module", "role_effect"]
            },
            "analysis.account_user.list": {
                "dept_info": ["id", "name", "is_enabled"],
                "roles": ["id", "name", "code", "is_enabled"],
            },
            "analysis.segment.list": {
                "update_date_range": ["start_date", "end_date"]
            },
            "analysis.event.info": {
                "dim_table": ["name", "cname", "data_type", "dim_using_table_name"]
            },
            "analysis.event_property.list": {
                "dim_table": ["name", "cname", "data_type", "dim_using_table_name"]
            },
            "analysis.event_property_group.list": {"children": ["id", "name"]},
            "analysis.dashboard.tree": {
                "folder_or_dashboard": [
                    "id",
                    "name",
                    "type",
                    "is_folder",
                    "app_id",
                    "space_id",
                    "folder_id",
                    "authority",
                    "ui_config",
                    "create_time",
                    "create_user_id",
                    "create_user_name",
                    "modify_time",
                    "refresh_type",
                    "update_user_id",
                    "update_user_name",
                    "dashboards",
                ],
                "dashboards": [
                    "id",
                    "name",
                    "type",
                    "is_folder",
                    "app_id",
                    "space_id",
                    "folder_id",
                    "authority",
                    "ui_config",
                    "create_time",
                    "create_user_id",
                    "create_user_name",
                    "modify_time",
                    "refresh_type",
                    "update_user_id",
                    "update_user_name",
                ],
            },
            "analysis.order_detail.list": {
                "re_attribute_info": [
                    "ReAttributeAdAid",
                    "ReAttributeAdCid",
                    "ReAttributeAdGid",
                    "ReAttributeAdPlatform",
                    "ReAttributeAdvertiserID",
                    "ReAttributeCSite",
                    "ReAttributeChannel",
                    "ReAttributeCreateTime",
                    "ReAttributeTurboPromotedObjectID",
                    "ReAttributeRetargetingCount",
                    "ReAttributeAdClickTime",
                ]
            },
            "analysis.user_property.list": {
                "dim_table": ["name", "cname", "data_type", "dim_using_table_name"]
            },
            "analysis.template.own.list": {"subject_names": ["id", "name"]},
            "analysis.template.share.list": {"subject_names": ["id", "name"]},
            "analysis.template.internal.list": {"subject_names": ["id", "name"]},
            "promotion.metric.list": {
                "children": ["name", "cname", "tip", "sort", "is_static", "is_offline"]
            },
            "material.metric.list": {"children": ["name", "cname", "tip", "sort"]},
            "report.business.metric.list": {
                "children": [
                    "label",
                    "name",
                    "tip",
                    "formula",
                    "sort",
                    "metric_label",
                    "metric_type",
                ]
            },
            "material.tag.list": {"category": ["id", "name"]},
            "material.tag_category.tree": {"tag_list": ["id", "name"]},
            "material.favorites.list": {
                "group": [
                    "id",
                    "name",
                    "material_num",
                    "parent_id",
                    "root_id",
                ],
                "material": [
                    "id",
                    "file_type",
                    "file_name",
                    "is_favorite",
                    "width",
                    "height",
                    "file_size",
                    "file_size_str",
                    "status",
                    "source_type",
                    "create_time",
                ],
            },
            "material.album.list": {
                "group": [
                    "id",
                    "name",
                    "material_num",
                    "parent_id",
                    "root_id",
                    "create_time",
                    "modify_time",
                    "create_user_id",
                    "create_user_name",
                    "cid",
                    "update_user_id",
                    "update_user_name",
                ],
                "material": [
                    "id",
                    "file_type",
                    "file_name",
                    "is_favorite",
                    "width",
                    "height",
                    "file_size",
                    "file_size_str",
                    "status",
                    "source_type",
                    "create_time",
                ],
            },
            "material.local.list": {
                "material_consumed": ["bytedance", "kuaishou", "tencent"],
                "material_report": ["create_time", "gravity_material_id"],
                "material_used": ["bytedance", "kuaishou", "tencent"],
            },
            "promotion.ai_trusteeship.detail": {
                "conditions": ["day", "metrics_name", "value"],
                "detail_list": ["advertiser_id", "count", "advertiser_name"],
                "operator_values": ["boost_value", "type", "value"],
                "send_way": ["type"],
                "target_values": ["advertiser_id"],
            },
            "promotion.conditions_history.list": {
                "condition_result": ["target_id"]
            },
            "promotion.history.list": {
                "detail_list": ["advertiser_id", "advertiser_name"],
                "target_values": ["advertiser_id"]
            },
            "metadata.metrics.get": {
                "metrics": ["cname", "formula", "name", "unit"]
            },
            "metadata.event_property_template_event_list.list": {
                "common": [
                    "cid",
                    "cname",
                    "create_time",
                    "data_type",
                    "id",
                    "is_common",
                    "is_preset",
                    "modify_time",
                    "name",
                    "template_id",
                ],
                "custom": [
                    "cid",
                    "cname",
                    "create_time",
                    "data_type",
                    "id",
                    "is_common",
                    "is_preset",
                    "modify_time",
                    "name",
                    "template_id",
                ],
                "preset": [
                    "cid",
                    "cname",
                    "create_time",
                    "data_type",
                    "id",
                    "is_common",
                    "is_preset",
                    "modify_time",
                    "name",
                    "template_id",
                ],
                "properties": ["common", "custom", "preset"],
            },
        }
        device_info = [
            "Android_Version",
            "Api_Version",
            "Rom_version",
            "Aspect_Ratio",
            "Phone_Brand",
            "Phone_Model",
            "OS",
        ]
        re_attribute_info = expected["analysis.order_detail.list"]["re_attribute_info"]
        expected["analysis.monetization_detail.list"] = {
            "device_info": [
                *device_info,
                "Idfa",
                "Idfv",
                "Caid1",
                "Caid2",
                "Oaid",
                "Imei",
                "AndroidId",
            ],
            "re_attribute_info": re_attribute_info,
        }
        expected["analysis.user_detail.list"] = {
            "device_info": [
                *device_info,
                "Idfa",
                "Idfv",
                "Caid1",
                "Caid2",
                "Oaid",
                "Imei",
                "AndroidId",
            ],
            "re_attribute_info": re_attribute_info,
        }
        expected["analysis.segment.user_detail.list"] = {
            "device_info": [
                "Idfa", "Idfv", "Caid1", "Caid2", "Oaid", "Imei", "AndroidId",
                *device_info,
            ],
            "re_attribute_info": re_attribute_info,
        }
        actual = {
            item["operation_id"]: item["response_projection"]["nested_item_keys"]
            for item in self.operations
            if "nested_item_keys" in item["response_projection"]
        }
        self.assertEqual(set(expected), set(actual))
        for operation_id, nested in expected.items():
            with self.subTest(operation_id=operation_id):
                self.assertEqual(nested, actual[operation_id])

        attribution = self.by_id["attribution.postback_map_collect.list"]
        self.assertNotIn("config", attribution["response_projection"]["item_keys"])
        self.assertEqual(
            ["config", "remark"],
            attribution["response_projection"]["known_omitted_item_keys"],
        )
        self.assertEqual(
            [
                "create_time",
                "modify_time",
                "app_id",
                "turbo_promoted_object_id",
                "turbo_promoted_object_name",
                "state",
            ],
            self.by_id["promotion.object.list"]["response_projection"]["item_keys"],
        )
        for operation_id in (
            "attribution.post_backtrack.list",
            "attribution.postback_mode.list",
        ):
            self.assertIn(
                "company", self.by_id[operation_id]["response_projection"]["item_keys"]
            )
        self.assertEqual(
            ["file_md5", "image_set", "remark"],
            self.by_id["material.recycle.list"]["response_projection"][
                "known_omitted_item_keys"
            ],
        )
        self.assertEqual(
            ["list", "page_info", "user_delete", "company_delete"],
            self.by_id["material.recycle.list"]["response_projection"]["data_keys"],
        )
        self.assertFalse(
            {"designer_image_id", "designer_image_name"}
            & set(
                self.by_id["material.recycle.list"]["privacy_policy"][
                    "redact_keys"
                ]
            )
        )
        self.assertEqual(
            [
                "id",
                "name",
                "category",
                "category_id",
                "cid",
                "create_time",
                "is_system",
                "modify_time",
                "source",
            ],
            self.by_id["material.tag.list"]["response_projection"]["item_keys"],
        )
        self.assertEqual(
            ["id", "is_system", "name", "parent_id", "source"],
            self.by_id["material.tag_category.list"]["response_projection"][
                "item_keys"
            ],
        )

        data_item_contracts = {
            item["operation_id"]: item["response_projection"]["data_item_keys"]
            for item in self.operations
            if "data_item_keys" in item["response_projection"]
        }
        self.assertEqual(
            {
                "attribution.attribution_detail.query": {
                    "attribution_list": [],
                    "device_white": [
                        "app_id",
                        "create_time",
                        "device_info",
                        "id",
                        "is_template",
                        "modify_time",
                        "name",
                        "remark",
                        "reuse_from_device_id",
                        "testing_company",
                        "testing_end_time",
                        "testing_start_time",
                        "testing_status",
                    ],
                    "pay_list": [],
                    "postback_list": [],
                },
                "report.my_template.detail": {
                    "detail": [
                        "id", "name", "remark", "category", "config", "app_id",
                        "project_id", "create_time", "update_time", "share_list",
                        "cid", "create_user_id", "create_user_name", "is_preset",
                        "is_public", "is_share", "modify_time", "order", "source_id",
                        "sub_type", "subject_ids", "subscribe", "template_type",
                        "update_user_id", "update_user_name",
                    ]
                },
                "analysis.event.info": {
                    "event_define": [
                        "accepted",
                        "app_id",
                        "cname",
                        "create_time",
                        "id",
                        "is_preset",
                        "lookup",
                        "modify_time",
                        "name",
                        "trigger_opportunity",
                        "uploaded",
                        "visible",
                    ]
                },
                "analysis.dashboard.event_list_info.get": {
                    "common": [
                        "app_id",
                        "cname",
                        "create_time",
                        "data_type",
                        "has_dict",
                        "id",
                        "is_common",
                        "is_preset",
                        "modify_time",
                        "name",
                        "prop_type",
                        "uploaded",
                        "visible",
                    ],
                    "custom": [
                        "app_id",
                        "cname",
                        "create_time",
                        "data_type",
                        "has_dict",
                        "id",
                        "is_common",
                        "is_preset",
                        "modify_time",
                        "name",
                        "prop_type",
                        "uploaded",
                        "visible",
                    ],
                    "preset": [
                        "app_id",
                        "cname",
                        "create_time",
                        "data_type",
                        "has_dict",
                        "id",
                        "is_common",
                        "is_preset",
                        "modify_time",
                        "name",
                        "prop_type",
                        "uploaded",
                        "visible",
                    ],
                },
                "analysis.dashboard.detail": {
                    "even_report": [
                        "report_id",
                        "name",
                        "subject",
                        "config",
                        "remark",
                    ],
                    "share_members": ["uid", "authority", "name", "uname"],
                },
                "analysis.dashboard.members.list": {
                    "creator": ["id", "uid", "name"],
                    "authUsers": ["uid", "authority", "name"],
                },
                "analysis.dashboard.space_members.list": {
                    "creator": ["id", "uid", "name"],
                    "authUsers": ["uid", "authority", "name"],
                },
                "analysis.dashboard.condition_favourite.default_to_me.get": {
                    "object": [
                        "app_id",
                        "cid",
                        "cond_logic",
                        "config",
                        "create_time",
                        "dashboard_id",
                        "default_to_all",
                        "default_to_one",
                        "id",
                        "isCollection",
                        "modify_time",
                        "name",
                        "show_order",
                        "to_use",
                        "create_user_id",
                        "create_user_name",
                        "update_user_id",
                        "update_user_name",
                    ]
                },
                "analysis.report_config.update": {
                    "object": ["id", "app_id"]
                },
                "analysis.template.subject.own.list": {
                    "page_info": ["page", "page_size", "total_number", "total_page"]
                },
                "analysis.template.subject.share.list": {
                    "page_info": ["page", "page_size", "total_number", "total_page"]
                },
                "analysis.order_detail.list": {
                    "total": [
                        "ClientID",
                        "AdPlatform",
                        "Amount",
                        "BackAmount",
                        "PayCount",
                        "PostbackStatus",
                        "PostBackCode",
                        "PassStatus",
                        "Status",
                        "event$pay_method",
                        "event$pay_reason",
                        "user$pay_amount_sum",
                        "user$pay_max_amount",
                        "Name",
                    ]
                },
                "analysis.monetization_detail.list": {
                    "total": [
                        "CreateTime",
                        "AdEventTime",
                        "AdPlatform",
                        "TurboPromotedObjectID",
                        "AdvertiserID",
                        "AdAid",
                        "event$ecpm",
                        "samount",
                        "event$ad_type",
                        "event$adn_type",
                        "event$ad_unit_id",
                        "event$ad_through",
                        "event$ad_source_id",
                        "event$ad_placement_id",
                        "re_attribute_info",
                        "user_id",
                        "event_user_id",
                        "device_id",
                        "ClientID",
                        "TraceID",
                        "device_info",
                        "user$ad_count",
                        "user$ad_avg_ecpm",
                        "user$ad_ltv",
                        "Name",
                        "WXOpenID",
                    ]
                },
                "attribution.attribution.query": {
                    "items": ["ad_platform", "date"],
                    "tips": [],
                    "total": ["ad_platform", "date"],
                },
                "report.get.query": {
                    "extra_data": [],
                    "page_info": ["total"],
                    "total": [
                        "stat_time",
                        "monetization_platform",
                        "ad_unit_id",
                    ],
                },
                "analysis.segment.detail": {
                    "update_date_range": ["start_date", "end_date"]
                },
                "analysis.segment.user_detail.list": {
                    "page_info": ["page", "page_size", "total_number", "total_page"]
                },
                "analysis.user_event.list": {
                    "device": [
                        "Android_Version",
                        "Api_Version",
                        "Aspect_Ratio",
                        "OS",
                        "Phone_Brand",
                        "Phone_Model",
                        "Rom",
                        "Rom_version",
                        "AndroidId",
                        "Caid1",
                        "Caid2",
                        "DeviceId",
                        "Idfa",
                        "Idfv",
                        "Imei",
                        "Oaid",
                    ],
                    "user": [
                        "ClientID",
                        "user_id",
                        "device_id",
                        "CreateTime",
                        "LatestLoginDay",
                        "modify_time",
                        "Name",
                        "WXOpenID",
                    ],
                    "re_attribute_records": re_attribute_info,
                },
                "app.capacity.get": {"data": ["capacity", "product"]},
                "app.role.detail": {
                    "data_permission": [
                        "child_module",
                        "effect_module",
                        "id",
                        "role_effect",
                    ],
                    "menu": ["id", "name"],
                },
                "app.realtime_event.list": {
                    "conf": [
                        "app_id",
                        "create_time",
                        "end_time",
                        "is_enabled",
                        "modify_time",
                        "start_time",
                    ]
                },
                "app.detail": {
                    "app": [
                        "create_time",
                        "modify_time",
                        "id",
                        "cid",
                        "name",
                        "is_enabled",
                        "os",
                        "package_name",
                        "industry_id",
                        "wechat_app_id",
                        "wechat_origin_id",
                        "event_version",
                        "is_iaa",
                    ]
                },
                "material.bytedance.project_material.list": {
                    "instant_play_material_list": [],
                    "trial_play_material_list": [],
                    "video_material_list": [
                        "file_name",
                        "file_url",
                        "material_id",
                        "thumbnail_url",
                        "type",
                    ]
                },
                "report.multidim.template.tree": {
                    "my_template": ["id", "name"],
                    "share_template": ["id", "name"],
                },
                "report.multidim.template.preset.get": {"detail": ["name"]},
                "promotion.ai_trusteeship.detail": {
                    "data": [
                        "caliber",
                        "check_fre",
                        "check_type",
                        "cid",
                        "condition_type",
                        "conditions",
                        "count",
                        "create_time",
                        "detail_list",
                        "frequency",
                        "id",
                        "last_check_time",
                        "media_type",
                        "modify_time",
                        "name",
                        "operator_values",
                        "params_md5",
                        "schedule_type",
                        "send_way",
                        "status",
                        "target",
                        "target_type",
                        "target_values",
                        "create_user_id",
                        "create_user_name",
                        "update_user_id",
                        "update_user_name",
                    ]
                },
                "promotion.bytedance.advertiser.list": {"total": ["stat_cost"]},
                "promotion.bilibili.account.list": {
                    "total": [
                        "average_cost_per_thousand",
                        "click_count",
                        "click_rate",
                        "cost_per_click",
                        "san_lian_launch_total_consume",
                        "show_count",
                        "total_cash_consume",
                        "total_consume",
                        "total_red_packet_consume",
                        "total_special_red_packet_consume",
                    ]
                },
                "promotion.bytedance.advertiser_performance.list": {
                    "total": ["stat_cost"]
                },
                "promotion.bytedance.project.list": {"total": ["stat_cost"]},
                "promotion.tencent.advertiser.list": {"total": ["cost"]},
                "promotion.taptap.group.list": {"total": []},
                "report.company_amount.query": {
                    "total": [
                        "ad_count",
                        "ad_create_amount_usage",
                        "adclick_count",
                        "cost_count",
                        "event_count",
                        "material_transmit_g_usage",
                        "profile_count",
                        "storage_count",
                        "tracking_count",
                        "user_count",
                    ]
                },
                "report.multidim.query": {
                    "extra_data": [],
                    "page_info": ["total"],
                    "total": ["ap_cost", "stat_time"],
                },
                # gi-final-unlock：overview 只暴露在线验证过的聚合列表字段。
                "report.overview.query": {
                    "columns": [
                        "AdCost",
                        "AppActivePayAmountSumReco",
                        "AppAdFirstDayRevenueReco",
                        "AppAdRevenueReco",
                        "AppDAUReco",
                        "AppFirstDayPayAmountStandardReco",
                        "AppROIReco",
                        "AppRealRegisterCnt",
                        "AppRevenueReco",
                    ],
                    "data_overview": ["base", "cname", "compare", "name", "ratio"],
                    "trend_overview2": [
                        "AdCost",
                        "AppActivePayAmountSumReco",
                        "AppAdFirstDayRevenueReco",
                        "AppAdRevenueReco",
                        "AppDAUReco",
                        "AppFirstDayPayAmountStandardReco",
                        "AppROIReco",
                        "AppRealRegisterCnt",
                        "AppRevenueReco",
                        "date",
                    ],
                },
                # 小时对比只暴露在线验证过的字段字典与今日/昨日聚合序列。
                "report.hour_comparison.query": {
                    "columns": [
                        "AdCost",
                        "AppActivePayAmountSumReco",
                        "AppAdFirstDayRevenueReco",
                        "AppAdRevenueReco",
                        "AppDAUReco",
                        "AppFirstDayPayAmountStandardReco",
                        "AppROIReco",
                        "AppRealRegisterCnt",
                        "AppRevenueReco",
                    ],
                    "today": [
                        "AppActivePayAmountSumReco",
                        "AppAdFirstDayRevenueReco",
                        "AppAdRevenueReco",
                        "AppDAUReco",
                        "AppFirstDayPayAmountStandardReco",
                        "AppRealRegisterCnt",
                        "AppRevenueReco",
                        "hour",
                    ],
                    "yesterday": [
                        "AppActivePayAmountSumReco",
                        "AppAdFirstDayRevenueReco",
                        "AppAdRevenueReco",
                        "AppDAUReco",
                        "AppFirstDayPayAmountStandardReco",
                        "AppRealRegisterCnt",
                        "AppRevenueReco",
                        "hour",
                    ],
                },
            },
            data_item_contracts,
        )

        self.assertEqual(
            {"data_dims": "string"},
            self.by_id["report.multidim.query"]["response_projection"][
                "data_scalar_list_types"
            ],
        )

        self.assertEqual(
            {
                "bytedance.optimization_goal": ["code", "name"],
                "bytedance.deep_optimization_goal": ["code", "name"],
                "bytedance.deep_bid_type": ["code", "name"],
                "tencent.optimization_goal": ["code", "name"],
                "tencent.deep_optimization_goal": ["code", "name", "order"],
                "kuaishou.optimization_goal": ["code", "name"],
                "kuaishou.deep_optimization_goal": ["code", "name"],
            },
            self.by_id["report.multidim.media_enum.list"]["response_projection"][
                "data_path_item_keys"
            ],
        )

        event_property_keys = [
            "app_id",
            "cname",
            "create_time",
            "data_type",
            "dim_table",
            "has_dict",
            "id",
            "is_common",
            "is_preset",
            "modify_time",
            "name",
            "prop_type",
            "uploaded",
            "visible",
        ]
        self.assertEqual(
            {
                "properties.common": event_property_keys,
                "properties.custom": event_property_keys,
                "properties.preset": event_property_keys,
            },
            self.by_id["analysis.event.info"]["response_projection"][
                "data_path_item_keys"
            ],
        )

        scalar_list_contracts = {
            item["operation_id"]: item["response_projection"]["scalar_list_item_types"]
            for item in self.operations
            if "scalar_list_item_types" in item["response_projection"]
        }
        self.assertEqual(
            {
                "analysis.order_detail.list": {"$split_trace_id_list": "string"},
                "app.list": {"sub_package_list": "string"},
                "app.template.list": {"menu_config": "integer"},
                "analysis.template.own.list": {"subject_ids": "integer"},
                "analysis.template.share.list": {"subject_ids": "integer"},
                "analysis.template.internal.list": {"subject_ids": "integer"},
                "material.bytedance.promotion_material.list": {
                    "labels": "string",
                    "organization_tags": "string",
                },
                "report.multidim.metric.list": {
                    "tag_ids": "integer",
                    "exclusion_dims": "string",
                },
                "report.metric.list": {
                    "tag_ids": "integer",
                    "exclusion_dims": "string",
                },
                "report.multidim.custom_metric.list": {
                    "tag_ids": "integer",
                    "exclusion_dims": "string",
                    "broken_words": "string",
                },
                "report.custom_metric.list": {
                    "tag_ids": "integer",
                    "exclusion_dims": "string",
                    "broken_words": "string",
                },
                "report.multidim.custom_metric.shared.list": {
                    "tag_ids": "integer",
                    "exclusion_dims": "string",
                },
                "report.multidim.metric_tag.list": {"exclusion_tags": "integer"},
            },
            scalar_list_contracts,
        )

    def test_verified_dynamic_totals_and_recursive_contracts_are_exact(self) -> None:
        promotion_totals = {
            item["operation_id"]: item["response_projection"][
                "data_dynamic_item_fields"
            ]["total"]
            for item in self.operations
            if item["domain"] == "promotion"
            and "total"
            in item["response_projection"].get("data_dynamic_item_fields", {})
        }
        self.assertEqual(25, len(promotion_totals))
        self.assertTrue(
            all(fields == ["query_fields"] for fields in promotion_totals.values())
        )
        self.assertNotIn("promotion.taptap.group.list", promotion_totals)

        self.assertEqual(
            {
                "ratio": ["metrics_list", "dims_list"],
                "total": ["metrics_list", "dims_list"],
            },
            self.by_id["report.business.query"]["response_projection"][
                "data_dynamic_item_fields"
            ],
        )
        business_fields = self.by_id["report.business.query"]["input_fields"]
        self.assertEqual(
            [
                "AdCost",
                "AppRevenue",
                "AppROI",
                "AppRealRegisterCnt",
                "AppGamePayUserCntReportingStandard",
                "AppDAUReco",
            ],
            business_fields["metrics_list"]["item_enum"],
        )
        self.assertEqual(
            ["stat_datetime", "advertiser_id", "ad_platform", "app_id"],
            business_fields["dims_list"]["item_enum"],
        )
        self.assertNotIn("operator", business_fields["dims_list"]["item_enum"])
        self.assertEqual(
            {
                "total": [
                    "data_dims",
                    "relate_dims",
                    "metrics_list",
                    "custom_metrics_list",
                    "time_dims",
                ]
            },
            self.by_id["report.multidim.query"]["response_projection"][
                "data_dynamic_item_fields"
            ],
        )
        self.assertEqual(
            {
                "tree": [
                    "id",
                    "label",
                    "parent_id",
                    "root_id",
                    "has_alum",
                    "children",
                ]
            },
            self.by_id["material.album.tree"]["response_projection"][
                "recursive_data_item_keys"
            ],
        )

        tag_category = self.by_id["report.multidim.metric_tag_category.list"]
        tag = self.by_id["report.multidim.metric_tag.list"]
        self.assertTrue(
            {"create_time", "modify_time"}
            <= set(tag_category["response_projection"]["item_keys"])
        )
        self.assertTrue(
            {"create_time", "modify_time", "exclusion_tags"}
            <= set(tag["response_projection"]["item_keys"])
        )
        self.assertIn(
            "expired_cnt",
            self.by_id["promotion.kuaishou.account.list"]["response_projection"][
                "data_keys"
            ],
        )

    def test_no_registered_path_looks_like_a_write_or_export(self) -> None:
        for item in self.operations:
            if item.get("effect") == "mutation":
                self.assertEqual("stable", item["stability"])
                self.assertFalse(item["live_probe"]["enabled"])
                continue
            segments = {
                segment.casefold()
                for segment in item["path_template"].split("/")
                if segment
            }
            with self.subTest(operation_id=item["operation_id"]):
                if item["operation_id"] == "report.subscribe.list":
                    self.assertEqual(
                        "/turbo_engine/api/v3/subscribe/list/", item["path_template"]
                    )
                    continue
                self.assertFalse(segments & WRITE_SEGMENTS)
                self.assertNotRegex(
                    item["path_template"],
                    re.compile(
                        r"/(?:edit|update|start|stop|switch|bind|unbind)/", re.I
                    ),
                )

    def test_platform_specific_wire_contracts_remain_explicit(self) -> None:
        alipay = self.by_id["promotion.alipay.advertiser.list"]
        self.assertEqual(["page", "page_size"], alipay["request"]["query_fields"])
        self.assertNotIn("page", alipay["request"]["body_fields"])

        bing = self.by_id["promotion.bing.advertiser.list"]
        self.assertEqual("string", bing["input_fields"]["filters"]["type"])

        wechat_video = self.by_id["promotion.wechat_video.report.list"]
        self.assertIn("extra.error", wechat_video["semantic_error_rules"])
        self.assertEqual("page_info", wechat_video["pagination"]["kind"])
        self.assertEqual(
            ["list", "page_info"],
            wechat_video["response_projection"]["data_keys"],
        )
        self.assertEqual(
            ["list"], wechat_video["response_projection"]["required_data_keys"]
        )
        self.assertTrue(
            wechat_video["response_projection"]["empty_object_as_empty_page"]
        )

        self.assertIn(
            "/qihu360/",
            self.by_id["promotion.qihu360.advertiser.list"]["path_template"],
        )
        self.assertIn(
            "/youdao/",
            self.by_id["promotion.youdao.advertiser.list"]["path_template"],
        )

        tencent = self.by_id["promotion.tencent.advertiser.list"]
        self.assertEqual(
            ["behavior", "active", "request"],
            tencent["input_fields"]["time_line"]["enum"],
        )
        self.assertEqual("behavior", tencent["request"]["defaults"]["time_line"])
        self.assertEqual("v3.0", tencent["request"]["fixed_body"]["version"])
        self.assertNotIn("version", tencent["input_fields"])
        self.assertTrue(
            {"operator_id", "operator_name"}
            <= set(tencent["response_projection"]["item_keys"])
        )

        material = self.by_id["material.tencent.list"]
        self.assertTrue(
            {
                "file_url",
                "thumbnail_url",
                "create_user_id",
                "create_user_name",
                "creative_user_id",
                "creative_user_name",
                "designer_id",
                "designer_name",
            }
            <= set(material["response_projection"]["item_keys"])
        )

        apple = self.by_id["promotion.apple.advertiser.list"]
        self.assertEqual("utc", apple["request"]["defaults"]["time_zone"])
        self.assertIn("time_zone", apple["request"]["body_fields"])

        multidim = self.by_id["report.multidim.query"]
        self.assertEqual("string", multidim["input_fields"]["time_dims"]["type"])
        self.assertEqual(
            ["hour", "day", "week", "month", "total"],
            multidim["input_fields"]["time_dims"]["enum"],
        )
        self.assertEqual("adreport", multidim["request"]["defaults"]["data_topic"])
        self.assertEqual(1, multidim["request"]["defaults"]["page"])
        self.assertEqual(100, multidim["request"]["defaults"]["page_size"])
        self.assertTrue(
            {"page", "page_size"} <= set(multidim["request"]["body_fields"])
        )
        self.assertEqual("none", multidim["pagination"]["kind"])
        self.assertEqual("", multidim["pagination"]["total_page_field"])

        calc_total = self.by_id["report.multidim.calc_total"]
        self.assertIn("data_list", calc_total["request"]["body_fields"])
        self.assertFalse(calc_total["input_fields"]["data_list"].get("required", False))
        self.assertIn("time_dims", calc_total["request"]["body_fields"])
        self.assertNotIn("page", calc_total["request"]["body_fields"])

    def test_row_projection_declares_safe_static_and_dynamic_fields(self) -> None:
        promotion = self.by_id["promotion.honor.advertiser.list"]
        self.assertIn("account_name", promotion["response_projection"]["item_keys"])
        self.assertEqual(
            ["query_fields"],
            promotion["response_projection"]["dynamic_item_fields"],
        )

        multidim = self.by_id["report.multidim.query"]
        self.assertIn("app_id", multidim["response_projection"]["item_keys"])
        self.assertIn("advertiser_id", multidim["response_projection"]["item_keys"])
        self.assertIn("gid", multidim["response_projection"]["item_keys"])
        self.assertEqual(
            {
                "data_dims",
                "relate_dims",
                "metrics_list",
                "custom_metrics_list",
                "time_dims",
            },
            set(multidim["response_projection"]["dynamic_item_fields"]),
        )

        row = {
            "account_name": "business-name",
            "spend": 1,
            "email_address": "private",
            "new_sensitive_field": "private",
        }
        allowed = set(promotion["response_projection"]["item_keys"])
        for source in promotion["response_projection"]["dynamic_item_fields"]:
            allowed.update({"query_fields": ["spend"]}.get(source, []))
        projected = {key: value for key, value in row.items() if key in allowed}
        self.assertEqual(
            {"account_name": "business-name", "spend": 1},
            projected,
        )

        metric = self.by_id["report.multidim.metric.list"]
        self.assertTrue(
            {
                "name",
                "cname",
                "metric_type",
                "tag_ids",
                "exclusion_dims",
                "tip",
            }
            <= set(metric["response_projection"]["item_keys"])
        )
        material = self.by_id["material.local.list"]
        self.assertTrue(
            {"file_name", "file_size", "audit_status", "tags", "media_status"}
            <= set(material["response_projection"]["item_keys"])
        )

    def test_metric_catalogs_use_the_observed_single_page_limit(self) -> None:
        for operation_id in (
            "report.metric.list",
            "report.multidim.metric.list",
        ):
            with self.subTest(operation_id=operation_id):
                operation = self.by_id[operation_id]
                self.assertEqual(2000, operation["input_fields"]["page_size"]["default"])
                self.assertEqual(2000, operation["request"]["defaults"]["page_size"])
                self.assertEqual(2000, operation["pagination"]["default_page_size"])
                self.assertEqual(2000, operation["pagination"]["max_page_size"])
                self.assertTrue(
                    {"data_topic", "is_media"}
                    <= set(operation["response_projection"]["item_keys"])
                )


if __name__ == "__main__":
    unittest.main()
