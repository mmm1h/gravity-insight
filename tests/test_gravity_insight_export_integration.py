from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from gravity_sdk.blob import (
    AuthorizedBlobSource,
    BlobMetadata,
    BlobPolicy,
    BlobTransferError,
    MagicSignature,
    SafeBlobTransfer,
)
from gravity_sdk.errors import (
    InputValidationError,
    PolicyViolation,
)
from gravity_sdk.client import GravityInsightClient
from gravity_sdk.export_contracts import ExportContractRegistry, validate_wire_projection
from gravity_sdk.export_gateway import (
    ExportTaskCenter,
    GravityExportGateway,
)
from gravity_sdk.export_cli import output_argument
from gravity_sdk.export_models import (
    ExportCreationRequest,
    ExportPrivacyContract,
    ExportRuntimeError,
    ExportState,
)
from gravity_sdk.export_privacy import ExportPrivacyFinalizer
from gravity_sdk.export_results import _snapshot_completeness, export_result_envelope
from gravity_sdk.models import load_operation_manifest
from gravity_sdk.registry import (
    EffectRoute,
    PolicyEngine,
    Registry,
    _consume_authorized_blob_download,
    _consume_authorized_request,
)
from gravity_sdk.cli import build_parser, main


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "exports"
    / "routes-v1.json"
)
COVERAGE_PATH = ROOT / "src" / "gravity_sdk" / "census" / "data" / "coverage.json"
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def read_registry() -> Registry:
    operations = []
    for path in sorted(
        (ROOT / "src" / "gravity_sdk" / "manifests").glob("*.json")
    ):
        operations.extend(load_operation_manifest(path))
    return Registry(operations)


class FakeRuntime:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def _request_insight(
        self,
        method,
        path,
        *,
        policy_authorization,
        params,
        json_body,
        **kwargs,
    ):
        query, body = _consume_authorized_request(
            policy_authorization,
            method=method,
            path=path,
            query=params,
            body=json_body,
        )
        self.calls.append((method, path, query, body, kwargs))
        return SimpleNamespace(
            status_code=200,
            payload=self.payloads.pop(0),
            headers={},
        )


class NeverBlobTransport:
    def open_download(self, *args, **kwargs):
        raise AssertionError("receipt rejection must happen before transport")

    def upload(self, *args, **kwargs):
        raise AssertionError("not used")


class ExportContractTests(unittest.TestCase):
    def test_all_22_census_routes_have_exact_method_and_effect_contracts(self):
        registry = ExportContractRegistry.from_file(CONTRACT_PATH)
        coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
        census = {
            (route["method"], route["path"])
            for route in coverage["routes"]
            if route["status"] == "uncovered_export"
        }
        contracted = {(item.method, item.path) for item in registry.all()}
        self.assertEqual(22, len(registry.all()))
        self.assertEqual(census, contracted)
        self.assertEqual(
            {
                "export_job_create": 16,
                "export_status": 4,
                "export_download": 1,
                "export_cancel": 1,
            },
            {
                effect: sum(item.effect == effect for item in registry.all())
                for effect in {
                    "export_job_create",
                    "export_status",
                    "export_download",
                    "export_cancel",
                }
            },
        )

    def test_unverified_route_is_catalog_only(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        with self.assertRaisesRegex(PolicyViolation, "catalog-only") as raised:
            policy._prepare_effect_request(
                "export.openapi.event.submit",
                "export_job_create",
                {},
            )
        self.assertEqual("operation_id", raised.exception.field)
        self.assertTrue(
            raised.exception.next_action.startswith("Run `gravity export describe ")
        )
        self.assertNotIn("export list`", raised.exception.next_action)

    def test_monetization_export_is_callable_and_declares_create_time_truncation(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        operation_id = "export.analysis.monetization_detail.start"
        description = contracts.describe(operation_id)

        self.assertTrue(description["currently_callable"])
        self.assertIsNone(description["block_reason"])
        self.assertEqual(
            "callable_with_create_time_truncation_audit",
            description["pagination_and_scale"]["status"],
        )
        self.assertEqual(
            ["事件发生时间", "客户ID"],
            description["columns"]["required_output_headers"],
        )
        self.assertEqual(
            ["AdEventTime", "ClientID"],
            description["columns"]["allowed_codes"],
        )
        self.assertEqual("complete", description["examples_status"])
        self.assertEqual(
            192 * 1024 * 1024,
            contracts.get(operation_id).privacy["max_uncompressed_size_bytes"],
        )

    def test_material_export_description_is_complete_and_runnable(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        description = contracts.describe("export.material.report.start")
        self.assertEqual(
            "gravity export describe export.material.report.start",
            contracts.get("export.material.report.start").capability()[
                "describe_command"
            ],
        )
        self.assertTrue(description["currently_callable"])
        self.assertEqual("export_job_create", description["effect"])
        self.assertFalse(
            description["input_schema"]["additional_properties"]
        )
        self.assertEqual([], description["input_schema"]["optional"])
        self.assertIn("filters", description["input_schema"]["required"])
        self.assertFalse(
            description["pagination_and_scale"]["page_size_limits_total_rows"]
        )
        self.assertEqual("complete", description["examples_status"])
        self.assertEqual(
            description["examples"][0]["input"]["export_col_list"],
            description["examples"][0]["columns"],
        )
        self.assertEqual(
            ["start", "wait", "download"], description["workflow"]["order"]
        )
        self.assertIn("gravity export run ", description["workflow"]["default_command"])
        self.assertTrue(
            all(
                command.startswith("gravity export ")
                for command in description["workflow"]["commands"]
            )
        )
        self.assertTrue(
            description["next_action"].startswith("Run `gravity export run ")
        )
        self.assertNotIn("python -m", json.dumps(description))
        self.assertEqual(
            "素材名称",
            description["columns"]["output_headers_by_code"]["file_name"],
        )

    def test_user_event_export_description_exposes_complete_file_schema(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        description = contracts.describe("export.analysis.user_event.start")
        columns = description["columns"]

        self.assertTrue(description["currently_callable"])
        self.assertEqual([], description["input_schema"]["optional"])
        expected = ["客户(client_id)", "用户注册时间", "事件发生时间", "事件", "事件属性"]
        self.assertEqual(expected, columns["allowed_codes"])
        self.assertEqual(expected, columns["required_codes"])
        self.assertEqual(
            ["identifier", "datetime", "datetime", "text", "json_object_or_array"],
            [item["logical_type"] for item in columns["file_schema"]["columns"]],
        )
        self.assertEqual("complete", description["examples_status"])
        self.assertFalse(description["pagination_and_scale"]["page_size_limits_total_rows"])
        origin = ExportContractRegistry.from_file(CONTRACT_PATH)
        self.assertTrue(origin.describe("export.analysis.origin_event.start")["currently_callable"])
        self.assertEqual(".csv.gz", origin.get("export.analysis.origin_event.start").privacy["extension"])

    def test_export_completion_statuses_are_mutually_distinct(self):
        receipt = SimpleNamespace(
            destination=Path("fixture.xlsx"), size_bytes=1, source_size_bytes=1,
            source_sha256="0" * 64, committed_sha256="0" * 64, content_type="xlsx",
            extension=".xlsx", etag=None, last_modified=None,
            finalization=SimpleNamespace(schema=("id",), rows_processed=0),
        )
        def status(error=None):
            result = SimpleNamespace(state=ExportState.COMMITTED if error is None else ExportState.FAILED,
                job_id="19", history=(), receipt=receipt if error is None else None,
                error=error, resumable=error is not None)
            return export_result_envelope("export.fixture", result)["completion_status"]
        statuses = {status(), *(status(BlobTransferError(name, code=code, stage="test")) for name, code in (
            ("partial", "BLOB_TRANSPORT_ERROR"), ("truncated", "BLOB_SIZE_LIMIT"),
            ("expired", "EXPORT_UPSTREAM_EXPIRED")))}
        receipt.finalization.rows_processed = 1
        statuses.update((status(), ExportContractRegistry.from_file(CONTRACT_PATH).describe(
            "export.analysis.stream_event.start")["completion_status"]))
        self.assertEqual({"empty", "partial", "truncated", "expired", "complete", "gap"}, statuses)
        pinned = {
            "known_total_items": 1_212_315,
            "known_total_source": "analysis.monetization_detail.list.page.total_items",
            "known_total_freshness": "create_time_preflight",
        }
        receipt.finalization.rows_processed = 1_000_000
        truncated = export_result_envelope(
            "export.analysis.monetization_detail.start",
            SimpleNamespace(
                state=ExportState.COMMITTED, job_id="19", history=(),
                receipt=receipt, error=None, resumable=False,
                completeness={
                    **pinned, "file_rows": 1_000_000, "missing_rows": 212_315,
                    "truncated": True, "complete": False, "row_limit": 1_000_000,
                },
            ),
        )
        self.assertEqual("truncated", truncated["completion_status"])
        self.assertEqual(1_000_000, truncated["file"]["rows"])
        self.assertEqual(1_212_315, truncated["completeness"]["known_total_items"])
        self.assertEqual(212_315, truncated["completeness"]["missing_rows"])
        uncapped = export_result_envelope(
            "export.analysis.monetization_detail.start",
            SimpleNamespace(
                state=ExportState.COMMITTED, job_id="19", history=(),
                receipt=receipt, error=None, resumable=False,
            ),
        )
        self.assertEqual("partial", uncapped["completion_status"])
        contract = ExportContractRegistry.from_file(CONTRACT_PATH).get("export.analysis.user_detail.start")
        validate_wire_projection(contract, SimpleNamespace(
            payload={"field_map": {"ClientID": "客户ID", "CreateTime": "注册时间"}},
            requested_columns=("ClientID", "CreateTime"),
        ))

    def test_snapshot_completeness_includes_mapping_values(self):
        self.assertEqual(
            {"completeness": {"complete": True}},
            _snapshot_completeness(SimpleNamespace(completeness={"complete": True})),
        )

    def test_empty_export_input_reports_a_field_and_public_recovery_command(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        client = object.__new__(GravityInsightClient)
        client._export_contracts = contracts
        client._export_policy = PolicyEngine(
            read_registry(), effect_routes=contracts.effect_routes()
        )
        client._export_runtime = SimpleNamespace()
        with self.assertRaises(InputValidationError) as raised:
            client._export_request(
                "export.material.report.start",
                {},
                requested_columns=("file_name", "gravity_material_id"),
                idempotency_key="fixture-export-key-0001",
            )
        self.assertEqual("data_dims", raised.exception.field)
        self.assertTrue(
            raised.exception.next_action.startswith("Run `gravity export describe ")
        )
        self.assertNotIn("contracts/", raised.exception.next_action)

    def test_online_task_routes_lock_the_observed_request_locations(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        self.assertEqual("body", contracts.get("export.task.list").request["location"])
        self.assertEqual("query", contracts.get("export.task.progress").request["location"])
        self.assertEqual("query", contracts.get("export.task.cancel").request["location"])
        self.assertEqual("none", contracts.get("export.task_type.list").request["location"])

    def test_wire_projection_must_equal_the_approved_request_columns(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        client = object.__new__(GravityInsightClient)
        client._export_contracts = contracts
        client._export_policy = PolicyEngine(
            read_registry(),
            effect_routes=contracts.effect_routes(),
        )
        client._export_runtime = SimpleNamespace()
        # Export inputs are now schema-validated before projection comparison, so
        # keep every unrelated field valid and isolate the projection mismatch.
        payload = {
            "data_dims": ["material"],
            "date_dims": "total",
            "metrics_list": ["stat_cost"],
            "gravity_metrics_list": ["AppRealRegisterCnt"],
            "stat_list": [],
            "filters": [
                {"field": "ad_platform", "operator": "EQUALS", "values": ["bytedance"]},
                {"field": "app_id", "operator": "IN", "values": ["fixture"]},
            ],
            "date_list": ["2026-08-08", "2026-08-08"],
            "relate_dims": [],
            "order_by": [],
            "page": 1,
            "page_size": 1,
            "export_col_list": ["file_name", "gravity_material_id", "unexpected"],
            "task_name": "fixture",
        }
        with self.assertRaisesRegex(ExportRuntimeError, "wire export columns"):
            client._export_request(
                "export.material.report.start",
                payload,
                requested_columns=("file_name", "gravity_material_id"),
                idempotency_key="fixture-export-key-0001",
            )

    def test_export_run_accepts_describe_request_column_codes(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        client = object.__new__(GravityInsightClient)
        client._export_contracts = contracts
        client._export_policy = PolicyEngine(
            read_registry(),
            effect_routes=contracts.effect_routes(),
        )
        client._export_runtime = SimpleNamespace()
        payload = {
            "app_id": 1,
            "field_map": {"ClientID": "客户ID", "CreateTime": "注册时间"},
            "task_name": "fixture-user-detail",
            "global_conditions": [
                {
                    "field": "create_date_list",
                    "operator": "RANGE_IN",
                    "type": "default_user",
                    "value": ["2026-08-16 00:00:00", "2026-08-16 23:59:59"],
                }
            ],
            "postback_conditions": [],
            "user_cond_logic": "AND",
            "postback_cond_logic": "AND",
        }
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "user-detail.xlsx"
            with patch.object(client, "_export_gateway") as gateway:
                gateway.return_value.create.side_effect = AssertionError(
                    "create must not run until column codes are accepted"
                )
                result = client.export_run(
                    "export.analysis.user_detail.start",
                    payload,
                    destination,
                    requested_columns=("ClientID", "CreateTime"),
                    idempotency_key="fixture-export-key-0001",
                )
        self.assertNotEqual(
            "requested export columns violate the privacy contract",
            (result.get("error") or {}).get("message"),
        )
        self.assertTrue(gateway.return_value.create.called)


class EffectReceiptTests(unittest.TestCase):
    def setUp(self):
        self.status = EffectRoute(
            operation_id="export.fixture.status",
            effect="export_status",
            method="GET",
            path="/turbo_engine/api/v1/task/download/progress/",
            request_location="body",
            allowed_fields=frozenset({"task_id"}),
            required_fields=frozenset({"task_id"}),
            executable=True,
            contract_status="verified",
        )
        self.create = EffectRoute(
            operation_id="export.fixture.start",
            effect="export_job_create",
            method="POST",
            path="/report/api/v3/datareport/material_get/export/",
            request_location="body",
            allowed_fields=frozenset({"task_name"}),
            required_fields=frozenset({"task_name"}),
            executable=True,
            contract_status="verified",
        )
        self.policy = PolicyEngine(
            read_registry(),
            effect_routes=(self.status, self.create),
        )

    def test_effect_receipt_is_exact_one_shot_and_stage_specific(self):
        receipt = self.policy._prepare_effect_request(
            self.status.operation_id,
            "export_status",
            {"task_id": 7},
        )
        with self.assertRaisesRegex(PolicyViolation, "effect"):
            self.policy._prepare_effect_request(
                self.status.operation_id,
                "export_cancel",
                {"task_id": 7},
            )
        query, body = _consume_authorized_request(
            receipt,
            method="GET",
            path=self.status.path,
            query={},
            body={"task_id": 7},
        )
        self.assertEqual({}, query)
        self.assertEqual({"task_id": 7}, body)
        with self.assertRaisesRegex(PolicyViolation, "already consumed"):
            _consume_authorized_request(
                receipt,
                method="GET",
                path=self.status.path,
                query={},
                body={"task_id": 7},
            )

    def test_effect_receipt_rejects_wire_mutation(self):
        receipt = self.policy._prepare_effect_request(
            self.create.operation_id,
            "export_job_create",
            {"task_name": "fixture"},
        )
        with self.assertRaisesRegex(PolicyViolation, "already consumed"):
            _consume_authorized_request(
                receipt,
                method="POST",
                path=self.create.path,
                query={},
                body={"task_name": "changed"},
            )

    def test_blob_receipt_requires_consumed_status_and_is_job_bound_one_shot(self):
        status_receipt = self.policy._prepare_effect_request(
            self.status.operation_id,
            "export_status",
            {"task_id": 7},
        )
        with self.assertRaisesRegex(PolicyViolation, "unconsumed"):
            self.policy.authorize_blob_download(
                status_receipt,
                job_id="7",
                url="https://files.example.test/signed/report.csv?Expires=1786280700",
                declared_path="/signed/report.csv",
                expires_at=NOW + timedelta(minutes=5),
                authorization_scope="export_download:fixture:7",
            )
        _consume_authorized_request(
            status_receipt,
            method="GET",
            path=self.status.path,
            query={},
            body={"task_id": 7},
        )
        blob_receipt = self.policy.authorize_blob_download(
            status_receipt,
            job_id="7",
            url="https://files.example.test/signed/report.csv?Expires=1786280700",
            declared_path="/signed/report.csv",
            expires_at=NOW + timedelta(minutes=5),
            authorization_scope="export_download:fixture:7",
        )
        source = AuthorizedBlobSource(
            url="https://files.example.test/signed/report.csv?Expires=1786280700",
            declared_path="/signed/report.csv",
            expires_at=NOW + timedelta(minutes=5),
            authorization_scope="export_download:fixture:7",
            job_id="7",
            declared_mime_type="text/csv",
            effect_receipt=blob_receipt,
        )
        _consume_authorized_blob_download(blob_receipt, source=source)
        with self.assertRaisesRegex(PolicyViolation, "already consumed"):
            _consume_authorized_blob_download(blob_receipt, source=source)

    def test_production_blob_policy_rejects_missing_effect_receipt_before_network(self):
        source = AuthorizedBlobSource(
            url="https://files.example.test/signed/report.csv",
            declared_path="/signed/report.csv",
            expires_at=NOW + timedelta(minutes=5),
            authorization_scope="export_download:fixture:7",
            job_id="7",
            declared_mime_type="text/csv",
        )
        policy = BlobPolicy(
            allowed_extensions=frozenset({".csv"}),
            allowed_mime_types=frozenset({"text/csv"}),
            magic_signatures={".csv": (MagicSignature(0, b"id,"),)},
            mime_types_by_extension={".csv": ("text/csv",)},
            allowed_hosts=frozenset({"files.example.test"}),
            allowed_path_prefixes={"files.example.test": ("/signed/",)},
            destination_root=ROOT / "tmp",
            temporary_root=ROOT / "tmp",
            require_effect_receipt=True,
        )
        with self.assertRaisesRegex(PolicyViolation, "requires a policy"):
            SafeBlobTransfer(
                NeverBlobTransport(),
                wall_clock=lambda: NOW,
            ).download(source, "fixture.csv", policy)


class GatewayAndCliTests(unittest.TestCase):
    def test_gateway_uses_distinct_create_and_status_receipts(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        runtime = FakeRuntime(
            [
                {"code": 0, "data": {"task_id": 19}},
                {"code": 0, "data": {"status": 1}},
            ]
        )
        gateway = GravityExportGateway(
            contracts,
            policy,
            runtime,
            "export.material.report.start",
        )
        contract = contracts.get("export.material.report.start")
        payload = {
            field: []
            for field in contract.request["required_fields"]
        }
        payload.update(
            {
                "data_dims": ["material"],
                "date_dims": "total",
                "page": 1,
                "page_size": 1,
                "task_name": "fixture",
            }
        )
        created = gateway.create(
            ExportCreationRequest(
                payload,
                ("file_name", "gravity_material_id"),
                "fixture-export-key-0001",
            ),
            timeout_seconds=10,
        )
        status = gateway.status("19", timeout_seconds=10)
        self.assertEqual(ExportState.QUEUED, created.state)
        self.assertEqual(ExportState.RUNNING, status.state)
        self.assertEqual({"task_id": 19}, runtime.calls[1][2])
        self.assertEqual({}, runtime.calls[1][3])
        self.assertEqual(
            ["export_job_create", "export_status"],
            [call[4]["attempts"] == 1 and "export_job_create" or "export_status" for call in runtime.calls],
        )

    def test_cancel_acknowledgement_is_not_reported_as_terminal(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        runtime = FakeRuntime([{"code": 0, "data": {}}])
        gateway = GravityExportGateway(
            contracts,
            policy,
            runtime,
            "export.material.report.start",
        )
        snapshot = gateway.cancel("19", timeout_seconds=10)
        self.assertEqual(ExportState.CANCEL_REQUESTED, snapshot.state)
        self.assertEqual({"task_id": 19}, runtime.calls[0][2])
        self.assertEqual({}, runtime.calls[0][3])

    def test_wait_failed_job_is_an_upstream_error_not_exit_zero_success(self):
        gateway = SimpleNamespace(
            status=lambda job_id, timeout_seconds: SimpleNamespace(
                job_id=job_id,
                state=ExportState.FAILED,
                download_source=None,
                failure_code="EXPORT_UPSTREAM_FAILED",
                failure_retryable=False,
            )
        )
        client = object.__new__(GravityInsightClient)
        with patch.object(
            GravityInsightClient, "_export_gateway", return_value=gateway
        ):
            result = client.export_wait(
                "export.material.report.start",
                "job-failed",
                interval_seconds=2,
                timeout_seconds=30,
            )
        self.assertFalse(result["ok"])
        self.assertEqual("FAILED", result["state"])
        self.assertEqual("UPSTREAM_UNAVAILABLE", result["error"]["code"])
        self.assertEqual("upstream", result["error"]["category"])
        self.assertTrue(
            result["error"]["next_action"].startswith("Run `gravity export list ")
        )

    def test_task_list_maps_operation_and_redacts_request_values(self):
        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        runtime = FakeRuntime(
            [
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "id": 19,
                                "task_name": "sensitive-product-name",
                                "task_type": "material_report",
                                "status": 2,
                                "download_url": "https://example.invalid/file.xlsx",
                                "create_time": "2026-08-09 12:00:00",
                            }
                        ],
                        "page_info": {"page": 1, "page_size": 100},
                    },
                }
            ]
        )
        result = ExportTaskCenter(contracts, policy, runtime).list()
        job = result["jobs"][0]
        self.assertEqual("gravity-insight.export-list.v2", result["schema_version"])
        self.assertEqual({"page": 1, "page_size": 100}, result["page_info"])
        self.assertEqual("export.material.report.start", job["operation_id"])
        self.assertEqual("verified", job["operation_mapping"])
        self.assertNotIn("task_name", job)
        self.assertNotIn("sensitive-product-name", json.dumps(job))
        self.assertTrue(job["request_summary"]["parameter_values_redacted"])
        self.assertIn("filters", job["request_summary"]["field_names"])

    def test_origin_event_evaluate_is_callable_via_export_evaluate(self):
        from types import SimpleNamespace

        contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        evaluate = next(
            contract
            for contract in contracts.all()
            if contract.effect == "export_status"
            and str(contract.operation_id).endswith(".evaluate")
        )
        description = contracts.describe(evaluate.operation_id)
        self.assertTrue(description["currently_callable"])
        self.assertIn("gravity export evaluate ", description["next_action"])
        self.assertEqual(["evaluate"], description["workflow"]["order"])
        captured: list[tuple[str, object]] = []

        class Runtime:
            def _request_insight(self, method, path, **kwargs):
                captured.append((method, path, kwargs.get("json_body")))
                return SimpleNamespace(
                    status_code=200, payload={"code": 0, "data": {"total": 1}}
                )

        from gravity_sdk.export_client import ExportClientMixin
        from gravity_sdk.registry import PolicyEngine

        class Client(ExportClientMixin):
            def __init__(self):
                self._export_contracts = contracts
                self._export_policy = PolicyEngine(
                    read_registry(), effect_routes=contracts.effect_routes()
                )
                self._export_runtime = Runtime()

        payload = {
            name: 29034827 if name == "app_id" else evaluate.request["fixed_fields"].get(name, [])
            if name in {"conditions", "event_name_list"}
            else evaluate.request["fixed_fields"].get(name, "AND" if name == "cond_logic" else "x")
            for name in evaluate.request["required_fields"]
        }
        payload["event_name_list"] = ["$preset"]
        payload["time_range"] = ["2026-08-11", "2026-08-17"]
        payload["conditions"] = []
        payload.update(evaluate.request.get("fixed_fields") or {})
        result = Client().export_evaluate(evaluate.operation_id, payload)
        self.assertEqual(1, result["estimated_rows"])
        self.assertEqual("gravity-insight.export-evaluate.v1", result["schema_version"])
        self.assertEqual("POST", captured[0][0])
        self.assertIn("evaluate_data", captured[0][1])

    def test_cli_declares_all_nine_export_commands(self):
        parser = build_parser()
        cases = {
            "list-capabilities": ["export", "list-capabilities"],
            "describe": [
                "export",
                "describe",
                "export.material.report.start",
            ],
            "start": [
                "export",
                "start",
                "export.material.report.start",
                "--input",
                "request.json",
                "--columns",
                "file_name,gravity_material_id",
                "--idempotency-key",
                "fixture-export-key-0001",
            ],
            "run": [
                "export", "run", "export.material.report.start",
                "--input", "{}", "--columns", "file_name,gravity_material_id",
                "--idempotency-key", "fixture-export-key-0001",
                "--output", "report.csv",
            ],
            "status": [
                "export",
                "status",
                "19",
                "--operation-id",
                "export.material.report.start",
            ],
            "wait": [
                "export",
                "wait",
                "19",
                "--operation-id",
                "export.material.report.start",
            ],
            "download": [
                "export",
                "download",
                "19",
                "--operation-id",
                "export.material.report.start",
                "--output",
                "report.csv",
            ],
            "cancel": [
                "export",
                "cancel",
                "19",
                "--operation-id",
                "export.material.report.start",
            ],
            "list": ["export", "list"],
            "evaluate": [
                "export",
                "evaluate",
                next(
                    contract.operation_id
                    for contract in ExportContractRegistry.from_file(CONTRACT_PATH).all()
                    if str(contract.operation_id).endswith(".evaluate")
                ),
                "--input",
                "request.json",
            ],
            "task-types": ["export", "task-types"],
        }
        self.assertEqual(11, len(cases))
        for name, argv in cases.items():
            with self.subTest(name=name):
                parsed = parser.parse_args(argv)
                self.assertEqual(name, parsed.export_command)
                if name in {"run", "download"}:
                    self.assertIsNone(output_argument(parsed))

    def test_cli_export_extension_error_uses_builtin_14_code_and_action(self):
        stderr = io.StringIO()
        error = ExportRuntimeError(
            "schema changed",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
        with patch("gravity_sdk.cli.dispatch_command", side_effect=error):
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["export", "list"])
        envelope = json.loads(stderr.getvalue())
        self.assertEqual(3, exit_code)
        self.assertEqual("CONTRACT_CHANGED", envelope["error"]["code"])
        self.assertIn("re-verify", envelope["error"]["next_action"])


class XlsxPrivacyFinalizerTests(unittest.TestCase):
    def test_promoted_xlsx_shapes_keep_headers_for_empty_and_nonempty_files(self):
        headers = (("用户ID",), ("客户ID", "注册时间"),
                   ("客户ID", "注册时间"), ("客户ID", "订单ID"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for family, header in enumerate(headers):
                for rows in ((), (tuple("value" for _ in header),)):
                    source, output = root / f"source-{family}-{len(rows)}.xlsx", root / f"output-{family}-{len(rows)}.xlsx"
                    _write_xlsx(source, header, rows)
                    contract = ExportPrivacyContract(allowed_columns=header,
                        required_columns=header, classification="user_level", format="xlsx")
                    result = ExportPrivacyFinalizer(contract).finalize(source, output, _xlsx_metadata(source))
                    self.assertEqual((header, len(rows)), (result.schema, result.rows_processed))
                    self.assertEqual(source.read_bytes(), output.read_bytes())

    def test_xlsx_unknown_column_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            output = root / "output.xlsx"
            _write_xlsx(source, ("name", "unexpected"), (("one", "value"),))
            contract = ExportPrivacyContract(
                allowed_columns=("name",),
                required_columns=("name",),
                classification="material",
                format="xlsx",
            )
            with self.assertRaises(ExportRuntimeError) as raised:
                ExportPrivacyFinalizer(contract).finalize(
                    source,
                    output,
                    _xlsx_metadata(source),
                )
            self.assertEqual("EXPORT_SCHEMA_MISMATCH", raised.exception.code)
            self.assertEqual(["unexpected"], raised.exception.details["unknown_columns"])
            self.assertFalse(output.exists())

    def test_xlsx_external_parts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            output = root / "output.xlsx"
            _write_xlsx(
                source,
                ("name",),
                (("one",),),
                extra_part="xl/externalLinks/externalLink1.xml",
            )
            contract = ExportPrivacyContract(
                allowed_columns=("name",),
                required_columns=("name",),
                classification="material",
                format="xlsx",
            )
            with self.assertRaises(ExportRuntimeError) as raised:
                ExportPrivacyFinalizer(contract).finalize(
                    source,
                    output,
                    _xlsx_metadata(source),
                )
            self.assertEqual("EXPORT_FORMAT_INVALID", raised.exception.code)
            self.assertFalse(output.exists())

    def test_xlsx_data_cannot_extend_past_the_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            output = root / "output.xlsx"
            _write_xlsx(source, ("name",), (("one", "hidden"),))
            contract = ExportPrivacyContract(
                allowed_columns=("name",),
                required_columns=("name",),
                classification="material",
                format="xlsx",
            )
            with self.assertRaises(ExportRuntimeError) as raised:
                ExportPrivacyFinalizer(contract).finalize(
                    source,
                    output,
                    _xlsx_metadata(source),
                )
            self.assertEqual("EXPORT_SCHEMA_MISMATCH", raised.exception.code)
            self.assertFalse(output.exists())


def _write_xlsx(
    path: Path,
    header: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    extra_part: str | None = None,
) -> None:
    strings = list(header) + [value for row in rows for value in row]
    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    row_xml = []
    index = 0
    for row_number, values in enumerate((header, *rows), start=1):
        cells = []
        for column_number, _ in enumerate(values, start=1):
            column = chr(ord("A") + column_number - 1)
            cells.append(
                f'<c r="{column}{row_number}" t="s"><v>{index}</v></c>'
            )
            index += 1
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + shared
            + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(row_xml)
            + "</sheetData></worksheet>",
        )
        if extra_part is not None:
            archive.writestr(extra_part, "<externalLink />")


def _xlsx_metadata(path: Path) -> BlobMetadata:
    return BlobMetadata(
        size_bytes=path.stat().st_size,
        sha256="0" * 64,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        extension=".xlsx",
        etag=None,
        last_modified=None,
        resumed=False,
    )


if __name__ == "__main__":
    unittest.main()
