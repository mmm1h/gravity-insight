from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPAQUE_FIXTURE = [{"shape_is_intentionally_unspecified": [1, None]}]

OBSERVED_FIELDS: dict[str, dict[str, Any]] = {
    "material.local.list": {
        "d3_action_user_id": OPAQUE_FIXTURE,
        "d3_render_user_id": OPAQUE_FIXTURE,
        "image_set": OPAQUE_FIXTURE,
        "other_user_id": OPAQUE_FIXTURE,
    },
    "material.recycle.list": {
        "capture_user_id": OPAQUE_FIXTURE,
        "create_user_id": 1,
        "create_user_name": "creator",
        "creative_user_id": 2,
        "creative_user_name": "creative",
        "d3_action_user_id": OPAQUE_FIXTURE,
        "d3_render_user_id": OPAQUE_FIXTURE,
        "delete_user_id": None,
        "delete_user_name": "deleter",
        "designer_id": 3,
        "designer_image_id": 4,
        "designer_image_name": "designer image",
        "designer_name": "designer",
        "dub_user_id": OPAQUE_FIXTURE,
        "file_sub_type": "video",
        "file_url": "https://example.invalid/material",
        "other_user_id": OPAQUE_FIXTURE,
        "performer_user_id": OPAQUE_FIXTURE,
        "thumbnail_url": "https://example.invalid/thumbnail",
        "transcribe_user_id": OPAQUE_FIXTURE,
        "update_user_id": None,
        "update_user_name": "updater",
        "video_cover_list": None,
    },
    "material.report.query": {
        "album_id": None,
        "album_name": "album",
        "capture_user_id": OPAQUE_FIXTURE,
        "capture_user_name": "capture",
        "create_time": "2026-09-05 00:00:00",
        "creative_user_id": 2,
        "creative_user_name": "creative",
        "d3_action_user_id": OPAQUE_FIXTURE,
        "d3_action_user_name": "action",
        "d3_render_user_id": OPAQUE_FIXTURE,
        "d3_render_user_name": "render",
        "designer_id": 3,
        "designer_image_id": None,
        "designer_image_name": "designer image",
        "designer_name": "designer",
        "dub_user_id": OPAQUE_FIXTURE,
        "dub_user_name": "dub",
        "file_md5": "0123456789abcdef",
        "file_type": "video",
        "file_url": "https://example.invalid/material",
        "folder_id": None,
        "folder_name": "folder",
        "image_set": OPAQUE_FIXTURE,
        "is_favorite": 0,
        "make_time": None,
        "other_user_id": OPAQUE_FIXTURE,
        "other_user_name": "other",
        "performer_user_id": OPAQUE_FIXTURE,
        "performer_user_name": "performer",
        "thumbnail_url": "https://example.invalid/thumbnail",
        "transcribe_user_id": OPAQUE_FIXTURE,
        "transcribe_user_name": "transcriber",
    },
}

OPAQUE_FIELDS = {
    "material.local.list": {
        "d3_action_user_id",
        "d3_render_user_id",
        "other_user_id",
    },
    "material.recycle.list": {
        "capture_user_id",
        "d3_action_user_id",
        "d3_render_user_id",
        "dub_user_id",
        "other_user_id",
        "performer_user_id",
        "transcribe_user_id",
    },
    "material.report.query": {
        "capture_user_id",
        "d3_action_user_id",
        "d3_render_user_id",
        "dub_user_id",
        "other_user_id",
        "performer_user_id",
        "transcribe_user_id",
    },
}

OMITTED_FIELDS = {
    "material.local.list": {"image_set"},
    "material.recycle.list": {"file_url", "thumbnail_url"},
    "material.report.query": {"file_url", "image_set", "thumbnail_url"},
}

INPUTS = {
    "material.local.list": {"page": 1, "page_size": 1},
    "material.recycle.list": {"filters": [], "page": 1, "page_size": 1},
    "material.report.query": {
        "app_list": ["fixture-app"],
        "date_list": ["2026-09-05", "2026-09-05"],
        "page": 1,
        "page_size": 1,
        "platform": "bytedance",
    },
}


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


class StaticTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-09-05T00:00:00Z")


def _client(operation_id: str, row: Mapping[str, Any]) -> GravityInsightClient:
    operations = [_contract(operation_id)]
    if operation_id == "material.report.query":
        operations.append(_contract("app.list"))
    payload = {
        "code": 0,
        "data": {
            "list": [row],
            "page_info": {
                "page": 1,
                "page_size": 1,
                "total_number": 1,
                "total_page": 1,
            },
        },
    }
    return GravityInsightClient._from_manifest_for_tests(
        {"manifest_version": 1, "operations": operations},
        transport=StaticTransport(payload),
    )


class MaterialBigResponseContractTests(unittest.TestCase):
    def test_all_observed_fields_are_declared_and_projected(self) -> None:
        for operation_id, observed in OBSERVED_FIELDS.items():
            with self.subTest(operation_id=operation_id):
                projection = _contract(operation_id)["response_projection"]
                projected_fields = set(observed) - OMITTED_FIELDS[operation_id]
                result = _client(operation_id, observed).read(
                    operation_id, INPUTS[operation_id]
                )

                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual("success", result["status"])
                self.assertNotIn("response_drift", result["result_audit"])
                self.assertLessEqual(projected_fields, set(projection["item_keys"]))
                self.assertLessEqual(
                    OMITTED_FIELDS[operation_id],
                    set(projection.get("known_omitted_item_keys", [])),
                )
                self.assertLessEqual(
                    OPAQUE_FIELDS[operation_id],
                    set(projection.get("opaque_json_item_keys", [])),
                )
                self.assertEqual(
                    {
                        field: value
                        for field, value in observed.items()
                        if field not in OMITTED_FIELDS[operation_id]
                    },
                    result["data"]["list"][0],
                )

    def test_non_json_values_remain_contract_changed(self) -> None:
        cases = (
            ("material.recycle.list", "create_user_name", object()),
            ("material.recycle.list", "capture_user_id", [object()]),
            ("material.report.query", "album_name", object()),
            ("material.report.query", "capture_user_id", [object()]),
        )
        for operation_id, field, invalid in cases:
            with self.subTest(operation_id=operation_id, field=field):
                result = _client(operation_id, {field: invalid}).read(
                    operation_id, INPUTS[operation_id]
                )

                self.assertFalse(result["ok"])
                self.assertEqual("contract_changed", result["status"])
                self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
                self.assertNotIn(field, result["data"]["list"][0])


if __name__ == "__main__":
    unittest.main()
