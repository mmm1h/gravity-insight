from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.bytedance.manager_project.list"
PARENT_OPERATION_ID = "promotion.bytedance.account.list"
TARGET_PATH = "/turbo_engine/api/v1/bytedance/manager/project/list/"


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
        return TransportResponse(
            200,
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "ad_type": "NORMAL",
                            "advertiser_id": 101,
                            "name": "Example Project",
                            "project_id": 202,
                            "status": "PROJECT_STATUS_ENABLE",
                            "delivery_range": {"inventory_catalog": "hidden"},
                            "audience": {"gender": "hidden"},
                            "open_url": "https://hidden.example.test",
                            "new_upstream_field": "hidden by default",
                        }
                    ]
                },
            },
            "2026-08-11T00:00:00Z",
        )


class BytedanceManagerProjectOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_enabled_project_request_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"advertiser_id": 101})

        self.assertEqual("contract_changed_additive", result["status"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(
            {
                "advertiser_id": 101,
                "filtering": {"status": "PROJECT_STATUS_ENABLE"},
            },
            dict(kwargs["body"]),
        )
        self.assertEqual(
            {
                "ad_type",
                "advertiser_id",
                "name",
                "project_id",
                "status",
            },
            set(result["data"]["list"][0]),
        )

    def test_invalid_or_unverified_inputs_fail_before_network(self) -> None:
        invalid_inputs = (
            {},
            {"advertiser_id": "101"},
            {"advertiser_id": 101, "filtering": {}},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
