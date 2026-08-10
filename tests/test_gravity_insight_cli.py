from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import cli, runtime
from gravity_sdk.domains import (
    ANALYSIS_AUXILIARY_OPERATIONS,
    ANALYSIS_DASHBOARD_OPERATIONS,
    ANALYSIS_DETAIL_OPERATIONS,
    ANALYSIS_DIRECTORY_OPERATIONS,
    ANALYSIS_METADATA_OPERATIONS,
    ANALYSIS_REPORT_CONFIG_OPERATIONS,
    ANALYSIS_SEGMENT_OPERATIONS,
    ANALYSIS_TEMPLATE_OPERATIONS,
    ANALYSIS_VALUE_OPERATIONS,
    ATTRIBUTION_STATUS_OPERATIONS,
    DOMAIN_OPERATIONS,
    MULTIDIM_METADATA_OPERATIONS,
    PROMOTION_PLATFORMS,
    PROMOTION_PRIMARY_OPERATIONS,
    promotion_operation,
)
from gravity_sdk.domains import (
    COMPILED_CATALOG_OPERATIONS,
    CatalogOperation,
    derive_legacy_domain_maps,
)

try:
    from gravity_sdk import GravityInsightClient
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient


ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self) -> None:
        operation_ids = {
            *(
                operation
                for choices in DOMAIN_OPERATIONS.values()
                for operation in choices
            ),
            *MULTIDIM_METADATA_OPERATIONS,
            *ATTRIBUTION_STATUS_OPERATIONS,
            *ANALYSIS_DETAIL_OPERATIONS.values(),
            *ANALYSIS_DIRECTORY_OPERATIONS.values(),
            *ANALYSIS_DASHBOARD_OPERATIONS.values(),
            *ANALYSIS_TEMPLATE_OPERATIONS.values(),
            *ANALYSIS_VALUE_OPERATIONS.values(),
            *ANALYSIS_AUXILIARY_OPERATIONS.values(),
            *ANALYSIS_REPORT_CONFIG_OPERATIONS.values(),
            *ANALYSIS_SEGMENT_OPERATIONS.values(),
            *(
                operation
                for levels in PROMOTION_PLATFORMS.values()
                for operation in levels.values()
            ),
        }
        self.operation_ids = operation_ids
        self.read_calls: list[tuple[str, dict]] = []
        self.read_all_calls: list[tuple[str, dict, int | None]] = []
        self.batch_calls: list[tuple[list[dict], int]] = []
        self.schema_calls: list[str] = []
        self.capability_calls: list[tuple[object, object, object]] = []

    def capabilities(self, *, domain=None, platform=None, stability="stable"):
        self.capability_calls.append((domain, platform, stability))
        values = [
            {
                "operation_id": operation_id,
                "domain": operation_id.split(".", 1)[0],
                "stability": "stable",
            }
            for operation_id in sorted(self.operation_ids)
        ]
        if domain:
            values = [item for item in values if item["domain"] == domain]
        if platform:
            values = [
                item
                for item in values
                if item["operation_id"].startswith(f"promotion.{platform}.")
            ]
        if stability:
            values = [item for item in values if item["stability"] == stability]
        return values

    def schema(self, operation_id: str):
        self.schema_calls.append(operation_id)
        fields: dict[str, dict] = {}
        if operation_id.startswith("promotion."):
            fields = {"query_fields": {}, "date_list": {}}
        elif operation_id == "report.multidim.query":
            fields = {
                "app_id": {},
                "media_type": {},
                "date_list": {},
                "time_dims": {},
                "data_dims": {},
                "metrics_list": {},
                "multi_keys": {},
                "advertiser_id": {},
                "filters": {},
            }
        elif operation_id == "report.multidim.calc_total":
            fields = {
                "date_list": {},
                "time_dims": {},
                "data_dims": {},
                "metrics_list": {},
                "multi_keys": {},
            }
        schema = {"operation_id": operation_id, "input_fields": fields}
        if operation_id == "app.list":
            schema["live_probe"] = {
                "enabled": True,
                "inputs": {"page": 1, "page_size": 1},
            }
        return schema

    def read(self, operation_id: str, inputs: dict):
        self.read_calls.append((operation_id, inputs))
        return {"operation_id": operation_id, "inputs": inputs, "mode": "read"}

    def read_all(self, operation_id: str, inputs: dict, limit: int | None = None):
        self.read_all_calls.append((operation_id, inputs, limit))
        return {
            "operation_id": operation_id,
            "inputs": inputs,
            "mode": "read_all",
            "limit": limit,
        }

    def batch(self, requests: list[dict], concurrency: int = 4):
        self.batch_calls.append((requests, concurrency))
        return [{"operation_id": item["operation_id"], "ok": True} for item in requests]


class GravityInsightCliTests(unittest.TestCase):
    def invoke(
        self, argv: list[str], client: FakeClient | None = None, stdin: str = ""
    ):
        client = client or FakeClient()
        automatic_output = (
            "--all-pages" in argv
            and "--output" not in argv
            and "--format" not in argv
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        file_rendered = None
        with contextlib.ExitStack() as stack:
            adjusted_argv = list(argv)
            output_path = None
            if automatic_output:
                directory = stack.enter_context(tempfile.TemporaryDirectory())
                output_path = Path(directory) / "result.json"
                adjusted_argv.extend(["--output", str(output_path)])
            stack.enter_context(
            patch(
                "gravity_sdk.cli.runtime.build_client", return_value=client
            ))
            stack.enter_context(patch(
                "gravity_sdk.cli.runtime.validate_manifest_json",
                return_value={
                    "manifest_files": 4,
                    "operations": len(client.operation_ids),
                },
            ))
            stack.enter_context(patch.object(sys, "stdin", io.StringIO(stdin)))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            code = cli.main(adjusted_argv)
            if output_path is not None and output_path.is_file():
                file_rendered = json.loads(output_path.read_text(encoding="utf-8"))
        rendered = (
            file_rendered
            if file_rendered is not None
            else json.loads(stdout.getvalue())
            if stdout.getvalue()
            else None
        )
        error = json.loads(stderr.getvalue()) if stderr.getvalue() else None
        return code, rendered, error, client

    def test_dry_run_validates_every_core_registry_schema_without_reads(self):
        code, result, error, client = self.invoke(["--dry-run"])
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertTrue(result["core_registry_validated"])
        self.assertFalse(result["network_called"])
        self.assertEqual(client.operation_ids, set(client.schema_calls))
        self.assertEqual([], client.read_calls)
        self.assertEqual([], client.read_all_calls)

    def test_runtime_reuses_one_long_lived_client(self):
        sentinel = object()

        class ClientClass:
            calls = 0

            @classmethod
            def from_env(cls):
                cls.calls += 1
                return sentinel

        class Sdk:
            GravityInsightClient = ClientClass

        with (
            patch.object(runtime, "_CLIENT", None),
            patch.object(runtime, "_sdk_module", return_value=Sdk),
        ):
            self.assertIs(sentinel, runtime.build_client())
            self.assertIs(sentinel, runtime.build_client())
        self.assertEqual(1, ClientClass.calls)

    def test_generic_read_supports_stdin_and_limit(self):
        operation_id = "promotion.bytedance.advertiser.list"
        code, result, _, client = self.invoke(
            ["read", operation_id, "--input", "-", "--limit", "25"],
            stdin='{"query_fields":["cost"],"date_list":["2026-08-01","2026-08-02"]}',
        )
        self.assertEqual(0, code)
        self.assertEqual("read_all", result["mode"])
        self.assertEqual(25, result["limit"])
        self.assertEqual(25, client.read_all_calls[0][2])

    def test_batch_read_passes_concurrency(self):
        payload = [{"operation_id": "app.list", "inputs": {}, "request_id": "apps"}]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, result, _, client = self.invoke(
                ["batch", "read", "--input", str(path), "--concurrency", "24"]
            )
        self.assertEqual(0, code)
        # CLI batch read now returns the public batch-level envelope instead of
        # a bare result array, so consumers can recover aggregate counts/codes.
        self.assertTrue(result["results"][0]["ok"])
        self.assertEqual(1, result["total_count"])
        self.assertEqual(1, result["success_count"])
        self.assertEqual(0, result["failure_count"])
        self.assertEqual(24, client.batch_calls[0][1])

    def test_batch_schema_publishes_wrapper_example_and_exit_rules(self):
        code, result, error, _ = self.invoke(["batch", "schema"])
        self.assertEqual(0, code)
        self.assertIsNone(error)
        item = result["wrapper"]["properties"]["requests"]["items"]
        self.assertEqual(
            ["input", "inputs", "operation_id", "read_all", "request_id"],
            item["allowed_fields"],
        )
        self.assertEqual("app.list", result["example"]["requests"][0]["operation_id"])
        self.assertIn("highest item exit code wins", result["exit_codes"]["aggregation"])

    def test_batch_unknown_item_field_lists_every_allowed_field(self):
        payload = {
            "requests": [
                {
                    "operation_id": "app.list",
                    "input": {"page": 1, "page_size": 1},
                    "max_pages": 1,
                    "max_items": 1,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, result, error, client = self.invoke(
                ["batch", "read", "--input", str(path)]
            )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertEqual("max_items", error["error"]["field"])
        self.assertIn(
            "allowed fields: input, inputs, operation_id, read_all, request_id",
            error["error"]["message"],
        )
        self.assertIn("batch schema", error["error"]["next_action"])
        self.assertEqual([], client.batch_calls)

    def test_batch_envelope_aggregates_counts_and_highest_exit_code(self):
        class PartialClient(FakeClient):
            def batch(self, requests: list[dict], concurrency: int = 4):
                self.batch_calls.append((requests, concurrency))
                return [
                    {"operation_id": requests[0]["operation_id"], "ok": True},
                    {
                        "operation_id": requests[1]["operation_id"],
                        "ok": False,
                        "error": {"category": "upstream", "code": "RATE_LIMITED"},
                    },
                ]

        payload = {
            "requests": [
                {"operation_id": "app.list", "input": {"page": 1}},
                {"operation_id": "app.list", "input": {"page": 2}},
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, result, error, _ = self.invoke(
                ["batch", "read", "--input", str(path)],
                client=PartialClient(),
            )
        self.assertEqual(3, code)
        self.assertIsNone(error)
        self.assertFalse(result["ok"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(2, result["total_count"])
        self.assertEqual(1, result["success_count"])
        self.assertEqual(1, result["failure_count"])
        self.assertEqual(3, result["exit_code"])

    def test_analysis_metadata_batches_all_four_catalogs(self):
        code, result, error, client = self.invoke(
            ["analysis", "metadata", "--app-id", "101"]
        )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual(4, len(result))
        requests, concurrency = client.batch_calls[0]
        self.assertEqual(4, concurrency)
        self.assertEqual(
            list(ANALYSIS_METADATA_OPERATIONS),
            [item["operation_id"] for item in requests],
        )
        self.assertTrue(all(item["read_all"] for item in requests))
        self.assertTrue(all(item["inputs"]["app_id"] == "101" for item in requests))

    def test_metadata_sync_all_apps_routes_to_persistent_sync_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            envelope = {
                "schema_version": "gravity-insight.metadata-sync.v1",
                "ok": True,
                "status": "success",
                "database": str(database),
                "exit_code": 0,
            }
            with patch(
                "gravity_sdk.metadata_sync.sync_all_apps", return_value=envelope
            ) as sync:
                code, result, error, client = self.invoke(
                    [
                        "metadata",
                        "sync",
                        "--all-apps",
                        "--database",
                        str(database),
                        "--concurrency",
                        "12",
                    ]
                )
            self.assertEqual(0, code)
            self.assertEqual(envelope, result)
            self.assertIsNone(error)
            sync.assert_called_once_with(
                client, database=database, concurrency=12
            )

    def test_stable_analysis_query_generates_frontend_query_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "event.json"
            path.write_text("{}", encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "query",
                    "--kind",
                    "event",
                    "--input",
                    str(path),
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.event.query", result["operation_id"])
        self.assertRegex(
            client.read_calls[0][1]["query_id"], r"^\d{13}[A-Za-z0-9]{19}$"
        )

    def test_inline_json_and_typed_set_merge_without_a_file(self):
        code, result, error, _ = self.invoke(
            [
                "read",
                "app.list",
                "--input",
                '{"nested":{"value":1},"source":"input"}',
                "--set",
                "nested.value=2",
                "--set",
                "enabled=true",
                "--set",
                'labels=["alpha","beta"]',
                "--set",
                "source=plain-text",
            ]
        )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual(
            {
                "nested": {"value": 2},
                "enabled": True,
                "labels": ["alpha", "beta"],
                "source": "plain-text",
            },
            result["inputs"],
        )

    def test_query_flags_override_set_and_inline_input(self):
        class AnalysisFlagClient(FakeClient):
            def schema(self, operation_id: str):
                schema = super().schema(operation_id)
                if operation_id == "analysis.event.query":
                    schema["input_fields"] = {
                        "app_id": {},
                        "date_list": {},
                        "query_item_list": {},
                        "query_id": {},
                    }
                return schema

        code, result, error, _ = self.invoke(
            [
                "analysis",
                "query",
                "--kind",
                "event",
                "--input",
                '{"app_id":"input","date_list":["old","old"]}',
                "--set",
                "app_id=set",
                "--set",
                'date_list=["set","set"]',
                "--set",
                "query_item_list=[]",
                "--app-id",
                "flag",
                "--start",
                "2026-08-01",
                "--end",
                "2026-08-02",
            ],
            client=AnalysisFlagClient(),
        )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("flag", result["inputs"]["app_id"])
        self.assertEqual(
            [{"start_date": "2026-08-01", "end_date": "2026-08-02"}],
            result["inputs"]["date_list"],
        )
        self.assertEqual([], result["inputs"]["query_item_list"])

    def test_operations_command_and_capabilities_search_alias_both_work(self):
        client = GravityInsightClient.from_env()
        client.operation_ids = {
            item["operation_id"] for item in client.capabilities(stability=None)
        }
        current, legacy = (
            self.invoke([name, "search", "retention"], client=client)[1]
            for name in ("operations", "capabilities")
        )
        self.assertIn("operations", current)
        self.assertNotIn("capabilities", current)
        self.assertIn("capabilities", legacy)
        self.assertNotIn("operations", legacy)
        self.assertEqual(
            [item["operation_id"] for item in current["operations"]],
            [item["operation_id"] for item in legacy["capabilities"]],
        )

    def test_experimental_analysis_requires_explicit_flag(self):
        class ExperimentalScatterClient(FakeClient):
            def schema(self, operation_id: str):
                schema = super().schema(operation_id)
                if operation_id == "analysis.scatter.query":
                    schema["stability"] = "experimental"
                return schema

        client = ExperimentalScatterClient()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scatter.json"
            path.write_text("{}", encoding="utf-8")
            argv = [
                "analysis",
                "query",
                "--kind",
                "scatter",
                "--input",
                str(path),
            ]
            code, result, error, _ = self.invoke(argv, client=client)
            self.assertEqual(2, code)
            self.assertIsNone(result)
            self.assertIn("--experimental", error["error"]["message"])
            self.assertEqual([], client.read_calls)

            code, result, error, _ = self.invoke(
                [*argv, "--experimental"], client=client
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.scatter.query", result["operation_id"])

    def test_analysis_segments_injects_controlled_app_filter(self):
        code, result, error, client = self.invoke(
            ["analysis", "segments", "--app-id", "101"]
        )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.segment.list", result["operation_id"])
        self.assertEqual("101", client.read_calls[0][1]["app_id"])

    def test_analysis_detail_routes_to_stable_user_read_without_extra_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "user.json"
            path.write_text(
                json.dumps({"app_id": "101", "date": "2026-08-08"}),
                encoding="utf-8",
            )
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "detail",
                    "--kind",
                    "user",
                    "--input",
                    str(path),
                    "--fields",
                    "ClientID,user_id",
                    "--fields",
                    "device_id",
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.user_detail.list", result["operation_id"])
        self.assertEqual("2026-08-08", client.read_calls[0][1]["date"])
        self.assertEqual(
            ["ClientID", "user_id", "device_id"], client.read_calls[0][1]["fields"]
        )

    def test_analysis_segment_history_supports_manifest_pagination(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "segment.json"
            path.write_text(json.dumps({"segment_id": "8"}), encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "segment",
                    "--kind",
                    "history",
                    "--input",
                    str(path),
                    "--all-pages",
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual(
            "analysis.segment.history_version.list", result["operation_id"]
        )
        self.assertEqual("8", client.read_all_calls[0][1]["segment_id"])

    def test_analysis_segment_evaluate_routes_structured_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "segment-rule.json"
            payload = {
                "app_id": "101",
                "name": "high-value users",
                "date_range": {"start_date": "2026-08-08", "end_date": None},
                "user_property_rules": {"cond_logic": "AND", "groups": []},
                "user_event_rules": {"cond_logic": "AND", "groups": []},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "segment",
                    "--kind",
                    "evaluate",
                    "--input",
                    str(path),
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.segment.evaluate_percent", result["operation_id"])
        self.assertEqual("high-value users", client.read_calls[0][1]["name"])

    def test_analysis_user_event_rejects_unproven_all_pages_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "user-event.json"
            path.write_text(
                json.dumps(
                    {
                        "app_id": "101",
                        "client_id": "client-1",
                        "date": "2026-08-08",
                    }
                ),
                encoding="utf-8",
            )
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "detail",
                    "--kind",
                    "user-event",
                    "--input",
                    str(path),
                    "--all-pages",
                ]
            )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("explicit page/page_size", error["error"]["message"])
        self.assertEqual([], client.read_calls)
        self.assertEqual([], client.read_all_calls)

    def test_analysis_user_event_allows_explicit_later_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "user-event-page.json"
            path.write_text(
                json.dumps(
                    {
                        "app_id": "101",
                        "client_id": "client-1",
                        "date": "2026-08-08",
                        "page": 2,
                        "page_size": 20,
                    }
                ),
                encoding="utf-8",
            )
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "detail",
                    "--kind",
                    "user-event",
                    "--input",
                    str(path),
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.user_event.list", result["operation_id"])
        self.assertEqual(2, client.read_calls[0][1]["page"])
        self.assertEqual([], client.read_all_calls)

    def test_analysis_report_config_routes_stable_list_and_get(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "saved.json"
            path.write_text(json.dumps({"app_id": "101", "id": "8"}), encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "report-config",
                    "--kind",
                    "get",
                    "--input",
                    str(path),
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.report_config.get", result["operation_id"])
        self.assertEqual("8", client.read_calls[0][1]["id"])

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "saved-list.json"
            path.write_text(json.dumps({"app_id": "101"}), encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "report-config",
                    "--kind",
                    "list",
                    "--input",
                    str(path),
                    "--all-pages",
                ]
            )
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("analysis.report_config.list", result["operation_id"])
        self.assertEqual("101", client.read_all_calls[0][1]["app_id"])

    def test_analysis_dashboard_routes_structured_inputs_and_pagination(self):
        cases = (
            ("tree", "analysis.dashboard.tree", False),
            ("detail", "analysis.dashboard.detail", False),
            ("members", "analysis.dashboard.members.list", False),
            ("space-members", "analysis.dashboard.space_members.list", False),
            ("favourites", "analysis.dashboard.condition_favourite.list", True),
            (
                "default-favourite",
                "analysis.dashboard.condition_favourite.default_to_me.get",
                False,
            ),
        )
        for kind, operation_id, paginated in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "dashboard.json"
                path.write_text(
                    json.dumps({"app_id": "101", "marker": kind}), encoding="utf-8"
                )
                argv = [
                    "analysis",
                    "dashboard",
                    "--kind",
                    kind,
                    "--input",
                    str(path),
                ]
                if paginated:
                    argv.append("--all-pages")
                code, result, error, client = self.invoke(argv)
                self.assertEqual(0, code)
                self.assertIsNone(error)
                self.assertEqual(operation_id, result["operation_id"])
                calls = client.read_all_calls if paginated else client.read_calls
                self.assertEqual(kind, calls[0][1]["marker"])

    def test_analysis_values_and_account_users_have_normal_cli_routes(self):
        cases = (
            (
                ["analysis", "values", "--kind", "user-property"],
                "analysis.user_property_value.list",
                False,
            ),
            (
                ["analysis", "values", "--kind", "event-property"],
                "analysis.event_property_value.list",
                False,
            ),
            (["analysis", "users"], "analysis.account_user.list", True),
        )
        for prefix, operation_id, paginated in cases:
            with self.subTest(operation_id=operation_id), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "analysis-input.json"
                path.write_text(json.dumps({"marker": operation_id}), encoding="utf-8")
                argv = [*prefix, "--input", str(path)]
                if paginated:
                    argv.append("--all-pages")
                code, result, error, client = self.invoke(argv)
                self.assertEqual(0, code)
                self.assertIsNone(error)
                self.assertEqual(operation_id, result["operation_id"])
                calls = client.read_all_calls if paginated else client.read_calls
                self.assertEqual(operation_id, calls[0][1]["marker"])

    def test_analysis_templates_routes_subjects_and_paginated_rows(self):
        cases = (
            ("subject-own", "analysis.template.subject.own.list", False),
            ("subject-share", "analysis.template.subject.share.list", False),
            ("subject-internal", "analysis.template.subject.internal.list", False),
            ("own", "analysis.template.own.list", True),
            ("share", "analysis.template.share.list", True),
            ("internal", "analysis.template.internal.list", True),
        )
        for kind, operation_id, paginated in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "templates.json"
                path.write_text(json.dumps({"marker": kind}), encoding="utf-8")
                argv = [
                    "analysis",
                    "templates",
                    "--kind",
                    kind,
                    "--input",
                    str(path),
                ]
                if paginated:
                    argv.append("--all-pages")
                code, result, error, client = self.invoke(argv)
                self.assertEqual(0, code)
                self.assertIsNone(error)
                self.assertEqual(operation_id, result["operation_id"])
                calls = client.read_all_calls if paginated else client.read_calls
                self.assertEqual(kind, calls[0][1]["marker"])

    def test_analysis_auxiliary_routes_structured_inputs_and_pagination(self):
        cases = (
            ("hidden-properties", "analysis.report.hidden_property.list", False),
            ("pay-events", "analysis.task.pay_event.list", True),
            ("other-events", "analysis.task.other_event.list", True),
        )
        for kind, operation_id, paginated in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "auxiliary.json"
                path.write_text(
                    json.dumps({"app_id": "101", "marker": kind}), encoding="utf-8"
                )
                argv = [
                    "analysis",
                    "auxiliary",
                    "--kind",
                    kind,
                    "--input",
                    str(path),
                ]
                if paginated:
                    argv.append("--all-pages")
                code, result, error, client = self.invoke(argv)
                self.assertEqual(0, code)
                self.assertIsNone(error)
                self.assertEqual(operation_id, result["operation_id"])
                calls = client.read_all_calls if paginated else client.read_calls
                self.assertEqual(kind, calls[0][1]["marker"])

    def test_analysis_bounded_routes_reject_all_pages_for_single_read_ops(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dashboard.json"
            path.write_text(json.dumps({"app_id": "101"}), encoding="utf-8")
            code, result, error, client = self.invoke(
                [
                    "analysis",
                    "dashboard",
                    "--kind",
                    "tree",
                    "--input",
                    str(path),
                    "--all-pages",
                ]
            )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("non-paginated", error["error"]["message"])
        self.assertEqual([], client.read_calls)
        self.assertEqual([], client.read_all_calls)

    def test_cli_rejects_concurrency_above_insight_safety_limit(self):
        for command in (
            ["batch", "read", "--input", "batch.json", "--concurrency", "25"],
            ["doctor", "--live", "--concurrency", "25"],
            ["promotion", "snapshot", "--platform", "all", "--concurrency", "25"],
        ):
            with (
                self.subTest(command=command),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(ValueError):
                    cli.build_parser().parse_args(command)

    def test_multidim_layout_scope_and_query_shortcuts(self):
        code, _, _, client = self.invoke(
            ["multidim", "templates", "list", "--scope", "mine"]
        )
        self.assertEqual(0, code)
        self.assertEqual("report.multidim.template.mine.list", client.read_calls[0][0])

        code, result, _, client = self.invoke(
            [
                "multidim",
                "query",
                "--app-id",
                "7",
                "--media",
                "bytedance",
                "--start",
                "2026-08-01",
                "--end",
                "2026-08-02",
                "--time-dim",
                "day",
                "--dimensions",
                "app,advertiser",
                "--metrics",
                "cost,click",
                "--parent-id",
                "parent-1",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual("report.multidim.query", result["operation_id"])
        self.assertEqual(["2026-08-01", "2026-08-02"], result["inputs"]["date_list"])
        self.assertEqual("day", result["inputs"]["time_dims"])
        self.assertEqual(["app", "advertiser"], result["inputs"]["data_dims"])
        self.assertEqual(["cost", "click"], result["inputs"]["metrics_list"])
        self.assertEqual("parent-1", result["inputs"]["advertiser_id"])
        self.assertEqual(
            [
                {"field": "app_id", "operator": "EQUALS", "values": ["7"]},
                {"field": "click_company", "operator": "IN", "values": ["bytedance"]},
            ],
            result["inputs"]["filters"],
        )

    def test_multidim_rejects_multiple_time_dimensions(self):
        code, result, error, _ = self.invoke(
            ["multidim", "query", "--time-dim", "day,hour"]
        )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("exactly one", error["error"]["message"])

    def test_multidim_query_accepts_controlled_multi_days(self):
        code, result, _, _ = self.invoke(
            [
                "multidim",
                "query",
                "--metrics",
                "multi_day_roi_all",
                "--multi-days",
                "2,3,7",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual([2, 3, 7], result["inputs"]["multi_keys"])

        code, result, error, _ = self.invoke(
            ["multidim", "query", "--multi-days", "3,2"]
        )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("unique ascending", error["error"]["message"])

    def test_promotion_snapshot_all_batches_exactly_one_primary_operation_per_platform(
        self,
    ):
        code, result, _, client = self.invoke(
            [
                "promotion",
                "snapshot",
                "--platform",
                "all",
                "--start",
                "2026-08-01",
                "--end",
                "2026-08-02",
                "--metrics",
                "cost,click",
                "--concurrency",
                "6",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual(25, result["platform_count"])
        requests, concurrency = client.batch_calls[0]
        self.assertEqual(6, concurrency)
        self.assertEqual(
            set(PROMOTION_PRIMARY_OPERATIONS.values()),
            {item["operation_id"] for item in requests},
        )
        self.assertTrue(all(item["read_all"] for item in requests))
        self.assertTrue(
            all(
                item["inputs"]["query_fields"] == ["cost", "click"] for item in requests
            )
        )

    def test_special_platform_defaults_use_explicit_primary_resources(self):
        expected = {
            "ubix": "promotion.ubix.group.list",
            "taptap": "promotion.taptap.group.list",
            "wechat_video": "promotion.wechat_video.report.list",
        }
        for platform, operation_id in expected.items():
            with self.subTest(platform=platform):
                self.assertEqual(operation_id, PROMOTION_PRIMARY_OPERATIONS[platform])
                self.assertEqual(operation_id, promotion_operation(platform))

    def test_snapshot_all_rejects_a_single_platform_level(self):
        code, result, error, client = self.invoke(
            ["promotion", "snapshot", "--platform", "all", "--level", "advertiser"]
        )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("cannot be combined", error["error"]["message"])
        self.assertEqual([], client.batch_calls)

    def test_promotion_snapshot_all_filters_supplied_fields_per_operation_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "query_fields": ["cost"],
                        "date_list": ["a", "b"],
                        "unknown": "drop",
                    }
                ),
                encoding="utf-8",
            )
            code, result, _, client = self.invoke(
                ["promotion", "snapshot", "--platform", "all", "--input", str(path)]
            )
        self.assertEqual(0, code)
        self.assertTrue(
            all("unknown" not in item["inputs"] for item in client.batch_calls[0][0])
        )
        self.assertTrue(
            all(
                "input:unknown" in values
                for values in result["ignored_shortcuts"].values()
            )
        )

    def test_actual_domain_mappings_cover_apps_objects_materials_and_attribution(self):
        commands = (
            (["apps", "list"], "app.list"),
            (["objects", "list"], "promotion.object.list"),
            (["materials", "list"], "material.local.list"),
            (["materials", "tags"], "material.tag.list"),
            (["materials", "reviews"], "material.review.list"),
            (["attribution", "maps"], "attribution.postback_map_collect.list"),
        )
        for argv, expected in commands:
            with self.subTest(argv=argv):
                code, result, _, _ = self.invoke(argv)
                self.assertEqual(0, code)
                self.assertEqual(expected, result["operation_id"])

        code, _, _, client = self.invoke(["attribution", "status"])
        self.assertEqual(0, code)
        self.assertEqual(
            set(ATTRIBUTION_STATUS_OPERATIONS),
            {item["operation_id"] for item in client.batch_calls[0][0]},
        )

    def test_multidim_metadata_batch_always_reads_all_pages(self):
        code, _, _, client = self.invoke(["multidim", "metadata"])
        self.assertEqual(0, code)
        requests, _ = client.batch_calls[0]
        self.assertEqual(
            set(MULTIDIM_METADATA_OPERATIONS),
            {item["operation_id"] for item in requests},
        )
        self.assertTrue(all(item["read_all"] is True for item in requests))

    def test_capability_filters_apply_domain_platform_and_stability(self):
        code, result, _, client = self.invoke(
            [
                "capabilities",
                "list",
                "--domain",
                "promotion",
                "--platform",
                "bytedance",
                "--stability",
                "stable",
            ]
        )
        self.assertEqual(0, code)
        self.assertGreater(result["count"], 0)
        self.assertTrue(
            all(
                item["operation_id"].startswith("promotion.bytedance.")
                for item in result["capabilities"]
            )
        )
        self.assertEqual(
            ("promotion", "bytedance", "stable"), client.capability_calls[-1]
        )

        code, result, _, client = self.invoke(["capabilities", "list"])
        self.assertEqual(0, code)
        self.assertEqual((None, None, None), client.capability_calls[-1])
        self.assertEqual(len(client.operation_ids), result["count"])

    def test_cli_rejects_external_repo_or_manifest_roots_before_client_creation(self):
        for flag in ("--repo-root", "--manifest-dir"):
            stderr = io.StringIO()
            with (
                self.subTest(flag=flag),
                patch("gravity_sdk.cli.runtime.build_client") as factory,
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(2, cli.main([flag, "D:/untrusted", "--dry-run"]))
                self.assertEqual(
                    "INPUT_INVALID", json.loads(stderr.getvalue())["error"]["code"]
                )
            factory.assert_not_called()

    def test_doctor_is_offline_by_default_and_live_uses_safe_app_probe(self):
        with patch(
            "gravity_sdk.cli.runtime.credential_status",
            return_value={"credential_present": True},
        ):
            code, result, _, client = self.invoke(["doctor"])
        self.assertEqual(0, code)
        self.assertFalse(result["live"])
        self.assertEqual([], client.read_calls)

        with patch(
            "gravity_sdk.cli.runtime.credential_status",
            return_value={"credential_present": True},
        ):
            code, result, _, client = self.invoke(["doctor", "--live"])
        self.assertEqual(0, code)
        self.assertTrue(result["probe_succeeded"])
        self.assertEqual(
            ("app.list", {"page": 1, "page_size": 1}),
            client.read_calls[0],
        )

    def test_json_boundary_redacts_credentials_operators_departments_and_urls(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli._write_json(
                {
                    "authorization": "Bearer secret-value",
                    "cookie": "secret",
                    "operator_name": "Private Operator",
                    "dept": "Private Dept",
                    "callback_url": "https://private.invalid/callback",
                    "click_url": "https://private.invalid/click",
                    "postback_url": "https://private.invalid/postback",
                    "token": "secret",
                    "email_address": "private@example.invalid",
                    "phone": "10086",
                    "mobile": "10010",
                    "user_name": "Private User",
                    "creator": "Private Creator",
                    "asset_url": "https://private.invalid/asset",
                    "session_token": "secret",
                    "owner_email": "private@example.invalid",
                    "owner_phone": "10000",
                    "owner_mobile": "10001",
                    "owner_user_id": "private-id",
                    "owner_user_name": "Private Owner",
                    "filter": {"field": "app_id", "operator": "EQUALS", "values": [7]},
                    "safe": "kept",
                }
            )
        self.assertEqual(
            {
                "safe": "kept",
                "filter": {"field": "app_id", "operator": "EQUALS", "values": [7]},
            },
            json.loads(output.getvalue()),
        )

    def test_analysis_json_boundary_preserves_contracted_business_identifiers(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli._write_json(
                {
                    "operation_id": "analysis.user_detail.list",
                    "data": {
                        "ClientID": "client-1",
                        "user_id": "user-1",
                        "device_id": "device-1",
                        "email": "member@example.invalid",
                        "phone": "10086",
                        "click_url": "https://business.invalid/click",
                        "authorization": "Bearer secret-value",
                        "session_token": "secret",
                    },
                }
            )
        rendered = json.loads(output.getvalue())
        self.assertEqual(
            {
                "ClientID": "client-1",
                "user_id": "user-1",
                "device_id": "device-1",
                "email": "member@example.invalid",
                "phone": "10086",
                "click_url": "https://business.invalid/click",
            },
            rendered["data"],
        )

    def test_domain_operation_ids_exist_in_current_manifests(self):
        operation_ids: set[str] = set()
        for path in (ROOT / "src" / "gravity_sdk" / "manifests").glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            operation_ids.update(item["operation_id"] for item in payload["operations"])
        for choices in DOMAIN_OPERATIONS.values():
            self.assertTrue(set(choices) & operation_ids, choices)
        self.assertTrue(set(MULTIDIM_METADATA_OPERATIONS) <= operation_ids)
        self.assertTrue(set(ATTRIBUTION_STATUS_OPERATIONS) <= operation_ids)
        self.assertTrue(set(PROMOTION_PRIMARY_OPERATIONS.values()) <= operation_ids)

    def test_promotion_shortcuts_validate_against_real_operation_schemas(self):
        client = GravityInsightClient.from_env()

        def shortcut_args(**overrides):
            values = {
                "app_id": None,
                "media": None,
                "start": "2026-08-01",
                "end": "2026-08-02",
                "time_dim": None,
                "dimensions": None,
                "metrics": None,
                "parent_id": None,
            }
            values.update(overrides)
            return argparse.Namespace(**values)

        video, _ = cli._merge_query_shortcuts(
            client,
            "promotion.wechat_video.report.list",
            shortcut_args(app_id="wx-app"),
            {},
        )
        self.assertEqual("wx-app", video["app_id"])
        client._registry.get("promotion.wechat_video.report.list").validate_inputs(
            video
        )

        with self.assertRaisesRegex(ValueError, "does not accept --parent-id"):
            cli._merge_query_shortcuts(
                client,
                "promotion.bytedance.project.list",
                shortcut_args(app_id="7", parent_id="adv-1"),
                {},
            )

        project, _ = cli._merge_query_shortcuts(
            client,
            "promotion.bytedance.project.list",
            shortcut_args(app_id="7"),
            {},
        )
        self.assertEqual(
            [{"field": "app_id", "operator": 1, "values": ["7"]}],
            project["filters"],
        )
        client._registry.get("promotion.bytedance.project.list").validate_inputs(
            project
        )

        analysis, _ = cli._merge_query_shortcuts(
            client,
            "analysis.event.query",
            shortcut_args(app_id="29034827"),
            {
                "query_id": "1700000000000abcdefghijklmnopqrs",
                "query_item_list": [
                    {
                        "event_name": "$PayEvent",
                        "event_label": "$PayEvent",
                        "custom_name": "$PayEvent",
                        "target": {"name": "PresetAllCount", "field": "PresetAllCount"},
                        "conditions": [],
                        "cond_logic": "AND",
                        "event_index": 0,
                    }
                ],
            },
        )
        client._registry.get("analysis.event.query").validate_inputs(analysis)
        self.assertEqual(
            [{"start_date": "2026-08-01", "end_date": "2026-08-02"}],
            analysis["date_list"],
        )

    def test_new_catalog_operations_extend_structural_shortcuts_without_code_changes(self):
        added = (
            CatalogOperation(
                operation_id="promotion.synthetic_network.advertiser.list",
                domain="promotion",
                resource="advertiser",
                action="list",
                platform="synthetic_network",
                stability="stable",
                executable=True,
                paginated=True,
            ),
            CatalogOperation(
                operation_id="report.multidim.template.team.list",
                domain="report",
                resource="template",
                action="list",
                platform=None,
                stability="stable",
                executable=True,
                paginated=True,
            ),
        )

        derived = derive_legacy_domain_maps((*COMPILED_CATALOG_OPERATIONS, *added))

        self.assertEqual(
            "promotion.synthetic_network.advertiser.list",
            derived.promotion_platforms["synthetic_network"]["advertiser"],
        )
        self.assertEqual(
            ("report.multidim.template.team.list",),
            derived.domain_operations["multidim.templates.team"],
        )
        self.assertIn("team", derived.multidim_template_scopes)

    def test_domain_and_cli_modules_have_no_compiled_operation_literals(self):
        profile = runtime.to_jsonable(
            __import__(
                "gravity_sdk.quality", fromlist=["inspect_repository"]
            ).inspect_repository(ROOT)
        )
        occurrences = profile["operation_literals"]
        target_paths = {
            "src/gravity_sdk/domains.py",
            "src/gravity_sdk/cli.py",
        }

        self.assertFalse(
            [item for item in occurrences if item["path"] in target_paths]
        )


if __name__ == "__main__":
    unittest.main()
