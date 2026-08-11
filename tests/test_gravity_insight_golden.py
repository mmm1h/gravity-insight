from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from gravity_sdk import models, registry


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = ROOT / "src" / "gravity_sdk" / "manifests"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "gravity_insight_golden"
WIRE_OPERATION_IDS = {
    "analysis.segment.list",
    "analysis.segment.evaluate_percent",
    "analysis.account_user.list",
    "analysis.order_detail.list",
    "analysis.monetization_detail.list",
    "analysis.user_detail.list",
    "analysis.user_event.list",
    "analysis.segment.uid_result.list",
    "analysis.segment.user_detail.list",
    "analysis.order_split_detail.list",
    "analysis.user_postback_log.list",
    "report.business.query",
    "material.report.query",
}


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(name): plain(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def normalize_input(field: models.InputField) -> dict[str, Any]:
    present = field.default is not models._MISSING
    return {
        "name": field.name,
        "type": field.type,
        "required": field.required,
        "nullable": field.nullable,
        "enum": plain(field.enum),
        "default": {
            "present": present,
            "value": plain(field.default) if present else None,
        },
        "description": field.description,
        "sensitive": field.sensitive,
        "item_type": field.item_type,
        "item_enum": plain(field.item_enum),
        "min_items": field.min_items,
        "max_items": field.max_items,
        "max_length": field.max_length,
        "max_depth": field.max_depth,
    }


def normalize_operation(operation: models.OperationSpec) -> dict[str, Any]:
    projection = operation.response_projection
    return {
        "operation_id": operation.operation_id,
        "domain": operation.domain,
        "resource": operation.resource,
        "action": operation.action,
        "platform": operation.platform,
        "description": operation.description,
        "stability": operation.stability,
        "executable": operation.executable,
        "block_reason": operation.block_reason,
        "contract_version": operation.contract_version,
        "upstream_method": operation.upstream_method,
        "path_template": operation.path_template,
        "auth_profile": operation.auth_profile,
        "input_fields": sorted(
            (normalize_input(field) for field in operation.input_fields),
            key=lambda item: item["name"],
        ),
        "request": {
            "location": operation.request.location,
            "path_fields": plain(operation.request.path_fields),
            "query_fields": plain(operation.request.query_fields),
            "body_fields": plain(operation.request.body_fields),
            "defaults": plain(operation.request.defaults),
            "fixed_query": plain(operation.request.fixed_query),
            "fixed_body": plain(operation.request.fixed_body),
        },
        "response_projection": {
            "data_shape": projection.data_shape,
            "data_keys": plain(projection.data_keys),
            "required_data_keys": plain(projection.required_data_keys),
            "item_keys": plain(projection.item_keys),
            "dynamic_item_fields": plain(projection.dynamic_item_fields),
            **(
                {
                    "numeric_suffix_item_fields": plain(
                        projection.numeric_suffix_item_fields
                    )
                }
                if projection.numeric_suffix_item_fields
                else {}
            ),
            "nested_item_keys": plain(projection.nested_item_keys),
            "known_omitted_nested_item_keys": plain(
                projection.known_omitted_nested_item_keys
            ),
            "data_item_keys": plain(projection.data_item_keys),
            "scalar_list_item_types": plain(projection.scalar_list_item_types),
            "data_scalar_list_types": plain(projection.data_scalar_list_types),
            "data_path_item_keys": plain(projection.data_path_item_keys),
            "data_dynamic_item_fields": plain(
                projection.data_dynamic_item_fields
            ),
            **(
                {
                    "data_numeric_suffix_item_fields": plain(
                        projection.data_numeric_suffix_item_fields
                    )
                }
                if projection.data_numeric_suffix_item_fields
                else {}
            ),
            "known_omitted_item_keys": plain(projection.known_omitted_item_keys),
            "recursive_data_item_keys": plain(
                projection.recursive_data_item_keys
            ),
            "known_omitted_data_keys": plain(projection.known_omitted_data_keys),
            "known_omitted_data_item_keys": plain(
                projection.known_omitted_data_item_keys
            ),
            "numeric_paths": plain(projection.numeric_paths),
            "empty_object_as_empty_page": projection.empty_object_as_empty_page,
            "empty_object_as_empty_result": projection.empty_object_as_empty_result,
            "opaque_json_item_keys": plain(projection.opaque_json_item_keys),
        },
        "pagination": {
            "kind": operation.pagination.kind,
            "page_field": operation.pagination.page_field,
            "page_size_field": operation.pagination.page_size_field,
            "items_field": operation.pagination.items_field,
            "page_info_field": operation.pagination.page_info_field,
            "total_page_field": operation.pagination.total_page_field,
            "list_path": operation.pagination.list_path,
            "page_info_path": operation.pagination.page_info_path,
            "default_page_size": operation.pagination.default_page_size,
            "max_page_size": operation.pagination.max_page_size,
        },
        "semantic_error_rules": [
            {
                "path": rule.path,
                "operator": rule.operator,
                "value": plain(rule.value),
                "values": plain(rule.values),
                "message": rule.message,
            }
            for rule in operation.semantic_error_rules
        ],
        "privacy_policy": {
            "classification": operation.privacy_policy.classification,
            "redact_fields": plain(operation.privacy_policy.redact_fields),
        },
        "required_parent": [
            {
                "operation_id": parent.operation_id,
                "input_field": parent.input_field,
            }
            for parent in operation.required_parent
        ],
        "live_probe": {
            "enabled": operation.live_probe.enabled,
            "inputs": plain(operation.live_probe.inputs),
        },
    }


def repository_operations() -> dict[str, models.OperationSpec]:
    operations: dict[str, models.OperationSpec] = {}
    for path in sorted(MANIFEST_ROOT.glob("*.json")):
        for operation in models.load_operation_manifest(path):
            if operation.operation_id in operations:
                raise AssertionError(f"duplicate operation: {operation.operation_id}")
            operations[operation.operation_id] = operation
    return operations


class GravityInsightGoldenTests(unittest.TestCase):
    def test_all_registered_operation_semantics_match_normalized_golden(self) -> None:
        expected = json.loads(
            (FIXTURE_ROOT / "operations.json").read_text(encoding="utf-8")
        )
        operations = repository_operations()
        probed_additions = {
            "material.asset_material_media_review_list.list",
            "material.tag_category.tree",
            "metadata.event_property_template_event_list.list",
            "metadata.promotion_gravity_metric.list",
            "metadata.property.list",
            "promotion.bytedance.project_filter.list",
            "promotion.bytedance.promotion_filter.list",
            "promotion.latest_account_status.get",
            "promotion.tencent.adgroup_filter.list",
            "report.metric.list",
            # gi-reprobe：参数契约装配后新升 stable。
            # 本集合刻意保持显式登记而非动态计算——每个新增 stable 都必须
            # 在这里被看见，否则契约可以悄悄混进 catalog 而不被任何人察觉。
            "promotion.bilibili.account.list",
            # gi-final-unlock：分页与 fail-closed 响应投影在线验证后新升 stable。
            "report.company_amount.query",
            "report.overview.query",
            # gi-cid-unblock：cid 租户标识复评后通过既有完整 probe 闸门。
            "promotion.bytedance.app.list",
            # gi-privacy：隐私分类闭环后通过既有成功 probe 闸门。
            "promotion.bytedance.site.list",
            "promotion.conditions_history.list",
            "promotion.history.list",
            # 巨量标题素材两条读取经非空分页探针验证后晋升 stable。
            "material.bytedance_asset_text_title.list",
            "material.bytedance_std_asset_text_title.list",
            # 巨量标题素材包经 app.list 父级、必填参数和分页复验后晋升。
            "material.bytedance_asset_text_title_package.list",
            "material.bytedance_std_asset_text_title_package.list",
            # 腾讯广告组配置经父资源解析、非空复验和 fail-closed 字段审查后晋升。
            "promotion.tencent.medium_adgroup.list",
            # 非空分页复验后晋升的 AI 托管与数据表配置读取。
            "promotion.ai_trusteeship.list",
            "metadata.version.list",
            "metadata.operation_log.list",
            # 修复整数页大小并完成分页复验后晋升。
            "metadata.event_property_template_event.list",
            "promotion.bytedance.custom_audience.list",
            # 修复歧义分页类型、完成非空分页复验并收窄筛选与响应投影后晋升。
            "material.asset_directional_package_bytedance.list",
            # 收敛前端超大分页默认值并完成非空分页与隐私投影复验后晋升。
            "report.tag.list",
            "report.tag_category.list",
            # 固定全局范围并完成嵌套聚合字段白名单复验后晋升。
            "report.hour_comparison.query",
            # 素材审核用户列表经非空验证和人员敏感字段收窄后晋升。
            "material.material_examine_user.list",
            # 素材相册列表经递归父级解析、分页复验和嵌套隐私投影后晋升。
            "material.album.list",
            # 巨量创意组件账户选择器完成精确请求绑定、分页和隐私复验后晋升。
            "promotion.bytedance.account.list",
            # 巨量图片素材列表完成父级、整数参数、分页和隐私复验后晋升。
            "material.bytedance_asset_material.list",
        }
        expected_ids = {
            item["operation_id"] for item in expected["operations"]
        }
        self.assertEqual(
            probed_additions,
            set(operations) - expected_ids,
        )
        actual = {
            "golden_version": 1,
            "operation_count": len(expected_ids),
            "operations": [
                normalize_operation(operation)
                for operation in sorted(
                    (
                        item for item in operations.values()
                        if item.operation_id in expected_ids
                    ),
                    key=lambda item: item.operation_id,
                )
            ],
        }
        self.assertEqual(len(expected["operations"]), expected["operation_count"])
        self.assertEqual(expected, actual)

    def test_all_13_special_codec_input_to_wire_cases_match_golden(self) -> None:
        expected = json.loads(
            (FIXTURE_ROOT / "wire.json").read_text(encoding="utf-8")
        )
        operations = repository_operations()
        self.assertEqual(13, expected["case_count"])
        self.assertEqual(
            WIRE_OPERATION_IDS,
            {case["operation_id"] for case in expected["cases"]},
        )
        with patch.object(
            registry.time, "time", return_value=1_786_147_200.0
        ), patch.object(
            registry.secrets,
            "token_hex",
            return_value="0123456789abcdef0123",
        ):
            for case in expected["cases"]:
                operation_id = case["operation_id"]
                operation = operations[operation_id]
                with self.subTest(operation_id=operation_id):
                    values = operation.validate_inputs(case["input"])
                    query, body = registry._request_parts(operation, values)
                    actual = {
                        "method": operation.upstream_method,
                        "path": operation.render_path(values),
                        "query": query,
                        "body": body,
                    }
                    self.assertEqual(case["wire"], actual)


if __name__ == "__main__":
    unittest.main()
