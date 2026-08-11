from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.bytedance.account_company.list"
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "operations"
    / f"{OPERATION_ID}.json"
)
TARGET_PATH = "/turbo_engine/api/v1/bytedance/manager/account/by_company/"


def manifest() -> dict[str, Any]:
    operation = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [operation]}


class RecordingTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        self.payload = payload or {
            "code": 0,
            "data": {
                "list": ["Example Company A", "Example Company B"],
                "new_upstream_field": "hidden by default",
            },
        }
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, self.payload, "2026-08-11T00:00:00Z")


class BytedanceAccountCompanyOperationTests(unittest.TestCase):
    def client(
        self, payload: Mapping[str, Any] | None = None
    ) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport(payload)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_scalar_list_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("contract_changed_additive", result["status"])
        self.assertEqual(
            ["Example Company A", "Example Company B"],
            result["data"]["list"],
        )
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertNotIn("new_upstream_field", result["data"])

    def test_unknown_input_fails_before_network(self) -> None:
        client, transport = self.client()

        with self.assertRaises(InputValidationError):
            client.read(OPERATION_ID, {"company": "unverified"})

        self.assertEqual([], transport.calls)

    def test_non_string_items_fail_closed(self) -> None:
        client, _ = self.client({"code": 0, "data": {"list": ["valid", 7]}})

        result = client.read(OPERATION_ID, {})

        self.assertEqual("contract_changed", result["status"])
        self.assertNotIn("list", result["data"])
        self.assertTrue(any("scalar list" in item for item in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
