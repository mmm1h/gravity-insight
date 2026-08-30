from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_insight" / "manifests"
VALUES_MANIFEST = MANIFEST_DIR / "analysis_values.json"


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


def page(rows: list[Mapping[str, Any]], *, page_size: int = 100) -> dict[str, Any]:
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


def enumerable_property(name: str = "region") -> dict[str, Any]:
    return {
        "name": name,
        "cname": name,
        "data_type": "STRING",
        "has_dict": True,
        "visible": True,
    }


def event_info(property_name: str = "region") -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "properties": {
                "common": [enumerable_property(property_name)],
                "custom": [],
                "preset": [],
            }
        },
    }


class GravityInsightAnalysisValueTests(unittest.TestCase):
    def test_manifest_records_two_stable_scalar_enums(self) -> None:
        document = json.loads(VALUES_MANIFEST.read_text(encoding="utf-8"))
        by_id = {item["operation_id"]: item for item in document["operations"]}
        self.assertEqual(
            {
                "analysis.user_property_value.list",
                "analysis.event_property_value.list",
            },
            set(by_id),
        )

        user_values = by_id["analysis.user_property_value.list"]
        self.assertEqual("stable", user_values["stability"])
        self.assertEqual("GET", user_values["upstream_method"])
        self.assertEqual(
            "/turbo_engine/api/v2/event/report_data_val_enum/user/list/",
            user_values["path_template"],
        )
        self.assertEqual(
            {"list": "string"},
            user_values["response_projection"]["data_scalar_list_types"],
        )
        self.assertEqual(
            {
                "app_id": "$first_app_id",
                "property_name": "$first_user_property_name",
            },
            user_values["live_probe"]["input"],
        )

        event_values = by_id["analysis.event_property_value.list"]
        self.assertEqual("stable", event_values["stability"])
        self.assertEqual("POST", event_values["upstream_method"])
        self.assertEqual(
            "/turbo_engine/api/v2/event/report_data_val_enum/event/list/",
            event_values["path_template"],
        )
        self.assertEqual(
            ["event_name_list", "property_name", "app_id"],
            event_values["request"]["body_fields"],
        )
        self.assertEqual(
            {"list": "string"},
            event_values["response_projection"]["data_scalar_list_types"],
        )


    def test_user_property_values_use_exact_get_wire_and_preserve_scalar_list(
        self,
    ) -> None:
        target_path = "/turbo_engine/api/v2/event/report_data_val_enum/user/list/"

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path == "/turbo_engine/api/v2/event/user_property_list/":
                return page([enumerable_property()])
            if path == target_path:
                return {"code": 0, "data": {"list": ["north", "south"]}}
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.user_property_value.list",
            handler=handler,
        )
        result = client.read(
            "analysis.user_property_value.list",
            {"app_id": "app-9", "property_name": "region"},
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(["north", "south"], result["data"]["list"])
        target_calls = [call for call in transport.calls if call[1] == target_path]
        self.assertEqual(1, len(target_calls))
        method, _path, kwargs = target_calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(
            {"app_id": "app-9", "property_name": "region"},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))

    def test_event_property_values_use_exact_post_wire_and_preserve_scalar_list(
        self,
    ) -> None:
        target_path = "/turbo_engine/api/v2/event/report_data_val_enum/event/list/"

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path == "/turbo_engine/api/v2/event/event_list/":
                return page([{"name": "purchase", "visible": True}])
            if path == "/turbo_engine/api/v2/event/event_info/":
                return event_info()
            if path == target_path:
                return {"code": 0, "data": {"list": ["mobile", "desktop"]}}
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.event_property_value.list",
            handler=handler,
        )
        request = {
            "app_id": "app-9",
            "event_name_list": ["purchase"],
            "property_name": "region",
        }
        result = client.read("analysis.event_property_value.list", request)

        self.assertEqual("success", result["status"])
        self.assertEqual(["mobile", "desktop"], result["data"]["list"])
        target_calls = [call for call in transport.calls if call[1] == target_path]
        self.assertEqual(1, len(target_calls))
        method, _path, kwargs = target_calls[0]
        self.assertEqual("POST", method)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(request, dict(kwargs["body"]))

    def test_unregistered_property_and_event_never_reach_value_endpoints(self) -> None:
        user_target = "/turbo_engine/api/v2/event/report_data_val_enum/user/list/"

        def user_handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path == "/turbo_engine/api/v2/event/user_property_list/":
                return page([enumerable_property()])
            raise AssertionError(f"value endpoint must not be called: {path}")

        user_client, user_transport = client_for(
            "analysis.user_property_value.list",
            handler=user_handler,
        )
        with self.assertRaisesRegex(InputValidationError, "enumerable metadata"):
            user_client.read(
                "analysis.user_property_value.list",
                {"app_id": "app-9", "property_name": "unknown_property"},
            )
        self.assertFalse(any(call[1] == user_target for call in user_transport.calls))

        event_target = "/turbo_engine/api/v2/event/report_data_val_enum/event/list/"

        def event_handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path == "/turbo_engine/api/v2/event/event_list/":
                return page([{"name": "purchase", "visible": True}])
            raise AssertionError(f"value endpoint must not be called: {path}")

        event_client, event_transport = client_for(
            "analysis.event_property_value.list",
            handler=event_handler,
        )
        with self.assertRaisesRegex(InputValidationError, "live metadata"):
            event_client.read(
                "analysis.event_property_value.list",
                {
                    "app_id": "app-9",
                    "event_name_list": ["unknown_event"],
                    "property_name": "region",
                },
            )
        self.assertFalse(any(call[1] == event_target for call in event_transport.calls))

    def test_invalid_scalar_value_shape_fails_closed(self) -> None:
        target_path = "/turbo_engine/api/v2/event/report_data_val_enum/user/list/"

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path == "/turbo_engine/api/v2/event/user_property_list/":
                return page([enumerable_property()])
            if path == target_path:
                return {"code": 0, "data": {"list": ["north", 7]}}
            raise AssertionError(f"unexpected path: {path}")

        client, _transport = client_for(
            "analysis.user_property_value.list",
            handler=handler,
        )
        result = client.read(
            "analysis.user_property_value.list",
            {"app_id": "app-9", "property_name": "region"},
        )

        self.assertEqual("contract_changed", result["status"])
        self.assertNotIn("list", result["data"])
        self.assertTrue(
            any("scalar list" in warning for warning in result["warnings"]),
            result["warnings"],
        )

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
