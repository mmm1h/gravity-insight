from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

try:
    from gravity_sdk import (
        GravityInsightClient,
        PermissionUnavailableError,
    )
    from gravity_sdk.cache import is_metadata_operation
    from gravity_sdk.catalog import OperationCatalog
    from gravity_sdk.composite import CompositeService
    from gravity_sdk.errors import InputValidationError
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import (
        GravityInsightClient,
        PermissionUnavailableError,
    )
    from gravity_sdk.cache import is_metadata_operation
    from gravity_sdk.catalog import OperationCatalog
    from gravity_sdk.composite import CompositeService
    from gravity_sdk.errors import InputValidationError


@dataclass(frozen=True)
class _Operation:
    operation_id: str
    domain: str = "report"
    platform: str | None = None
    resource: str = "metric"
    contract_marker: str = "v1"
    description: str = "agent-facing documentation"

    def operation_summary(self):
        return {
            "operation_id": self.operation_id,
            "domain": self.domain,
            "platform": self.platform,
            "resource": self.resource,
            "stability": "stable",
        }

    def schema(self):
        return {
            **self.operation_summary(),
            "contract_marker": self.contract_marker,
            "description": self.description,
        }

    def contract_fingerprint_payload(self):
        return {
            **self.operation_summary(),
            "contract_marker": self.contract_marker,
        }


class GravityInsightCliCatalogHardeningTests(unittest.TestCase):
    def test_legacy_catalog_fingerprint_is_upgraded_without_losing_probe_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "capability-catalog.json"
            operation = _Operation("report.metric.list")
            legacy_fingerprint = hashlib.sha256(
                json.dumps(
                    operation.schema(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "probes": {
                            operation.operation_id: {
                                "last_attempted_at": "2026-08-08T01:00:00Z",
                                "last_verified_at": "2026-08-08T01:00:00Z",
                                "status": "success",
                                "schema_fingerprint": "a" * 64,
                                "warnings_count": 0,
                                "contract_fingerprint": legacy_fingerprint,
                            },
                            "retired.operation": {
                                "status": "empty",
                                "contract_fingerprint": "b" * 64,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            catalog = OperationCatalog([operation], state_path=state_path)
            restored = catalog.probe(operation.operation_id)
            migrated = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual("success", restored["status"])
            self.assertEqual("2026-08-08T01:00:00Z", restored["last_verified_at"])
            self.assertNotEqual(legacy_fingerprint, restored["contract_fingerprint"])
            self.assertEqual(
                restored["contract_fingerprint"],
                migrated["probes"][operation.operation_id]["contract_fingerprint"],
            )
            self.assertIn("retired.operation", migrated["probes"])

    def test_persisted_success_is_restored_only_for_the_same_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "capability-catalog.json"
            original = _Operation("report.metric.list", contract_marker="schema-v1")
            catalog = OperationCatalog([original], state_path=state_path)
            catalog.record(
                original.operation_id,
                status="success",
                schema_fingerprint="a" * 64,
                verified_at="2026-08-08T01:00:00Z",
            )

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            saved_probe = persisted["probes"][original.operation_id]
            saved_contract_fingerprint = saved_probe["contract_fingerprint"]
            self.assertEqual(64, len(saved_contract_fingerprint))

            restored = OperationCatalog(
                [_Operation(original.operation_id, contract_marker="schema-v1")],
                state_path=state_path,
            )
            restored_probe = restored.probe(original.operation_id)
            self.assertEqual("success", restored_probe["status"])
            self.assertEqual("2026-08-08T01:00:00Z", restored_probe["last_verified_at"])
            self.assertEqual("a" * 64, restored_probe["schema_fingerprint"])
            self.assertEqual(
                saved_contract_fingerprint,
                restored_probe["contract_fingerprint"],
            )

            changed = OperationCatalog(
                [_Operation(original.operation_id, contract_marker="schema-v2")],
                state_path=state_path,
            )
            changed_probe = changed.probe(original.operation_id)
            self.assertNotEqual(
                saved_contract_fingerprint,
                changed_probe["contract_fingerprint"],
            )
            self.assertEqual("unverified", changed_probe["status"])
            self.assertIsNone(changed_probe["last_attempted_at"])
            self.assertIsNone(changed_probe["last_verified_at"])
            self.assertIsNone(changed_probe["schema_fingerprint"])
            self.assertEqual(1, changed.coverage()["unverified"])

    def test_probe_all_isolates_unreadable_first_app_from_other_stable_probes(self):
        def operation(
            operation_id,
            *,
            domain,
            resource,
            inputs=None,
            probe_inputs=None,
        ):
            input_fields = dict(inputs or {})
            return {
                "operation_id": operation_id,
                "domain": domain,
                "resource": resource,
                "action": "list",
                "contract_version": 1,
                "upstream_method": "GET",
                "path_template": f"/report/api/v3/probe/{resource}/",
                "auth_profile": "gravity_authorization",
                "stability": "stable",
                "input_fields": input_fields,
                "request": {
                    "path_fields": [],
                    "query_fields": list(input_fields),
                    "body_fields": [],
                    "defaults": {},
                    "fixed_query": {},
                    "fixed_body": {},
                },
                "response_projection": {
                    "data_shape": "list",
                    "data_keys": [],
                    "required_data_keys": [],
                    "item_keys": ["id"],
                    "dynamic_item_fields": [],
                },
                "pagination": {"kind": "none"},
                "semantic_error_rules": ["code", "extra.error"],
                "privacy_policy": {
                    "classification": "configuration",
                    "redact_keys": ["authorization", "token", "cookie"],
                },
                "required_parent": [],
                "live_probe": {"enabled": True, "input": dict(probe_inputs or {})},
            }

        test_manifest = {
            "manifest_version": 1,
            "operations": [
                operation("app.list", domain="app", resource="app"),
                operation(
                    "report.requires_app.list",
                    domain="report",
                    resource="requires_app",
                    inputs={"app_id": {"type": "string", "required": True}},
                    probe_inputs={"app_id": "$first_app_id"},
                ),
                operation(
                    "report.independent.list",
                    domain="report",
                    resource="independent",
                ),
            ],
        }

        class NeverTransport:
            is_test_transport = True

            def request(self, *_args, **_kwargs):
                raise AssertionError("probe batch was replaced; no transport call is expected")

        client = GravityInsightClient._from_manifest_for_tests(
            test_manifest, transport=NeverTransport()
        )
        executed = []

        def successful_batch(requests, **_options):
            executed.extend(item["operation_id"] for item in requests)
            return [
                {
                    "operation_id": item["operation_id"],
                    "request_id": item["request_id"],
                    "ok": True,
                    "status": "success",
                    "data": {"status": "success"},
                }
                for item in requests
            ]

        with patch.object(
            client,
            "_first_probe_app_id",
            side_effect=PermissionUnavailableError(
                "no readable App is available for the minimum report probe"
            ),
        ), patch.object(client, "batch", side_effect=successful_batch):
            result = client.probe_all(max_workers=2)

        self.assertEqual("partial", result["status"])
        self.assertEqual(3, result["probed"])
        by_operation = {item["operation_id"]: item for item in result["results"]}
        self.assertEqual(
            "permission_unavailable",
            by_operation["report.requires_app.list"]["status"],
        )
        self.assertFalse(by_operation["report.requires_app.list"]["ok"])
        self.assertEqual("success", by_operation["app.list"]["status"])
        self.assertEqual("success", by_operation["report.independent.list"]["status"])
        self.assertEqual(
            {"app.list", "report.independent.list"},
            set(executed),
        )

    def test_metadata_classifier_includes_templates_and_report_groups(self):
        for resource in ("template", "preset_template", "report_group"):
            with self.subTest(resource=resource):
                self.assertTrue(
                    is_metadata_operation(
                        {"domain": "report", "resource": resource, "action": "list"}
                    )
                )

    def test_catalog_failures_are_attempted_not_verified(self):
        catalog = OperationCatalog([_Operation("report.metric.list")])
        catalog.record(
            "report.metric.list",
            status="semantic_error",
            verified_at="2026-08-08T01:00:00Z",
        )
        probe = catalog.probe("report.metric.list")
        self.assertEqual("2026-08-08T01:00:00Z", probe["last_attempted_at"])
        self.assertIsNone(probe["last_verified_at"])
        self.assertEqual(
            {"verified": 0, "attempted": 1, "failed": 1, "unverified": 0},
            {
                key: catalog.coverage()[key]
                for key in ("verified", "attempted", "failed", "unverified")
            },
        )

        catalog.record(
            "report.metric.list",
            status="success",
            verified_at="2026-08-08T02:00:00Z",
        )
        self.assertEqual(1, catalog.coverage()["verified"])
        catalog.record(
            "report.metric.list",
            status="error",
            verified_at="2026-08-08T03:00:00Z",
        )
        probe = catalog.probe("report.metric.list")
        self.assertEqual("2026-08-08T03:00:00Z", probe["last_attempted_at"])
        self.assertEqual("2026-08-08T02:00:00Z", probe["last_verified_at"])
        self.assertEqual(0, catalog.coverage()["verified"])
        self.assertEqual(1, catalog.coverage()["failed"])

    def test_metadata_snapshot_skips_required_inputs_unless_supplied(self):
        class Client:
            def __init__(self):
                self.batch_requests = []

            def operations(self, **_filters):
                return [
                    {
                        "operation_id": "report.template.list",
                        "domain": "report",
                        "resource": "template",
                        "action": "list",
                        "stability": "stable",
                    },
                    {
                        "operation_id": "promotion.metric.list",
                        "domain": "promotion",
                        "resource": "metric",
                        "action": "list",
                        "stability": "stable",
                    },
                    {
                        "operation_id": "promotion.report_group.list",
                        "domain": "promotion",
                        "resource": "report_group",
                        "action": "list",
                        "stability": "stable",
                    },
                ]

            def schema(self, operation_id=None):
                resources = {
                    "report.template.list": ("report", "template", {}),
                    "promotion.metric.list": (
                        "promotion",
                        "metric",
                        {"media_type": {"required": True}},
                    ),
                    "promotion.report_group.list": (
                        "promotion",
                        "report_group",
                        {"filters": {"required": True}},
                    ),
                }
                domain, resource, fields = resources[operation_id]
                return {
                    "operation_id": operation_id,
                    "domain": domain,
                    "resource": resource,
                    "action": "list",
                    "input_fields": fields,
                }

            def batch(self, requests, **_options):
                self.batch_requests = list(requests)
                return [
                    {
                        "operation_id": item["operation_id"],
                        "request_id": item["request_id"],
                        "ok": True,
                        "status": "success",
                    }
                    for item in requests
                ]

            def read(self, *_args, **_kwargs):
                raise AssertionError("not used")

            def read_all(self, *_args, **_kwargs):
                raise AssertionError("not used")

        client = Client()
        service = CompositeService(client)
        snapshot = service.metadata_snapshot()
        self.assertEqual(
            ["report.template.list"],
            [item["operation_id"] for item in client.batch_requests],
        )
        self.assertEqual(2, snapshot["coverage"]["skipped_input_required"])
        self.assertEqual(
            {"promotion.metric.list", "promotion.report_group.list"},
            {item["operation_id"] for item in snapshot["skipped_input_required"]},
        )
        with self.assertRaisesRegex(InputValidationError, "requires inputs"):
            service.metadata_snapshot(["promotion.metric.list"])

        service.metadata_snapshot(
            ["promotion.metric.list"],
            inputs_by_operation={"promotion.metric.list": {"media_type": "bytedance"}},
        )
        self.assertEqual(
            {"media_type": "bytedance"}, client.batch_requests[0]["inputs"]
        )
        self.assertTrue(client.batch_requests[0]["read_all"])

    def test_composite_primary_snapshot_rejects_unproved_platform_before_inventory(self):
        capabilities = {
            "ubix": ("group", "promotion.ubix.group.list"),
            "taptap": ("group", "promotion.taptap.group.list"),
            "wechat_video": ("report", "promotion.wechat_video.report.list"),
            "bytedance": ("advertiser", "promotion.bytedance.advertiser.list"),
        }

        class Client:
            def __init__(self):
                self.batch_requests = []

            def operations(self, **filters):
                resource, operation_id = capabilities[filters["platform"]]
                return [
                    {
                        "operation_id": operation_id,
                        "domain": "promotion",
                        "platform": filters["platform"],
                        "resource": resource,
                        "action": "list",
                        "stability": "stable",
                    }
                ]

            def batch(self, requests, **_options):
                self.batch_requests = list(requests)
                return [
                    {
                        "operation_id": item["operation_id"],
                        "request_id": item["request_id"],
                        "ok": True,
                        "status": "success",
                    }
                    for item in requests
                ]

            def schema(self, *_args, **_kwargs):
                return {}

            def read(self, *_args, **_kwargs):
                return {}

            def read_all(self, *_args, **_kwargs):
                return {}

        client = Client()
        with self.assertRaises(InputValidationError) as raised:
            CompositeService(client).promotion_snapshot(
                ["taptap"],
                common_inputs={
                    "app_id": 17,
                    "date_list": ["2026-08-01", "2026-08-07"],
                    "query_fields": ["stat_cost"],
                },
            )
        self.assertEqual("platforms", raised.exception.field)
        self.assertEqual([], client.batch_requests)


if __name__ == "__main__":
    unittest.main()
