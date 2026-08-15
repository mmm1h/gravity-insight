from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "app.capacity.list"
PARENT_OPERATION_ID = "app.capacity.get"
TARGET_PATH = "/account_center/api/v1/company/capacity/list/"
PARENT_PATH = "/account_center/api/v1/company/capacity/info/"


def _contract(operation_id: str) -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_sdk"
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
                    "data": {
                        "capacity": {"company_id": 10},
                        "product": {"id": 1},
                    }
                },
            }
        else:
            payload = {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "ad_create_amount": 100,
                            "ad_create_amount_usage": 20,
                            "capacity_type": "LIMITED",
                            "company_id": 10,
                            "id": 7,
                            "relation_package": [
                                {
                                    "name": "standard",
                                    "package_id": 1,
                                    "package_total_million": 10,
                                    "formula": "hidden",
                                    "new_package_field": "hidden by default",
                                }
                            ],
                            "company_position": "hidden",
                            "our_salesman_id": 8,
                            "new_upstream_field": "hidden by default",
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 20,
                        "total_number": 1,
                        "total_page": 1,
                    },
                },
            }
        return TransportResponse(200, payload, "2026-08-11T00:00:00Z")


class CapacityListOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_recursive_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(
            OPERATION_ID, {"company_id": 10, "page": 1, "page_size": 20}
        )

        self.assertEqual("contract_changed", result["status"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual(
            {"company_id": 10, "page": 1, "page_size": 20},
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "ad_create_amount": 100,
                "ad_create_amount_usage": 20,
                "capacity_type": "LIMITED",
                "company_id": 10,
                "company_position": "hidden",
                "id": 7,
                "our_salesman_id": 8,
                "relation_package": [
                    {
                        "name": "standard",
                        "package_id": 1,
                        "package_total_million": 10,
                    }
                ],
            },
            result["data"]["list"][0],
        )

    def test_public_probe_resolves_current_company_before_target(self) -> None:
        transport = RecordingTransport()
        client = GravityInsightClient.from_env(transport=transport)

        result = client.probe(OPERATION_ID)

        self.assertIn(result["status"], {"success", "contract_changed"})
        self.assertEqual([PARENT_PATH, TARGET_PATH], [call[1] for call in transport.calls])
        self.assertEqual(
            {"company_id": 10, "page": 1, "page_size": 1},
            dict(transport.calls[1][2]["query"]),
        )

    def test_missing_and_invalid_inputs_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"company_id": "10"},
            {"company_id": 10, "page_size": 101},
            {"company_id": 10, "unknown": 1},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
