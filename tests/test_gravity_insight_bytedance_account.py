from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.bytedance.account.list"
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_insight"
    / "contracts"
    / "operations"
    / f"{OPERATION_ID}.json"
)
TARGET_PATH = "/turbo_engine/api/v1/bytedance/manage/account/list/"
FIXED_BODY = {
    "filters": [
        {
            "field": "account_role",
            "operator": 6,
            "values": ["ADVERTISER"],
        }
    ]
}


def manifest() -> dict[str, Any]:
    operation = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [operation]}


class RecordingTransport:
    is_test_transport = True

    def __init__(self, handler=None) -> None:
        self.handler = handler or self._default
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    @staticmethod
    def _default(
        _method: str, _path: str, _kwargs: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {
            "code": 0,
            "data": {
                "expired_cnt": 0,
                "list": [
                    {
                        "account_id": "account-1",
                        "account_name": "verified account",
                        "account_role": "ADVERTISER",
                        "ad_platform": "BYTEDANCE",
                        "advertiser_id": 101,
                        "app_id": 202,
                        "grant_type": 1,
                        "media_status": "VALID",
                        "put_status": "ENABLE",
                        "account_email": "hidden@example.test",
                        "advertiser_name": "hidden advertiser",
                        "financial_info": {"grant": 999},
                        "new_upstream_field": "hidden by default",
                    }
                ],
                "page_info": {
                    "page": 1,
                    "page_size": 20,
                    "total_page": 1,
                    "total_number": 1,
                },
            },
        }

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            self.handler(method, path, kwargs),
            "2026-08-11T00:00:00Z",
        )


class BytedanceAccountOperationTests(unittest.TestCase):
    def client(self, handler=None) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport(handler)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_query_pagination_fixed_role_filter_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertTrue(result["warnings"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({"page": 1, "page_size": 20}, dict(kwargs["query"]))
        self.assertEqual(FIXED_BODY, dict(kwargs["body"]))
        self.assertEqual(0, result["data"]["expired_cnt"])
        self.assertEqual(
            {
                "account_id",
                "account_email",
                "account_name",
                "account_role",
                "ad_platform",
                "advertiser_id",
                "advertiser_name",
                "app_id",
                "grant_type",
                "media_status",
                "put_status",
            },
            set(result["data"]["list"][0]),
        )

    def test_invalid_or_unverified_controls_fail_before_network(self) -> None:
        invalid_inputs = (
            {"filters": []},
            {"page": 0},
            {"page_size": 101},
            {"page_size": 1.5},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)

    def test_read_all_stops_at_verified_total_page(self) -> None:
        def handler(
            _method: str, _path: str, kwargs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            self.assertEqual(FIXED_BODY, dict(kwargs["body"]))
            page = int(kwargs["query"]["page"])
            return {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "account_id": f"account-{page}",
                            "account_name": f"account {page}",
                        }
                    ],
                    "page_info": {
                        "page": page,
                        "page_size": 1,
                        "total_page": 2,
                        "total_number": 2,
                    },
                },
            }

        client, transport = self.client(handler)
        result = client.read_all(
            OPERATION_ID, {"page_size": 1}, max_pages=3, max_items=10
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(
            ["account-1", "account-2"],
            [row["account_id"] for row in result["data"]["list"]],
        )
        self.assertEqual(2, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
