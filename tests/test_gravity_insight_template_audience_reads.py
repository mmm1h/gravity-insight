from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_insight" / "contracts" / "operations"

CASES = {
    "metadata.event_property_template_event.list": {
        "path": "/turbo_engine/api/v2/event/property_template/event/list/",
        "safe_field": "template_type",
        "exposed": ("cid", "create_user_id"),
        "hidden": ("remark",),
        "row": {
            "id": 1,
            "name": "safe event type",
            "template_type": 2,
            "cid": 3,
            "create_user_id": 4,
            "remark": "hidden remark",
        },
    },
    "promotion.bytedance.custom_audience.list": {
        "path": "/turbo_engine/api/v1/bytedance/custom_audience_list/v2/",
        "safe_field": "custom_audience_id",
        "exposed": ("cid", "company", "create_user_name", "tag"),
        "hidden": (),
        "row": {
            "id": 1,
            "custom_audience_id": 2,
            "advertiser_id": 3,
            "name": "safe audience",
            "cover_num": 100,
            "cid": 4,
            "company": "hidden company",
            "create_user_name": "hidden user",
            "tag": "hidden label",
        },
    },
}


def manifest(operation_id: str) -> dict[str, Any]:
    source = json.loads(
        (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
    )
    return {"manifest_version": 1, "operations": [source["operation"]]}


class RecordingTransport:
    is_test_transport = True

    def __init__(self, row: Mapping[str, Any]) -> None:
        self.row = dict(row)
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            {
                "code": 0,
                "data": {
                    "list": [dict(self.row)],
                    "page_info": {
                        "page": 1,
                        "page_size": 100,
                        "total_page": 1,
                        "total_number": 1,
                    },
                },
            },
            "2026-08-11T00:00:00Z",
        )


class TemplateAudienceReadTests(unittest.TestCase):
    def test_verified_routes_fixed_filters_and_projection(self) -> None:
        for operation_id, case in CASES.items():
            with self.subTest(operation_id=operation_id):
                transport = RecordingTransport(case["row"])
                client = GravityInsightClient._from_manifest_for_tests(
                    manifest(operation_id), transport=transport
                )

                result = client.read(
                    operation_id, {"page": 1, "page_size": 100}
                )

                self.assertEqual("success", result["status"])
                self.assertEqual("POST", transport.calls[0][0])
                self.assertEqual(case["path"], transport.calls[0][1])
                self.assertEqual(
                    {"filters": [], "page": 1, "page_size": 100},
                    dict(transport.calls[0][2]["body"]),
                )
                row = result["data"]["list"][0]
                self.assertIn(case["safe_field"], row)
                for field in case["exposed"]:
                    self.assertIn(field, row)
                for field in case["hidden"]:
                    self.assertNotIn(field, row)

    def test_unverified_filters_and_oversized_pages_fail_before_network(self) -> None:
        for operation_id, case in CASES.items():
            for inputs in ({"filters": []}, {"page_size": 101}):
                with self.subTest(operation_id=operation_id, inputs=inputs):
                    transport = RecordingTransport(case["row"])
                    client = GravityInsightClient._from_manifest_for_tests(
                        manifest(operation_id), transport=transport
                    )
                    with self.assertRaises(InputValidationError):
                        client.read(operation_id, inputs)
                    self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
