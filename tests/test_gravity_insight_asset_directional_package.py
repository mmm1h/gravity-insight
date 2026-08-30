from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "material.asset_directional_package_bytedance.list"
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_insight"
    / "contracts"
    / "operations"
    / f"{OPERATION_ID}.json"
)
TARGET_PATH = "/turbo_engine/api/v1/asset/directional_package/bytedance/list/"


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
                "list": [
                    {
                        "advertiser_id": "advertiser-1",
                        "audience_name": "verified package",
                        "create_time": "2026-08-01 00:00:00",
                        "id": 7,
                        "landing_type": "APP",
                        "media_targeting_id": "targeting-1",
                        "media_type": "BYTEDANCE",
                        "modify_time": "2026-08-02 00:00:00",
                        "cid": 99,
                        "company": "hidden company",
                        "create_data": {"gender": "hidden targeting detail"},
                        "create_user_id": 88,
                        "create_user_name": "hidden operator",
                        "description": "hidden free text",
                        "file_md5": "hidden fingerprint",
                        "update_user_id": 77,
                        "update_user_name": "hidden updater",
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


class AssetDirectionalPackageOperationTests(unittest.TestCase):
    def client(self, handler=None) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport(handler)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_fixed_empty_filters_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertTrue(result["warnings"])
        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(TARGET_PATH, transport.calls[0][1])
        self.assertEqual(
            {"filters": [], "page": 1, "page_size": 20},
            dict(transport.calls[0][2]["body"]),
        )
        self.assertEqual(
            {
                "advertiser_id",
                "audience_name",
                "cid",
                "company",
                "create_time",
                "create_user_id",
                "create_user_name",
                "id",
                "landing_type",
                "media_targeting_id",
                "media_type",
                "modify_time",
                "update_user_id",
                "update_user_name",
            },
            set(result["data"]["list"][0]),
        )

    def test_invalid_controls_fail_before_network(self) -> None:
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
            body = kwargs["body"]
            self.assertEqual([], body["filters"])
            page = int(body["page"])
            return {
                "code": 0,
                "data": {
                    "list": [{"id": page, "audience_name": f"package-{page}"}],
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
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual(2, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
