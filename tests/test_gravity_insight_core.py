from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

try:
    from gravity_sdk import (
        CredentialProvider,
        Credential,
        CompositeService,
        GravityInsightClient,
        InputValidationError,
        ManifestError,
        MetadataCache,
        PaginationError,
        PermissionUnavailableError,
        PolicyViolation,
        UnknownOperationError,
    )
    from gravity_sdk.credentials import _atomic_update_env
    from gravity_sdk.executor import _project as project_response
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.http_runtime import GravityHttpRuntime
    from gravity_sdk.registry import (
        PolicyEngine,
        Registry,
        _AuthorizedRequest,
    )
    from gravity_sdk.transport import Transport, TransportResponse
except ModuleNotFoundError:  # source checkout without an editable install
    from gravity_sdk import (
        CredentialProvider,
        Credential,
        CompositeService,
        GravityInsightClient,
        InputValidationError,
        ManifestError,
        MetadataCache,
        PaginationError,
        PermissionUnavailableError,
        PolicyViolation,
        UnknownOperationError,
    )
    from gravity_sdk.credentials import _atomic_update_env
    from gravity_sdk.executor import _project as project_response
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.http_runtime import GravityHttpRuntime
    from gravity_sdk.registry import (
        PolicyEngine,
        Registry,
        _AuthorizedRequest,
    )
    from gravity_sdk.transport import Transport, TransportResponse


NOW = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def manifest(*, stability: str = "stable", path: str = "/report/api/v3/example/list/"):
    return {
        "manifest_version": 1,
        "operations": [
            {
                "operation_id": "example.items.list",
                "domain": "example",
                "resource": "items",
                "action": "list",
                "contract_version": 1,
                "upstream_method": "POST",
                "path_template": path,
                "auth_profile": "gravity_authorization",
                "stability": stability,
                "platform": "test_platform",
                "input_fields": {
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 2},
                    "filter": {"type": "string", "default": ""},
                },
                "request": {
                    "path_fields": [],
                    "query_fields": [],
                    "body_fields": ["page", "page_size", "filter"],
                    "defaults": {"page": 1, "page_size": 2, "filter": ""},
                    "fixed_query": {},
                    "fixed_body": {"read_mode": "safe"},
                },
                "response_projection": {
                    "data_keys": ["list", "page_info"],
                    "required_data_keys": ["list"],
                    "item_keys": ["id", "value", "email_address"],
                    "dynamic_item_fields": [],
                },
                "pagination": {
                    "kind": "page_info",
                    "page_field": "page",
                    "page_size_field": "page_size",
                    "list_path": "data.list",
                    "page_info_path": "data.page_info",
                    "total_page_field": "total_page",
                    "default_page_size": 2,
                    "max_page_size": 2,
                },
                "semantic_error_rules": ["code", "extra.error"],
                "privacy_policy": {
                    "classification": "internal",
                    "redact_keys": ["operator_name", "email"],
                },
                "required_parent": [],
                "live_probe": {"enabled": True, "input": {"page": 1, "page_size": 1}},
            }
        ],
    }


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, url, **kwargs):
        with self.lock:
            self.calls.append((method, url, kwargs))
            if not self.responses:
                raise AssertionError("unexpected request")
            response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeTransport:
    is_test_transport = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, path, **kwargs):
        with self.lock:
            self.calls.append((method, path, kwargs))
            if not self.responses:
                raise AssertionError("unexpected request")
            value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        payload = value._payload if isinstance(value, FakeResponse) else value
        status = value.status_code if isinstance(value, FakeResponse) else 200
        payload = {} if status == 204 and payload is None else payload
        return TransportResponse(status, payload, "2026-08-08T06:00:00Z")


def env_file(root: Path, *, token: str = "opaque-token", expires: datetime | None = None) -> Path:
    path = root / ".env.gravity.local"
    lines = ["GRAVITY_USERNAME=user@example.invalid", "GRAVITY_PASSWORD=local-secret", f"GRAVITY_AUTH_TOKEN={token}"]
    if expires:
        lines.append(f"GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI={expires.isoformat()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def client_for(
    tmp: Path,
    responses,
    *,
    operation_manifest=None,
    allow_experimental=False,
):
    env_file(tmp)
    transport = FakeTransport(responses)
    client = GravityInsightClient._from_manifest_for_tests(
        operation_manifest or manifest(),
        transport=transport,
        allow_experimental=allow_experimental,
    )
    return client, transport


def repository_manifest(*operation_ids: str):
    wanted = set(operation_ids)
    operations = []
    root = Path(__file__).resolve().parents[1] / "src" / "gravity_sdk" / "manifests"
    for path in sorted(root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operations.extend(
            operation
            for operation in document.get("operations", [])
            if operation.get("operation_id") in wanted
        )
    if {item["operation_id"] for item in operations} != wanted:
        raise AssertionError("test operation is absent from the repository manifests")
    return {"manifest_version": 1, "operations": operations}


class GravityInsightCoreTests(unittest.TestCase):
    def test_contract_fingerprint_ignores_operation_and_field_descriptions(self):
        original = manifest()
        documented = copy.deepcopy(original)
        documented_operation = documented["operations"][0]
        documented_operation["description"] = "Improved agent-facing operation guidance."
        documented_operation["input_fields"]["filter"]["description"] = (
            "Improved agent-facing field guidance."
        )

        original_registry = Registry(load_operation_manifest(original))
        documented_registry = Registry(load_operation_manifest(documented))

        self.assertEqual(
            original_registry.fingerprint("example.items.list"),
            documented_registry.fingerprint("example.items.list"),
        )

    def test_contract_fingerprint_changes_for_input_requiredness_and_effect(self):
        original = manifest()
        required = copy.deepcopy(original)
        required["operations"][0]["input_fields"]["filter"]["required"] = True
        changed_effect = copy.deepcopy(original)
        changed_effect["operations"][0]["effect"] = "export_status"

        original_fingerprint = Registry(load_operation_manifest(original)).fingerprint(
            "example.items.list"
        )

        self.assertNotEqual(
            original_fingerprint,
            Registry(load_operation_manifest(required)).fingerprint(
                "example.items.list"
            ),
        )
        self.assertNotEqual(
            original_fingerprint,
            Registry(load_operation_manifest(changed_effect)).fingerprint(
                "example.items.list"
            ),
        )

    def test_repository_manifests_load_the_locked_contract(self):
        root = Path(__file__).resolve().parents[1] / "src" / "gravity_sdk" / "manifests"
        operations = []
        for path in sorted(root.glob("*.json")):
            operations.extend(load_operation_manifest(path))
        self.assertGreaterEqual(len(operations), 70)
        by_id = {item.operation_id: item for item in operations}
        report = by_id["report.multidim.query"]
        self.assertEqual("page_info", report.pagination.kind)
        self.assertEqual("data.list", report.pagination.list_path)
        self.assertEqual(("code", "extra.error"), tuple(rule.path for rule in report.semantic_error_rules))
        self.assertTrue(report.response_projection.required_data_keys)
        self.assertEqual(
            "json_scalar", report.schema()["response_projection"]["leaf_contract"]
        )

    def test_operations_schema_and_unknown_operation_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            client, session = client_for(Path(directory), [])
            self.assertEqual(1, len(client.operations(domain="example", platform="test_platform")))
            self.assertEqual("example.items.list", client.schema("example.items.list")["operation_id"])
            with self.assertRaises(UnknownOperationError):
                client.read("example.unknown.list", {})
            self.assertEqual([], session.calls)

    def test_schema_results_cannot_mutate_internal_contracts_or_live_probes(self):
        isolated = manifest()
        operation = isolated["operations"][0]
        operation["input_fields"]["config"] = {
            "type": "object",
            "default": {"safe": True},
            "enum": [{"safe": True}],
        }
        operation["request"]["body_fields"].append("config")
        operation["request"]["defaults"]["config"] = {"safe": True}
        success = {
            "code": 0,
            "data": {
                "list": [],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory), [FakeResponse(success)], operation_manifest=isolated
            )
            original_fingerprint = client._registry.fingerprint("example.items.list")
            exposed = client.schema("example.items.list")
            exposed["input_fields"]["config"]["enum"][0]["evil"] = True
            exposed["input_fields"]["config"]["default"]["evil"] = True
            exposed["live_probe"]["inputs"]["page"] = 999

            with self.assertRaises(InputValidationError):
                client.read(
                    "example.items.list",
                    {"config": {"safe": True, "evil": True}},
                )
            self.assertEqual([], transport.calls)
            self.assertEqual(
                original_fingerprint,
                client._registry.fingerprint("example.items.list"),
            )
            fresh = client.schema("example.items.list")
            self.assertNotIn("evil", fresh["input_fields"]["config"]["enum"][0])
            client.probe("example.items.list")
            self.assertEqual(1, transport.calls[0][2]["body"]["page"])

    def test_material_probe_resolves_advertiser_from_registered_parent(self):
        parent = {
            "code": 0,
            "data": {
                "list": [{"advertiser_id": "advertiser-1"}],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
            },
        }
        child = {
            "code": 0,
            "data": {
                "list": [],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
            },
        }
        controlled = repository_manifest(
            "promotion.tencent.advertiser.list",
            "material.tencent.list",
        )
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(parent), FakeResponse(child)],
                operation_manifest=controlled,
            )
            result = client.probe("material.tencent.list")
        self.assertEqual("empty", result["status"])
        self.assertEqual(2, len(transport.calls))
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/advertiser/list/v2/",
            transport.calls[0][1],
        )
        self.assertEqual(
            {
                "advertiser_id": "advertiser-1",
                "check_local_exist": 1,
                "filters": [],
            },
            transport.calls[1][2]["body"],
        )

    def test_template_detail_probe_resolves_parent_and_omits_deep_config(self):
        parent = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "id": "template-1",
                        "name": "safe",
                        "category": "preset",
                        "remark": "safe",
                        "modify_time": "2026-08-08",
                    }
                ],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
            },
        }
        detail = {
            "code": 0,
            "data": {
                "detail": {
                    "name": "safe",
                    "remark": "safe",
                    "config": {"callback_url": "https://private.invalid"},
                }
            },
        }
        controlled = repository_manifest(
            "report.multidim.template.preset.list",
            "report.multidim.template.preset.get",
        )
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(parent), FakeResponse(detail)],
                operation_manifest=controlled,
            )
            result = client.probe("report.multidim.template.preset.get")
        self.assertEqual("success", result["status"])
        self.assertEqual({"name": "safe"}, result["data"]["detail"])
        self.assertNotIn("remark", result["data"]["detail"])
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(
            {"id": "template-1", "category": "preset"},
            transport.calls[1][2]["query"],
        )

    def test_write_path_and_experimental_operation_require_explicit_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            client, session = client_for(
                Path(directory), [], operation_manifest=manifest(path="/report/api/v3/example/create/")
            )
            with self.assertRaises(PolicyViolation):
                client.read("example.items.list", {})
            self.assertEqual([], session.calls)

        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [], operation_manifest=manifest(stability="experimental"))
            with self.assertRaisesRegex(PolicyViolation, "explicit opt-in"):
                client.read("example.items.list", {})

        catalog_only = repository_manifest("candidate.material.platform.list")
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [],
                operation_manifest=catalog_only,
                allow_experimental=True,
            )
            operation = client.operations(stability="deprecated")[0]
            self.assertEqual(
                "deprecated", operation["availability_status"]
            )
            with self.assertRaisesRegex(PolicyViolation, "catalog-only"):
                client.read("candidate.material.platform.list", {})
            self.assertEqual([], transport.calls)

    def test_read_returns_complete_private_envelope_and_contract_drift(self):
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "id": 1,
                        "operator_name": "private",
                        "email_address": "private@example.invalid",
                        "value": 4,
                    }
                ],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1, "total_number": 1},
                "unregistered": {"raw": "omitted"},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, session = client_for(Path(directory), [FakeResponse(payload)])
            result = client.read("example.items.list", {"filter": "safe"})
        self.assertEqual(
            {
                "schema_version",
                "result_source",
                "result_audit",
                "status",
                "source",
                "fetched_at",
                "schema_fingerprint",
                "operation_id",
                "contract_version",
                "request",
                "page",
                "data",
                "warnings",
                "error",
            },
            set(result),
        )
        # Unknown response fields are additive: projection still omits them, but
        # the read remains callable and must not be escalated to fail-closed drift.
        self.assertEqual("success", result["status"])
        described = client.describe("example.items.list")
        self.assertEqual(
            "contract_changed_additive", described["health"]["status"]
        )
        self.assertTrue(described["currently_callable"])
        self.assertEqual("example.items.list", result["operation_id"])
        self.assertEqual(
            {"operation_id": "/operation_id", "contract_version": "/contract_version"},
            result["result_audit"]["fact_paths"],
        )
        self.assertNotIn("operation_id", result["result_audit"])
        drift = result["result_audit"]["response_drift"]
        self.assertEqual(
            ("gravity.response-drift.v1", "response", "additive"),
            (drift["schema_version"], drift["direction"], drift["classification"]),
        )
        self.assertIn(
            {"path": "/data/unregistered", "observed_type": "object"},
            drift["fields"],
        )
        self.assertNotIn("operator_name", json.dumps(result["data"]))
        self.assertEqual(
            "private@example.invalid",
            result["data"]["list"][0]["email_address"],
        )
        self.assertNotIn("unregistered", result["data"])
        self.assertIn("contract_fingerprint", result["source"])
        self.assertNotEqual(result["schema_fingerprint"], result["source"]["contract_fingerprint"])
        sent = session.calls[0][2]["body"]
        self.assertEqual("safe", sent["filter"])
        self.assertEqual("safe", sent["read_mode"])

    def test_unregistered_credential_field_is_drift_and_never_leaks(self):
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "value": 4, "access_token": "private"}],
                "page_info": {
                    "page": 1,
                    "page_size": 2,
                    "total_page": 1,
                    "total_number": 1,
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse(payload)])
            result = client.read("example.items.list", {"filter": "safe"})
        self.assertEqual("success", result["status"])
        self.assertEqual({"id": 1, "value": 4}, result["data"]["list"][0])
        self.assertIn(
            {"path": "/data/list/*/access_token", "observed_type": "string"},
            result["result_audit"]["response_drift"]["fields"],
        )
        self.assertNotIn("private", json.dumps(result))

    def test_unregistered_request_field_still_fails_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(Path(directory), [])
            with self.assertRaisesRegex(InputValidationError, "unknown operation input"):
                client.read("example.items.list", {"future_request_field": True})
        self.assertEqual([], transport.calls)

    def test_newly_stable_context_reads_project_sanitized_contract_fixtures(self):
        operation_ids = (
            "promotion.object.list",
            "attribution.post_backtrack.list",
            "attribution.postback_mode.list",
            "attribution.postback_map_collect.list",
            "material.recycle.list",
        )
        page_info = {
            "page": 1,
            "page_size": 1,
            "total_number": 1,
            "total_page": 1,
        }
        responses = [
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "page_info": page_info,
                        "list": [
                            {
                                "create_time": "safe",
                                "modify_time": "safe",
                                "app_id": 1,
                                "turbo_promoted_object_id": "object-1",
                                "turbo_promoted_object_name": "safe",
                                "remark": "safe",
                                "state": 1,
                                "create_user_name": "private person",
                                "callback_url": "https://private.invalid",
                                "redirect_url": "https://private.invalid",
                            }
                        ],
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "app_id": 1,
                                "days": 7,
                                "minutes": 0,
                                "window_type": 1,
                                "create_time": "safe",
                                "modify_time": "safe",
                                "company": "private company",
                            }
                        ]
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "app_id": 1,
                                "mode": 1,
                                "create_time": "safe",
                                "modify_time": "safe",
                                "company": "private company",
                            }
                        ]
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "page_info": page_info,
                        "list": [
                            {
                                "id": 1,
                                "cid": 2,
                                "app_id": 3,
                                "name": "safe",
                                "remark": "safe",
                                "create_time": "safe",
                                "modify_time": "safe",
                                "config": "private mapping configuration",
                                "operator_name": "private person",
                            }
                        ],
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "page_info": page_info,
                        "list": [
                            {
                                "id": 1,
                                "file_name": "safe.mp4",
                                "file_type": "video",
                                "file_size": 1,
                                "status": 1,
                                "file_md5": "private fingerprint",
                                "image_set": [{"url": "https://private.invalid"}],
                                "file_url": "https://private.invalid",
                                "create_user_name": "private person",
                                "designer_image_id": 9,
                                "designer_image_name": "private person",
                            }
                        ],
                    },
                }
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                responses,
                operation_manifest=repository_manifest("app.list", *operation_ids),
            )
            results = [
                client.read(
                    operation_id,
                    (
                        {"app_id": "1", "page": 1, "page_size": 1}
                        if operation_id == "promotion.object.list"
                        else {
                            "app_id": "1",
                            "filters": [],
                            "page": 1,
                            "page_size": 1,
                        }
                        if operation_id == "attribution.postback_map_collect.list"
                        else {"app_id": "1"}
                        if operation_id.startswith("attribution.")
                        else {"filters": [], "page": 1, "page_size": 1}
                    ),
                )
                for operation_id in operation_ids
            ]
        self.assertEqual(
            ["success"] * 5,
            [result["status"] for result in results],
        )
        self.assertEqual(
            3,
            sum("response_drift" in result["result_audit"] for result in results),
        )
        serialized = json.dumps(results)
        for omitted_value in (
            "private mapping configuration",
            "private fingerprint",
            "https://private.invalid",
        ):
            self.assertNotIn(omitted_value, serialized)
        self.assertIn("private company", serialized)
        self.assertEqual(
            "object-1", results[0]["data"]["list"][0]["turbo_promoted_object_id"]
        )
        self.assertEqual(7, results[1]["data"]["list"][0]["days"])
        self.assertEqual("safe.mp4", results[4]["data"]["list"][0]["file_name"])

    def test_empty_list_status_and_required_response_drift(self):
        empty = {"code": 0, "data": {"list": [], "page_info": {"page": 1, "page_size": 2, "total_page": 1}}}
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse(empty)])
            self.assertEqual("empty", client.read("example.items.list", {})["status"])
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse({"code": 0, "data": {}})])
            drift = client.read("example.items.list", {})
            self.assertEqual("contract_changed", drift["status"])
            self.assertIsNone(drift["error"])
            self.assertTrue(drift["warnings"])
            self.assertEqual(
                "upstream_changed",
                client.describe("example.items.list")["health"]["status"],
            )

    def test_list_rows_fail_closed_without_an_item_allowlist(self):
        unsafe = manifest()
        unsafe["operations"][0]["response_projection"].pop("item_keys")
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "email_address": "private@example.invalid"}],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory), [FakeResponse(payload)], operation_manifest=unsafe
            )
            result = client.read("example.items.list", {})
        self.assertEqual([{}], result["data"]["list"])
        self.assertEqual("contract_changed", result["status"])
        self.assertTrue(any("no item allowlist" in warning for warning in result["warnings"]))
        self.assertNotIn("private@example.invalid", json.dumps(result))

    def test_explicitly_omitted_data_containers_are_acknowledged_but_never_output(self):
        controlled = manifest()
        operation = controlled["operations"][0]
        operation["response_projection"] = {
            "data_keys": ["detail"],
            "required_data_keys": ["detail"],
            "item_keys": [],
            "dynamic_item_fields": [],
            "data_item_keys": {"detail": ["name"]},
            "known_omitted_data_keys": ["secret_top"],
            "known_omitted_data_item_keys": {"detail": ["config"]},
        }
        operation["pagination"] = {"kind": "none"}
        payload = {
            "code": 0,
            "data": {
                "detail": {
                    "name": "safe",
                    "config": {"secret": "private nested"},
                },
                "secret_top": {"token": "private top"},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse(payload)],
                operation_manifest=controlled,
            )
            result = client.read("example.items.list", {})
        self.assertEqual("success", result["status"])
        self.assertEqual({"detail": {"name": "safe"}}, result["data"])
        self.assertNotIn("private", json.dumps(result))

        invalid = json.loads(json.dumps(controlled))
        invalid_projection = invalid["operations"][0]["response_projection"]
        invalid_projection["data_keys"].append("secret_top")
        with self.assertRaises(ManifestError):
            load_operation_manifest(invalid)

    def test_explicitly_omitted_nested_row_fields_are_never_output(self):
        controlled = manifest()
        projection = controlled["operations"][0]["response_projection"]
        projection["item_keys"] = ["type", "group", "material"]
        projection["nested_item_keys"] = {
            "group": ["id", "name"],
            "material": ["id", "file_name"],
        }
        projection["known_omitted_nested_item_keys"] = {
            "group": ["previews", "create_user"],
            "material": ["file_url", "image_set"],
        }
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "type": "group",
                        "group": {
                            "id": "group-1",
                            "name": "safe",
                            "previews": ["https://private.invalid/preview"],
                            "create_user": {"name": "private person"},
                        },
                        "material": {
                            "id": "material-1",
                            "file_name": "safe.mp4",
                            "file_url": "https://private.invalid/file",
                            "image_set": ["https://private.invalid/image"],
                        },
                    }
                ],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse(payload)],
                operation_manifest=controlled,
            )
            result = client.read("example.items.list", {})
        self.assertEqual("success", result["status"])
        self.assertEqual([], result["warnings"])
        self.assertEqual(
            {
                "type": "group",
                "group": {"id": "group-1", "name": "safe"},
                "material": {"id": "material-1", "file_name": "safe.mp4"},
            },
            result["data"]["list"][0],
        )
        self.assertNotIn("private", json.dumps(result))

    def test_empty_object_can_be_an_explicit_empty_configuration(self):
        controlled = manifest()
        operation = controlled["operations"][0]
        operation["response_projection"] = {
            "data_keys": ["is_enabled", "unit", "second", "minute"],
            "required_data_keys": [],
            "item_keys": [],
            "dynamic_item_fields": [],
            "empty_object_as_empty_result": True,
        }
        operation["pagination"] = {"kind": "none"}
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse({"code": 0, "data": {}})],
                operation_manifest=controlled,
            )
            result = client.read("example.items.list", {})
        self.assertEqual("empty", result["status"])
        self.assertEqual({}, result["data"])
        self.assertEqual([], result["warnings"])

    def test_analysis_numeric_leaves_require_exact_manifest_paths(self):
        controlled = manifest()
        document = controlled["operations"][0]
        document["operation_id"] = "analysis.event.query"
        document["response_projection"] = {
            "data_keys": ["list"],
            "required_data_keys": ["list"],
            "item_keys": [],
            "dynamic_item_fields": [],
            "numeric_paths": [
                "list.[].[].event_index",
                "list.[].[].values.*.count",
            ],
        }
        document["pagination"] = {"kind": "none"}
        operation = load_operation_manifest(controlled)[0]
        payload = {
            "data": {
                "list": [
                    [
                        {
                            "event_index": 7,
                            "count": True,
                            "value": 900,
                            "values": [901],
                            "group_cols": [902],
                        },
                        {
                            "event_index": 8,
                            "values": {
                                "total": {"count": 4, "value": 903}
                            },
                        },
                    ]
                ]
            }
        }

        projected, warnings, changed, _ = project_response(operation, payload, {})

        self.assertTrue(changed)
        self.assertTrue(warnings)
        self.assertEqual(
            {
                "list": [
                    [
                        {"event_index": 7, "count": True, "values": []},
                        {
                            "event_index": 8,
                            "values": {"total": {"count": 4}},
                        },
                    ]
                ]
            },
            projected,
        )
        serialized = json.dumps(projected)
        for malicious in (900, 901, 902, 903):
            self.assertNotIn(str(malicious), serialized)
        self.assertEqual(
            [
                "list.[].[].event_index",
                "list.[].[].values.*.count",
            ],
            operation.schema()["response_projection"]["numeric_paths"],
        )

        denied = json.loads(json.dumps(controlled))
        denied["operations"][0]["response_projection"]["numeric_paths"] = []
        denied_operation = load_operation_manifest(denied)[0]
        denied_projected, _, denied_changed, _ = project_response(
            denied_operation, payload, {}
        )
        self.assertTrue(denied_changed)
        denied_serialized = json.dumps(denied_projected)
        self.assertNotIn("event_index", denied_serialized)
        self.assertNotIn('"count": 4', denied_serialized)
        self.assertIn('"count": true', denied_serialized)

        invalid = json.loads(json.dumps(controlled))
        invalid["operations"][0]["response_projection"]["numeric_paths"] = [
            "list.**.value"
        ]
        with self.assertRaises(ManifestError):
            load_operation_manifest(invalid)

    def test_scalar_and_mixed_list_items_are_dropped_fail_closed(self):
        payload = {
            "code": 0,
            "data": {
                "list": ["private scalar", {"id": 1}, ["private nested"], 42],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse(payload)])
            result = client.read("example.items.list", {})
        self.assertEqual([{"id": 1}], result["data"]["list"])
        self.assertEqual("contract_changed", result["status"])
        self.assertTrue(any("non-object" in warning for warning in result["warnings"]))
        self.assertNotIn("private scalar", json.dumps(result))
        self.assertNotIn("private nested", json.dumps(result))

        non_json_payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "value": float("nan")}],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse(non_json_payload)])
            non_json = client.read("example.items.list", {})
        self.assertEqual([{"id": 1}], non_json["data"]["list"])
        self.assertEqual("contract_changed", non_json["status"])
        self.assertTrue(any("non-JSON scalar" in item for item in non_json["warnings"]))

    def test_typed_scalar_lists_require_every_item_to_match(self):
        typed = manifest()
        projection = typed["operations"][0]["response_projection"]
        projection["item_keys"].extend(["tag_ids", "exclusion_dims"])
        projection["scalar_list_item_types"] = {
            "tag_ids": "integer",
            "exclusion_dims": "string",
        }
        valid_payload = {
            "code": 0,
            "data": {
                "list": [
                    {"id": 1, "tag_ids": [1, 2], "exclusion_dims": ["country"]}
                ],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        invalid_payload = {
            "code": 0,
            "data": {
                "list": [
                    {"id": 1, "tag_ids": [1, "2"], "exclusion_dims": ["country"]}
                ],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory), [FakeResponse(valid_payload)], operation_manifest=typed
            )
            valid = client.read("example.items.list", {})
        self.assertEqual([1, 2], valid["data"]["list"][0]["tag_ids"])
        self.assertEqual(["country"], valid["data"]["list"][0]["exclusion_dims"])

        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory), [FakeResponse(invalid_payload)], operation_manifest=typed
            )
            invalid = client.read("example.items.list", {})
        self.assertNotIn("tag_ids", invalid["data"]["list"][0])
        self.assertEqual(["country"], invalid["data"]["list"][0]["exclusion_dims"])
        self.assertEqual("contract_changed", invalid["status"])
        self.assertTrue(any("uncontracted nested" in warning for warning in invalid["warnings"]))

    def test_dynamic_item_fields_only_admit_requested_columns(self):
        dynamic = repository_manifest(
            "promotion.metric.list",
            "promotion.bytedance.advertiser.list",
        )
        metadata_payload = {"code": 0, "data": [{"name": "metric_a"}]}
        business_payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "metric_a": 2, "metric_b": 3}],
                "page_info": {"page": 1, "page_size": 10, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata_payload), FakeResponse(business_payload)],
                operation_manifest=dynamic,
            )
            result = client.read(
                "promotion.bytedance.advertiser.list",
                {
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "query_fields": ["metric_a"],
                },
            )
        self.assertEqual({"id": 1, "metric_a": 2}, result["data"]["list"][0])
        self.assertNotIn("metric_b", json.dumps(result["data"]))
        # metric_b is an additive upstream field; metric_a remains safely projected.
        self.assertEqual("success", result["status"])
        self.assertIn(
            {"path": "/data/list/*/metric_b", "observed_type": "integer"},
            result["result_audit"]["response_drift"]["fields"],
        )
        self.assertEqual(2, len(transport.calls))

        with self.assertRaisesRegex(InputValidationError, "live platform metadata"):
            client.read(
                "promotion.bytedance.advertiser.list",
                {
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "query_fields": ["arbitrary_private_field"],
                },
            )
        self.assertEqual(2, len(transport.calls))

        dynamic = manifest()
        operation = dynamic["operations"][0]
        operation["input_fields"]["query_fields"] = {
            "type": "array",
            "required": True,
        }
        operation["request"]["body_fields"].append("query_fields")
        operation["response_projection"]["dynamic_item_fields"] = ["undeclared"]
        with self.assertRaises(ManifestError):
            load_operation_manifest(dynamic)

    def test_business_query_uses_static_item_allowlists_and_controlled_filter_codec(self):
        controlled = repository_manifest("app.list", "report.business.query")
        payload = {
            "code": 0,
            "data": {
                "items": [],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
                "ratio": [],
                "total": [],
            },
        }
        inputs = {
            "page": 1,
            "page_size": 1,
            "date_list": ["2026-08-08", "2026-08-08"],
            "app_list": ["app-1"],
            "metrics_list": ["AdCost"],
            "dims_list": ["stat_datetime"],
            "ad_platform_list": ["bytedance", "tencent", "kuaishou"],
            "need_ratio": True,
            "calc_diff": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(payload)],
                operation_manifest=controlled,
            )
            result = client.read("report.business.query", inputs)
            with self.assertRaisesRegex(InputValidationError, "outside its allowlist"):
                client.read(
                    "report.business.query",
                    {**inputs, "metrics_list": ["private_metric"]},
                )
        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(transport.calls))
        self.assertEqual(
            {
                "page": 1,
                "page_size": 1,
                "date_list": ["2026-08-08", "2026-08-08"],
                "app_list": ["app-1"],
                "metrics_list": ["AdCost"],
                "dims_list": ["stat_datetime"],
                "filtering": {
                    "ad_platform_list": ["bytedance", "tencent", "kuaishou"]
                },
                "need_ratio": True,
            },
            transport.calls[0][2]["body"],
        )

    def test_material_report_codec_removes_personnel_grouping(self):
        controlled = repository_manifest("app.list", "material.report.query")
        payload = {
            "code": 0,
            "data": {
                "list": [],
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
                "total": {},
                "update_at": {},
            },
        }
        inputs = {
            "platform": "kuaishou",
            "page": 1,
            "page_size": 1,
            "date_list": ["2026-08-08", "2026-08-08"],
            "app_list": ["app-1"],
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(payload)],
                operation_manifest=controlled,
            )
            result = client.read("material.report.query", inputs)
            with self.assertRaisesRegex(InputValidationError, "allowed value"):
                client.read(
                    "material.report.query",
                    {**inputs, "platform": "private_platform"},
                )
        self.assertEqual("empty", result["status"])
        self.assertEqual(1, len(transport.calls))
        body = transport.calls[0][2]["body"]
        self.assertEqual([], body["stat_list"])
        self.assertNotIn("designer_id", repr(body))
        self.assertEqual(
            ["charge", "action_ratio", "conversion_ratio"],
            body["metrics_list"],
        )
        self.assertEqual(
            [
                {
                    "field": "ad_platform",
                    "operator": "EQUALS",
                    "values": ["kuaishou"],
                },
                {"field": "app_id", "operator": "IN", "values": ["app-1"]},
            ],
            body["filters"],
        )

    def test_bound_executor_cannot_bypass_dynamic_field_metadata_policy(self):
        dynamic = repository_manifest(
            "promotion.metric.list",
            "promotion.bytedance.advertiser.list",
        )
        metadata_payload = {"code": 0, "data": [{"name": "known_metric"}]}
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata_payload)],
                operation_manifest=dynamic,
            )
            with self.assertRaisesRegex(InputValidationError, "live platform metadata"):
                client._executor.execute(
                    "promotion.bytedance.advertiser.list",
                    {
                        "date_list": ["2026-08-07", "2026-08-07"],
                        "query_fields": ["arbitrary_private_field"],
                    },
                )
        self.assertEqual(1, len(transport.calls))
        self.assertIn("promotion_metrics", transport.calls[0][1])
        self.assertFalse(
            any("bytedance/advertiser" in call[1] for call in transport.calls)
        )

    def test_additive_metadata_drift_does_not_block_registered_dynamic_fields(self):
        dynamic = repository_manifest(
            "promotion.metric.list",
            "promotion.bytedance.advertiser.list",
        )
        metadata_with_drift = {
            "code": 0,
            "data": [{"name": "known_metric", "uncontracted_field": "hidden"}],
        }
        business = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "known_metric": 2}],
                "page_info": {"page": 1, "page_size": 10, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata_with_drift), FakeResponse(business)],
                operation_manifest=dynamic,
            )
            result = client.read(
                "promotion.bytedance.advertiser.list",
                {
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "query_fields": ["known_metric"],
                },
            )
        self.assertEqual(("success", 2), (result["status"], len(transport.calls)))
        self.assertEqual({"id": 1, "known_metric": 2}, result["data"]["list"][0])
        self.assertIn("promotion_metrics", transport.calls[0][1])
        self.assertIn("bytedance", transport.calls[1][1])
        self.assertIn("advertiser/list", transport.calls[1][1])

    def test_nested_promotion_filtering_is_rejected_before_network(self):
        controlled = repository_manifest("promotion.bytedance.advertiser.list")
        for unsafe_value in ({"nested": "value"}, ["value"], None):
            with self.subTest(unsafe_value=unsafe_value), tempfile.TemporaryDirectory() as directory:
                client, transport = client_for(
                    Path(directory), [], operation_manifest=controlled
                )
                with self.assertRaisesRegex(InputValidationError, "must be scalar"):
                    client.read(
                        "promotion.bytedance.advertiser.list",
                        {
                            "date_list": ["2026-08-07", "2026-08-07"],
                            "filtering": {"app_id": unsafe_value},
                        },
                    )
                self.assertEqual([], transport.calls)

    def test_promotion_field_policy_uses_verified_apple_and_tencent_profiles(self):
        dynamic = repository_manifest(
            "promotion.metric.list",
            "promotion.apple.advertiser.list",
            "promotion.tencent.advertiser.list",
        )
        metadata = {"code": 0, "data": [{"name": "metric_value"}]}
        business = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "metric_value": 1}],
                "page_info": {"page": 1, "page_size": 10, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [
                    FakeResponse(metadata),
                    FakeResponse(business),
                    FakeResponse(metadata),
                    FakeResponse(business),
                ],
                operation_manifest=dynamic,
            )
            apple = client.read(
                "promotion.apple.advertiser.list",
                {
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "query_fields": ["metric_value"],
                },
            )
            tencent = client.read(
                "promotion.tencent.advertiser.list",
                {
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "query_fields": ["metric_value"],
                    "time_line": "active",
                },
            )

        self.assertEqual("success", apple["status"])
        self.assertEqual("success", tencent["status"])
        apple_metadata_query = dict(transport.calls[0][2]["query"])
        tencent_metadata_query = dict(transport.calls[2][2]["query"])
        self.assertEqual({"media_type": "asa"}, apple_metadata_query)
        self.assertEqual(
            {"media_type": "tencentV3", "metric_type": "active"},
            tencent_metadata_query,
        )

    def test_sensitive_filter_conditions_are_redacted_from_request_envelope(self):
        filtered = manifest()
        operation = filtered["operations"][0]
        operation["input_fields"]["filter"] = {"type": "array", "required": True}
        payload = {
            "code": 0,
            "data": {
                "list": [],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        sensitive_filters = [
            {
                "field": "advertiser_name",
                "operator": "IN",
                "values": ["Private Account"],
            },
            {
                "field": "click_url",
                "operator": "EQUALS",
                "values": ["https://private.example.invalid/?token=secret"],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory), [FakeResponse(payload)], operation_manifest=filtered
            )
            result = client.read("example.items.list", {"filter": sensitive_filters})

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("advertiser_name", serialized)
        self.assertNotIn("Private Account", serialized)
        self.assertNotIn("click_url", serialized)
        self.assertNotIn("private.example.invalid", serialized)
        self.assertNotIn("token=secret", serialized)
        self.assertEqual("[REDACTED]", result["request"]["inputs"]["filter"][0]["field"])
        self.assertTrue(result["request"]["inputs"]["filter"][0]["redacted"])

    def test_metadata_cache_is_ten_minute_thread_safe_and_business_reads_bypass(self):
        current = [0.0]
        cache = MetadataCache(
            ["report.multidim.metric.list"], clock=lambda: current[0]
        )
        calls = []
        gate = threading.Event()
        started = threading.Event()

        def load():
            calls.append("metadata")
            started.set()
            gate.wait(1)
            return {"data": {"list": [{"name": "metric"}]}}

        with ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(
                cache.get_or_load, "report.multidim.metric.list", {"page": 1}, load
            )
            started.wait(1)
            others = [
                pool.submit(
                    cache.get_or_load,
                    "report.multidim.metric.list",
                    {"page": 1},
                    load,
                )
                for _ in range(2)
            ]
            gate.set()
            values = [first.result(), *(future.result() for future in others)]
        self.assertEqual(1, len(calls))
        values[0]["data"]["list"][0]["name"] = "mutated"
        cached = cache.get_or_load(
            "report.multidim.metric.list", {"page": 1}, load
        )
        self.assertEqual("metric", cached["data"]["list"][0]["name"])
        self.assertEqual(600.0, cache.stats()["ttl_seconds"])

        current[0] = 601.0
        cache.get_or_load("report.multidim.metric.list", {"page": 1}, load)
        self.assertEqual(2, len(calls))
        cache.get_or_load("report.multidim.query", {}, load)
        cache.get_or_load("report.multidim.query", {}, load)
        self.assertEqual(4, len(calls))

    def test_client_caches_only_metadata_and_catalog_records_no_values(self):
        metadata_contract = manifest()
        operation = metadata_contract["operations"][0]
        operation.update(
            {
                "operation_id": "report.multidim.metric.list",
                "domain": "report",
                "resource": "metric",
            }
        )
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "value": "private metadata value"}],
                "page_info": {"page": 1, "page_size": 2, "total_page": 1},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory), [FakeResponse(payload)], operation_manifest=metadata_contract
            )
            first = client.read("report.multidim.metric.list", {"filter": "private filter"})
            first["data"]["list"][0]["value"] = "mutated"
            second = client.read("report.multidim.metric.list", {"filter": "private filter"})
        self.assertEqual(1, len(transport.calls))
        self.assertEqual("private metadata value", second["data"]["list"][0]["value"])
        operation = client.operations(domain="report")[0]
        self.assertEqual("success", operation["probe"]["status"])
        self.assertEqual(64, len(operation["probe"]["schema_fingerprint"]))
        self.assertEqual(1, client.operation_coverage(domain="report")["verified"])
        catalog_json = json.dumps(client.operations(domain="report"))
        self.assertNotIn("private metadata value", catalog_json)
        self.assertNotIn("private filter", catalog_json)

    def test_read_all_follows_page_info_and_combines_rows(self):
        responses = [
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [{"id": 1}, {"id": 2}],
                        "page_info": {"page": 1, "page_size": 2, "total_page": 2, "total_number": 3},
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "data": {
                        "list": [{"id": 3}],
                        "page_info": {"page": 2, "page_size": 2, "total_page": 2, "total_number": 3},
                    },
                }
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            client, session = client_for(Path(directory), responses)
            result = client.read_all("example.items.list", {})
        self.assertEqual([1, 2, 3], [item["id"] for item in result["data"]["list"]])
        self.assertEqual(2, result["page"]["pages_fetched"])
        self.assertEqual(2, session.calls[1][2]["body"]["page"])

    def test_atomic_multidim_fields_are_metadata_validated_before_business_network(self):
        multidim = repository_manifest(
            "report.multidim.metric.list",
            "report.multidim.custom_metric.list",
            "report.multidim.custom_metric.shared.list",
            "report.multidim.query",
        )
        standard = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "name": "ap_cost",
                        "tag_ids": [],
                        "exclusion_dims": ["country"],
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        empty_custom = {
            "code": 0,
            "data": {
                "list": [],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        business = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "day": "2026-08-07",
                        "advertiser_id": "advertiser-1",
                        "gid": "group-1",
                        "ap_cost": 1,
                    }
                ],
                "page_info": {"page": 1, "page_size": 100, "total_page": 1},
            },
        }
        base_inputs = {
            "time_dims": "day",
            "date_list": ["2026-08-07", "2026-08-07"],
            "metrics_list": ["ap_cost"],
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [
                    FakeResponse(standard),
                    FakeResponse(empty_custom),
                    FakeResponse(empty_custom),
                    FakeResponse(business),
                ],
                operation_manifest=multidim,
                allow_experimental=True,
            )
            with self.assertRaisesRegex(InputValidationError, "data_dims/relate_dims"):
                client.read(
                    "report.multidim.query",
                    {**base_inputs, "data_dims": ["arbitrary_private_dimension"]},
                )
            self.assertEqual(3, len(transport.calls))

            result = client.read(
                "report.multidim.query",
                {**base_inputs, "data_dims": ["day"]},
            )
        self.assertEqual(4, len(transport.calls))
        self.assertEqual("success", result["status"])
        self.assertEqual(
            {
                "day": "2026-08-07",
                "advertiser_id": "advertiser-1",
                "gid": "group-1",
                "ap_cost": 1,
            },
            result["data"]["list"][0],
        )

    def test_multidim_numeric_suffix_metrics_are_projected_for_requested_days(self):
        multidim = repository_manifest(
            "report.multidim.metric.list",
            "report.multidim.query",
        )
        metadata = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "name": "multi_day_roi_all",
                        "tag_ids": [],
                        "exclusion_dims": [],
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        business = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "stat_time": "2026-08-07",
                        "multi_day_roi_all_2": 0.03,
                        "multi_day_roi_all_3": 0.04,
                    }
                ],
                "total": {
                    "stat_time": "-",
                    "multi_day_roi_all_2": 0.03,
                    "multi_day_roi_all_3": 0.04,
                },
                "page_info": {"total": 1},
            },
        }
        inputs = {
            "time_dims": "day",
            "date_list": ["2026-08-07", "2026-08-07"],
            "data_dims": [],
            "metrics_list": ["multi_day_roi_all"],
            "multi_keys": [2, 3],
        }
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata), FakeResponse(business)],
                operation_manifest=multidim,
            )
            result = client.read("report.multidim.query", inputs)

        self.assertEqual("success", result["status"])
        self.assertEqual(
            {
                "stat_time": "2026-08-07",
                "multi_day_roi_all_2": 0.03,
                "multi_day_roi_all_3": 0.04,
            },
            result["data"]["list"][0],
        )
        self.assertEqual(0.04, result["data"]["total"]["multi_day_roi_all_3"])
        self.assertEqual(
            [2, 3], transport.calls[1][2]["body"]["data_conf"]["multi_keys"]
        )
        self.assertNotIn("multi_keys", transport.calls[1][2]["body"])

    def test_multidim_reviewed_implicit_metric_dependencies_are_omitted(self):
        multidim = repository_manifest(
            "report.multidim.metric.list",
            "report.multidim.query",
        )
        metadata = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "name": "multi_day_revenue",
                        "tag_ids": [],
                        "exclusion_dims": [],
                    }
                ],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        horizons = (2, 3, 7, 14, 30)
        requested = {
            f"multi_day_revenue_{horizon}": float(horizon)
            for horizon in horizons
        }
        implicit = {
            "ad_1day_amount": 1.0,
            "standard_1day_pay_amount": 2.0,
            **{
                f"multi_day_ad_amount_{horizon}": float(horizon)
                for horizon in horizons
            },
            **{
                f"multi_day_pay_amount_{horizon}": float(horizon)
                for horizon in horizons
            },
        }
        business = {
            "code": 0,
            "data": {
                "list": [
                    {"stat_time": "2026-07-01", **requested, **implicit}
                ],
                "total": {"stat_time": "-", **requested, **implicit},
                "page_info": {"page": 1, "page_size": 1, "total_page": 1},
            },
        }
        inputs = {
            "time_dims": "day",
            "date_list": ["2026-07-01", "2026-07-01"],
            "data_dims": [],
            "metrics_list": ["multi_day_revenue"],
            "multi_keys": list(horizons),
            "page": 1,
            "page_size": 1,
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _transport = client_for(
                Path(directory),
                [FakeResponse(metadata), FakeResponse(business)],
                operation_manifest=multidim,
            )
            result = client.read("report.multidim.query", inputs)

        self.assertEqual("success", result["status"])
        self.assertEqual(
            {"stat_time": "2026-07-01", **requested},
            result["data"]["list"][0],
        )
        self.assertEqual(
            {"stat_time": "-", **requested},
            result["data"]["total"],
        )
        self.assertFalse(
            any("unregistered" in warning for warning in result["warnings"])
        )

    def test_multidim_paid_retention_implicit_count_is_omitted(self):
        multidim = repository_manifest(
            "report.multidim.metric.list", "report.multidim.query"
        )
        metrics = "standard_activate_cnt standard_1day_pay_uv standard_1day_pay_rate multi_day_1day_pay_user_retention_rate multi_day_pay_user_retention_cnt".split()
        metadata = {
            "code": 0,
            "data": {"list": [{"name": name, "tag_ids": [], "exclusion_dims": []} for name in metrics]},
        }
        row = {
            "stat_time": "2026-07-01", "standard_activate_cnt": 3,
            "standard_1day_pay_uv": 2, "standard_1day_pay_rate": 0.5,
            "multi_day_1day_pay_user_retention_rate_2": 0.25,
            "multi_day_pay_user_retention_cnt_2": 1,
            "multi_day_1day_pay_user_retention_cnt_2": 1,
        }
        business = {"code": 0, "data": {"list": [row], "total": row}}
        inputs = {
            "time_dims": "day", "date_list": ["2026-07-01", "2026-07-01"],
            "metrics_list": metrics, "multi_keys": [2],
        }
        with tempfile.TemporaryDirectory() as directory:
            client, _transport = client_for(
                Path(directory), [FakeResponse(metadata), FakeResponse(business)], operation_manifest=multidim,
            )
            result = client.read("report.multidim.query", inputs)

        expected = {key: value for key, value in row.items() if "_cnt_2" not in key or key == "multi_day_pay_user_retention_cnt_2"}
        self.assertEqual("success", result["status"])
        self.assertEqual(expected, result["data"]["list"][0])
        self.assertEqual(expected, result["data"]["total"])

    def test_calc_total_data_rows_are_field_controlled_before_network(self):
        calc_only = repository_manifest(
            "report.multidim.query", "report.multidim.calc_total"
        )
        base = {
            "time_dims": "day",
            "date_list": ["2026-08-07", "2026-08-07"],
            "data_dims": [],
            "metrics_list": ["ap_cost"],
        }
        unsafe_rows = [
            {"email_address": "private@example.invalid"},
            {"new_sensitive_field": "private"},
            {"ap_cost": {"nested": 1}},
        ]
        for row in unsafe_rows:
            with self.subTest(row_keys=tuple(row)), tempfile.TemporaryDirectory() as directory:
                client, transport = client_for(
                    Path(directory), [], operation_manifest=calc_only
                )
                with self.assertRaises(InputValidationError):
                    client.read(
                        "report.multidim.calc_total",
                        {**base, "data_list": [row]},
                    )
                self.assertEqual([], transport.calls)

        controlled = repository_manifest(
            "report.multidim.metric.list",
            "report.multidim.query",
            "report.multidim.calc_total",
        )
        metadata = {
            "code": 0,
            "data": {
                "list": [
                    {"name": "ap_cost", "tag_ids": [], "exclusion_dims": []}
                ],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        total = {"code": 0, "data": {"list": [{"ap_cost": 1}]}}
        safe_row = {"day": "2026-08-07", "ap_cost": 1}
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata), FakeResponse(total)],
                operation_manifest=controlled,
            )
            result = client.read(
                "report.multidim.calc_total",
                {**base, "data_list": [safe_row]},
            )
        self.assertEqual("success", result["status"])
        self.assertEqual([safe_row], transport.calls[1][2]["body"]["data_list"])

    def test_composite_calc_total_accepts_contracted_advertiser_and_group_ids(self):
        multidim = repository_manifest(
            "report.multidim.metric.list",
            "report.multidim.query",
            "report.multidim.calc_total",
        )
        metadata = {
            "code": 0,
            "data": {
                "list": [
                    {"name": "ap_cost", "tag_ids": [], "exclusion_dims": []}
                ],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }
        row = {
            "day": "2026-08-07",
            "advertiser_id": "advertiser-1",
            "gid": "group-1",
            "ap_cost": 1,
        }
        query = {
            "code": 0,
            "data": {
                "list": [row],
                "page_info": {"page": 1, "page_size": 100, "total_page": 1},
            },
        }
        total = {"code": 0, "data": {"list": [row]}}
        with tempfile.TemporaryDirectory() as directory:
            client, transport = client_for(
                Path(directory),
                [FakeResponse(metadata), FakeResponse(query), FakeResponse(total)],
                operation_manifest=multidim,
            )
            result = CompositeService(client).multidim_query(
                {
                    "time_dims": "day",
                    "date_list": ["2026-08-07", "2026-08-07"],
                    "data_dims": ["day"],
                    "metrics_list": ["ap_cost"],
                },
                include_total=True,
            )

        self.assertEqual("success", result["status"])
        self.assertEqual(row, transport.calls[2][2]["body"]["data_list"][0])
        self.assertEqual(row, result["total"]["data"]["list"][0])

    def test_read_all_enforces_item_limit_for_nonpaginated_direct_lists(self):
        direct_list = manifest()
        operation = direct_list["operations"][0]
        operation["response_projection"] = {
            "data_shape": "list",
            "data_keys": [],
            "required_data_keys": [],
            "item_keys": ["id"],
            "dynamic_item_fields": [],
        }
        operation["pagination"] = {"kind": "none"}
        payload = {"code": 0, "data": [{"id": 1}, {"id": 2}, {"id": 3}]}
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory), [FakeResponse(payload)], operation_manifest=direct_list
            )
            with self.assertRaisesRegex(PaginationError, "item safety bound"):
                client.read_all("example.items.list", {}, max_items=2)

    def test_composite_service_validates_live_metadata_and_returns_partial_snapshots(self):
        class PublicClient:
            def __init__(self, *, metadata_available=True):
                self.calls = []
                self.metadata_available = metadata_available

            def operations(self, **filters):
                if filters.get("domain") != "promotion":
                    return []
                if filters.get("platform") == "bytedance":
                    return [
                        {
                            "operation_id": "promotion.bytedance.advertiser.list",
                            "domain": "promotion",
                            "platform": "bytedance",
                            "resource": "advertiser",
                            "action": "list",
                            "stability": "stable",
                        }
                    ]
                return []

            def schema(self, operation_id=None):
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
                raise KeyError(operation_id)

            def read_all(self, operation_id, inputs=None, **bounds):
                self.calls.append(("read_all", operation_id, inputs, bounds))
                if not self.metadata_available:
                    raise InputValidationError("metadata unavailable")
                return {
                    "status": "success",
                    "data": {
                        "list": [
                            {"name": "ap_cost", "exclusion_dims": ["country"]}
                        ]
                    },
                }

            def read(self, operation_id, inputs=None):
                self.calls.append(("read", operation_id, inputs))
                if operation_id == "report.multidim.query":
                    return {
                        "status": "success",
                        "data": {"list": [{"ap_cost": 1}]},
                    }
                if operation_id == "report.multidim.calc_total":
                    return {"status": "success", "data": {"list": []}}
                raise AssertionError(operation_id)

            def batch(self, requests, **options):
                self.calls.append(("batch", requests, options))
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

        public = PublicClient()
        service = CompositeService(public)
        result = service.multidim_query(
            {"metrics_list": ["ap_cost"], "data_dims": ["day"]},
            include_total=True,
        )
        self.assertEqual("validated_exclusions_only", result["validation"]["status"])
        self.assertEqual("success", result["status"])
        calc_call = next(call for call in public.calls if call[1] == "report.multidim.calc_total")
        self.assertEqual([{"ap_cost": 1}], calc_call[2]["data_list"])

        public.calls.clear()
        paged = service.multidim_query(
            {"metrics_list": ["ap_cost"], "data_dims": []},
            read_all=True,
            max_pages=7,
            max_items=321,
            max_workers=9,
        )
        self.assertEqual("success", paged["status"])
        query_call = next(
            call
            for call in public.calls
            if call[0] == "read_all" and call[1] == "report.multidim.query"
        )
        self.assertEqual(
            {"max_pages": 7, "max_items": 321, "max_workers": 9},
            query_call[3],
        )

        public.calls.clear()
        with self.assertRaises(InputValidationError):
            service.multidim_query(
                {"metrics_list": ["unknown_metric"], "data_dims": []}
            )
        self.assertFalse(any(call[1] == "report.multidim.query" for call in public.calls))

        public.calls.clear()
        with self.assertRaisesRegex(InputValidationError, "data_dims"):
            service.multidim_query({"metrics_list": [], "data_dims": ["day"]})
        self.assertEqual([], public.calls)

        public.calls.clear()
        with self.assertRaises(InputValidationError):
            service.multidim_query(
                {"metrics_list": ["ap_cost"], "data_dims": ["country"]}
            )
        self.assertFalse(any(call[1] == "report.multidim.query" for call in public.calls))

        unavailable = PublicClient(metadata_available=False)
        with self.assertRaisesRegex(InputValidationError, "not executed"):
            CompositeService(unavailable).multidim_query(
                {"metrics_list": ["ap_cost"], "data_dims": []}
            )
        self.assertFalse(any(call[1] == "report.multidim.query" for call in unavailable.calls))

        snapshot = service.promotion_snapshot(
            ["bytedance", "kuaishou"], common_inputs={"page": 1}
        )
        self.assertEqual("partial", snapshot["status"])
        self.assertEqual(2, snapshot["coverage"]["requested"])
        self.assertEqual("success", snapshot["results"][0]["status"])
        self.assertEqual("unavailable", snapshot["results"][1]["status"])

    def test_transport_retries_transient_status_and_semantic_error_is_sanitized(self):
        success = {"code": 0, "data": {"list": [], "page_info": {"page": 1, "total_page": 1}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = CredentialProvider(env_file(root), environ={}, persist=False)
            session = FakeSession([FakeResponse({}, 503), FakeResponse(success)])
            operation = load_operation_manifest(manifest())[0]
            policy = PolicyEngine(Registry([operation]))
            transport = Transport(
                provider,
                policy=policy,
                session=session,
                sleeper=lambda _: None,
            )
            authorization = policy._prepare_request(operation.operation_id, {})
            response = transport.request(
                authorization.method,
                authorization.path,
                operation=operation,
                query=authorization.query,
                body=authorization.body,
                authorization=authorization,
            )
            self.assertEqual(0, response.payload["code"])
            self.assertEqual(2, len(session.calls))
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse({
                    "code": 0,
                    "data": {
                        "list": [{"id": 1, "value": 2, "future_rank": 7}],
                        "page_info": {"page": 1, "total_page": 1},
                    },
                })],
            )
            drifted = client.read("example.items.list", {})
            self.assertEqual("success", drifted["status"])
            self.assertIn(
                {"path": "/data/list/*/future_rank", "observed_type": "integer"},
                drifted["result_audit"]["response_drift"]["fields"],
            )
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse({"code": 0, "msg": "成功", "extra": {"error": "无数据"},
                               "data": {"list": [], "page_info": {"page": 1, "total_page": 1},
                                        "future_empty": []}})],
            )
            explicit_empty = client.read("example.items.list", {})
            self.assertEqual("empty", explicit_empty["status"])
            self.assertNotIn("response_drift", explicit_empty["result_audit"])
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse({"code": 200, "data": {"list": []}})])
            self.assertEqual("empty", client.read("example.items.list", {})["status"])
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [FakeResponse(None, 204)])
            self.assertEqual("empty", client.read("example.items.list", {})["status"])
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [FakeResponse({"code": 0, "extra": {"error": "private upstream detail"}, "data": {"list": []}})],
            )
            semantic = client.read("example.items.list", {})
            self.assertEqual("semantic_error", semantic["status"])
            self.assertEqual("INPUT_INVALID", semantic["error"]["code"])
            self.assertEqual("caller", semantic["error"]["category"])
            self.assertFalse(semantic["error"]["retryable"])
            self.assertNotIn("private upstream detail", json.dumps(semantic))

    def test_transport_auth_refresh_gets_one_retry_with_attempts_one(self):
        class Credentials:
            def __init__(self):
                self.refreshes = 0

            def get(self):
                return Credential("old")

            def refresh(self):
                self.refreshes += 1
                return Credential("new")

        credentials = Credentials()
        session = FakeSession(
            [
                FakeResponse({}, 401),
                FakeResponse(
                    {"code": 0, "data": {"list": [], "page_info": {"page": 1, "total_page": 1}}}
                ),
            ]
        )
        operation = load_operation_manifest(manifest())[0]
        policy = PolicyEngine(Registry([operation]))
        transport = Transport(
            credentials,
            policy=policy,
            session=session,
            attempts=1,
            sleeper=lambda _: None,
        )
        authorization = policy._prepare_request(operation.operation_id, {})
        result = transport.request(
            authorization.method,
            authorization.path,
            operation=operation,
            query=authorization.query,
            body=authorization.body,
            authorization=authorization,
        )
        self.assertEqual(0, result.payload["code"])
        self.assertEqual(1, credentials.refreshes)
        self.assertEqual(2, len(session.calls))

    def test_transport_applies_a_shared_proactive_rate_limit(self):
        class Credentials:
            def get(self):
                return Credential("opaque")

        now = [0.0]
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        success = {
            "code": 0,
            "data": {"list": [], "page_info": {"page": 1, "total_page": 1}},
        }
        session = FakeSession([FakeResponse(success), FakeResponse(success)])
        operation = load_operation_manifest(manifest())[0]
        policy = PolicyEngine(Registry([operation]))
        transport = Transport(
            Credentials(),
            policy=policy,
            session=session,
            sleeper=sleep,
            requests_per_second=2,
            rate_clock=lambda: now[0],
        )
        for _ in range(2):
            authorization = policy._prepare_request(operation.operation_id, {})
            transport.request(
                authorization.method,
                authorization.path,
                operation=operation,
                query=authorization.query,
                body=authorization.body,
                authorization=authorization,
            )
        self.assertEqual([0.5], sleeps)
        self.assertEqual(2, len(session.calls))

    def test_transport_403_after_refresh_becomes_permission_envelope(self):
        class Credentials:
            def __init__(self):
                self.refreshes = 0

            def get(self):
                return Credential("opaque")

            def refresh(self):
                self.refreshes += 1
                return Credential("refreshed")

        credentials = Credentials()
        session = FakeSession([FakeResponse({}, 403), FakeResponse({}, 403)])
        operation = load_operation_manifest(manifest())[0]
        policy = PolicyEngine(Registry([operation]))
        transport = Transport(
            credentials,
            policy=policy,
            session=session,
            attempts=1,
            sleeper=lambda _: None,
        )
        authorization = policy._prepare_request(operation.operation_id, {})
        with self.assertRaises(PermissionUnavailableError):
            transport.request(
                authorization.method,
                authorization.path,
                operation=operation,
                query=authorization.query,
                body=authorization.body,
                authorization=authorization,
            )
        self.assertEqual(1, credentials.refreshes)
        self.assertEqual(2, len(session.calls))

        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(
                Path(directory),
                [PermissionUnavailableError("private permission detail")],
            )
            envelope = client.read("example.items.list", {})
        self.assertEqual("permission_unavailable", envelope["status"])
        # Permission is account/caller state, not evidence that the upstream
        # capability or its contract is unhealthy.
        self.assertEqual(0, client.operation_coverage()["failed"])

    def test_transport_rejects_unowned_operation_specs_before_network(self):
        safe = load_operation_manifest(manifest())[0]
        session = FakeSession([])

        class Credentials:
            def get(self):
                return Credential("opaque")

        transport = Transport(
            Credentials(),
            policy=PolicyEngine(Registry([safe])),
            session=session,
        )
        same_id_write = load_operation_manifest(
            manifest(path="/report/api/v3/example/create/")
        )[0]
        different_id_document = manifest(path="/report/api/v3/example/update/")
        different_id_document["operations"][0]["operation_id"] = "evil.items.list"
        different_id_write = load_operation_manifest(different_id_document)[0]

        for operation in (same_id_write, different_id_write):
            with self.subTest(operation_id=operation.operation_id):
                with self.assertRaises(PolicyViolation):
                    transport.request(
                        "POST",
                        operation.path_template,
                        operation=operation,
                        body={},
                    )
        self.assertEqual([], session.calls)

    def test_transport_rejects_direct_extra_query_or_body_fields_before_network(self):
        operation = load_operation_manifest(manifest())[0]
        session = FakeSession([])

        class Credentials:
            def get(self):
                return Credential("opaque")

        transport = Transport(
            Credentials(),
            policy=PolicyEngine(Registry([operation])),
            session=session,
        )
        attempts = (
            {
                "query": {"unauthorized_extra": "private"},
                "body": {
                    "page": 1,
                    "page_size": 2,
                    "filter": "",
                    "read_mode": "safe",
                },
            },
            {
                "query": {},
                "body": {
                    "page": 1,
                    "page_size": 2,
                    "filter": "",
                    "read_mode": "safe",
                    "unauthorized_extra": "private",
                },
            },
            {
                "query": {},
                "body": {
                    "page": 1,
                    "page_size": 2,
                    "filter": "",
                    "read_mode": "tampered",
                },
            },
        )
        for request in attempts:
            with self.subTest(query=request["query"], body=request["body"]):
                with self.assertRaises(PolicyViolation):
                    transport.request(
                        "POST",
                        operation.path_template,
                        operation=operation,
                        query=request["query"],
                        body=request["body"],
                    )
        self.assertEqual([], session.calls)

    def test_transport_authorization_is_exact_and_one_shot(self):
        operation = load_operation_manifest(manifest())[0]
        policy = PolicyEngine(Registry([operation]))
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "list": [],
                            "page_info": {"page": 1, "total_page": 1},
                        },
                    }
                )
            ]
        )

        class Credentials:
            def get(self):
                return Credential("opaque")

        transport = Transport(Credentials(), policy=policy, session=session)
        authorization = policy._prepare_request(operation.operation_id, {})
        transport.request(
            authorization.method,
            authorization.path,
            operation=operation,
            query=authorization.query,
            body=authorization.body,
            authorization=authorization,
        )
        self.assertEqual(1, len(session.calls))

        with self.assertRaises(PolicyViolation):
            transport.request(
                authorization.method,
                authorization.path,
                operation=operation,
                query=authorization.query,
                body=authorization.body,
                authorization=authorization,
            )

        tampered_query = policy._prepare_request(operation.operation_id, {})
        with self.assertRaises(PolicyViolation):
            transport.request(
                tampered_query.method,
                tampered_query.path,
                operation=operation,
                query={**tampered_query.query, "unauthorized_extra": "private"},
                body=tampered_query.body,
                authorization=tampered_query,
            )

        tampered_body = policy._prepare_request(operation.operation_id, {})
        with self.assertRaises(PolicyViolation):
            transport.request(
                tampered_body.method,
                tampered_body.path,
                operation=operation,
                query=tampered_body.query,
                body={**tampered_body.body, "read_mode": "tampered"},
                authorization=tampered_body,
            )
        self.assertEqual(1, len(session.calls))

    def test_manifest_authorized_get_can_send_its_exact_json_body(self):
        controlled = manifest()
        document = controlled["operations"][0]
        document["upstream_method"] = "GET"
        document["input_fields"] = {
            "app_id": {"type": "string", "required": True}
        }
        document["request"] = {
            "path_fields": [],
            "query_fields": [],
            "body_fields": ["app_id"],
            "defaults": {},
            "fixed_query": {},
            "fixed_body": {},
        }
        document["live_probe"] = {
            "enabled": True,
            "input": {"app_id": "app-1"},
        }
        document["pagination"] = {"kind": "none"}
        operation = load_operation_manifest(controlled)[0]
        policy = PolicyEngine(Registry([operation]))
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "list": [],
                            "page_info": {"page": 1, "total_page": 1},
                        },
                    }
                )
            ]
        )

        class Credentials:
            def get(self):
                return Credential("opaque")

        transport = Transport(Credentials(), policy=policy, session=session)
        authorization = policy._prepare_request(
            operation.operation_id, {"app_id": "app-1"}
        )
        transport.request(
            authorization.method,
            authorization.path,
            operation=operation,
            query=authorization.query,
            body=authorization.body,
            authorization=authorization,
        )
        self.assertEqual("GET", session.calls[0][0])
        self.assertEqual({"app_id": "app-1"}, session.calls[0][2]["json"])

    def test_runtime_rejects_forged_receipt_and_unregistered_path_before_network(self):
        operation = load_operation_manifest(manifest())[0]
        policy = PolicyEngine(Registry([operation]))
        session = FakeSession([])

        class Credentials:
            def get(self):
                return Credential("opaque")

        runtime = GravityHttpRuntime(
            session=session,
            credentials=Credentials(),
            requests_per_second=100,
            sleeper=lambda _delay: None,
            interval_jitter_ratio=0.0,
        )
        genuine = policy._prepare_request(operation.operation_id, {})
        forged = _AuthorizedRequest(
            nonce=genuine.nonce,
            operation=genuine.operation,
            method=genuine.method,
            path=genuine.path,
            query=genuine.query,
            body=genuine.body,
        )
        with self.assertRaises(PolicyViolation):
            runtime._request_insight(
                forged.method,
                forged.path,
                policy_authorization=forged,
                params=forged.query,
                json_body=forged.body,
            )
        self.assertEqual([], session.calls)

        with self.assertRaises(PolicyViolation):
            runtime._request_insight(
                genuine.method,
                "/report/api/v3/unregistered/list/",
                policy_authorization=genuine,
                params=genuine.query,
                json_body=genuine.body,
            )
        self.assertEqual([], session.calls)

    def test_manifest_authorized_account_and_apprank_reads_reach_runtime(self):
        class Credentials:
            def get(self):
                return Credential("opaque")

        paths = (
            "/account_center/api/v1/company/capacity/info/",
            "/apprank/api/v1/app/list/",
        )
        for path in paths:
            with self.subTest(path=path):
                operation = load_operation_manifest(manifest(path=path))[0]
                policy = PolicyEngine(Registry([operation]))
                session = FakeSession([FakeResponse({"code": 0, "data": []})])
                runtime = GravityHttpRuntime(
                    session=session,
                    credentials=Credentials(),
                    requests_per_second=100,
                    sleeper=lambda _delay: None,
                    interval_jitter_ratio=0.0,
                )
                authorization = policy._prepare_request(operation.operation_id, {})

                response = runtime._request_insight(
                    authorization.method,
                    authorization.path,
                    policy_authorization=authorization,
                    params=authorization.query,
                    json_body=authorization.body,
                )

                self.assertEqual(200, response.status_code)
                self.assertTrue(session.calls[0][1].endswith(path))

    def test_manifest_policy_keeps_account_login_outside_read_surface(self):
        operation = load_operation_manifest(
            manifest(path="/account_center/api/v1/user_login/v2/")
        )[0]
        policy = PolicyEngine(Registry([operation]))

        with self.assertRaisesRegex(PolicyViolation, "approved Gravity API namespaces"):
            policy._prepare_request(operation.operation_id, {})

    def test_authorized_wire_payload_is_a_deep_toctou_safe_snapshot(self):
        controlled = manifest()
        operation_document = controlled["operations"][0]
        operation_document["input_fields"]["filters"] = {
            "type": "array",
            "default": [],
        }
        operation_document["request"]["body_fields"].append("filters")
        operation_document["request"]["defaults"]["filters"] = []
        operation = load_operation_manifest(controlled)[0]
        policy = PolicyEngine(Registry([operation]))
        entered = threading.Event()
        release = threading.Event()

        class Credentials:
            def get(self):
                return Credential("opaque")

        class BlockingSession:
            def __init__(self):
                self.wire_body = None

            def request(self, _method, _url, **kwargs):
                entered.set()
                if not release.wait(2):
                    raise AssertionError("test did not release the request")
                self.wire_body = json.loads(json.dumps(kwargs["json"]))
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "list": [],
                            "page_info": {"page": 1, "total_page": 1},
                        },
                    }
                )

        session = BlockingSession()
        transport = Transport(Credentials(), policy=policy, session=session)
        caller_inputs = {
            "filters": [
                {"field": "id", "operator": "EQUALS", "values": [1]}
            ]
        }
        authorization = policy._prepare_request(operation.operation_id, caller_inputs)
        failure = []

        def send():
            try:
                transport.request(
                    authorization.method,
                    authorization.path,
                    operation=operation,
                    query=authorization.query,
                    body=authorization.body,
                    authorization=authorization,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                failure.append(exc)

        thread = threading.Thread(target=send)
        thread.start()
        self.assertTrue(entered.wait(2))
        caller_inputs["filters"][0]["field"] = "new_sensitive_field"
        authorization.body["filters"][0]["field"] = "new_sensitive_field"
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], failure)
        self.assertEqual("id", session.wire_body["filters"][0]["field"])

    def test_package_public_surface_excludes_low_level_request_primitives(self):
        try:
            import gravity_sdk as public_package
        except ModuleNotFoundError:
            import gravity_sdk as public_package

        for name in (
            "Transport",
            "TransportResponse",
            "OperationSpec",
            "Registry",
            "PolicyEngine",
            "ReadExecutor",
            "load_operation_manifest",
            "GravityHttpRuntime",
            "GravityRequester",
            "HostRateLimiter",
            "RequestProfile",
            "INSIGHT_PROFILE",
            "SQL_PROFILE",
            "get_shared_runtime",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(public_package, name))

        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), [])
            for name in (
                "registry",
                "executor",
                "field_policy",
                "metadata_cache",
                "operation_catalog",
            ):
                self.assertFalse(hasattr(client, name))

    def test_public_client_cannot_load_an_external_manifest(self):
        self.assertFalse(hasattr(GravityInsightClient, "from_manifest"))
        with self.assertRaises(TypeError):
            GravityInsightClient.from_env(manifest_dir=Path("outside"))
        for path in (
            "/report/api/v3/example/submit/",
            "/report/api/v3/example/update_operator/",
            "/report/api/v3/example/favorites/collect/",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                client, transport = client_for(
                    Path(directory), [], operation_manifest=manifest(path=path)
                )
                with self.assertRaises(PolicyViolation):
                    client.read("example.items.list", {})
                self.assertEqual([], transport.calls)

    def test_batch_preserves_order_and_contains_safe_failures(self):
        responses = [
            FakeResponse({"code": 0, "data": {"list": [], "page_info": {"page": 1, "total_page": 1}}}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            client, _ = client_for(Path(directory), responses)
            result = client.batch(
                [
                    {"request_id": "one", "operation_id": "example.items.list", "inputs": {}},
                    {"request_id": "two", "operation_id": "unknown.items.list", "inputs": {}},
                ],
                max_workers=1,
            )
        self.assertTrue(result[0]["ok"])
        self.assertFalse(result[1]["ok"])
        self.assertEqual(["one", "two"], [item["request_id"] for item in result])

    def test_login_uses_trimmed_md5_seven_days_and_jwt_expiry(self):
        exp = int((NOW + timedelta(hours=3)).timestamp())
        jwt_body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        token = f"header.{jwt_body}.signature"
        login_session = FakeSession(
            [FakeResponse({"code": 0, "data": {"day": 7, "user": {"Authorization": token}}})]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text("GRAVITY_USERNAME= user@example.invalid \nGRAVITY_PASSWORD= pass word \n", encoding="utf-8")
            provider = CredentialProvider(
                path,
                environ={},
                session=login_session,
                clock=lambda: NOW,
                persist=False,
            )
            credential = provider.get()
        body = login_session.calls[0][2]["json"]
        self.assertEqual(7, body["free_login_day"])
        self.assertEqual(hashlib.md5(b"pass word").hexdigest(), body["password"])
        self.assertEqual(datetime.fromtimestamp(exp, timezone.utc), credential.expires_at)
        self.assertNotIn(token, repr(credential))

    def test_refresh_is_single_flight_and_atomic_update_preserves_other_keys(self):
        calls = 0
        gate = threading.Event()

        def login(username, password):
            nonlocal calls
            calls += 1
            gate.wait(1)
            return {"code": 0, "data": {"day": 7, "user": {"Authorization": "fresh-token"}}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = env_file(root, expires=NOW - timedelta(hours=1))
            provider = CredentialProvider(path, environ={}, login=login, clock=lambda: NOW, persist=False)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(provider.get) for _ in range(4)]
                gate.set()
                credentials = [future.result() for future in futures]
            self.assertEqual(1, calls)
            self.assertEqual({"fresh-token"}, {item.token for item in credentials})

            path.write_text("# keep\nGRAVITY_USERNAME=user\nCUSTOM_KEY=value\nGRAVITY_AUTH_TOKEN=old\n", encoding="utf-8")
            with patch(f"{_atomic_update_env.__module__}._restrict_secret_file") as restrict:
                _atomic_update_env(path, {"GRAVITY_AUTH_TOKEN": "new", "GRAVITY_AUTH_UPDATED_AT": "now"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("# keep", text)
            self.assertIn("CUSTOM_KEY=value", text)
            self.assertIn("GRAVITY_AUTH_TOKEN=new", text)
            restrict.assert_called_once()

    def test_environment_overrides_file_without_mutating_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = env_file(Path(directory), token="file-token")
            provider = CredentialProvider(path, environ={"GRAVITY_AUTH_TOKEN": "env-token"}, persist=False)
            self.assertEqual("env-token", provider.get().token)


if __name__ == "__main__":
    unittest.main()
