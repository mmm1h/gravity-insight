from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli, runtime
from gravity_sdk.analysis_spec import analysis_query_spec_schema
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
    ATTRIBUTION_SNAPSHOT_OPERATIONS,
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
        self.validate_calls: list[tuple[str, dict]] = []
        self.operation_calls: list[tuple[object, object, object]] = []

    def operations(self, *, domain=None, platform=None, stability="stable"):
        self.operation_calls.append((domain, platform, stability))
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

    def validate(self, operation_id: str, inputs: dict):
        self.validate_calls.append((operation_id, inputs))
        return {
            "ok": True,
            "status": "needs_live_metadata",
            "network_called": False,
            "live_metadata_dependencies": ["analysis.user_property.list"],
        }

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
        return [
            {
                "operation_id": item["operation_id"],
                "ok": True,
                **(
                    {"request_id": item["request_id"]}
                    if "request_id" in item
                    else {}
                ),
            }
            for item in requests
        ]


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

    def test_analysis_spec_schema_preserves_every_required_property(self):
        code, result, error, client = self.invoke(
            ["analysis", "query", "--kind", "retention", "--spec-schema"]
        )
        self.assertEqual((0, None, []), (code, error, client.read_calls))
        self.assertEqual(
            analysis_query_spec_schema(),
            {key: value for key, value in result.items() if key != "requested_kind"},
        )
        pending = [result]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if "properties" in value:
                    self.assertTrue(set(value.get("required", ())) <= set(value["properties"]))
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        operator = result["definitions"]["condition"]["properties"]["operator"]
        self.assertIn("EQUALS", operator["enum"])

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
        self.assertEqual(
            "gravity batch read --input <batch.json> --concurrency 1",
            result["command"],
        )
        self.assertIn("highest item exit code wins", result["exit_codes"]["aggregation"])

    def test_batch_run_schema_and_execution_share_the_resolver_protocol(self):
        code, schema, error, _ = self.invoke(["batch", "schema", "--mode", "run"])
        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual(
            "gravity-insight.resolver-batch-schema.v1", schema["schema_version"]
        )

        payload = {
            "requests": [
                {
                    "selector": "app.list",
                    "apps": "*",
                    "request_id": "apps",
                }
            ]
        }
        workspace = SimpleNamespace(apps={"zeta": 2, "alpha": 1})

        def resolved(selector, **kwargs):
            return {
                "schema_version": "gravity-insight.resolve.v1",
                "ok": True,
                "status": "success",
                "operation_id": selector,
            }

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "resolver-batch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                patch("gravity_sdk.workspace.load_workspace", return_value=workspace),
                patch(
                    "gravity_sdk.resolver_batch.resolve_and_run", side_effect=resolved
                ) as run,
            ):
                code, result, error, _ = self.invoke(
                    [
                        "batch", "run", "--input", str(path),
                        "--concurrency", "2", "--max-pages", "7",
                        "--max-items", "321",
                    ]
                )

        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("gravity-insight.resolver-batch.v1", result["schema_version"])
        self.assertEqual(["apps:alpha", "apps:zeta"], [
            item["request_id"] for item in result["results"]
        ])
        self.assertEqual(2, run.call_count)
        self.assertTrue(all(call.kwargs["max_workers"] == 1 for call in run.call_args_list))
        self.assertTrue(all(call.kwargs["max_pages"] == 7 for call in run.call_args_list))
        self.assertTrue(all(call.kwargs["max_items"] == 321 for call in run.call_args_list))

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
        self.assertEqual(
            "Run `gravity batch schema` and retry with only the documented wrapper and item fields.",
            error["error"]["next_action"],
        )
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

    def test_raw_analysis_query_dry_run_is_rejected_without_reading(self):
        code, _, error, client = self.invoke(
            [
                "analysis", "query", "--kind", "event",
                "--input", "{}", "--dry-run",
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("dry_run", error["error"]["field"])
        self.assertEqual([], client.read_calls)

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

    def test_operations_command_is_the_only_discovery_entrypoint(self):
        client = GravityInsightClient.from_env()
        client.operation_ids = {
            item["operation_id"] for item in client.operations(stability=None)
        }
        code, current, _, _ = self.invoke(
            ["operations", "search", "retention"], client=client
        )
        self.assertEqual(0, code)
        self.assertIn("operations", current)
        self.assertNotIn("capabilities", current)
        code, _, _, _ = self.invoke(["capabilities", "search", "retention"])
        self.assertEqual(2, code)

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

    def test_analysis_segment_compact_spec_previews_then_executes_one_read(self):
        spec = json.dumps({"name": "private audience", "start": "2026-08-01"})
        code, preview, error, client = self.invoke([
            "analysis", "segment", "evaluate", "--app", "101",
            "--spec", spec, "--dry-run",
        ])
        self.assertEqual((0, None, []), (code, error, client.read_calls))
        self.assertEqual(("compiled", False), (
            preview["status"], preview["network_called"]
        ))
        self.assertNotIn("private audience", repr(preview))
        code, result, error, client = self.invoke([
            "analysis", "segment", "evaluate", "--app", "101", "--spec", spec,
        ])
        self.assertEqual((0, None), (code, error))
        self.assertEqual(
            "analysis.segment.evaluate_percent", client.read_calls[0][0]
        )
        self.assertEqual("private audience", client.read_calls[0][1]["name"])

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

    def test_dashboard_snapshot_cli_binds_one_workspace_and_product(self):
        expected = {"schema_version": "gravity-insight.dashboard-snapshot.v1", "ok": True}
        workspace = object()
        with (
            patch("gravity_sdk.dashboard_snapshot_cli.load_workspace", return_value=workspace),
            patch("gravity_sdk.dashboard_snapshot_cli.resolve_workspace_app", return_value=17) as resolve,
            patch("gravity_sdk.dashboard_snapshot_cli.dashboard_snapshot", return_value=expected) as snapshot,
        ):
            code, result, error, client = self.invoke([
                "analysis", "dashboard", "snapshot", "--app", "main", "--ref", "Overview",
                "--concurrency", "4", "--max-pages", "3", "--max-items", "50",
            ])
        self.assertEqual((0, expected, None), (code, result, error))
        resolve.assert_called_once_with(workspace, "main")
        snapshot.assert_called_once_with(
            client, 17, "Overview", max_workers=4, max_pages=3, max_items=50
        )

    def test_dashboard_snapshot_help_exposes_trailing_output_options(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args(
                ["analysis", "dashboard", "snapshot", "--help"]
            )
        self.assertEqual(0, raised.exception.code)
        self.assertIn("--output", output.getvalue())
        self.assertIn("--format {json,ndjson}", output.getvalue())

    def test_dashboard_parser_marks_only_complete_unmixed_forms_as_networked(self):
        from gravity_sdk.onboarding import command_requires_credentials

        offline = (
            ["analysis", "dashboard"],
            ["analysis", "dashboard", "--kind", "tree"],
            ["analysis", "dashboard", "--input", "{}"],
            [
                "analysis", "dashboard", "--kind", "tree", "snapshot",
                "--app", "main", "--ref", "Overview",
            ],
        )
        for arguments in offline:
            with self.subTest(arguments=arguments):
                self.assertFalse(command_requires_credentials(arguments, cli.build_parser))
        self.assertTrue(command_requires_credentials(
            ["analysis", "dashboard", "--kind", "tree", "--input", "{}"],
            cli.build_parser,
        ))
        self.assertTrue(command_requires_credentials(
            ["analysis", "dashboard", "--kind", "tree", "--set", "app_id=17"],
            cli.build_parser,
        ))
        self.assertTrue(command_requires_credentials(
            ["analysis", "dashboard", "snapshot", "--app", "main", "--ref", "Overview"],
            cli.build_parser,
        ))

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

    def test_nested_help_uses_copyable_gravity_command(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args(["attribution", "snapshot", "--help"])

        self.assertEqual(0, raised.exception.code)
        self.assertTrue(output.getvalue().startswith("usage: gravity attribution snapshot"))

    def test_multidim_layout_scope_and_query_shortcuts(self):
        code, _, _, client = self.invoke(
            ["multidim", "templates", "list", "--scope", "mine"]
        )
        self.assertEqual(0, code)
        self.assertEqual("report.multidim.template.mine.list", client.read_calls[0][0])

        envelope = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True,
            "status": "success",
            "exit_code": 0,
        }
        with patch(
            "gravity_sdk.multidim_product.run_multidim_query",
            return_value=envelope,
        ) as run:
            code, result, _, _ = self.invoke(
                [
                    "multidim",
                    "query",
                    "--app",
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
                ]
            )
        self.assertEqual(0, code)
        self.assertEqual(envelope, result)
        inputs = run.call_args.args[1]
        self.assertEqual(["2026-08-01", "2026-08-02"], inputs["date_list"])
        self.assertEqual("day", inputs["time_dims"])
        self.assertEqual(["app", "advertiser"], inputs["data_dims"])
        self.assertEqual(["cost", "click"], inputs["metrics_list"])
        self.assertEqual(
            [
                {"field": "click_company", "operator": "IN", "values": ["bytedance"]},
                {"field": "app_id", "operator": "EQUALS", "values": ["7"]},
            ],
            inputs["filters"],
        )

    def test_multidim_shortcuts_override_set_and_input_and_reject_multiple_filters(self):
        raw = ('{"date_list":["2026-08-01","2026-08-02"],"time_dims":"day",'
               '"metrics_list":["cost"],"custom_metrics_list":["input"],'
               '"relate_dims":["input"],"filters":[]}')
        with patch("gravity_sdk.multidim_product.run_multidim_query", return_value={}) as run:
            code, _, _, _ = self.invoke([
                "multidim", "query", "--app", "7", "--input", raw,
                "--set", 'custom_metrics_list=["set"]', "--custom-metric", "custom_a,custom_b",
                "--set", 'relate_dims=["set"]', "--relate-dim", "campaign_name",
                "--set", 'filters=[{"field":"day","operator":"EQUALS","values":["input"]}]',
                "--filter", "advertiser_id", "IN", "1,2",
            ])
        inputs = run.call_args.args[1]
        self.assertEqual((0, ["custom_a", "custom_b"], ["campaign_name"]),
                         (code, inputs["custom_metrics_list"], inputs["relate_dims"]))
        self.assertEqual([1, 2], inputs["filters"][0]["values"])
        invalid = (
            (["--filter", "day", "EQUALS", "x", "--filter", "hour", "EQUALS", "1"], "filter"),
            (["--filter", "bad field", "IN", "x"], "filters[].field"),
            (["--filter", "day", "BAD", "x"], "filters[].operator"),
            (["--filter", "day", "IN", "x,"], "filter.values"),
        )
        for options, field in invalid:
            code, _, error, _ = self.invoke([
                "multidim", "query", "--app", "7", "--input", raw, *options
            ])
            self.assertEqual((2, field), (code, error["error"]["field"]))

    def test_multidim_rejects_multiple_time_dimensions(self):
        code, result, error, _ = self.invoke(
            ["multidim", "query", "--app", "7", "--time-dim", "day,hour"]
        )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("exactly one", error["error"]["message"])

    def test_multidim_query_accepts_controlled_multi_days(self):
        envelope = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True,
            "status": "success",
            "exit_code": 0,
        }
        with patch(
            "gravity_sdk.multidim_product.run_multidim_query",
            return_value=envelope,
        ) as run:
            code, result, _, _ = self.invoke(
                [
                    "multidim",
                    "query",
                    "--app",
                    "7",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-02",
                    "--time-dim",
                    "day",
                    "--metrics",
                    "multi_day_roi_all",
                    "--multi-days",
                    "2,3,7",
                ]
            )
        self.assertEqual(0, code)
        self.assertEqual(envelope, result)
        self.assertEqual([2, 3, 7], run.call_args.args[1]["multi_keys"])

        code, result, error, _ = self.invoke(
            ["multidim", "query", "--app", "7", "--multi-days", "3,2"]
        )
        self.assertEqual(2, code)
        self.assertIsNone(result)
        self.assertIn("unique ascending", error["error"]["message"])

    def test_multidim_query_include_total_uses_composite_with_page_bounds(self):
        class CompositeClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.bounded_read_calls = []

            def schema(self, operation_id: str):
                if operation_id == "report.multidim.metric.list":
                    return {
                        "operation_id": operation_id,
                        "domain": "report",
                        "resource": "metric",
                        "action": "list",
                    }
                if operation_id == "report.multidim.calc_total":
                    return {
                        "operation_id": operation_id,
                        "input_fields": {
                            "metrics_list": {},
                            "data_dims": {},
                            "data_list": {},
                        },
                    }
                return super().schema(operation_id)

            def read_all(
                self,
                operation_id: str,
                inputs: dict,
                *,
                max_pages: int = 1_000,
                max_items: int = 100_000,
                max_workers: int = 6,
            ):
                self.bounded_read_calls.append(
                    (operation_id, inputs, max_pages, max_items, max_workers)
                )
                if operation_id == "report.multidim.metric.list":
                    return {
                        "status": "success",
                        "data": {
                            "list": [
                                {
                                    "name": "cost",
                                    "exclusion_dims": [],
                                }
                            ]
                        },
                    }
                if operation_id == "report.multidim.query":
                    return {
                        "status": "success",
                        "data": {"list": [{"day": "2026-08-01", "cost": 1}]},
                    }
                raise AssertionError(operation_id)

            def read(self, operation_id: str, inputs: dict):
                self.read_calls.append((operation_id, inputs))
                if operation_id == "report.multidim.calc_total":
                    return {"status": "success", "data": {"list": [{"cost": 1}]}}
                return super().read(operation_id, inputs)

        client = CompositeClient()
        code, result, error, _ = self.invoke(
            [
                "multidim",
                "query",
                "--app",
                "7",
                "--start",
                "2026-08-01",
                "--end",
                "2026-08-02",
                "--time-dim",
                "day",
                "--metrics",
                "cost",
                "--include-total",
                "--all-pages",
                "--max-pages",
                "7",
                "--max-items",
                "321",
                "--concurrency",
                "9",
            ],
            client=client,
        )

        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual("gravity-insight.composite.multidim.v1", result["schema_version"])
        self.assertTrue(result["ok"])
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("success", result["status"])
        query_call = next(
            call
            for call in client.bounded_read_calls
            if call[0] == "report.multidim.query"
        )
        self.assertEqual((7, 321, 9), query_call[2:])
        self.assertEqual(
            [{"day": "2026-08-01", "cost": 1}],
            client.read_calls[0][1]["data_list"],
        )

    def test_multidim_include_total_propagates_partial_failure_exit_code(self):
        class PartialClient(FakeClient):
            def schema(self, operation_id: str):
                if operation_id == "report.multidim.calc_total":
                    return {"operation_id": operation_id, "input_fields": {"data_list": {}}}
                return super().schema(operation_id)

            def read(self, operation_id: str, inputs: dict):
                if operation_id == "report.multidim.query":
                    return {"ok": True, "status": "success", "data": {"list": [{"day": "2026-08-01"}]}}
                if operation_id == "report.multidim.calc_total":
                    return {
                        "ok": False,
                        "status": "error",
                        "error": {
                            "code": "UPSTREAM_UNAVAILABLE",
                            "category": "upstream",
                            "message": "unsafe upstream token=secret",
                        },
                    }
                return super().read(operation_id, inputs)

        code, result, error, _ = self.invoke(
            [
                "multidim", "query", "--app", "7",
                "--input", '{"metrics_list":[]}',
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--time-dim", "day", "--include-total",
            ],
            client=PartialClient(),
        )

        self.assertEqual(3, code)
        self.assertIsNone(error)
        self.assertFalse(result["ok"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(3, result["exit_code"])
        self.assertEqual("total", result["error"]["stage"])
        self.assertNotIn("token=secret", json.dumps(result))

        class ActionClient(PartialClient):
            def __init__(self, code: str, category: str):
                super().__init__()
                self.error_code = code
                self.error_category = category

            def read(self, operation_id: str, inputs: dict):
                if operation_id == "report.multidim.calc_total":
                    return {
                        "ok": False,
                        "status": "error",
                        "error": {
                            "code": self.error_code,
                            "category": self.error_category,
                            "retry_after_ms": 250 if self.error_code == "RATE_LIMITED" else None,
                        },
                    }
                return super().read(operation_id, inputs)

        actions = (
            ("AUTH_MISSING", "caller", "gravity auth status"),
            ("INPUT_INVALID", "caller", "operations describe"),
            ("RATE_LIMITED", "upstream", "retry_after_ms"),
        )
        for error_code, category, expected_action in actions:
            with self.subTest(error_code=error_code):
                action_code, action_result, _, _ = self.invoke(
                    [
                        "multidim", "query", "--app", "7",
                        "--input", '{"metrics_list":[]}',
                        "--start", "2026-08-01", "--end", "2026-08-02",
                        "--time-dim", "day", "--include-total",
                    ],
                    client=ActionClient(error_code, category),
                )
                self.assertEqual(2 if category == "caller" else 3, action_code)
                self.assertIn(expected_action, action_result["next_action"])

    def test_multidim_include_total_contract_change_is_nonzero_but_empty_is_success(self):
        class QueryClient(FakeClient):
            def __init__(self, status: str):
                super().__init__()
                self.status = status

            def read(self, operation_id: str, inputs: dict):
                if operation_id == "report.multidim.query":
                    return {"status": self.status, "data": {"list": []}}
                return super().read(operation_id, inputs)

        changed_code, changed, _, _ = self.invoke(
            [
                "multidim", "query", "--app", "7",
                "--input", '{"metrics_list":[]}',
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--time-dim", "day", "--include-total",
            ],
            client=QueryClient("contract_changed"),
        )
        failed_code, failed, _, _ = self.invoke(
            [
                "multidim", "query", "--app", "7",
                "--input", '{"metrics_list":[]}',
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--time-dim", "day", "--include-total",
            ],
            client=QueryClient("error"),
        )
        empty_code, empty, _, _ = self.invoke(
            [
                "multidim", "query", "--app", "7",
                "--input", '{"metrics_list":[]}',
                "--start", "2026-08-01", "--end", "2026-08-02",
                "--time-dim", "day", "--include-total",
            ],
            client=QueryClient("empty"),
        )

        self.assertEqual(3, changed_code)
        self.assertFalse(changed["ok"])
        self.assertEqual("contract_changed", changed["status"])
        self.assertEqual("query", changed["error"]["stage"])
        self.assertEqual(3, failed_code)
        self.assertFalse(failed["ok"])
        self.assertEqual("error", failed["status"])
        self.assertEqual("query", failed["error"]["stage"])
        self.assertEqual(0, empty_code)
        self.assertTrue(empty["ok"])
        self.assertEqual("empty", empty["status"])

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

    def test_attribution_snapshot_batches_every_stable_configuration(self):
        code, result, error, client = self.invoke(
            [
                "attribution", "snapshot", "--app-id", "101",
                "--concurrency", "8",
            ]
        )

        self.assertEqual(0, code)
        self.assertIsNone(error)
        self.assertEqual(
            "gravity-insight.attribution-snapshot.v1", result["schema_version"]
        )
        requests, concurrency = client.batch_calls[0]
        self.assertEqual(8, concurrency)
        self.assertEqual(
            list(ATTRIBUTION_SNAPSHOT_OPERATIONS),
            [item["operation_id"] for item in requests],
        )
        self.assertTrue(all(item["inputs"] == {"app_id": "101"} for item in requests))

    def test_attribution_snapshot_returns_partial_results_with_aggregate_exit(self):
        class PartialClient(FakeClient):
            def batch(self, requests: list[dict], concurrency: int = 4):
                self.batch_calls.append((requests, concurrency))
                return [
                    {
                        "operation_id": item["operation_id"],
                        "request_id": item["request_id"],
                        "ok": index != 0,
                        **(
                            {}
                            if index
                            else {
                                "error": {
                                    "category": "upstream",
                                    "code": "UPSTREAM_UNAVAILABLE",
                                }
                            }
                        ),
                    }
                    for index, item in enumerate(requests)
                ]

        code, result, error, _ = self.invoke(
            ["attribution", "snapshot", "--app-id", "101"],
            client=PartialClient(),
        )

        self.assertEqual(3, code)
        self.assertIsNone(error)
        self.assertEqual("partial", result["status"])
        self.assertEqual(1, result["failure_count"])

    def test_attribution_snapshot_rejects_invalid_app_id_before_batch(self):
        client = FakeClient()

        for invalid in ("alias", "-1"):
            with self.subTest(app_id=invalid):
                code, result, error, _ = self.invoke(
                    ["attribution", "snapshot", "--app-id", invalid],
                    client=client,
                )
                self.assertEqual(2, code)
                self.assertIsNone(result)
                self.assertEqual("INPUT_INVALID", error["error"]["code"])
                self.assertNotIn(invalid, json.dumps(error))
        self.assertEqual([], client.batch_calls)

    def test_operation_filters_apply_domain_platform_and_stability(self):
        code, result, _, client = self.invoke(
            [
                "operations",
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
                for item in result["operations"]
            )
        )
        self.assertEqual(
            ("promotion", "bytedance", "stable"), client.operation_calls[-1]
        )

        code, result, _, client = self.invoke(["operations", "list"])
        self.assertEqual(0, code)
        self.assertEqual((None, None, None), client.operation_calls[-1])
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

    def test_json_boundary_preserves_business_fields_and_scrubs_credentials(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaXh0dXJlIn0.signature"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli._write_json(
                {
                    "authorization": "Bearer credential-authorization",
                    "cookie": "credential-cookie",
                    "access_token": "credential-access",
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
                    "continuation_token": "cursor-1",
                    "filter": {"field": "app_id", "operator": "EQUALS", "values": [7]},
                    "nested": {
                        "refresh_token": "credential-refresh",
                        "message": "Bearer credential-bearer",
                        "rows": [
                            {"jwt": jwt, "email": "nested@example.invalid"},
                            {"gravity_authorization": "credential-nested"},
                        ],
                    },
                    "safe": "kept",
                }
            )
        rendered_text = output.getvalue()
        rendered = json.loads(rendered_text)
        for secret in (
            "credential-authorization", "credential-cookie", "credential-access",
            "credential-refresh", "credential-nested", "credential-bearer", jwt,
        ):
            self.assertNotIn(secret, rendered_text)
        self.assertNotIn("authorization", rendered)
        self.assertNotIn("cookie", rendered)
        self.assertNotIn("access_token", rendered)
        self.assertNotIn("token", rendered)
        self.assertNotIn("session_token", rendered)
        self.assertTrue({
            "operator_name", "dept", "callback_url", "click_url", "postback_url",
            "email_address", "phone", "mobile", "user_name", "creator", "asset_url",
            "owner_email", "owner_phone", "owner_mobile", "owner_user_id",
            "owner_user_name",
        } <= rendered.keys())
        self.assertEqual("Private Operator", rendered["operator_name"])
        self.assertEqual("Private Dept", rendered["dept"])
        self.assertEqual("https://private.invalid/asset", rendered["asset_url"])
        self.assertEqual("private@example.invalid", rendered["owner_email"])
        self.assertEqual("private-id", rendered["owner_user_id"])
        self.assertEqual("cursor-1", rendered["continuation_token"])
        self.assertEqual("[REDACTED]", rendered["nested"]["rows"][0]["jwt"])
        self.assertEqual("nested@example.invalid", rendered["nested"]["rows"][0]["email"])
        ndjson = cli._render_ndjson([
            {"nested": [{"access_token": "credential-ndjson", "file_url": "kept"}]}
        ])
        self.assertNotIn("credential-ndjson", ndjson)
        self.assertIn('"file_url": "kept"', ndjson)

    def test_cli_preserves_the_sdk_business_field_set(self):
        sdk_result = {
            "schema_version": "gravity-insight.read.v1",
            "ok": True,
            "status": "success",
            "data": {
                "email": "member@example.invalid",
                "operator_name": "Operator",
                "dept_id": 7,
                "icon_url": "https://business.invalid/icon",
                "owner_user_id": "user-1",
                "continuation_token": "cursor-1",
            },
        }
        stdout = io.StringIO()
        with (
            patch("gravity_sdk.cli.dispatch_command", return_value=sdk_result),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(0, cli.main(["doctor"]))
        self.assertEqual(sdk_result, json.loads(stdout.getvalue()))

    def test_error_output_scrubs_credential_assignments_bearer_and_jwt(self):
        secrets = (
            "credential-authorization", "credential-cookie", "credential-access",
            "credential-bearer", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJlcnJvciJ9.signature",
        )
        message = (
            f"authorization={secrets[0]}, cookie={secrets[1]}, "
            f"access_token={secrets[2]}, Bearer {secrets[3]}, jwt={secrets[4]}"
        )
        stderr = io.StringIO()
        with (
            patch("gravity_sdk.cli.dispatch_command", side_effect=RuntimeError(message)),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(4, cli.main(["doctor"]))
        for secret in secrets:
            self.assertNotIn(secret, stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())

    def test_analysis_json_boundary_uses_the_same_credential_only_policy(self):
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
            shortcut_args(app_id="1001"),
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
