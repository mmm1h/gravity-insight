from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "material.bytedance.promotion_material.list"
PARENT_OPERATION_ID = "promotion.bytedance.promotion_filter.list"
TARGET_PATH = "/turbo_engine/api/v1/bytedance/promotion/material/list/"
DEFAULT_METRICS = [
    "stat_cost",
    "show_cnt",
    "cpm_platform",
    "click_cnt",
    "ctr",
    "cpc_platform",
]


def _contract(operation_id: str) -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_insight"
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
                            "bit_rate": 1024,
                            "click_cnt": 7,
                            "cover_source": "hidden",
                            "cpc_platform": 1.25,
                            "cpm_platform": 2.5,
                            "create_time": "2026-08-04 00:00:00",
                            "ctr": 3.5,
                            "duration": 12,
                            "file_type": "video",
                            "filename": "synthetic.mp4",
                            "format": "mp4",
                            "height": 1920,
                            "id": "row-1",
                            "labels": ["hidden"],
                            "material_id": 303,
                            "material_info": {"url": "https://hidden.invalid/video"},
                            "organization_tags": ["hidden"],
                            "poster_url": "https://hidden.invalid/poster",
                            "show_cnt": 100,
                            "signature": "hidden-fingerprint",
                            "size": 4096,
                            "source": "local",
                            "star_author_id": "hidden-author",
                            "stat_cost": 10.0,
                            "url": "https://hidden.invalid/material",
                            "video_cover_id": "cover-1",
                            "width": 1080,
                            "new_upstream_field": "hidden by default",
                        }
                    ]
                },
            },
            "2026-08-11T00:00:00Z",
        )


class BytedancePromotionMaterialOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_request_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(
            OPERATION_ID,
            {
                "advertiser_id": "101",
                "promotion_id": "201",
                "start_time": "2026-08-04",
                "end_time": "2026-08-11",
            },
        )

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(
            {
                "advertiser_id": "101",
                "promotion_id": "201",
                "start_time": "2026-08-04",
                "end_time": "2026-08-11",
                "query_fields": DEFAULT_METRICS,
            },
            dict(kwargs["body"]),
        )
        self.assertEqual(
            {
                "bit_rate",
                "click_cnt",
                "cover_source",
                "cpc_platform",
                "cpm_platform",
                "create_time",
                "ctr",
                "duration",
                "file_type",
                "filename",
                "format",
                "height",
                "id",
                "labels",
                "material_id",
                "material_info",
                "organization_tags",
                "poster_url",
                "show_cnt",
                "signature",
                "size",
                "source",
                "star_author_id",
                "stat_cost",
                "url",
                "video_cover_id",
                "width",
            },
            set(result["data"]["list"][0]),
        )
        self.assertIsInstance(result["data"]["list"][0]["material_info"], dict)
        self.assertIsInstance(result["data"]["list"][0]["labels"], list)

    def test_invalid_or_unverified_inputs_fail_before_network(self) -> None:
        invalid_inputs = (
            {},
            {
                "advertiser_id": "101",
                "promotion_id": "201",
                "start_time": "2026-08-04",
            },
            {
                "advertiser_id": 101,
                "promotion_id": "201",
                "start_time": "2026-08-04",
                "end_time": "2026-08-11",
            },
            {
                "advertiser_id": "101",
                "promotion_id": 201,
                "start_time": "2026-08-04",
                "end_time": "2026-08-11",
            },
            {
                "advertiser_id": "101",
                "promotion_id": "201",
                "start_time": "2026/08/04",
                "end_time": "2026-08-11",
            },
            {
                "advertiser_id": "101",
                "promotion_id": "201",
                "start_time": "2026-08-04",
                "end_time": "2026-08-11",
                "query_fields": ["stat_cost"],
            },
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
