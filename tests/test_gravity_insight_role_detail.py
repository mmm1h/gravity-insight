from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.role.detail"
PARENT_OPERATION_ID = "app.role.list"
TARGET_PATH = "/account_center/api/v1/role/detail/"
PARENT_PATH = "/account_center/api/v1/role/list/"


def _contract(operation_id: str) -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_insight"
        / "contracts"
        / "operations"
        / f"{operation_id}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["operation"]


def manifest() -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "operations": [_contract(PARENT_OPERATION_ID), _contract(OPERATION_ID)],
    }


class RecordingTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        if path == PARENT_PATH:
            payload: dict[str, Any] = {
                "code": 0,
                "data": {
                    "list": [{"id": 7}],
                    "page_info": {
                        "page": 1,
                        "page_size": 1,
                        "total_number": 1,
                        "total_page": 1,
                    },
                },
            }
        else:
            payload = {
                "code": 0,
                "data": {
                    "code": "analyst",
                    "create_time": "2026-08-11 00:00:00",
                    "data_permission": [
                        {
                            "child_module": "event",
                            "effect_module": "analysis",
                            "id": 31,
                            "role_effect": 1,
                            "new_nested_field": "hidden by default",
                        }
                    ],
                    "id": 7,
                    "is_default": False,
                    "is_deleted": False,
                    "is_enabled": True,
                    "menu": [
                        {
                            "id": 101,
                            "menu_url": "/hidden/internal/path",
                            "name": "数据分析",
                            "sort_order": 1,
                            "new_menu_field": "hidden by default",
                        }
                    ],
                    "modify_time": "2026-08-11 01:00:00",
                    "name": "分析角色",
                    "product_id": "turbo",
                    "remark": "hidden free text",
                    "new_upstream_field": "hidden by default",
                },
            }
        return TransportResponse(200, payload, "2026-08-11T00:00:00Z")


class RoleDetailOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_fail_closed_permission_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"role_id": 7})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual(
            {"need_menu": True, "product_name": "turbo", "role_id": 7},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "code": "analyst",
                "create_time": "2026-08-11 00:00:00",
                "data_permission": [
                    {
                        "child_module": "event",
                        "effect_module": "analysis",
                        "id": 31,
                        "role_effect": 1,
                    }
                ],
                "id": 7,
                "is_default": False,
                "is_deleted": False,
                "is_enabled": True,
                "menu": [{"id": 101, "name": "数据分析"}],
                "modify_time": "2026-08-11 01:00:00",
                "name": "分析角色",
                "product_id": "turbo",
            },
            result["data"],
        )

    def test_public_probe_selects_one_readable_role(self) -> None:
        transport = RecordingTransport()
        client = GravityInsightClient.from_env(transport=transport)

        result = client.probe(OPERATION_ID)

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertEqual([PARENT_PATH, TARGET_PATH], [call[1] for call in transport.calls])
        self.assertEqual(
            {"need_menu": False, "page": 1, "page_size": 1},
            dict(transport.calls[0][2]["query"]),
        )
        self.assertEqual(
            {"need_menu": True, "product_name": "turbo", "role_id": 7},
            dict(transport.calls[1][2]["query"]),
        )

    def test_missing_invalid_and_internal_inputs_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"role_id": "7"},
            {"role_id": True},
            {"role_id": 7, "need_menu": False},
            {"role_id": 7, "product_name": "other"},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
