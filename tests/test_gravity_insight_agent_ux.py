from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli, runtime
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_analysis_task import analysis_task_cards
from gravity_sdk.agent_batch import capabilities_many, iter_ndjson_records
from gravity_sdk.agent_batch_sources import AgentSourceSnapshot
from gravity_sdk.agent_client import DeferredAgentClient
from gravity_sdk.agent_handoff import apply_workspace_prefix
from gravity_sdk.agent_sources import OperationDiscovery, discover_operation_cards
from gravity_sdk.workspace import load_workspace

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.credentials import CredentialConfig
    from gravity_sdk.errors import (
        InputValidationError,
        OperationNotImplementedError,
        UpstreamError,
        error_detail_from_exception,
    )
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.credentials import CredentialConfig
    from gravity_sdk.errors import (
        InputValidationError,
        OperationNotImplementedError,
        UpstreamError,
        error_detail_from_exception,
    )


NOW = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)


def _jwt(expires_at: datetime) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(expires_at.timestamp())}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


def _paged_operation() -> dict[str, object]:
    return {
        "operation_id": "example.items.list",
        "domain": "example",
        "resource": "items",
        "action": "list",
        "contract_version": 1,
        "upstream_method": "GET",
        "path_template": "/report/api/v3/example/items/",
        "auth_profile": "gravity_authorization",
        "stability": "stable",
        "input_fields": {
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 20},
        },
        "request": {
            "path_fields": [],
            "query_fields": ["page", "page_size"],
            "body_fields": [],
            "defaults": {"page": 1, "page_size": 20},
            "fixed_query": {},
            "fixed_body": {},
        },
        "response_projection": {
            "data_shape": "object",
            "data_keys": ["list", "page_info"],
            "required_data_keys": ["list"],
            "item_keys": ["id"],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "page_info",
            "page_field": "page",
            "page_size_field": "page_size",
            "list_path": "data.list",
            "page_info_path": "data.page_info",
            "total_page_field": "total_page",
            "default_page_size": 20,
            "max_page_size": 100,
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "configuration",
            "redact_keys": ["authorization", "token", "cookie"],
        },
        "required_parent": [],
        "live_probe": {"enabled": True, "input": {}},
    }


class _NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("caller validation must not invoke transport")


class CredentialUxTests(unittest.TestCase):
    def test_newer_managed_file_beats_stale_ambient_process_token(self) -> None:
        stale_token = _jwt(NOW - timedelta(hours=1))
        fresh_token = _jwt(NOW + timedelta(days=7))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text(
                "\n".join(
                    (
                        "GRAVITY_USERNAME=analyst@example.invalid",
                        "GRAVITY_PASSWORD=secret",
                        f"GRAVITY_AUTH_TOKEN={fresh_token}",
                        "GRAVITY_AUTH_UPDATED_AT=2026-08-09T11:00:00+08:00",
                        "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI=2026-08-16T11:00:00+08:00",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"GRAVITY_AUTH_TOKEN": stale_token},
                clear=True,
            ):
                config = CredentialConfig.from_env(path)

            self.assertEqual(fresh_token, config.token)
            self.assertEqual("credential_file", config.token_source)
            self.assertGreater(config.expires_at, NOW)

            explicit = CredentialConfig.from_env(
                path, environ={"GRAVITY_AUTH_TOKEN": stale_token}
            )
            self.assertEqual(stale_token, explicit.token)
            self.assertEqual("process_environment", explicit.token_source)

    def test_auth_status_identifies_account_without_disclosing_username(self) -> None:
        config = SimpleNamespace(
            token="secret",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            updated_at=NOW,
            username="analyst@example.invalid",
            password="secret",
            token_source="credential_file",
        )

        class Config:
            @classmethod
            def from_env(cls, _path):
                return config

        with patch.object(
            runtime,
            "_sdk_module",
            return_value=SimpleNamespace(CredentialConfig=Config),
        ):
            status = runtime.credential_status()

        self.assertEqual("a***@example.invalid", status["account_hint"])
        self.assertNotIn("analyst@example.invalid", json.dumps(status))
        self.assertEqual("credential_file", status["token_source"])
        self.assertTrue(status["token_valid"])
        self.assertNotIn("auth refresh", status["next_action"])

    def test_refresh_returns_the_post_refresh_auth_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refreshed = {
                "auth_state": "valid_token",
                "token_valid": True,
                "account_hint": "a***@example.invalid",
            }

            class Provider:
                def __init__(self, path, *, environ):
                    self.path = path
                    self.environ = environ

                def refresh(self):
                    return SimpleNamespace(token="internal")

            with (
                patch.object(runtime, "REPO_ROOT", root),
                patch.object(
                    runtime,
                    "_sdk_module",
                    return_value=SimpleNamespace(CredentialProvider=Provider),
                ),
                patch.object(runtime, "credential_status", return_value=refreshed),
            ):
                result = runtime.refresh_credentials()

        self.assertEqual("success", result["status"])
        self.assertEqual("refreshed_internal_session", result["refresh"]["action"])
        self.assertEqual(refreshed, result["auth"])


class ErrorAndHealthUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [_paged_operation()]},
            transport=_NeverTransport(),
        )

    def test_input_invalid_has_field_and_does_not_change_health(self) -> None:
        before = self.client.describe("example.items.list")["health"]

        with self.assertRaises(InputValidationError) as raised:
            self.client.read(
                "example.items.list", {"page": "1", "page_size": 1}
            )

        detail = raised.exception.to_error_detail(
            operation_id="example.items.list"
        )
        after = self.client.describe("example.items.list")["health"]
        self.assertEqual("page", detail.field)
        self.assertEqual(before, after)

        validation = self.client.validate(
            "example.items.list", {"page": "1", "page_size": 1}
        )
        self.assertEqual("page", validation["error"]["field"])
        self.assertEqual(before, self.client.describe("example.items.list")["health"])

    def test_cli_exit_codes_match_error_categories(self) -> None:
        cases = (
            (InputValidationError("input 'page' must be integer"), 2, "caller"),
            (UpstreamError("upstream unavailable"), 3, "upstream"),
            (OSError("local disk unavailable"), 4, "local"),
        )
        for error, expected_code, expected_category in cases:
            with self.subTest(category=expected_category):
                stderr = io.StringIO()
                with (
                    patch(
                        "gravity_sdk.cli.dispatch_command",
                        side_effect=error,
                    ),
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = cli.main(["operations", "list"])
                envelope = json.loads(stderr.getvalue())
                self.assertEqual(expected_code, exit_code)
                self.assertEqual(expected_category, envelope["error"]["category"])


class DiscoveryUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()

    def test_default_search_prioritizes_callable_and_only_previews_draft_noise(self) -> None:
        result = self.client.search_operations(
            "当前账号 App", stability=None, limit=10
        )
        operations = result["operations"]
        non_callable = [item for item in operations if not item["executable"]]

        self.assertTrue(operations)
        self.assertEqual("stable", operations[0]["stability"])
        self.assertTrue(operations[0]["executable"])
        self.assertEqual(1, len(non_callable))
        self.assertEqual(
            "callable_stable_first", result["presentation"]["mode"]
        )
        self.assertGreater(result["total"], result["count"])
        self.assertIsNotNone(result["continuation_token"])

    def test_agent_operation_discovery_scans_inventory_once_without_search_pages(self) -> None:
        with (
            patch.object(
                self.client, "operations", wraps=self.client.operations
            ) as inventory,
            patch.object(
                self.client, "search_operations", wraps=self.client.search_operations
            ) as search,
        ):
            discovered = discover_operation_cards(
                self.client,
                "event",
                domain=None,
                platform=None,
            )

        self.assertTrue(discovered.matches)
        inventory.assert_called_once_with(
            domain=None, platform=None, stability="stable"
        )
        search.assert_not_called()

    def test_agent_export_card_is_direct_and_privacy_blocked_routes_stay_hidden(self) -> None:
        operation_id = "export.material.report.start"
        for query in ("export", "导出素材报表", operation_id):
            with self.subTest(query=query):
                result = discover_capabilities(query, client=self.client, limit=1)
                card = result["candidates"][0]
                self.assertEqual(("export", operation_id), (card["kind"], card["selector"]))
                self.assertEqual("export_job_create", card["effect"])
                self.assertTrue(card["currently_callable"])
                self.assertFalse(card["natural_language_auto_execute"])
                self.assertIsNone(card["plan_node"])
                self.assertFalse(card["next"]["ready_without_input"])
                self.assertEqual(
                    ["input", "columns", "idempotency_key", "output"],
                    card["required_inputs"],
                )
                self.assertEqual(
                    ["gravity", "export", "run", operation_id],
                    card["next"]["argv"][:4],
                )
                self.assertIn("allowed_codes", card["columns"])
                self.assertEqual(300, card["timeout"]["default_seconds"])
        for blocked in (
            "export.analysis.segment.result.start",
            "export.analysis.user_event.start",
            "export.task.cancel",
        ):
            result = discover_capabilities(blocked, client=self.client)
            self.assertNotIn(blocked, [card["selector"] for card in result["candidates"]])

    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_agent_batch_snapshots_export_inventory_once(self, _metadata) -> None:
        workspace = SimpleNamespace(recipes={}, products={}, datasources={})
        with (
            patch.object(self.client, "export_capabilities", wraps=self.client.export_capabilities) as listing,
            patch.object(self.client, "export_describe", wraps=self.client.export_describe) as describe,
        ):
            result = capabilities_many(
                [
                    {"id": "english", "query": "export"},
                    {"id": "chinese", "query": "素材报表导出"},
                ],
                client=self.client,
                workspace=workspace,
            )
        cards = [item["result"]["candidates"][0] for item in result["results"]]
        listing.assert_called_once_with()
        describe.assert_called_once_with("export.material.report.start")
        self.assertEqual(["export", "export"], [card["kind"] for card in cards])
        self.assertTrue(all(card["plan_node"] is None for card in cards))

    def test_agent_discovers_registered_composites_with_handoff_templates(self) -> None:
        cases = (
            ("analysis context", "analysis_context", ["app"]),
            (
                "analyze dashboard details members filters",
                "dashboard_snapshot",
                ["app", "ref"],
            ),
            (
                "inspect dashboard members and saved filters",
                "dashboard_snapshot",
                ["app", "ref"],
            ),
            ("can you show me dashboard members and filters", "dashboard_snapshot", ["app", "ref"]),
            ("分析看板详情成员筛选", "dashboard_snapshot", ["app", "ref"]),
            ("请查看看板成员和筛选收藏", "dashboard_snapshot", ["app", "ref"]),
            ("查看一下看板的成员和筛选收藏", "dashboard_snapshot", ["app", "ref"]),
            ("app snapshots", "app_snapshot", ["app"]),
            ("attribution snapshot", "attribution_snapshot", ["app"]),
            ("multi dimensions", "multidim", ["app", "inputs"]),
            ("business pulse", "business_pulse", ["apps", "start", "end"]),
        )
        for query, name, missing in cases:
            with self.subTest(query=query):
                domain = "report" if query == "分析看板详情成员筛选" else None
                result = discover_capabilities(query, client=self.client, domain=domain, limit=1)
                card = result["candidates"][0]
                self.assertEqual(name, card["composite"])
                self.assertEqual("composite", card["plan_node"]["kind"])
                self.assertEqual(missing, card["missing_inputs"])
                if name != "multidim":
                    self.assertEqual(set(missing), set(card["input_template"]))
                else:
                    schema = card["input_schema"]["inputs"]["machine_schema"]
                    self.assertEqual(
                        (False, ["date_list", "time_dims", "metrics_list"]),
                        (schema["additionalProperties"], schema["required"]),
                    )
                    self.assertEqual(
                        ({"app", "inputs", "include_total", "read_all"},
                         {"name", "app", "inputs", "include_total", "read_all"}),
                        (set(card["input_template"]), set(card["plan_node"]["request"])),
                    )
                    self.assertFalse(card["natural_language_auto_execute"])
                if name == "dashboard_snapshot":
                    self.assertEqual((1, 1), (result["count"], result["total"]))
                    self.assertEqual(missing, card["required_inputs"])
                    self.assertEqual(set(missing), set(card["input_schema"]))
                    self.assertEqual(
                        {
                            "name": name,
                            "app": "<app:string|integer>",
                            "ref": "<ref:string|integer>",
                        },
                        card["plan_node"]["request"],
                    )
                    self.assertFalse(card["natural_language_auto_execute"])
        for query in ("run dashboard charts", "replay dashboard charts", "重放看板图表"):
            result = discover_capabilities(query, client=self.client, limit=5)
            self.assertNotIn(
                "dashboard_snapshot", [card.get("composite") for card in result["candidates"]]
            )

    def test_multidim_intent_is_authoritative_but_excludes_adjacent_products(self) -> None:
        for query in ("multidim", "multidimensional report query", "执行多维报表查询"):
            with self.subTest(query=query):
                result = discover_capabilities(query, client=self.client, limit=5)
                self.assertEqual(["multidim"], [c.get("composite") for c in result["candidates"]])
        for query in (
            "multidim template", "multi dimension layout", "多维报表收藏权限",
            "business pulse", "multidim funnel analysis",
        ):
            with self.subTest(query=query):
                result = discover_capabilities(query, client=self.client, limit=5)
                self.assertNotIn("multidim", [c.get("composite") for c in result["candidates"]])

    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_multidim_batch_reuses_one_local_snapshot(self, metadata) -> None:
        with patch.object(
            self.client, "operation_inventory", wraps=self.client.operation_inventory
        ) as operations:
            result = capabilities_many(
                ["multidimensional report query", "执行多维报表查询"],
                client=self.client,
                workspace=SimpleNamespace(recipes={}, products={}, datasources={}),
            )
        operations.assert_not_called()
        metadata.assert_called_once_with("", limit=None, offset=0)
        self.assertEqual([1, 1], [item["result"]["total"] for item in result["results"]])

    def test_agent_table_lineage_is_one_offline_plan_handoff(self) -> None:
        workspace = SimpleNamespace(path=Path("D:/private/workspaces/analyst.toml"))
        for query in (
            "table lineage",
            "table versions",
            "table operation logs",
            "表版本",
            "表变更",
            "数据表的版本",
        ):
            with self.subTest(query=query):
                result = discover_capabilities(
                    query, client=None, workspace=workspace, limit=5
                )
                self.assertEqual((1, 1), (result["total"], result["count"]))
                card = result["candidates"][0]
                self.assertEqual("metadata:table_lineage", card["selector"])
                self.assertEqual("strong", card["match"]["confidence"])
                self.assertEqual([], card["missing_inputs"])
                self.assertIn("query", card["input_template"])
                self.assertIn("next_action", card)
                self.assertEqual(
                    {"query": "", "kind": "table_lineage"},
                    card["plan_node"]["request"],
                )
                self.assertEqual("metadata_search", card["plan_node"]["kind"])
                self.assertFalse(result["network_called"])

        with patch("gravity_sdk.agent_batch_sources.search_metadata") as metadata:
            metadata.return_value = {"results": []}
            batch = capabilities_many(
                [
                    {"id": "versions", "query": "table versions"},
                    {"id": "changes", "query": "表变更"},
                ],
                client=self.client,
                workspace=load_workspace(
                    Path(__file__).resolve().parents[1]
                    / "examples" / "workspace" / "gravity.toml"
                ),
            )
        cards = [item["result"]["candidates"][0] for item in batch["results"]]
        self.assertEqual(["versions", "changes"], [item["question_id"] for item in batch["results"]])
        self.assertEqual(2, len({card["plan_node"]["id"] for card in cards}))
        self.assertNotIn("gravity.toml", json.dumps([card["plan_node"] for card in cards]))

    def test_agent_vocabulary_is_an_offline_typed_plan_handoff(self) -> None:
        from gravity_sdk.find import metadata_capability_cards

        cases = (
            ("physical metric", "metric", "report_metrics", "Revenue", {"metrics_list": ["Revenue"]}),
            ("custom metric", "custom_metric", "custom_metrics", "Profit", {"custom_metrics_list": ["Profit"]}),
            ("metric tag", "metric_tag", "metric_tags", "Growth", None),
            ("metric tag category", "metric_tag_category", "metric_tag_categories", "Acquisition", None),
            ("media enum", "media_enum", "media_enums", "Bytedance", None),
            ("analysis template", "template", "mine_templates", "Daily KPI", None),
        )
        for query, kind, source, name, fragment in cases:
            with self.subTest(kind=kind):
                row = {
                    "kind": kind, "scope": "workspace", "source": source,
                    "operation_id": f"report.multidim.{kind}.list", "name": name,
                    "cname": name, "score": 100, "payload": {"name": name},
                }
                with patch(
                    "gravity_sdk.find.search_metadata", return_value={"results": [row]}
                ) as search:
                    direct, warnings = metadata_capability_cards(query, limit=1)
                self.assertEqual([], warnings)
                self.assertEqual("strong", direct[0]["match"]["confidence"])
                search.assert_called_once_with("", limit=None, offset=0)
                sources = AgentSourceSnapshot(
                    None, (), (), (), (row,), (), (), "0" * 64
                )
                result = discover_capabilities(query, client=None, sources=sources)
                card = result["candidates"][0]
                self.assertEqual((kind, "workspace"), (card["metadata_kind"], card["scope"]))
                self.assertNotIn("app_id", card)
                self.assertEqual("metadata_search", card["plan_node"]["kind"])
                self.assertEqual(name, card["lookup_query"])
                self.assertEqual({"query": name, "kind": kind}, card["plan_node"]["request"])
                self.assertEqual(fragment, card.get("request_fragment"))
                self.assertEqual(
                    ["gravity", "metadata", "vocabulary", name, "--kind", kind],
                    card["next"]["argv"],
                )
                if kind == "template":
                    self.assertTrue(card["catalog_only"])
                    self.assertFalse(card["replay_supported"])

    @patch("gravity_sdk.agent_batch_sources.search_metadata")
    def test_agent_batch_loads_vocabulary_once_and_namespaces_nodes(self, search) -> None:
        search.return_value = {"results": [
            {
                "kind": "metric_tag", "scope": "workspace", "source": "metric_tags",
                "operation_id": "report.multidim.metric_tag.list", "name": "Growth",
                "cname": "Growth", "score": 100, "payload": {"name": "Growth"},
            },
            {
                "kind": "template", "scope": "workspace", "source": "mine_templates",
                "operation_id": "report.multidim.template.mine.list", "name": "Daily KPI",
                "cname": "Daily KPI", "score": 100, "payload": {"name": "Daily KPI"},
            },
        ]}
        builds = 0

        def build_client():
            nonlocal builds
            builds += 1
            return self.client

        batch = capabilities_many(
            [
                {"id": "tags", "query": "metric tags"},
                {"id": "templates", "query": "analysis template"},
            ],
            client=DeferredAgentClient(build_client),
        )
        nodes = [item["result"]["candidates"][0]["plan_node"] for item in batch["results"]]
        search.assert_called_once_with("", limit=None, offset=0)
        self.assertEqual(0, builds)
        self.assertEqual(2, len({node["id"] for node in nodes}))

    def test_agent_exact_selector_and_plural_query_choose_app_list(self) -> None:
        exact = discover_capabilities("app.list", client=self.client, limit=3)
        plural = discover_capabilities(
            "list apps", client=self.client, domain="app", limit=1
        )
        self.assertEqual(["app.list"], [item["selector"] for item in exact["candidates"]])
        self.assertTrue(exact["candidates"][0]["match"]["exact_selector"])
        self.assertEqual("app.list", plural["candidates"][0]["selector"])

    def test_agent_analysis_query_compiler_hands_off_to_spec_schema(self) -> None:
        result = discover_capabilities(
            "analysis query compiler", client=self.client, limit=1
        )
        card = result["candidates"][0]
        self.assertEqual("analysis_query_spec", card["kind"])
        self.assertEqual(["kind", "app", "spec"], card["missing_inputs"])
        self.assertEqual("<plan.json>", card["next"]["argv"][-1])
        self.assertEqual("--spec-schema", card["next"]["schema_argv"][-1])
        self.assertTrue(card["plan_executable"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertEqual(
            {"name": "analysis_query"}, card["plan_node"]["request"]
        )
        self.assertEqual("composite", card["plan_node"]["kind"])
        self.assertIn("funnel_window", card["input_schema"]["spec"]["definitions"])

    def test_agent_prefers_one_kind_specific_analysis_spec_card(self) -> None:
        cases = (
            ("event analysis", "event"),
            ("analysis.query.spec:event", "event"),
            ("事件分析", "event"),
            ("funnel analysis", "funnel"),
            ("转化漏斗", "funnel"),
            ("property analysis", "property"),
            ("用户属性分析", "property"),
            ("retention analysis", "retention"),
            ("留存分析", "retention"),
            ("scatter plot analysis", "scatter"),
            ("散点图", "scatter"),
        )
        for query, kind in cases:
            with self.subTest(query=query):
                result = discover_capabilities(
                    query, client=self.client, domain="analysis", limit=2
                )
                card = result["candidates"][0]
                self.assertEqual("analysis_query_spec", card["kind"])
                self.assertEqual(kind, card["analysis_kind"])
                self.assertEqual("strong", card["match"]["confidence"])
                self.assertEqual(["app", "spec"], card["missing_inputs"])
                self.assertEqual(kind, card["input_template"]["kind"])
                self.assertTrue(card["input_template"]["spec"])
                spec_contract = card["input_schema"]["spec"]
                self.assertEqual(kind, spec_contract["selected_kind"])
                self.assertEqual([kind], list(spec_contract["variants_by_kind"]))
                self.assertEqual(
                    {"name": "analysis_query", "kind": kind},
                    card["plan_node"]["request"],
                )
                self.assertEqual("composite", card["plan_node"]["kind"])

    def test_agent_segment_rule_evaluation_is_one_explicit_plan_handoff(self) -> None:
        cases = (
            "segment rule population estimate",
            "evaluate audience rule percentage",
            "评估人群规则命中人数",
            "受众规则占比评估",
            "analysis.segment.rule.spec",
        )
        for query in cases:
            with self.subTest(query=query):
                result = discover_capabilities(
                    query, client=None, domain="analysis", limit=3
                )
                self.assertEqual((1, 1), (result["count"], result["total"]))
                card = result["candidates"][0]
                self.assertEqual("segment_rule_spec", card["kind"])
                self.assertEqual(["app", "spec"], card["missing_inputs"])
                self.assertFalse(card["natural_language_auto_execute"])
                request = card["plan_node"]["request"]
                self.assertEqual("segment_evaluate", request["name"])
                self.assertEqual(card["input_template"]["app"], request["app"])
                self.assertEqual(card["input_template"]["spec"], request["spec"])
                self.assertEqual("composite", card["plan_node"]["kind"])
                spec = card["input_schema"]["spec"]
                self.assertEqual(
                    "gravity-insight.segment-rule-spec.v1",
                    spec["schema_version"],
                )
                self.assertIn("event_rule", spec["definitions"])
                self.assertIn("property_rules", spec["schema"]["properties"])
                self.assertNotIn("FE_CONFIG", json.dumps(card))
        class NoOperationClient:
            def operation_inventory(self, **_options):
                self.fail("segment compiler discovery must not scan operations")

        batch = capabilities_many(
            [{"id": "segment", "query": cases[0], "domain": "analysis"}],
            client=NoOperationClient(),
        )
        self.assertEqual(
            "segment_rule_spec",
            batch["results"][0]["result"]["candidates"][0]["kind"],
        )

    def test_agent_segment_rule_intent_does_not_capture_related_products(self) -> None:
        for query in (
            "segment",
            "segment members",
            "segment history",
            "audience detail",
            "用户分群",
            "人群成员详情",
            "人群导出",
        ):
            with self.subTest(query=query):
                result = discover_capabilities(query, client=self.client, limit=5)
                self.assertNotIn(
                    "segment_rule_spec",
                    [card["kind"] for card in result["candidates"]],
                )

    def test_agent_analysis_task_and_user_journey_are_single_safe_handoffs(self) -> None:
        class NoOperationClient:
            def operation_inventory(self, **_options):
                raise AssertionError("local Agent handoffs must not scan operations")

        with patch(
            "gravity_sdk.agent_batch_sources.search_metadata",
            side_effect=OSError("catalog unavailable"),
        ):
            task = capabilities_many(
                [{"id": "conversion", "query": "分析过去7天成交用户数和转化率"}],
                client=NoOperationClient(),
            )["results"][0]["result"]
        self.assertEqual((1, 1), (task["count"], task["total"]))
        handoff = task["candidates"][0]
        self.assertEqual("analysis_task", handoff["kind"])
        self.assertIsNone(handoff["plan_node"])
        self.assertTrue(handoff["catalog_missing"])
        self.assertEqual(
            ["gravity", "metadata", "sync", "--all-apps"],
            handoff["catalog_sync_argv"],
        )
        metadata_card = {
            "kind": "metadata",
            "metadata_kind": "event",
            "name": "Purchase",
            "display_name": "购买",
            "operation_id": "analysis.event.list",
            "match": {"confidence": "strong"},
        }
        with patch(
            "gravity_sdk.agent.catalog_cards",
            return_value=([metadata_card], 1, [], "0" * 64),
        ):
            available = discover_capabilities(
                "analyze purchase trends", client=None
            )["candidates"][0]
        self.assertFalse(available["catalog_missing"])
        self.assertEqual(
            "Purchase", available["metadata_candidates"]["events"][0]["name"]
        )

        journey = discover_capabilities(
            "single user events and postbacks", client=None, domain="analysis"
        )
        self.assertEqual((1, 1), (journey["count"], journey["total"]))
        card = journey["candidates"][0]
        self.assertEqual("composite:user_journey", card["selector"])
        self.assertTrue(card["input_schema"]["client_id"]["sensitive"])
        self.assertEqual({"name": "user_journey"}, card["plan_node"]["request"])
        self.assertNotIn("client_id", card["plan_node"]["request"])

    @patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={"results": []})
    def test_agent_batch_namespaces_analysis_spec_plan_nodes(self, _metadata) -> None:
        result = capabilities_many(
            [
                {"id": "acquisition", "query": "funnel analysis", "domain": "analysis"},
                {"id": "cohort", "query": "留存分析", "domain": "analysis"},
            ],
            client=self.client,
        )
        self.assertEqual(
            ["acquisition", "cohort"],
            [item["question_id"] for item in result["results"]],
        )
        cards = [item["result"]["candidates"][0] for item in result["results"]]
        self.assertEqual(2, len({card["plan_node"]["id"] for card in cards}))
        self.assertEqual(
            ["funnel", "retention"],
            [card["plan_node"]["request"]["kind"] for card in cards],
        )
        for card in cards:
            spec = card["input_schema"]["spec"]
            self.assertEqual(card["spec_schema_version"], spec["schema_version"])
            self.assertNotIn("definitions", spec)
            self.assertNotIn("variants_by_kind", spec)
            self.assertEqual(
                card["analysis_kind"], spec["contract_ref"]["selected_kind"]
            )
            self.assertEqual(
                card["next"]["schema_argv"],
                spec["contract_ref"]["schema_argv"],
            )
        handoff = result["analysis_query_batch"]
        self.assertEqual(
            "gravity.analysis-query-batch.v1", handoff["schema_version"]
        )
        self.assertFalse(handoff["natural_language_auto_execute"])
        self.assertEqual(
            ["acquisition", "cohort"],
            [query["id"] for query in handoff["queries"]],
        )
        self.assertEqual(
            ["funnel", "retention"],
            [query["kind"] for query in handoff["queries"]],
        )
        self.assertEqual("batch", handoff["command"][3])

    @patch("gravity_sdk.agent_batch_sources.search_metadata")
    def test_agent_batch_namespaces_plan_nodes_and_exposes_ndjson_rows(self, metadata) -> None:
        metadata.return_value = {"results": [{
            "kind": "metric", "scope": "workspace", "source": "report_metrics",
            "operation_id": "report.multidim.metric.list", "name": "Revenue",
            "cname": "Revenue", "score": 100, "payload": {"name": "Revenue"},
        }]}
        builds = 0

        def build_client():
            nonlocal builds
            builds += 1
            return self.client

        result = capabilities_many(
            [
                {"id": "metric", "query": "Revenue"},
                {"id": "events", "query": "analysis.event.list"},
            ],
            client=DeferredAgentClient(build_client),
        )
        cards = [item["result"]["candidates"][0] for item in result["results"]]
        self.assertEqual(2, len({card["plan_node"]["id"] for card in cards}))
        self.assertEqual(1, builds)
        self.assertEqual([], cards[0]["missing_inputs"])
        self.assertEqual(["app_id"], cards[1]["missing_inputs"])
        rows = list(iter_ndjson_records(result))
        self.assertEqual(3, len(rows))
        self.assertEqual("metric", rows[0]["question_id"])
        self.assertEqual(2, rows[-1]["_gravity_agent_batch"]["rows_written"])

    def test_agent_protocol_and_discovery_are_bounded_offline_and_executable(self) -> None:
        protocol = cli.run_agent_command(
            SimpleNamespace(
                query=None, domain=None, platform=None, limit=3, continuation=None
            ),
            self.client,
        )
        self.assertEqual("gravity.agent.v1", protocol["schema_version"])
        self.assertEqual("protocol", protocol["mode"])
        self.assertFalse(protocol["network_called"])
        self.assertIn("--concurrency", protocol["execution"]["input_forms"])
        self.assertIn("--concurrency", protocol["execution"]["large_result_argv_suffix"])
        self.assertEqual("gravity", protocol["workflow"][0]["argv"][0])
        self.assertEqual({"0", "2", "3", "4"}, set(protocol["exit_codes"]))

        discovered = cli.run_agent_command(
            SimpleNamespace(
                query="retention",
                domain=None,
                platform=None,
                limit=2,
                continuation=None,
            ),
            self.client,
        )
        self.assertEqual("discover_and_describe", discovered["mode"])
        self.assertLessEqual(discovered["count"], 2)
        self.assertTrue(discovered["candidates"])
        candidate = discovered["candidates"][0]
        self.assertEqual("gravity", candidate["next"]["argv"][0])
        self.assertEqual("run", candidate["next"]["argv"][1])
        self.assertIn("input_schema", candidate)
        self.assertNotIn("response_projection", candidate)

    def test_agent_prefers_a_matching_workspace_recipe_in_the_same_call(self) -> None:
        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        with patch("gravity_sdk.agent_sources.load_workspace", return_value=workspace):
            result = cli.run_agent_command(
                SimpleNamespace(
                    query="retention",
                    domain=None,
                    platform=None,
                    limit=2,
                    continuation=None,
                ),
                self.client,
            )

        self.assertLessEqual(result["count"], 2)
        self.assertEqual("recipe", result["candidates"][0]["kind"])
        self.assertEqual("@demo-retention", result["candidates"][0]["selector"])
        self.assertEqual("gravity", result["candidates"][0]["next"]["argv"][0])

    @patch("gravity_sdk.agent_batch_sources.search_metadata")
    def test_agent_workspace_is_preserved_in_single_and_batch_handoffs(self, metadata) -> None:
        metadata.return_value = {"results": []}
        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        prefix = ["gravity", "--workspace", str(workspace.path)]
        single = discover_capabilities(
            "demo-retention", client=self.client, workspace=workspace, limit=1
        )
        recipe = single["candidates"][0]
        self.assertEqual(prefix, recipe["next"]["argv"][:3])
        self.assertEqual(1, recipe["next"]["argv"].count("--workspace"))
        self.assertEqual(prefix, single["execution"]["argv"][:3])
        self.assertTrue(all(item["argv"][:3] == prefix for item in single["fallbacks"]))

        batch = capabilities_many(
            [{"id": "context", "query": "analysis context"}],
            client=self.client,
            workspace=workspace,
        )
        composite = batch["results"][0]["result"]["candidates"][0]
        self.assertEqual(prefix, composite["next"]["argv"][:3])
        task = capabilities_many(
            [{"id": "kpi", "query": "analyze weekly purchase count"}],
            client=self.client,
            workspace=workspace,
        )["results"][0]["result"]["candidates"][0]
        self.assertFalse(task["catalog_missing"])
        self.assertEqual(prefix, task["next"]["argv"][:3])
        self.assertEqual(prefix, task["next"]["schema_argv"][:3])
        missing = apply_workspace_prefix(
            analysis_task_cards("analyze weekly purchase count", metadata_rows=None)[0],
            workspace.path,
        )
        self.assertEqual(prefix, missing["catalog_sync_argv"][:3])
        self.assertEqual(prefix, missing["catalog"]["next"]["argv"][:3])
        rebound = apply_workspace_prefix(missing, workspace.path)
        self.assertEqual(1, rebound["catalog_sync_argv"].count("--workspace"))

    def test_agent_returns_matching_workspace_sql_product_in_the_same_call(self) -> None:
        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        with (
            patch("gravity_sdk.agent_sources.load_workspace", return_value=workspace),
            patch(
                "gravity_sdk.agent_sources.metadata_capability_cards",
                return_value=([], []),
            ),
        ):
            result = cli.run_agent_command(
                SimpleNamespace(
                    query="daily event summary",
                    domain=None,
                    platform=None,
                    limit=3,
                    continuation=None,
                ),
                self.client,
            )

        product = result["candidates"][0]
        self.assertEqual("sql_product", product["kind"])
        self.assertEqual("sql:daily-event-summary", product["selector"])
        self.assertEqual("strong", product["match"]["confidence"])
        self.assertNotIn("sql", product)
        self.assertEqual(
            "daily event summary", result["fallbacks"][0]["argv"][-1]
        )

        with (
            patch("gravity_sdk.agent_sources.load_workspace", return_value=workspace),
            patch(
                "gravity_sdk.agent_sources.metadata_capability_cards",
                return_value=([], []),
            ),
        ):
            insight_first = cli.run_agent_command(
                SimpleNamespace(
                    query="event",
                    domain=None,
                    platform=None,
                    limit=3,
                    continuation=None,
                ),
                self.client,
            )
        self.assertEqual("operation", insight_first["candidates"][0]["kind"])
        self.assertGreater(insight_first["total"], insight_first["count"])
        self.assertIsNotNone(insight_first["continuation_token"])

    def test_agent_total_is_independent_of_limit_for_one_strong_sql_match(self) -> None:
        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        results = []
        with (
            patch("gravity_sdk.agent_sources.load_workspace", return_value=workspace),
            patch(
                "gravity_sdk.agent_sources.metadata_capability_cards",
                return_value=([], []),
            ),
        ):
            for limit in (1, 3):
                results.append(
                    cli.run_agent_command(
                        SimpleNamespace(
                            query="daily event summary",
                            domain=None,
                            platform=None,
                            limit=limit,
                            continuation=None,
                        ),
                        self.client,
                    )
                )

        self.assertEqual([1, 1], [result["total"] for result in results])
        self.assertEqual([1, 1], [result["count"] for result in results])
        self.assertTrue(all(result["continuation_token"] is None for result in results))

    def test_agent_pages_every_catalog_in_priority_order_without_duplicates(self) -> None:
        catalog = [
            {"kind": "recipe", "selector": "@recipe"},
            {"kind": "sql_product", "selector": "sql:product"},
            {"kind": "metadata", "selector": "metadata:event:1"},
        ]
        operations = OperationDiscovery(
            matches=[
                {
                    "operation_id": "app.list",
                    "agent_match": {
                        "confidence": "strong",
                        "coverage": 1.0,
                        "matched_terms": ["app"],
                        "missing_terms": [],
                        "score": 100,
                    },
                }
            ],
            weak=[],
        )
        selectors: list[str] = []
        totals: list[int] = []
        token = None
        with (
            patch(
                "gravity_sdk.agent.catalog_cards",
                return_value=(catalog, len(catalog), [], "0" * 64),
            ),
            patch(
                "gravity_sdk.agent.discover_operation_cards",
                return_value=operations,
            ),
        ):
            while True:
                result = cli.run_agent_command(
                    SimpleNamespace(
                        query="app",
                        domain=None,
                        platform=None,
                        limit=1,
                        continuation=token,
                    ),
                    self.client,
                )
                totals.append(result["total"])
                self.assertEqual(1, result["count"])
                selectors.append(result["candidates"][0]["selector"])
                token = result["continuation_token"]
                if token is None:
                    break

        self.assertEqual([5, 5, 5, 5, 5], totals)
        self.assertEqual(
            [
                "@recipe",
                "app.list",
                "sql:product",
                "metadata:event:1",
                "composite:app_snapshot",
            ],
            selectors,
        )
        self.assertEqual(len(selectors), len(set(selectors)))

    def test_agent_weak_only_result_has_zero_total_and_no_false_page(self) -> None:
        weak = {"operation_id": "analysis.event.list", "score": 1}
        with (
            patch("gravity_sdk.agent.catalog_cards", return_value=([], 0, [], "0" * 64)),
            patch(
                "gravity_sdk.agent.discover_operation_cards",
                return_value=OperationDiscovery(matches=[], weak=[weak]),
            ),
        ):
            result = cli.run_agent_command(
                SimpleNamespace(
                    query="missing capability",
                    domain=None,
                    platform=None,
                    limit=1,
                    continuation=None,
                ),
                self.client,
            )

        self.assertEqual("capability_gap", result["status"])
        self.assertEqual(0, result["total"])
        self.assertEqual(0, result["count"])
        self.assertIsNone(result["continuation_token"])

    def test_agent_does_not_promote_weak_partial_matches(self) -> None:
        with patch(
            "gravity_sdk.agent.catalog_cards", return_value=([], 0, [], "0" * 64)
        ):
            result = cli.run_agent_command(
                SimpleNamespace(
                    query="push campaign nonexistent capability",
                    domain=None,
                    platform=None,
                    limit=3,
                    continuation=None,
                ),
                self.client,
            )

        self.assertEqual("capability_gap", result["status"])
        self.assertEqual([], result["candidates"])
        gap = result["capability_gaps"][0]
        self.assertTrue(gap["weak_matches"])
        self.assertEqual(
            "partial", gap["weak_matches"][0]["match"]["confidence"]
        )
        self.assertNotIn("next", gap)

    def test_agent_reports_exact_draft_blockers_without_execution_argv(self) -> None:
        operation_id = "promotion.alipay.campaign.list"
        with patch(
            "gravity_sdk.agent.catalog_cards", return_value=([], 0, [], "0" * 64)
        ):
            result = cli.run_agent_command(
                SimpleNamespace(
                    query=operation_id,
                    domain=None,
                    platform=None,
                    limit=3,
                    continuation=None,
                ),
                self.client,
            )

        self.assertEqual("capability_gap", result["status"])
        gap = result["capability_gaps"][0]
        self.assertEqual("draft_capability_gap", gap["kind"])
        self.assertEqual(operation_id, gap["operation_id"])
        self.assertTrue(gap["blockers"])
        self.assertNotIn("next", gap)

    def test_agent_metadata_source_is_safe_and_warns_when_default_is_unavailable(self) -> None:
        from gravity_sdk.find import metadata_capability_cards

        metadata_result = {
            "results": [
                {
                    "kind": "event",
                    "app_id": "101",
                    "name": "Purchase",
                    "cname": "Purchase event",
                    "operation_id": "analysis.event.list",
                    "score": 100,
                    "payload": {"name": "Purchase", "internal": "not-for-card"},
                }
            ]
        }
        with patch(
            "gravity_sdk.find.search_metadata", return_value=metadata_result
        ) as search:
            cards, warnings = metadata_capability_cards("purchase", limit=2)

        self.assertEqual([], warnings)
        self.assertEqual("metadata", cards[0]["kind"])
        self.assertNotIn("payload", cards[0])
        self.assertEqual(
            ["gravity", "metadata", "events", "purchase", "--app-id", "101"],
            cards[0]["next"]["argv"],
        )
        search.assert_called_once_with("purchase", limit=None, offset=0)

        broad_results = {
            "total": 250,
            "results": [
                {
                    "kind": "event",
                    "app_id": str(index),
                    "name": f"Event {index}",
                    "cname": "Broad event",
                    "operation_id": "analysis.event.list",
                    "score": 60,
                }
                for index in range(250)
            ],
        }
        with patch(
            "gravity_sdk.find.search_metadata", return_value=broad_results
        ) as broad_search:
            broad_cards, _ = metadata_capability_cards("event", limit=None)
        self.assertEqual(250, len(broad_cards))
        broad_search.assert_called_once_with("event", limit=None, offset=0)

        with patch(
            "gravity_sdk.find.search_metadata",
            side_effect=InputValidationError("missing", field="database"),
        ):
            cards, warnings = metadata_capability_cards("purchase", limit=2)
        self.assertEqual([], cards)
        self.assertIn("metadata sync --all-apps", warnings[0])
        self.assertNotIn("\\", warnings[0])

    def test_agent_recipe_page_continuation_remains_valid(self) -> None:
        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        with patch("gravity_sdk.agent_sources.load_workspace", return_value=workspace):
            first = cli.run_agent_command(
                SimpleNamespace(
                    query="analysis",
                    domain=None,
                    platform=None,
                    limit=2,
                    continuation=None,
                ),
                self.client,
            )
            second = cli.run_agent_command(
                SimpleNamespace(
                    query="analysis",
                    domain=None,
                    platform=None,
                    limit=2,
                    continuation=first["continuation_token"],
                ),
                self.client,
            )

        self.assertEqual("recipe", first["candidates"][0]["kind"])
        self.assertTrue(first["continuation_token"])
        self.assertEqual(first["total"], second["total"])
        self.assertNotEqual(
            first["candidates"][-1]["selector"],
            second["candidates"][0]["selector"],
        )
        self.assertEqual("operation", second["candidates"][0]["kind"])
        token = first["continuation_token"]
        padding = "=" * (-len(token) % 4)
        token_payload = json.loads(
            base64.urlsafe_b64decode(token + padding).decode("utf-8")
        )
        self.assertRegex(token_payload["catalog_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertRegex(token_payload["candidates_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertNotIn("SELECT", json.dumps(token_payload))
        self.assertNotIn(str(workspace.path), json.dumps(token_payload))

    def test_agent_continuation_binds_operation_inventory_candidates(self) -> None:
        class InventoryClient:
            def __init__(self, operation_ids: list[str]) -> None:
                self.operation_ids = operation_ids

            def operations(self, **_filters):
                return [
                    {
                        "operation_id": operation_id,
                        "domain": "analysis",
                        "resource": "event",
                        "action": "list",
                        "stability": "stable",
                        "executable": True,
                        "contract_version": "1",
                    }
                    for operation_id in self.operation_ids
                ]

            def describe(self, operation_id: str):
                return {
                    "operation_id": operation_id,
                    "input_schema": {},
                    "stability": "stable",
                    "executable": True,
                }

        workspace = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        first_client = InventoryClient(["event.a", "event.b"])
        first = discover_capabilities(
            "event", client=first_client, workspace=workspace, limit=1
        )
        same = discover_capabilities(
            "event",
            client=InventoryClient(["event.a", "event.b"]),
            workspace=workspace,
            limit=1,
            continuation=first["continuation_token"],
        )
        self.assertEqual("event.a", first["candidates"][0]["selector"])
        self.assertEqual("event.b", same["candidates"][0]["selector"])

        with self.assertRaises(InputValidationError) as raised:
            discover_capabilities(
                "event",
                client=InventoryClient(["event.x", "event.y"]),
                workspace=workspace,
                limit=1,
                continuation=first["continuation_token"],
            )
        self.assertEqual("continuation", raised.exception.field)

    def test_agent_continuation_binds_metadata_candidates(self) -> None:
        def metadata_card(selector: str) -> dict[str, object]:
            return {
                "kind": "metadata",
                "selector": selector,
                "metadata_kind": "event",
                "app_id": "1",
                "name": selector,
                "display_name": selector,
                "operation_id": "analysis.event.list",
            }

        first_catalog = [metadata_card("metadata:event:1:a"), metadata_card("metadata:event:1:b")]
        changed_catalog = [metadata_card("metadata:event:1:x"), metadata_card("metadata:event:1:y")]
        empty_operations = OperationDiscovery(matches=[], weak=[])
        with (
            patch(
                "gravity_sdk.agent.catalog_cards",
                side_effect=(
                    (first_catalog, 2, [], "0" * 64),
                    (changed_catalog, 2, [], "0" * 64),
                ),
            ),
            patch(
                "gravity_sdk.agent.discover_operation_cards",
                return_value=empty_operations,
            ),
        ):
            first = discover_capabilities("event", client=self.client, limit=1)
            with self.assertRaises(InputValidationError) as raised:
                discover_capabilities(
                    "event",
                    client=self.client,
                    limit=1,
                    continuation=first["continuation_token"],
                )

        self.assertEqual("continuation", raised.exception.field)

    def test_agent_continuation_rejects_explicit_workspace_switch(self) -> None:
        workspace_a = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        product_name = workspace_a.product_names[0]
        product = dict(workspace_a.products[product_name])
        product["measurement"] = "changed aggregate contract"
        workspace_b = replace(
            workspace_a,
            path=Path("B:/different/gravity.toml"),
            products={**workspace_a.products, product_name: product},
        )
        first = discover_capabilities(
            "event", client=self.client, workspace=workspace_a, limit=1
        )
        self.assertIsNotNone(first["continuation_token"])

        with self.assertRaises(InputValidationError) as raised:
            discover_capabilities(
                "event",
                client=self.client,
                workspace=workspace_b,
                limit=1,
                continuation=first["continuation_token"],
            )

        self.assertEqual("continuation", raised.exception.field)
        self.assertEqual("caller", error_detail_from_exception(raised.exception).category)

    def test_agent_continuation_rejects_default_cwd_workspace_switch(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        ).read_text(encoding="utf-8")
        changed = source.replace(
            "Fictional project-owned retention recipe",
            "Changed project-owned retention recipe",
        )
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"GRAVITY_WORKSPACE": ""}
        ):
            root = Path(temporary)
            workspace_a = root / "a"
            workspace_b = root / "b"
            workspace_a.mkdir()
            workspace_b.mkdir()
            (workspace_a / "gravity.toml").write_text(source, encoding="utf-8")
            (workspace_b / "gravity.toml").write_text(changed, encoding="utf-8")
            try:
                os.chdir(workspace_a)
                first = discover_capabilities("event", client=self.client, limit=1)
                os.chdir(workspace_b)
                with self.assertRaises(InputValidationError) as raised:
                    discover_capabilities(
                        "event",
                        client=self.client,
                        limit=1,
                        continuation=first["continuation_token"],
                    )
            finally:
                os.chdir(original_cwd)

        self.assertEqual("continuation", raised.exception.field)

    def test_agent_continuation_rejects_same_workspace_contract_drift(self) -> None:
        base = load_workspace(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "workspace"
            / "gravity.toml"
        )
        recipe_name = base.recipe_names[0]
        product_name = base.product_names[0]
        changed_recipe = replace(
            base.recipes[recipe_name], description="changed recipe contract"
        )
        changed_product = dict(base.products[product_name])
        changed_product["max_rows"] = int(changed_product["max_rows"]) + 1
        variants = (
            replace(base, recipes={**base.recipes, recipe_name: changed_recipe}),
            replace(base, products={**base.products, product_name: changed_product}),
        )
        for kind, changed_workspace in zip(("recipe", "product"), variants):
            with self.subTest(changed=kind):
                first = discover_capabilities(
                    "event", client=self.client, workspace=base, limit=1
                )
                with self.assertRaises(InputValidationError) as raised:
                    discover_capabilities(
                        "event",
                        client=self.client,
                        workspace=changed_workspace,
                        limit=1,
                        continuation=first["continuation_token"],
                    )
                self.assertEqual("continuation", raised.exception.field)

    def test_agent_cli_emits_one_json_document_and_stable_empty_success(self) -> None:
        class EmptySearchClient:
            def search_operations(self, *_args, **_kwargs):
                return {
                    "operations": [],
                    "total": 0,
                    "continuation_token": None,
                }

        for argv, expected_status, selected_client in (
            (["agent"], "ready", self.client),
            (
                ["agent", "no-such-capability-xyz"],
                "capability_gap",
                EmptySearchClient(),
            ),
        ):
            with self.subTest(argv=argv):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch("gravity_sdk.cli.runtime.build_client", return_value=selected_client),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = cli.main(argv)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(0, exit_code)
                self.assertEqual(expected_status, payload["status"])
                self.assertIn("next_action", payload)
                self.assertEqual("", stderr.getvalue())

    def test_agent_ndjson_emits_one_candidate_per_line_and_terminal_metadata(self) -> None:
        stdout = io.StringIO()
        with (
            patch("gravity_sdk.cli.runtime.build_client", return_value=self.client),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = cli.main(
                ["agent", "report", "--limit", "1", "--format", "ndjson"]
            )

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(0, exit_code)
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("operation_id", lines[0])
        self.assertEqual(len(lines) - 1, lines[-1]["_gravity_insight"]["rows_written"])
        terminal = lines[-1]["_gravity_insight"]
        self.assertEqual("gravity.agent.v1", terminal["payload_schema_version"])
        self.assertTrue(terminal["ok"])
        self.assertTrue(terminal["offline"])
        self.assertFalse(terminal["network_called"])
        self.assertEqual("discover_and_describe", terminal["mode"])
        self.assertEqual(terminal["rows_written"], terminal["count"])
        self.assertIn("continuation_token", terminal)
        self.assertIsNotNone(terminal["continuation_token"])
        self.assertIn("next_action", terminal)
        self.assertIn("execution", terminal)
        self.assertEqual(
            "workspace_recipes_analysis_query_spec_segment_rule_spec_stable_insight_composites_"
            "sql_products_governed_exports_and_local_metadata",
            terminal["scope"],
        )
        self.assertTrue(terminal["fallbacks"])
        self.assertIn("catalog_warnings", terminal)

    def test_draft_action_is_written_for_sdk_users(self) -> None:
        operation_id = "app.app_info.get"
        described = self.client.describe(operation_id)
        action = described["next_action"]

        self.assertFalse(described["user_can_unlock"])
        self.assertIn("Contact the Gravity Insight SDK maintainers", action)
        self.assertIn(operation_id, action)
        for internal_term in ("targeted probe", "request binding", "promote contract"):
            self.assertNotIn(internal_term, action)

        with self.assertRaises(OperationNotImplementedError) as raised:
            self.client.read(operation_id, {})
        self.assertEqual(action, raised.exception.next_action)


if __name__ == "__main__":
    unittest.main()
