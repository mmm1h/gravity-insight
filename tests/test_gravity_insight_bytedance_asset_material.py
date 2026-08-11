from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "material.bytedance_asset_material.list"
PARENT_OPERATION_ID = "promotion.bytedance.account.list"
CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "operations"
    / f"{OPERATION_ID}.json"
)
PARENT_CONTRACT_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "operations"
    / f"{PARENT_OPERATION_ID}.json"
)
TARGET_PATH = "/turbo_engine/api/v1/bytedance/asset/material/list/"


def manifest() -> dict[str, Any]:
    operation = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))["operation"]
    parent = json.loads(PARENT_CONTRACT_PATH.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [parent, operation]}


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
                        "aigc": False,
                        "create_time": "2026-08-01 00:00:00",
                        "filename": "verified-image.png",
                        "format": "png",
                        "height": 276,
                        "id": "asset-1",
                        "material_id": 101,
                        "size": 4096,
                        "width": 540,
                        "signature": "hidden fingerprint",
                        "url": "https://hidden.example.test/image.png",
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


class BytedanceAssetMaterialOperationTests(unittest.TestCase):
    def client(self, handler=None) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport(handler)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_fixed_image_query_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"advertiser_id": 101})

        self.assertEqual("contract_changed_additive", result["status"])
        self.assertTrue(result["warnings"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual(
            {
                "advertiser_id": 101,
                "file_type": "image",
                "page": 1,
                "page_size": 20,
            },
            dict(kwargs["query"]),
        )
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "aigc",
                "create_time",
                "filename",
                "format",
                "height",
                "id",
                "material_id",
                "size",
                "width",
            },
            set(result["data"]["list"][0]),
        )

    def test_invalid_or_unverified_controls_fail_before_network(self) -> None:
        invalid_inputs = (
            {},
            {"advertiser_id": "101"},
            {"advertiser_id": 101, "file_type": "video"},
            {"advertiser_id": 101, "page": 0},
            {"advertiser_id": 101, "page_size": 101},
            {"advertiser_id": 101, "page_size": 1.5},
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
            query = kwargs["query"]
            self.assertEqual("image", query["file_type"])
            self.assertEqual(101, query["advertiser_id"])
            page = int(query["page"])
            return {
                "code": 0,
                "data": {
                    "list": [{"id": f"asset-{page}", "material_id": page}],
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
            OPERATION_ID,
            {"advertiser_id": 101, "page_size": 1},
            max_pages=3,
            max_items=10,
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(
            ["asset-1", "asset-2"],
            [row["id"] for row in result["data"]["list"]],
        )
        self.assertEqual(2, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
