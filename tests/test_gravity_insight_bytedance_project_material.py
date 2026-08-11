from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "material.bytedance.project_material.list"
PARENT_OPERATION_ID = "promotion.bytedance.project_filter.list"
TARGET_PATH = "/turbo_engine/api/v1/bytedance/project/material_get/"


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
                    "video_material_list": [
                        {
                            "file_name": "example-video.mp4",
                            "material_id": 303,
                            "type": "VIDEO",
                            "file_url": "https://hidden.example.test/video.mp4",
                            "thumbnail_url": "https://hidden.example.test/thumb.jpg",
                            "new_item_field": "hidden by default",
                        }
                    ],
                    "instant_play_material_list": [{"secret": "hidden"}],
                    "trial_play_material_list": [{"secret": "hidden"}],
                    "new_data_field": "hidden by default",
                },
            },
            "2026-08-11T00:00:00Z",
        )


class ByteDanceProjectMaterialOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_project_request_and_nested_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(
            OPERATION_ID,
            {"advertiser_id": 101, "project_id": 202},
        )

        self.assertEqual("contract_changed_additive", result["status"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        self.assertEqual(
            {"advertiser_id": 101, "project_id": 202},
            dict(kwargs["body"]),
        )
        self.assertEqual(
            {"file_name", "material_id", "type"},
            set(result["data"]["video_material_list"][0]),
        )
        self.assertNotIn("instant_play_material_list", result["data"])
        self.assertNotIn("trial_play_material_list", result["data"])
        self.assertNotIn("new_data_field", result["data"])

    def test_invalid_or_unverified_inputs_fail_before_network(self) -> None:
        invalid_inputs = (
            {},
            {"advertiser_id": 101},
            {"advertiser_id": "101", "project_id": 202},
            {"advertiser_id": 101, "project_id": "202"},
            {"advertiser_id": 101, "project_id": 202, "material_type": "video"},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
