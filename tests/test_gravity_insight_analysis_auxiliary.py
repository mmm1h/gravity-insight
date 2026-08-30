from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError, PolicyViolation
    from gravity_insight.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import (
        InputValidationError,
        PolicyViolation,
    )
    from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_insight" / "manifests"
AUXILIARY_MANIFEST = MANIFEST_DIR / "analysis_auxiliary.json"


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


def all_repository_operations() -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for operation in document.get("operations", []):
            operations[operation["operation_id"]] = operation
    return operations


def repository_manifest(*operation_ids: str) -> dict[str, Any]:
    all_operations = all_repository_operations()
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


def page(rows: list[Mapping[str, Any]], *, page_size: int) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "list": rows,
            "page_info": {
                "page": 1,
                "page_size": page_size,
                "total_page": 1,
                "total_number": len(rows),
            },
        },
    }


class GravityInsightAnalysisAuxiliaryTests(unittest.TestCase):
    def test_manifest_records_three_stable_reads_and_two_catalog_only_ai_loaders(
        self,
    ) -> None:
        document = json.loads(AUXILIARY_MANIFEST.read_text(encoding="utf-8"))
        by_id = {item["operation_id"]: item for item in document["operations"]}
        self.assertEqual(
            {
                "analysis.report.hidden_property.list",
                "analysis.task.pay_event.list",
                "analysis.task.other_event.list",
                "analysis.ai.conversation.list",
                "analysis.ai.message.list",
            },
            set(by_id),
        )
        self.assertEqual(
            {
                "analysis.report.hidden_property.list",
                "analysis.task.pay_event.list",
                "analysis.task.other_event.list",
            },
            {
                operation_id
                for operation_id, operation in by_id.items()
                if operation["stability"] == "stable"
            },
        )
        hidden = by_id["analysis.report.hidden_property.list"]
        self.assertEqual("GET", hidden["upstream_method"])
        self.assertEqual(
            "/turbo_engine/api/v2/event/in_report/hide_or_delete_prop/",
            hidden["path_template"],
        )
        self.assertEqual(
            ["data_type", "action_type", "data_cname", "data_name"],
            hidden["response_projection"]["item_keys"],
        )
        for operation_id in (
            "analysis.ai.conversation.list",
            "analysis.ai.message.list",
        ):
            operation = by_id[operation_id]
            self.assertEqual("experimental", operation["stability"])
            self.assertFalse(operation["executable"])
            self.assertEqual(
                "static_declaration_without_invocation",
                operation["block_reason"],
            )
            self.assertFalse(operation["live_probe"]["enabled"])

    def test_hidden_property_get_projects_only_observed_row_keys(self) -> None:
        client, transport = client_for(
            "analysis.report.hidden_property.list",
            handler=lambda _method, _path, _kwargs: {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "data_type": "mata_event",
                            "action_type": "delete",
                            "data_cname": "支付事件",
                            "data_name": "pay_event",
                            "password": "must-not-leak",
                        }
                    ]
                },
            },
        )
        result = client.read(
            "analysis.report.hidden_property.list",
            {"report_id": "report-17", "app_id": "app-9"},
        )
        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertEqual(
            {
                "data_type": "mata_event",
                "action_type": "delete",
                "data_cname": "支付事件",
                "data_name": "pay_event",
            },
            result["data"]["list"][0],
        )
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(
            "/turbo_engine/api/v2/event/in_report/hide_or_delete_prop/",
            path,
        )
        self.assertEqual(
            {"report_id": "report-17", "app_id": "app-9"},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))

    def test_pay_event_post_preserves_structured_filters_and_user_identifiers(
        self,
    ) -> None:
        filters = [
            {"field": "task_status", "operator": "EQUALS", "values": [1]},
            {"field": "client_id", "operator": "IN", "values": ["client-1"]},
            {"field": "trace_id", "operator": "IN", "values": ["order-1"]},
        ]
        row = {
            "client_id": "client-1",
            "trace_id": "order-1",
            "event_type": "$PayEvent",
            "pay_amount": 199,
            "task_status": 1,
            "create_user_name": "operator-a",
            "create_time": "2026-08-08 08:00:00",
            "reason": "queued",
            "token": "must-not-leak",
        }
        client, transport = client_for(
            "analysis.task.pay_event.list",
            handler=lambda _method, _path, _kwargs: page([row], page_size=20),
        )
        result = client.read(
            "analysis.task.pay_event.list",
            {"app_id": "app-9", "page": 1, "page_size": 20, "filters": filters},
        )
        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertEqual(
            {key: value for key, value in row.items() if key != "token"},
            result["data"]["list"][0],
        )
        self.assertNotIn("token", result["data"]["list"][0])
        self.assertEqual("operator-a", result["data"]["list"][0]["create_user_name"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual("/turbo_engine/api/v1/task/user/pay_event/list/", path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(
            {"app_id": "app-9", "page": 1, "page_size": 20, "filters": filters},
            dict(kwargs["body"]),
        )

    def test_other_event_accepts_the_full_frontend_filter_shape(self) -> None:
        filters = [
            {
                "field": "create_time",
                "operator": "RANGE_IN",
                "values": ["2026-08-07", "2026-08-08"],
            },
            {"field": "create_user_id", "operator": "IN", "values": ["user-7"]},
            {"field": "task_status", "operator": "EQUALS", "values": [2]},
            {"field": "client_id", "operator": "IN", "values": ["client-2"]},
        ]
        row = {
            "event_type": "purchase",
            "task_status": 2,
            "create_user_id": "user-7",
            "create_user_name": "operator-b",
            "client_id": "client-2",
            "create_time": "2026-08-08 08:01:00",
            "reason": "completed",
        }
        client, transport = client_for(
            "analysis.task.other_event.list",
            handler=lambda _method, _path, _kwargs: page([row], page_size=10),
        )
        result = client.read(
            "analysis.task.other_event.list",
            {"app_id": "app-9", "page": 1, "page_size": 10, "filters": filters},
        )
        self.assertEqual("success", result["status"])
        self.assertEqual(row, result["data"]["list"][0])
        self.assertEqual("user-7", result["data"]["list"][0]["create_user_id"])
        self.assertEqual("operator-b", result["data"]["list"][0]["create_user_name"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual("/turbo_engine/api/v1/task/user/other_event/list/", path)
        self.assertEqual(
            {"app_id": "app-9", "page": 1, "page_size": 10, "filters": filters},
            dict(kwargs["body"]),
        )

    def test_auxiliary_filter_and_page_contracts_fail_before_network(self) -> None:
        client, transport = client_for(
            "analysis.task.other_event.list",
            handler=lambda _method, _path, _kwargs: page([], page_size=10),
        )
        with self.assertRaisesRegex(InputValidationError, "filter field"):
            client.read(
                "analysis.task.other_event.list",
                {
                    "app_id": "app-9",
                    "filters": [
                        {
                            "field": "callback_url",
                            "operator": "EQUALS",
                            "values": ["https://invalid.example"],
                        }
                    ],
                },
            )
        with self.assertRaisesRegex(InputValidationError, "page size"):
            client.read(
                "analysis.task.other_event.list",
                {"app_id": "app-9", "page": 1, "page_size": 31, "filters": []},
            )
        self.assertEqual([], transport.calls)

    def test_promoted_object_route_remains_single_owned_and_sends_analysis_constants(
        self,
    ) -> None:
        operations = all_repository_operations()
        owners = [
            operation["operation_id"]
            for operation in operations.values()
            if operation["upstream_method"] == "GET"
            and operation["path_template"]
            == "/turbo_engine/api/v1/user/promoted_object/list/"
        ]
        self.assertEqual(["promotion.object.list"], owners)
        client, transport = client_for(
            "promotion.object.list",
            handler=lambda _method, _path, _kwargs: page(
                [
                    {
                        "app_id": "app-9",
                        "turbo_promoted_object_id": "object-1",
                        "turbo_promoted_object_name": "对象一",
                    }
                ],
                page_size=1,
            ),
        )
        result = client.read(
            "promotion.object.list",
            {"app_id": "app-9", "page": 1, "page_size": 1},
        )
        self.assertEqual("success", result["status"])
        query = dict(transport.calls[0][2]["query"])
        self.assertEqual("PostBackMap_PostBackMap", query["origin"])
        self.assertEqual(1, query["performance_mode"])

    def test_ai_list_candidates_are_non_executable_even_with_experimental_opt_in(
        self,
    ) -> None:
        client, transport = client_for(
            "analysis.ai.conversation.list",
            "analysis.ai.message.list",
            handler=lambda _method, _path, _kwargs: {"code": 0, "data": {}},
            allow_experimental=True,
        )
        for operation_id in (
            "analysis.ai.conversation.list",
            "analysis.ai.message.list",
        ):
            with self.subTest(operation_id=operation_id):
                with self.assertRaisesRegex(PolicyViolation, "catalog-only"):
                    client.read(operation_id, {})
        self.assertEqual([], transport.calls)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
