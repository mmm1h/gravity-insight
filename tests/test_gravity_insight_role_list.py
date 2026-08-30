from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.role.list"
TARGET_PATH = "/account_center/api/v1/role/list/"


def manifest() -> dict[str, Any]:
    contract_path = (
        ROOT
        / "src"
        / "gravity_insight"
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
                            "code": "analyst",
                            "create_time": "2026-08-11 00:00:00",
                            "id": 7,
                            "is_default": False,
                            "is_deleted": False,
                            "is_enabled": True,
                            "modify_time": "2026-08-11 01:00:00",
                            "name": "数据分析",
                            "person_num": 3,
                            "product_id": "turbo",
                            "remark": "hidden free text",
                            "new_upstream_field": "hidden by default",
                        }
                    ],
                    "page_info": {
                        "page": 2,
                        "page_size": 2,
                        "total_number": 3,
                        "total_page": 2,
                    },
                },
            },
            "2026-08-11T00:00:00Z",
        )


class RoleListOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_pagination_and_fail_closed_role_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"page": 2, "page_size": 2})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual(
            {"need_menu": False, "page": 2, "page_size": 2},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "code": "analyst",
                "create_time": "2026-08-11 00:00:00",
                "id": 7,
                "is_default": False,
                "is_deleted": False,
                "is_enabled": True,
                "modify_time": "2026-08-11 01:00:00",
                "name": "数据分析",
                "person_num": 3,
                "product_id": "turbo",
            },
            result["data"]["list"][0],
        )
        self.assertEqual(2, result["data"]["page_info"]["page"])

    def test_defaults_and_invalid_inputs_are_enforced_before_network(self) -> None:
        client, transport = self.client()
        client.read(OPERATION_ID, {})
        self.assertEqual(
            {"need_menu": False, "page": 1, "page_size": 20},
            dict(transport.calls[0][2]["query"]),
        )

        invalid_inputs = (
            {"page": "1"},
            {"page_size": True},
            {"page": 1, "page_size": 101},
            {"need_menu": True},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
