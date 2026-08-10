from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts" / "operations"

CASES = {
    "promotion.ai_trusteeship.list": {
        "path": "/turbo_engine/api/v1/task/ai_trusteeship/list/",
        "safe_field": "name",
        "hidden": (
            "cid",
            "conditions",
            "create_user_id",
            "target_values",
        ),
        "row": {
            "id": 1,
            "name": "safe rule",
            "status": 1,
            "cid": 2,
            "conditions": [{"metrics_name": "cost"}],
            "create_user_id": 3,
            "target_values": {"advertiser_id": 4},
        },
    },
    "metadata.version.list": {
        "path": "/turbo_engine/api/v2/event_dim/data_table/version/list/",
        "safe_field": "version_id",
        "hidden": (
            "cid",
            "create_user_name",
            "info",
            "name_en_cn_dict",
        ),
        "row": {
            "id": 1,
            "table_id": 2,
            "version_id": 3,
            "cid": 4,
            "create_user_name": "hidden user",
            "info": {"row_num": 5},
            "name_en_cn_dict": {"item_id": "道具"},
        },
    },
    "metadata.operation_log.list": {
        "path": "/turbo_engine/api/v2/event_dim/data_table/operation_log/list/",
        "safe_field": "action_type",
        "hidden": ("cid", "create_user_id", "detail"),
        "row": {
            "id": 1,
            "action_type": "UPDATE",
            "table_id": 2,
            "version_id": 3,
            "cid": 4,
            "create_user_id": 5,
            "detail": {"table_name": "hidden detail"},
        },
    },
    "report.tag.list": {
        "path": "/turbo_engine/api/v3/confmetric/tag/list/",
        "safe_field": "category_id",
        "hidden": ("exclusion_tags", "remark"),
        "row": {
            "id": 1,
            "category_id": 2,
            "name": "safe-tag",
            "cname": "安全标签",
            "data_topic": "event",
            "order": 1,
            "exclusion_tags": [3],
            "remark": "hidden note",
        },
    },
    "report.tag_category.list": {
        "path": "/turbo_engine/api/v3/confmetric/tag_category/list/",
        "safe_field": "data_topic",
        "hidden": ("remark",),
        "row": {
            "id": 1,
            "name": "safe-category",
            "cname": "安全分类",
            "data_topic": "event",
            "order": 1,
            "remark": "hidden note",
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


class PromotedConfigurationReadTests(unittest.TestCase):
    def test_verified_routes_pagination_and_projection(self) -> None:
        for operation_id, case in CASES.items():
            with self.subTest(operation_id=operation_id):
                transport = RecordingTransport(case["row"])
                client = GravityInsightClient._from_manifest_for_tests(
                    manifest(operation_id), transport=transport
                )
                result = client.read(
                    operation_id,
                    {"page": 1, "page_size": 100},
                )

                self.assertEqual("success", result["status"])
                self.assertEqual("POST", transport.calls[0][0])
                self.assertEqual(case["path"], transport.calls[0][1])
                body = dict(transport.calls[0][2]["body"])
                if operation_id.startswith(("metadata.", "report.")):
                    self.assertEqual([], body["filters"])
                else:
                    self.assertNotIn("filters", body)
                self.assertEqual(100, body["page_size"])
                row = result["data"]["list"][0]
                self.assertIn(case["safe_field"], row)
                for field in case["hidden"]:
                    self.assertNotIn(field, row)

    def test_unverified_filters_and_oversized_pages_fail_before_network(self) -> None:
        for operation_id in CASES:
            invalid_inputs = (
                {"page_size": 101},
                {"filters": []},
            )
            for inputs in invalid_inputs:
                with self.subTest(operation_id=operation_id, inputs=inputs):
                    transport = RecordingTransport(CASES[operation_id]["row"])
                    client = GravityInsightClient._from_manifest_for_tests(
                        manifest(operation_id), transport=transport
                    )
                    with self.assertRaises(InputValidationError):
                        client.read(operation_id, inputs)
                    self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
