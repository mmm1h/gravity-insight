from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.http_runtime import INSIGHT_PROFILE
    from gravity_insight.models import load_operation_manifest
    from gravity_insight.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.http_runtime import INSIGHT_PROFILE
    from gravity_insight.models import load_operation_manifest
    from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_insight" / "manifests"
DIRECTORY_MANIFEST = MANIFEST_DIR / "analysis_directory.json"


class RoutingTransport:
    is_test_transport = True

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        with self.lock:
            self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            self.handler(method, path, kwargs),
            "2026-08-08T08:00:00Z",
        )


def repository_manifest(*operation_ids: str) -> dict[str, Any]:
    all_operations: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for operation in document.get("operations", []):
            all_operations[operation["operation_id"]] = operation

    selected: dict[str, dict[str, Any]] = {}
    pending = list(operation_ids)
    while pending:
        operation_id = pending.pop()
        if operation_id in selected:
            continue
        operation = all_operations.get(operation_id)
        if operation is None:
            raise AssertionError(f"missing repository operation: {operation_id}")
        selected[operation_id] = operation
        pending.extend(operation.get("required_parent", ()))
    return {"manifest_version": 1, "operations": list(selected.values())}


def client_for(*operation_ids: str, handler):
    transport = RoutingTransport(handler)
    client = GravityInsightClient._from_manifest_for_tests(
        repository_manifest(*operation_ids),
        transport=transport,
    )
    return client, transport


class GravityInsightAnalysisDirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.operations = load_operation_manifest(DIRECTORY_MANIFEST)
        cls.by_id = {operation.operation_id: operation for operation in cls.operations}

    def test_manifest_registers_only_two_exact_stable_reads(self) -> None:
        expected = {
            "analysis.account_user.list": (
                "GET",
                "/account_center/api/v1/user/list/",
            ),
            "analysis.dashboard.condition_favourite.default_to_me.get": (
                "POST",
                "/turbo_engine/api/v2/datamanageconfig/analysis_dashboard_condition_favourite/default_to_me/",
            ),
        }
        self.assertEqual(expected, {
            operation.operation_id: (
                operation.upstream_method,
                operation.path_template,
            )
            for operation in self.operations
        })
        for operation in self.operations:
            self.assertEqual("stable", operation.stability)
            self.assertTrue(operation.executable)
            self.assertTrue(operation.live_probe.enabled)

    def test_http_runtime_profile_accepts_governed_read_namespaces(self) -> None:
        self.assertTrue(
            INSIGHT_PROFILE.accepts("GET", "/account_center/api/v1/user/list/")
        )
        self.assertTrue(
            INSIGHT_PROFILE.accepts("POST", "/apprank/api/v1/app/list/")
        )
        self.assertFalse(
            INSIGHT_PROFILE.accepts("GET", "/outside/api/v1/user/list/")
        )

    def test_account_user_projects_analysis_safe_member_contract(self) -> None:
        row = {
            "avatar": "avatar-url",
            "company_id": 2,
            "company_name": "company",
            "create_time": "2026-08-08 00:00:00",
            "dept_id": 3,
            "dept_info": {"id": 3, "name": "dept", "is_enabled": True},
            "email": "member@example.invalid",
            "id": 4,
            "is_banned": False,
            "is_deleted": False,
            "is_main": True,
            "is_superuser": False,
            "modify_time": "2026-08-08 00:00:00",
            "name": "member",
            "phone": "masked-phone",
            "remark": "remark",
            "roles": [
                {"id": 5, "name": "role", "code": "reader", "is_enabled": 1}
            ],
            "user_id": 4,
        }
        client, transport = client_for(
            "analysis.account_user.list",
            handler=lambda _method, _path, _kwargs: {
                "code": 0,
                "data": {
                    "list": [row],
                    "page_info": {
                        "page": 1,
                        "page_size": 1,
                        "total_number": 1,
                        "total_page": 1,
                    },
                },
            },
        )

        result = client.read(
            "analysis.account_user.list",
            {"page": 1, "page_size": 1, "filters": []},
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(row, result["data"]["list"][0])
        self.assertIsInstance(result["data"]["list"][0]["is_superuser"], bool)
        self.assertEqual("dept", result["data"]["list"][0]["dept_info"]["name"])
        self.assertEqual("role", result["data"]["list"][0]["roles"][0]["name"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual("/account_center/api/v1/user/list/", path)
        self.assertEqual({"page": 1, "page_size": 1}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))

    def test_account_user_encodes_only_current_frontend_filters(self) -> None:
        client, transport = client_for(
            "analysis.account_user.list",
            handler=lambda _method, _path, _kwargs: {
                "code": 0,
                "data": {
                    "list": [],
                    "page_info": {
                        "page": 2,
                        "page_size": 20,
                        "total_number": 0,
                        "total_page": 0,
                    },
                },
            },
        )
        filters = [
            {"field": "dept_id", "operator": 6, "values": [7]},
            {"field": "role_id", "operator": 6, "values": [8]},
        ]

        result = client.read(
            "analysis.account_user.list",
            {"page": 2, "page_size": 20, "filters": filters},
        )

        self.assertEqual("empty", result["status"])
        query = dict(transport.calls[0][2]["query"])
        self.assertEqual(2, query.pop("page"))
        self.assertEqual(20, query.pop("page_size"))
        self.assertEqual(
            json.dumps(filters, ensure_ascii=False, separators=(",", ":")),
            query.pop("filters"),
        )
        self.assertEqual({}, query)

    def test_account_user_filter_profile_fails_closed_before_network(self) -> None:
        client, transport = client_for(
            "analysis.account_user.list",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )
        invalid = (
            [{"field": "company_id", "operator": 1, "values": [2]}],
            [{"field": "dept_id", "operator": 8, "values": [2]}],
            [{"field": "name", "operator": 6, "values": ["member"]}],
            [{"field": "name", "operator": 8, "values": ["member"]}],
            [{"field": "phone", "operator": 8, "values": ["123"]}],
            [{"field": "email", "operator": 8, "values": ["example"]}],
            [{"field": "email", "operator": 8, "values": [1]}],
        )
        for filters in invalid:
            with self.subTest(filters=filters):
                with self.assertRaises(InputValidationError):
                    client.read(
                        "analysis.account_user.list",
                        {"page": 1, "page_size": 10, "filters": filters},
                    )
        self.assertEqual([], transport.calls)

    def test_default_favourite_preserves_opaque_config_and_redacts_secrets(self) -> None:
        favourite = {
            "id": 9,
            "app_id": 101,
            "dashboard_id": 3,
            "name": "default",
            "default_to_one": True,
            "default_to_all": False,
            "isCollection": True,
            "cond_logic": "AND",
            "condition": [
                {"field": "country", "operator": "IN", "value": ["CN"]}
            ],
            "config": {
                "uid": "filter-1",
                "filterCondition": "且",
                "eventLabel": "event",
                "eventValue": "purchase",
                "filter": [
                    {
                        "uid": "condition-1",
                        "type": "user",
                        "value": ["CN", 1, True],
                        "conditionList": ["CN"],
                        "token": "must-not-leak",
                    }
                ],
                "cookie": "must-not-leak",
            },
            "remark": "",
            "to_use": True,
            "show_order": 1,
        }
        client, transport = client_for(
            "analysis.dashboard.condition_favourite.default_to_me.get",
            handler=lambda _method, _path, _kwargs: {
                "code": 0,
                "data": {"object": favourite},
            },
        )

        result = client.read(
            "analysis.dashboard.condition_favourite.default_to_me.get",
            {"app_id": "101", "dashboard_id": "3"},
        )

        self.assertEqual("success", result["status"])
        projected = result["data"]["object"]
        self.assertNotIn("condition", projected)
        self.assertNotIn("remark", projected)
        self.assertEqual(["CN", 1, True], projected["config"]["filter"][0]["value"])
        encoded = json.dumps(projected, ensure_ascii=False).casefold()
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn('"token"', encoded)
        self.assertNotIn('"cookie"', encoded)
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertTrue(path.endswith("/default_to_me/"))
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(
            {"app_id": "101", "dashboard_id": "3"},
            dict(kwargs["body"]),
        )

    def test_default_favourite_probe_uses_first_dashboard_resolver(self) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("/user/open_app/list/"):
                return {
                    "code": 0,
                    "data": {"list": [{"id": 101}], "page_info": {}},
                }
            if path.endswith("/kanban/tree/"):
                return {
                    "code": 0,
                    "data": [
                        {
                            "id": 1,
                            "name": "space",
                            "folder_or_dashboard": [
                                {
                                    "id": 3,
                                    "name": "dashboard",
                                    "is_folder": False,
                                    "space_id": 1,
                                }
                            ],
                        }
                    ],
                }
            if path.endswith("/default_to_me/"):
                self.assertEqual(
                    {"app_id": "101", "dashboard_id": "3"},
                    dict(kwargs["body"]),
                )
                return {"code": 0, "data": {"object": None}}
            raise AssertionError(path)

        client, transport = client_for(
            "analysis.dashboard.condition_favourite.default_to_me.get",
            handler=handler,
        )
        result = client.probe(
            "analysis.dashboard.condition_favourite.default_to_me.get"
        )

        self.assertIn(result["status"], {"success", "empty"})
        self.assertEqual(3, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
