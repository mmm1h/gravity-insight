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
            **(
                {
                    "unreliable_item_keys": plain(projection.unreliable_item_keys)
                }
                if projection.unreliable_item_keys
                else {}
            ),
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
            # 调用方公开商店 URL 首次取得成功非空 App 信息合同后晋升。
            "app.app_info.get",
            # D28：catalog#2 非空 item/total 后晋升；分页为实测 none。
            "report.get.query",
            # D35：完整前端 builder 加明确空/非空生产证据后晋升。
            "attribution.attribution.query",
            "material.asset_material_media_review_list.list",
            "metadata.promotion_gravity_metric.list",
            "metadata.property.list",
            "promotion.bytedance.project_filter.list",
            "promotion.bytedance.promotion_filter.list",
            "promotion.latest_account_status.get",
            "promotion.tencent.adgroup_filter.list",
            "report.metric.list",
            # 多 App 复验取得默认值字典非空 shape 后晋升 stable。
            "analysis.default_val.list",
            # gi-reprobe：参数契约装配后新升 stable。
            # 本集合刻意保持显式登记而非动态计算——每个新增 stable 都必须
            # 在这里被看见，否则契约可以悄悄混进 catalog 而不被任何人察觉。
            # gi-final-unlock：分页与 fail-closed 响应投影在线验证后新升 stable。
            "report.company_amount.query",
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
            # 收敛前端超大分页默认值并完成非空分页与响应投影复验后晋升。
            "report.tag.list",
            "report.tag_category.list",
            # 固定全局范围并完成嵌套聚合字段白名单复验后晋升。
            "report.hour_comparison.query",
            # 素材审核用户列表经非空验证和人员敏感字段收窄后晋升。
            "material.material_examine_user.list",
            # 素材相册列表经递归父级解析、分页复验和嵌套响应投影后晋升。
            "material.album.list",
            # 巨量创意组件账户选择器完成精确请求绑定、分页和字段复验后晋升。
            "promotion.bytedance.account.list",
            # 巨量账户主体选择器完成标量列表投影与字段复验后晋升。
            "promotion.bytedance.account_company.list",
            # 巨量启用项目列表完成父级、固定过滤和保守响应投影复验后晋升。
            "promotion.bytedance.manager_project.list",
            # 巨量可投放广告列表完成账户父级、固定过滤和响应投影复验后晋升。
            "promotion.bytedance.manager_promotion.list",
            # 巨量图片素材列表完成父级、整数参数、分页和字段复验后晋升。
            "material.bytedance_asset_material.list",
            # 巨量项目素材列表完成同源父级、非空样本和嵌套响应投影后晋升。
            "material.bytedance.project_material.list",
            # 巨量广告素材表现完成同源父级、默认指标和响应投影复验后晋升。
            "material.bytedance.promotion_material.list",
            # 巨量广告主表现首屏完成精确无拉数请求和响应投影复验后晋升。
            "promotion.bytedance.advertiser_performance.list",
            # 公司套餐容量完成精确 GET、嵌套投影和字段复验后晋升。
            "app.capacity.get",
            # 容量历史完成当前公司父级、分页和嵌套响应投影复验后晋升。
            "app.capacity.list",
            # 腾讯账户主体选择器完成标量类型和字段复验后晋升。
            "promotion.tencent.account_company.list",
            # 快手账户主体选择器完成布尔请求和标量类型复验后晋升。
            "promotion.kuaishou.account_company.list",
            # AI 托管详情完成规则列表父级、GET 参数和递归响应投影复验后晋升。
            "promotion.ai_trusteeship.detail",
            # 实时事件配置完成应用父级、GET 参数和自由文本隐私收口后晋升。
            "app.realtime_event.list",
            # AI 托管指标字典完成媒体类型父级、嵌套字段和路由字段复验后晋升。
            "metadata.metrics.get",
            # 权限菜单完成网页端固定产品参数、递归投影和字段复验后晋升。
            "app.permission_menu.list",
            # 角色列表完成固定菜单开关、分页上限和字段复验后晋升。
            "app.role.list",
            # 角色详情完成角色列表父级、固定产品参数和嵌套字段复验后晋升。
            "app.role.detail",
            # 角色模板完成固定产品参数、分页和嵌套配置投影复验后晋升。
            "app.template.list",
            # 报表/订阅以 marker-governed 写取得非空 schema 后晋升。
            "report.my_template.detail",
            "report.report.detail",
            "report.report.list",
            "report.report.update",
            "report.subscribe.create",
            "report.subscribe.delete",
            "report.subscribe.list",
            "report.template.create",
            "report.template.update",
            # 写操作范围裁决后首批晋升；只允许显式确认的 Segment mutation。
            "analysis.dataanalysis.segment.update",
            "analysis.from.history.version.create",
            "analysis.from.tmp.segment.create",
            "analysis.segment.by.manual.update",
            "analysis.segment.from.analysis.create",
            "analysis.segment.from.rule.create",
            "analysis.segment.from.rule.update",
            # Marker-governed Kanban writes: explicit preview/confirmation only.
            "analysis.datamanageconfig.kanban.dashboard.copy",
            "analysis.datamanageconfig.kanban.dashboard.create",
            "analysis.datamanageconfig.kanban.dashboard.dc7858a7.update",
            "analysis.datamanageconfig.kanban.dashboard.delete",
            "analysis.datamanageconfig.kanban.dashboard.move",
            "analysis.datamanageconfig.kanban.dashboard.update",
            "analysis.datamanageconfig.kanban.folder.create",
            "analysis.datamanageconfig.kanban.folder.delete",
            "analysis.datamanageconfig.kanban.folder.move",
            "analysis.datamanageconfig.kanban.folder.update",
            "analysis.datamanageconfig.kanban.note.update",
            "analysis.datamanageconfig.kanban.space.create",
            "analysis.datamanageconfig.kanban.space.delete",
            "analysis.datamanageconfig.kanban.space.move",
            "analysis.datamanageconfig.kanban.space.update",
            "analysis.engine.datamanageconfig.kanban.delete",
            "analysis.kanban.dashboard.folder.move",
            "analysis.kanban.dashboard.order.update",
            # F40 完成测试设备父行枚举、单次详情和完整已观察投影后晋升。
            "app.testing_tool.list",
            "attribution.attribution_detail.query",
            # Current confmetric custom-metric CRUD completed one live
            # create/read/update/query/delete lifecycle without replacing old routes.
            "report.custom_metric.list",
            "report.confmetric.custom.metric.update",
            "report.confmetric.custom.metric.8ef6d12d.delete",
            # Event/property template lifecycle completed a bounded
            # create/member-readback/remove/delete production loop.
            "metadata.event.property.template.079c8246.create",
            "metadata.event.property.template.create",
            "metadata.property.template.event.delete",
            "metadata.property.template.property.delete",
            # Saved Analysis CRUD completed the shared update-route wire and
            # one event create/read/update/replay/delete production loop.
            "analysis.report_config.update",
            # 腾讯广告组报表经 hash-matched 控制流确认、非空 page_info 实测后晋升。
            "promotion.tencent.tencent_adgroup_v2.list",
            # 腾讯 medium creative 经 hash-matched 控制流确认、非空 item schema 后晋升。
            "material.tencent_medium_creative.list",
            # 实时事件入库开关从 reservation 晋升为受治理 mutation。
            "app.user.realtime.event.update",
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
