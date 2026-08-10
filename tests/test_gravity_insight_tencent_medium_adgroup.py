from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import (
    GravityInsightClient,
    InputValidationError,
)
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.tencent.medium_adgroup.list"
PARENT_OPERATION_ID = "promotion.tencent.adgroup_filter.list"
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts" / "operations"


def manifest() -> dict[str, Any]:
    operations = []
    for operation_id in (PARENT_OPERATION_ID, OPERATION_ID):
        source = json.loads(
            (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        operations.append(source["operation"])
    return {"manifest_version": 1, "operations": operations}


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
                            "adgroup_id": 7,
                            "adgroup_name": "safe adgroup",
                            "configured_status": "AD_STATUS_NORMAL",
                            "begin_date": "2026-08-01",
                            "end_date": "2026-08-31",
                            "bid_amount": 100,
                            "bid_mode": "BID_MODE_OCPC",
                            "daily_budget": 500,
                            "total_budget": 1000,
                        }
                    ]
                },
            },
            "2026-08-11T00:00:00Z",
        )


class TencentMediumAdgroupOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        return (
            GravityInsightClient._from_manifest_for_tests(
                manifest(), transport=transport
            ),
            transport,
        )

    def test_verified_route_defaults_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"advertiser_id": "123456"})

        self.assertEqual("success", result["status"])
        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/medium/adgroup/list/",
            transport.calls[0][1],
        )
        self.assertEqual(
            {"advertiser_id": "123456", "api_version": "v3.0"},
            dict(transport.calls[0][2]["body"]),
        )
        row = result["data"]["list"][0]
        self.assertEqual("safe adgroup", row["adgroup_name"])
        for field in ("bid_amount", "bid_mode", "daily_budget", "total_budget"):
            self.assertNotIn(field, row)

    def test_parent_and_version_validation_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertFalse(result["ok"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"advertiser_id": "123456", "api_version": "v2.0"},
            {"advertiser_id": "123456", "fields": ["bid_amount"]},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
