from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.permission_menu.list"
TARGET_PATH = "/account_center/api/v1/permission_menu/list/"


def manifest() -> dict[str, Any]:
    contract_path = (
        ROOT
        / "src"
        / "gravity_sdk"
        / "contracts"
        / "operations"
        / f"{OPERATION_ID}.json"
    )
    operation = json.loads(contract_path.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [operation]}


class RecordingTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": 1,
                            "name": "分析",
                            "parent_id": None,
                            "person_num": 12,
                            "menu_url": "/analysis",
                            "remark": "hidden free text",
                            "sort_order": 1,
                            "new_upstream_field": "hidden by default",
                            "children": [
                                {
                                    "id": 2,
                                    "name": "事件分析",
                                    "parent_id": 1,
                                    "person_num": 7,
                                    "menu_url": "/analysis/event",
                                    "remark": "hidden nested free text",
                                    "sort_order": 2,
                                    "new_nested_field": "hidden by default",
                                    "children": [],
                                }
                            ],
                        }
                    ]
                },
            },
            "2026-08-11T00:00:00Z",
        )


class PermissionMenuOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_fixed_query_and_recursive_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("contract_changed", result["status"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({"product_name": "turbo"}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "id": 1,
                "name": "分析",
                "parent_id": None,
                "person_num": 12,
                "children": [
                    {
                        "id": 2,
                        "name": "事件分析",
                        "parent_id": 1,
                        "person_num": 7,
                    }
                ],
            },
            result["data"]["list"][0],
        )

    def test_all_caller_supplied_inputs_fail_before_network(self) -> None:
        for inputs in ({"product_name": "turbo"}, {"unknown": 1}):
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
