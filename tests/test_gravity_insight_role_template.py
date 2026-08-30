from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.template.list"
TARGET_PATH = "/account_center/api/v1/role/template/list/"


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
                            "cid": 10,
                            "code": "analyst_template",
                            "create_time": "2026-08-11 00:00:00",
                            "data_config": [
                                {
                                    "child_module": "event",
                                    "effect_module": "analysis",
                                    "role_effect": 1,
                                    "new_nested_field": "hidden by default",
                                }
                            ],
                            "id": 11,
                            "menu_config": [101, 102],
                            "modify_time": "2026-08-11 01:00:00",
                            "name": "分析模板",
                            "product_id": "turbo",
                            "remark": "hidden free text",
                            "new_upstream_field": "hidden by default",
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 100,
                        "total_number": 1,
                        "total_page": 1,
                    },
                },
            },
            "2026-08-11T00:00:00Z",
        )


class RoleTemplateOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_fail_closed_template_configuration_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual(
            {"page": 1, "page_size": 100, "product_name": "turbo"},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "cid": 10,
                "code": "analyst_template",
                "create_time": "2026-08-11 00:00:00",
                "data_config": [
                    {
                        "child_module": "event",
                        "effect_module": "analysis",
                        "role_effect": 1,
                    }
                ],
                "id": 11,
                "menu_config": [101, 102],
                "modify_time": "2026-08-11 01:00:00",
                "name": "分析模板",
                "product_id": "turbo",
            },
            result["data"]["list"][0],
        )

    def test_invalid_or_internal_inputs_fail_before_network(self) -> None:
        invalid_inputs = (
            {"page": "1"},
            {"page_size": True},
            {"page": 1, "page_size": 101},
            {"product_name": "other"},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
