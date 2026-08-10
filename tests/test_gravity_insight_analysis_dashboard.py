from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import InputValidationError
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import InputValidationError
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_sdk" / "manifests"
DASHBOARD_MANIFEST = MANIFEST_DIR / "analysis_dashboard.json"


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


def client_for(*operation_ids: str, handler, allow_experimental: bool = False):
    transport = RoutingTransport(handler)
    client = GravityInsightClient._from_manifest_for_tests(
        repository_manifest(*operation_ids),
        transport=transport,
        allow_experimental=allow_experimental,
    )
    return client, transport


class GravityInsightAnalysisDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.operations = load_operation_manifest(DASHBOARD_MANIFEST)
        cls.by_id = {operation.operation_id: operation for operation in cls.operations}

    def test_manifest_registers_exact_dashboard_and_template_catalog(self) -> None:
        expected_routes = {
            "analysis.dashboard.tree": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/kanban/tree/",
            ),
            "analysis.dashboard.detail": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/kanban/dashboard/detial/",
            ),
            "analysis.dashboard.members.list": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/kanban/dashboard/members/",
            ),
            "analysis.dashboard.space_members.list": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/kanban/space/members/",
            ),
            "analysis.dashboard.condition_favourite.list": (
                "POST",
                "/turbo_engine/api/v2/datamanageconfig/analysis_dashboard_condition_favourite/list/",
            ),
            "analysis.dashboard.event_list_info.get": (
                "GET",
                "/turbo_engine/api/v2/event/event_list_info/",
            ),
            "analysis.template.subject.own.list": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/template/subject/list/",
            ),
            "analysis.template.subject.share.list": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/template/subject/share/list/",
            ),
            "analysis.template.subject.internal.list": (
                "GET",
                "/turbo_engine/api/v2/datamanageconfig/template/subject_internal/list/",
            ),
            "analysis.template.own.list": (
                "POST",
                "/turbo_engine/api/v2/datamanageconfig/template/list/",
            ),
            "analysis.template.share.list": (
                "POST",
                "/turbo_engine/api/v2/datamanageconfig/template/share/list/",
            ),
            "analysis.template.internal.list": (
                "POST",
                "/turbo_engine/api/v2/datamanageconfig/template_internal/list/",
            ),
        }
        self.assertEqual(set(expected_routes), set(self.by_id))
        self.assertEqual(12, len(self.operations))
        self.assertEqual(
            expected_routes,
            {
                operation.operation_id: (
                    operation.upstream_method,
                    operation.path_template,
                )
                for operation in self.operations
            },
        )

    def test_stable_boundary_is_probeable_and_experimental_is_catalog_only(self) -> None:
        stable = set(self.by_id)
        self.assertEqual(
            stable,
            {
                operation.operation_id
                for operation in self.operations
                if operation.stability == "stable"
            },
        )
        for operation in self.operations:
            if operation.operation_id in stable:
                self.assertTrue(operation.executable)
                self.assertTrue(operation.live_probe.enabled)

    def test_dashboard_tree_uses_exact_get_query_and_recursive_projection(self) -> None:
        payload = {
            "code": 0,
            "data": [
                {
                    "id": 1,
                    "name": "space",
                    "children": None,
                    "folder_or_dashboard": [
                        {
                            "id": 2,
                            "name": "folder",
                            "type": 1,
                            "is_folder": True,
                            "dashboards": [
                                {
                                    "id": 3,
                                    "name": "dashboard",
                                    "type": 2,
                                    "is_folder": False,
                                    "space_id": 1,
                                    "authority": 2,
                                    "ui_config": "opaque-layout",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        client, transport = client_for(
            "analysis.dashboard.tree",
            handler=lambda _method, _path, _kwargs: payload,
        )

        result = client.read("analysis.dashboard.tree", {"app_id": "101"})

        self.assertEqual("success", result["status"])
        self.assertEqual(
            [
                {
                    "id": 1,
                    "name": "space",
                    "folder_or_dashboard": [
                        {
                            "id": 2,
                            "name": "folder",
                            "type": 1,
                            "is_folder": True,
                            "dashboards": [
                                {
                                    "id": 3,
                                    "name": "dashboard",
                                    "type": 2,
                                    "is_folder": False,
                                    "space_id": 1,
                                    "authority": 2,
                                }
                            ],
                        }
                    ],
                }
            ],
            result["data"],
        )
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertTrue(path.endswith("/kanban/tree/"))
        self.assertEqual({"app_id": "101"}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))

    def test_dashboard_probe_resolves_first_space_and_dashboard(self) -> None:
        tree = {
            "code": 0,
            "data": [
                {
                    "id": 1,
                    "name": "space",
                    "folder_or_dashboard": [
                        {
                            "id": 2,
                            "name": "folder",
                            "is_folder": True,
                            "dashboards": [
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
            ],
        }

        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("/user/open_app/list/"):
                return {
                    "code": 0,
                    "data": {"list": [{"id": 101}], "page_info": {}},
                }
            if path.endswith("/kanban/tree/"):
                return tree
            if path.endswith("/kanban/dashboard/detial/"):
                self.assertEqual(
                    {"app_id": "101", "id": "3", "space_id": "1"},
                    dict(kwargs["query"]),
                )
                return {"code": 0, "data": {"id": 3, "name": "dashboard"}}
            raise AssertionError(path)

        client, transport = client_for("analysis.dashboard.detail", handler=handler)
        result = client.probe("analysis.dashboard.detail")

        self.assertEqual("success", result["status"])
        self.assertEqual(3, len(transport.calls))

    def test_dashboard_and_template_opaque_configs_are_preserved_and_redacted(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("/analysis_dashboard_condition_favourite/list/"):
                return {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "id": 1,
                                "dashboard_id": 3,
                                "name": "favourite",
                                "condition": [
                                    {
                                        "field": "country",
                                        "operator": "IN",
                                        "type": "user",
                                        "value": ["CN", 1, True],
                                    }
                                ],
                                "config": {
                                    "filterCondition": "且",
                                    "filter": [{"field": "country", "value": ["CN"]}],
                                    "token": "must-not-leak",
                                },
                            }
                        ],
                        "page_info": {"page": 1, "page_size": 1, "total_page": 1},
                    },
                }
            if path.endswith("/template/list/"):
                return {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "id": 9,
                                "name": "template",
                                "template_type": "report",
                                "subject_ids": [],
                                "subject_names": [],
                                "config": {
                                    "layoutUi": {"columns": ["amount"]},
                                    "originParams": {"group_by": "day"},
                                    "cookie": "must-not-leak",
                                },
                            }
                        ],
                        "page_info": {"page": 1, "page_size": 15, "total_page": 1},
                    },
                }
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.dashboard.condition_favourite.list",
            "analysis.template.own.list",
            handler=handler,
        )
        favourite = client.read(
            "analysis.dashboard.condition_favourite.list",
            {
                "app_id": "101",
                "page": 1,
                "page_size": 1,
                "filters": [
                    {"field": "dashboard_id", "operator": 1, "values": ["3"]}
                ],
            },
        )
        template = client.read("analysis.template.own.list")

        self.assertEqual("success", favourite["status"])
        self.assertNotIn("condition", favourite["data"]["list"][0])
        self.assertEqual(
            {"columns": ["amount"]},
            template["data"]["list"][0]["config"]["layoutUi"],
        )
        encoded = json.dumps({"favourite": favourite, "template": template}).casefold()
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn('"token"', encoded)
        self.assertNotIn('"cookie"', encoded)

    def test_event_list_info_projects_only_contracted_property_metadata(self) -> None:
        row = {
            "app_id": 101,
            "cname": "amount",
            "create_time": "2026-08-08 00:00:00",
            "data_type": "FLOAT",
            "dim_table": [{"name": "region"}],
            "extra": "opaque",
            "has_dict": False,
            "id": 1,
            "is_common": True,
            "is_preset": False,
            "modify_time": "2026-08-08 00:00:00",
            "name": "amount",
            "prop_type": 1,
            "remark": "",
            "rules": "opaque",
            "uploaded": True,
            "visible": True,
        }
        payload = {
            "code": 0,
            "data": {"common": [row], "custom": [], "preset": []},
        }
        client, transport = client_for(
            "analysis.dashboard.event_list_info.get",
            handler=lambda _method, _path, _kwargs: payload,
        )

        result = client.read(
            "analysis.dashboard.event_list_info.get",
            {"app_id": "101", "event_name_list": "purchase"},
        )

        self.assertEqual("success", result["status"])
        encoded = json.dumps(result["data"], ensure_ascii=False)
        self.assertNotIn("dim_table", encoded)
        self.assertNotIn("opaque", encoded)
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertTrue(path.endswith("/event/event_list_info/"))
        self.assertEqual(
            {"app_id": "101", "event_name_list": "purchase"},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))

    def test_subject_lists_preserve_page_shape_and_redact_session_secrets(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if "/subject_internal/" in path:
                return {
                    "code": 0,
                    "data": {"list": [{"id": 1, "name": "internal", "token": "x"}]},
                }
            return {
                "code": 0,
                "data": {
                    "list": [],
                    "page_info": {
                        "page": 1,
                        "page_size": 15,
                        "total_number": 0,
                        "total_page": 0,
                    },
                },
            }

        client, transport = client_for(
            "analysis.template.subject.own.list",
            "analysis.template.subject.share.list",
            "analysis.template.subject.internal.list",
            handler=handler,
        )
        own = client.read("analysis.template.subject.own.list")
        shared = client.read("analysis.template.subject.share.list")
        internal = client.read("analysis.template.subject.internal.list")

        self.assertEqual("empty", own["status"])
        self.assertEqual(1, own["data"]["page_info"]["page"])
        self.assertEqual("empty", shared["status"])
        self.assertEqual("success", internal["status"])
        self.assertEqual([{"id": 1, "name": "internal"}], internal["data"]["list"])
        self.assertNotIn("token", json.dumps(internal).casefold())
        self.assertEqual(3, len(transport.calls))
        for method, _path, kwargs in transport.calls:
            self.assertEqual("GET", method)
            self.assertEqual({}, dict(kwargs["query"]))
            self.assertEqual({}, dict(kwargs["body"]))

    def test_dashboard_and_template_filters_are_exact_before_network(self) -> None:
        client, transport = client_for(
            "analysis.dashboard.condition_favourite.list",
            "analysis.template.own.list",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )

        invalid_requests = (
            (
                "analysis.dashboard.condition_favourite.list",
                {
                    "app_id": "101",
                    "filters": [
                        {"field": "dashboard_id", "operator": 1, "values": [["3"]]}
                    ],
                },
            ),
            (
                "analysis.dashboard.condition_favourite.list",
                {
                    "app_id": "101",
                    "filters": [
                        {"field": "default_to_one", "operator": 1, "values": [1]}
                    ],
                },
            ),
            (
                "analysis.template.own.list",
                {
                    "filters": [
                        {"field": "template_type", "operator": 1, "values": ["sql"]}
                    ]
                },
            ),
            (
                "analysis.template.own.list",
                {
                    "filters": [
                        {
                            "field": "template_type",
                            "operator": 1,
                            "values": ["report"],
                            "extra": "not-wire",
                        }
                    ]
                },
            ),
        )
        for operation_id, inputs in invalid_requests:
            with self.subTest(operation_id=operation_id, inputs=inputs):
                with self.assertRaises(InputValidationError):
                    client.read(operation_id, inputs)
        self.assertEqual([], transport.calls)

    def test_catalog_only_post_contracts_capture_full_frontend_wire(self) -> None:
        favourite = self.by_id["analysis.dashboard.condition_favourite.list"]
        self.assertEqual(
            ("page", "page_size", "app_id", "filters"),
            favourite.request.body_fields,
        )
        self.assertEqual(20, favourite.request.defaults["page_size"])
        self.assertEqual("object", favourite.fields["filters"].item_type)
        self.assertEqual(4, favourite.fields["filters"].max_items)

        for operation_id in (
            "analysis.template.own.list",
            "analysis.template.internal.list",
        ):
            operation = self.by_id[operation_id]
            self.assertEqual(
                ("page", "page_size", "filters", "subject_ids"),
                operation.request.body_fields,
            )
            self.assertEqual(15, operation.request.defaults["page_size"])
            default_filters = operation.request.defaults["filters"]
            self.assertEqual(1, len(default_filters))
            self.assertEqual("template_type", default_filters[0]["field"])
            self.assertEqual(1, default_filters[0]["operator"])
            self.assertEqual(("report",), default_filters[0]["values"])
        shared = self.by_id["analysis.template.share.list"]
        self.assertEqual(
            ("page", "page_size", "filters", "subject_ids", "create_user_ids"),
            shared.request.body_fields,
        )

    def test_member_ids_and_authority_are_contracted_but_names_are_not(self) -> None:
        for operation_id in (
            "analysis.dashboard.detail",
            "analysis.dashboard.members.list",
            "analysis.dashboard.space_members.list",
        ):
            policy = self.by_id[operation_id].privacy_policy
            self.assertEqual("user_level", policy.classification)
            self.assertIn("authorization", policy.redact_fields)
            self.assertIn("cookie", policy.redact_fields)
        members = self.by_id["analysis.dashboard.members.list"]
        self.assertEqual(
            ("uid", "authority"),
            members.response_projection.data_item_keys["authUsers"],
        )
        self.assertIn(
            "name",
            members.response_projection.known_omitted_data_item_keys["authUsers"],
        )


if __name__ == "__main__":
    unittest.main()
