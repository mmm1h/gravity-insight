from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {
    "promotion.bytedance.account_company.list": (
        "/turbo_engine/api/v1/bytedance/manager/account/by_company/"
    ),
    "promotion.tencent.account_company.list": (
        "/turbo_engine/api/v1/tencent/manager/account/by_company/"
    ),
}


def manifest(operation_id: str) -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_sdk"
        / "contracts"
        / "operations"
        / f"{operation_id}.json"
    )
    operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [operation]}


class RecordingTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        self.payload = (
            payload
            if payload is not None
            else {
                "code": 0,
                "data": {
                    "list": ["Example Company A", "Example Company B"],
                    "new_upstream_field": "hidden by default",
                },
            }
        )
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, self.payload, "2026-08-11T00:00:00Z")


class AccountCompanyOperationTests(unittest.TestCase):
    def client(
        self, operation_id: str, payload: Mapping[str, Any] | None = None
    ) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport(payload)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(operation_id), transport=transport
        )
        return client, transport

    def test_exact_get_and_scalar_list_projection(self) -> None:
        for operation_id, target_path in OPERATIONS.items():
            with self.subTest(operation_id=operation_id):
                client, transport = self.client(operation_id)

                result = client.read(operation_id, {})

                self.assertEqual("contract_changed_additive", result["status"])
                self.assertEqual(
                    ["Example Company A", "Example Company B"],
                    result["data"]["list"],
                )
                method, path, kwargs = transport.calls[0]
                self.assertEqual("GET", method)
                self.assertEqual(target_path, path)
                self.assertEqual({}, dict(kwargs["query"]))
                self.assertEqual({}, dict(kwargs["body"]))
                self.assertNotIn("new_upstream_field", result["data"])

    def test_unknown_input_fails_before_network(self) -> None:
        for operation_id in OPERATIONS:
            with self.subTest(operation_id=operation_id):
                client, transport = self.client(operation_id)

                with self.assertRaises(InputValidationError):
                    client.read(operation_id, {"company": "unverified"})

                self.assertEqual([], transport.calls)

    def test_non_string_items_fail_closed(self) -> None:
        payload = {"code": 0, "data": {"list": ["valid", 7]}}
        for operation_id in OPERATIONS:
            with self.subTest(operation_id=operation_id):
                client, _ = self.client(operation_id, payload)

                result = client.read(operation_id, {})

                self.assertEqual("contract_changed", result["status"])
                self.assertNotIn("list", result["data"])
                self.assertTrue(
                    any("scalar list" in item for item in result["warnings"])
                )


if __name__ == "__main__":
    unittest.main()
