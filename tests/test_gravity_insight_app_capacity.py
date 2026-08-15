from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.capacity.get"
TARGET_PATH = "/account_center/api/v1/company/capacity/info/"
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "operations"
    / f"{OPERATION_ID}.json"
)


def manifest() -> dict[str, Any]:
    operation = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["operation"]
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
                    "data": {
                        "capacity": {
                            "ad_create_amount": 100,
                            "ad_create_amount_usage": 20,
                            "capacity_type": "LIMITED",
                            "company_position": "hidden",
                            "create_user_name": "hidden",
                            "our_salesman_id": 7,
                            "relation_package": [
                                {
                                    "name": "standard",
                                    "package_id": 1,
                                    "package_total_million": 10,
                                    "formula": "hidden",
                                    "new_package_field": "hidden",
                                }
                            ],
                            "new_capacity_field": "hidden",
                        },
                        "product": {
                            "id": 2,
                            "product_id": "product-1",
                            "status": 1,
                            "remark": "hidden",
                            "new_product_field": "hidden",
                        },
                        "new_section": {"value": "hidden"},
                    }
                },
            },
            "2026-08-11T00:00:00Z",
        )


class AppCapacityOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_recursive_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))
        data = result["data"]["data"]
        self.assertEqual(
            {
                "ad_create_amount": 100,
                "ad_create_amount_usage": 20,
                "capacity_type": "LIMITED",
                "company_position": "hidden",
                "create_user_name": "hidden",
                "our_salesman_id": 7,
                "relation_package": [
                    {
                        "name": "standard",
                        "package_id": 1,
                        "package_total_million": 10,
                    }
                ],
            },
            data["capacity"],
        )
        self.assertEqual(
            {"id": 2, "product_id": "product-1", "status": 1},
            data["product"],
        )
        self.assertEqual({"capacity", "product"}, set(data))

    def test_unknown_input_fails_before_network(self) -> None:
        client, transport = self.client()

        with self.assertRaises(InputValidationError):
            client.read(OPERATION_ID, {"company_id": 1})

        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
