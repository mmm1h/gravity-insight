from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli, runtime

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import (
        ErrorCode,
        ErrorDetail,
        InputValidationError,
        UpstreamError,
        exit_code_for_error,
    )
    from gravity_sdk.models import ReadResult
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import (
        ErrorCode,
        ErrorDetail,
        InputValidationError,
        UpstreamError,
        exit_code_for_error,
    )
    from gravity_sdk.models import ReadResult


ROOT = Path(__file__).resolve().parents[1]


def _operation(
    operation_id: str,
    resource: str,
    *,
    input_fields=None,
    required_parent=None,
    pagination=False,
):
    fields = dict(input_fields or {})
    request_fields = list(fields)
    request = {
        "path_fields": [],
        "query_fields": request_fields,
        "body_fields": [],
        "defaults": {
            name: spec["default"]
            for name, spec in fields.items()
            if "default" in spec
        },
        "fixed_query": {},
        "fixed_body": {},
    }
    return {
        "operation_id": operation_id,
        "domain": "example",
        "resource": resource,
        "action": "list",
        "contract_version": 1,
        "upstream_method": "GET",
        "path_template": f"/report/api/v3/agent/{resource}/",
        "auth_profile": "gravity_authorization",
        "stability": "stable",
        "input_fields": fields,
        "request": request,
        "response_projection": {
            "data_shape": "object" if pagination else "list",
            "data_keys": ["list", "page_info"] if pagination else [],
            "required_data_keys": ["list"] if pagination else [],
            "item_keys": ["id"],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "page_info" if pagination else "none",
            "page_field": "page",
            "page_size_field": "page_size",
            "list_path": "data.list",
            "page_info_path": "data.page_info",
            "total_page_field": "total_page",
            "default_page_size": 2 if pagination else None,
            "max_page_size": 100 if pagination else None,
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "configuration",
            "redact_keys": ["authorization", "token", "cookie"],
        },
        "required_parent": list(required_parent or []),
        "live_probe": {"enabled": True, "input": {}},
    }


class _NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("offline agent-surface test must not use transport")


class GravityInsightAgentSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = GravityInsightClient.from_env()

    def test_error_code_table_is_stable_and_extension_codes_are_accepted(self):
        self.assertEqual(
            {
                "UNKNOWN_OPERATION",
                "INPUT_INVALID",
                "PARENT_REQUIRED",
                "AUTH_MISSING",
                "AUTH_REJECTED",
                "PERMISSION_UNAVAILABLE",
                "RATE_LIMITED",
                "UPSTREAM_UNAVAILABLE",
                "CONTRACT_CHANGED",
                "UNSUPPORTED",
                "NOT_IMPLEMENTED",
                "PAGINATION_LIMIT",
                "EXPORT_TIMEOUT",
                "LOCAL_IO_ERROR",
            },
            {item.value for item in ErrorCode},
        )
        extension = ErrorDetail.create(
            "BLOB_CHECKSUM_MISMATCH",
            "downloaded bytes do not match the declared digest",
            next_action="Retry the same ranged download once.",
        )
        self.assertEqual("BLOB_CHECKSUM_MISMATCH", extension.code)
        self.assertEqual("local", extension.category)

    def test_operation_search_is_semantic_bounded_and_continuable(self):
        semantic = self.client.search_operations("用户分群", limit=3)
        self.assertLessEqual(semantic["count"], 3)
        self.assertTrue(
            any("segment" in item["operation_id"] for item in semantic["operations"])
        )

        first = self.client.search_operations("report", limit=2)
        self.assertIsNotNone(first["continuation_token"])
        second = self.client.search_operations(
            "report", limit=2, continuation=first["continuation_token"]
        )
        first_ids = {item["operation_id"] for item in first["operations"]}
        second_ids = {item["operation_id"] for item in second["operations"]}
        self.assertFalse(first_ids & second_ids)

        irrelevant = self.client.search_operations(
            "zzzz-no-such-capability-987654", limit=3
        )
        self.assertEqual(0, irrelevant["count"])
        self.assertEqual([], irrelevant["operations"])

    def test_describe_includes_source_contract_health_and_parent_trace(self):
        described = self.client.describe("analysis.dashboard.members.list")
        self.assertEqual("read", described["effect"])
        self.assertIn("input_schema", described)
        self.assertIn("response_projection", described)
        self.assertIn("pagination", described)
        self.assertIn("classification", described["privacy"])
        self.assertIn(described["health"]["status"], {
            "stable", "suspect", "upstream_changed", "blocked"
        })
        self.assertTrue(described["provenance"]["source_files"])
        self.assertEqual(
            {
                "operation_id": "analysis.dashboard.detail",
                "output_path": "data.id",
                "selection": "unique",
                "target_input": "dashboard_id",
            },
            described["required_parent"][0],
        )

    def test_contract_example_and_parent_trace_fill_rates_are_locked(self):
        operation_root = (
            ROOT / "src" / "gravity_sdk" / "contracts" / "operations"
        )
        examples_complete = 0
        examples_unknown = 0
        parents_complete = 0
        parents_unknown = 0
        for path in operation_root.glob("*.json"):
            operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
            if operation["stability"] == "stable":
                if operation["examples"]:
                    examples_complete += 1
                    spec = self.client._registry.get(operation["operation_id"])
                    for example in operation["examples"]:
                        spec.validate_inputs(example["inputs"])
                else:
                    examples_unknown += 1
            described = self.client.describe(operation["operation_id"])
            for parent in described["required_parent"]:
                if all(
                    parent.get(name) is not None
                    for name in ("output_path", "selection", "target_input")
                ):
                    parents_complete += 1
                else:
                    parents_unknown += 1
        # gi-reprobe 后为 (54, 81)；report.company_amount.query 与前趟两个
        # 成功 probe 可重放输入共增加三个完整 example。cid 复评又解锁
        # promotion.bytedance.app.list，随后隐私复评解锁三条成功 probe，
        # stable 总数随后增加两条巨量标题素材、一条腾讯广告组配置，
        # 三条 AI 托管/数据表配置读取、两条模板/自定义人群读取，以及一条
        # 巨量素材定向包读取、两条报表标签配置读取和一条小时聚合对比均带
        # example；两条标题素材包依赖运行时选择 app_id，不伪造可执行示例；
        # 素材审核用户列表无需输入，晋升后再增加一个完整 example；素材
        # 相册列表依赖运行时从递归父级树选取 album_id，不伪造静态示例；
        # 巨量广告主账户列表无需业务输入，晋升后再增加一个完整 example；
        # 巨量图片素材列表依赖调用方选择 advertiser_id，不伪造静态示例；
        # 巨量账户主体选择器无需输入，晋升后再增加一个完整 example；
        # 巨量项目列表依赖调用方选择 advertiser_id，不伪造静态示例；
        # 项目素材列表依赖同一项目行的两个 ID，也不伪造静态示例。
        # 这条断言锁的是「填充率不许退化」——examples_complete 只许涨不许跌，
        # 新增 stable 带来的 unknown 增长必须显式在此登记，不能被平均掉。
        # 广告素材表现读取依赖同一广告行的两个 ID，也不伪造静态示例；
        # 广告主表现首屏只需日期窗口，晋升后增加一个完整 example。
        # 公司容量读取无需业务输入，晋升后再增加一个完整 example。
        # 腾讯账户主体选择器无需输入，晋升后再增加一个完整 example。
        # 快手账户主体选择器只有已验证布尔默认值，再增加一个完整 example。
        # AI 托管详情依赖运行时从规则列表选择 ai_id，不伪造静态示例。
        # 实时事件配置依赖运行时从应用列表选择 app_id，同样不伪造示例。
        # AI 托管指标字典依赖规则列表中的 media_type，也不伪造示例。
        # 权限菜单读取由 SDK 固定产品常量，无需业务输入，再增加一个完整 example。
        # 角色列表仅需分页默认值并固定关闭菜单展开，再增加一个完整 example。
        # 角色模板列表有已验证分页默认值，再增加一个完整 example。
        # 容量历史依赖当前租户的公司容量父级，不伪造静态示例。
        # 角色详情依赖运行时从角色列表选取 role_id，同样不伪造静态示例。
        self.assertEqual((83, 93), (examples_complete, examples_unknown))
        # 本趟按父 response projection 与调用方选择语义补全 9 条边；剩余
        # 16 条涉及 runtime-v1 target 投影、递归、同一行关联或嵌套输入变换。
        # 素材相册列表再补一条递归父级边，公开 probe 会按目标字符串契约转换；
        # 巨量图片素材列表与巨量项目列表各补一条账户 advertiser_id 的
        # 完整父级边；项目素材列表再补两条项目筛选器父级边，巨量广告
        # 选择器再补一条账户父级边。
        # 广告素材表现读取再补两条同源广告筛选器父级边；AI 托管详情
        # 再补一条规则列表 id 父级边；实时事件配置再补一条应用父级边；
        # AI 托管指标字典再补一条规则媒体类型父级边。
        # 容量历史再补一条当前公司 ID 父级边。
        # 角色详情再补一条角色列表 ID 父级边。
        self.assertEqual((62, 16), (parents_complete, parents_unknown))

        transformed = self.client.describe("analysis.event.query")["required_parent"][0]
        self.assertEqual("data.list[].name", transformed["output_path"])
        self.assertIsNone(transformed["selection"])
        self.assertEqual("query_item_list", transformed["target_input"])

    def test_validate_returns_all_three_states_without_transport(self):
        valid = self.client.validate(
            "app.list", {"page": 1, "page_size": 20}, render_wire=True
        )
        self.assertEqual("valid_offline", valid["status"])
        self.assertFalse(valid["network_called"])
        self.assertEqual("GET", valid["wire"]["method"])
        self.assertEqual(20, valid["wire"]["query"]["page_size"])

        invalid = self.client.validate("app.list", {"page": 0, "page_size": 20})
        self.assertEqual("invalid", invalid["status"])
        self.assertEqual("INPUT_INVALID", invalid["error"]["code"])

        live = self.client.validate(
            "analysis.user_property_value.list",
            {"app_id": "1", "property_name": "level"},
        )
        self.assertEqual("needs_live_metadata", live["status"])
        self.assertFalse(live["network_called"])
        self.assertIn(
            "analysis.user_property.list", live["live_metadata_dependencies"]
        )

    def test_validate_supports_export_input_and_export_specific_recovery(self):
        operation_id = "export.material.report.start"
        example = json.loads(
            json.dumps(
                self.client.export_describe(operation_id)["examples"][0]["input"]
            )
        )
        example["date_list"] = ["2026-08-08", "2026-08-08"]
        for item in example["filters"]:
            if item["field"] == "app_id":
                item["values"] = ["fixture-app-id"]

        valid = self.client.validate(operation_id, example, render_wire=True)
        self.assertEqual("valid_offline", valid["status"])
        self.assertFalse(valid["network_called"])
        self.assertEqual("POST", valid["wire"]["method"])
        self.assertEqual(example, valid["wire"]["body"])
        self.assertEqual(
            "validated_by_export_start",
            valid["validation_scope"]["columns"],
        )

        invalid_input = dict(example)
        invalid_input.pop("filters")
        invalid = self.client.validate(operation_id, invalid_input)
        self.assertEqual("invalid", invalid["status"])
        self.assertEqual("INPUT_INVALID", invalid["error"]["code"])
        self.assertEqual("filters", invalid["error"]["field"])
        self.assertIn("export describe", invalid["error"]["next_action"])

        unknown = self.client.validate("export.unknown.start", {})
        self.assertEqual("invalid", unknown["status"])
        self.assertEqual("UNKNOWN_OPERATION", unknown["error"]["code"])
        self.assertIn("export list-capabilities", unknown["error"]["next_action"])

    def test_parent_and_batch_failures_use_the_same_error_detail(self):
        parent = _operation("example.parent.list", "parent")
        child = _operation(
            "example.child.list",
            "child",
            input_fields={"parent_id": {"type": "string"}},
            required_parent=[
                {"operation_id": "example.parent.list", "input_field": "parent_id"}
            ],
        )
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [parent, child]},
            transport=_NeverTransport(),
        )
        envelope = client.read("example.child.list", {})
        self.assertFalse(envelope["ok"])
        self.assertEqual("PARENT_REQUIRED", envelope["error"]["code"])
        self.assertIn("example.parent.list", envelope["error"]["next_action"])

        batch = client.batch([{"operation_id": "example.unknown.list", "inputs": {}}])
        self.assertFalse(batch[0]["ok"])
        self.assertEqual("UNKNOWN_OPERATION", batch[0]["error"]["code"])
        self.assertIn("operations search", batch[0]["error"]["next_action"])

    def test_read_limited_stops_at_five_or_two_hundred_with_continuation(self):
        operation = _operation(
            "example.items.list",
            "items",
            input_fields={
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 2},
            },
            pagination=True,
        )
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [operation]},
            transport=_NeverTransport(),
        )

        def page_result(_operation_id, inputs):
            page = inputs.get("page", 1)
            rows = ({"id": page * 10 + 1}, {"id": page * 10 + 2})
            page_info = {"page": page, "page_size": 2, "total_page": 3}
            return ReadResult(
                "gravity-insight.read.v1",
                "success",
                {},
                "2026-08-09T00:00:00Z",
                "a" * 64,
                "1",
                dict(inputs),
                {"number": page, "size": 2, "item_count": 2, "total_items": 6},
                {"list": list(rows), "page_info": page_info},
                "example.items.list",
                items=rows,
                page_info=page_info,
            )

        with patch.object(client, "_execute_result", side_effect=page_result):
            result = client.read_limited(
                "example.items.list", {}, max_pages=2, max_items=4
            )
        self.assertTrue(result["truncated"])
        self.assertEqual(4, result["page"]["item_count"])
        self.assertEqual(3, result["next_page_input"]["page"])
        self.assertEqual(2, result["total"]["returned_pages"])
        self.assertFalse(result["safety_limits"]["page_size_clamped"])

    def test_cli_all_pages_guard_and_exit_codes_are_stable(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli.main(["read", "app.list", "--all-pages"])
        payload = json.loads(stderr.getvalue())
        self.assertEqual(2, code)
        self.assertEqual("INPUT_INVALID", payload["error"]["code"])

        with patch("gravity_sdk.cli.run", side_effect=UpstreamError("down")):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(3, cli.main(["operations", "list"]))
        with patch("gravity_sdk.cli.run", side_effect=OSError("disk")):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(4, cli.main(["operations", "list"]))
        self.assertEqual(2, exit_code_for_error(InputValidationError("bad")))

    def test_stdout_summarizes_large_values_and_caps_lists(self):
        result = cli._safe_stdout_result(
            {
                "operation_id": "example.items.list",
                "data": {
                    "list": list(range(500)),
                    "config": {"payload": "x" * 10_000},
                },
            }
        )
        self.assertTrue(result["truncated"])
        self.assertEqual(200, len(result["data"]["list"]))
        self.assertIn("reference", result["data"]["config"])
        self.assertIn("summarized_fields", result)

    def test_auth_status_distinguishes_token_credentials_and_missing(self):
        now = datetime.now(timezone.utc)

        def status_for(config):
            class Config:
                @classmethod
                def from_env(cls, _path):
                    return config

            with patch.object(runtime, "_sdk_module", return_value=SimpleNamespace(
                CredentialConfig=Config
            )):
                return runtime.credential_status()

        token = status_for(SimpleNamespace(
            token="secret", expires_at=now + timedelta(hours=1), updated_at=now,
            username=None, password=None
        ))
        credentials = status_for(SimpleNamespace(
            token=None, expires_at=None, updated_at=None,
            username="analyst", password="secret"
        ))
        missing = status_for(SimpleNamespace(
            token=None, expires_at=None, updated_at=None,
            username=None, password=None
        ))
        self.assertEqual("valid_token", token["status"])
        self.assertEqual("credentials_available", credentials["status"])
        self.assertTrue(credentials["can_exchange_credentials"])
        self.assertEqual("missing", missing["status"])
        self.assertFalse(missing["can_authenticate"])


if __name__ == "__main__":
    unittest.main()
