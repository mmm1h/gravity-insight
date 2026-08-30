from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_insight" / "contracts" / "operations"
OPERATION_IDS = (
    "material.bytedance_asset_text_title.list",
    "material.bytedance_std_asset_text_title.list",
)
PACKAGE_OPERATION_IDS = (
    "material.bytedance_asset_text_title_package.list",
    "material.bytedance_std_asset_text_title_package.list",
)


def manifest(*operation_ids: str) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    pending = list(operation_ids)
    loaded: set[str] = set()
    while pending:
        operation_id = pending.pop(0)
        if operation_id in loaded:
            continue
        source = json.loads(
            (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        operation = source["operation"]
        operations.append(operation)
        loaded.add(operation_id)
        pending.extend(
            str(parent["operation_id"])
            for parent in operation.get("required_parent", [])
            if parent.get("operation_id")
        )
    return {"manifest_version": 1, "operations": operations}


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
                        "id": 7,
                        "app_id": 101,
                        "title": "safe title",
                        "history_cost": 12.5,
                        "cid": 99,
                        "create_user_id": 88,
                        "create_user_name": "hidden operator",
                        "update_user_id": 77,
                    }
                ],
                "page_info": {
                    "page": 2,
                    "page_size": 100,
                    "total_page": 2,
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


class MaterialTitleOperationTests(unittest.TestCase):
    def test_fixed_routes_controls_and_projection(self) -> None:
        paths = {
            OPERATION_IDS[0]: "/turbo_engine/api/v1/bytedance/asset/text/title/list/",
            OPERATION_IDS[1]: "/turbo_engine/api/v1/bytedance/std/asset/text/title/list/",
        }
        for operation_id in OPERATION_IDS:
            with self.subTest(operation_id=operation_id):
                transport = RecordingTransport()
                client = GravityInsightClient._from_manifest_for_tests(
                    manifest(operation_id), transport=transport
                )
                result = client.read(
                    operation_id,
                    {
                        "filters": [
                            {"field": "title", "operator": 8, "values": ["safe"]}
                        ],
                        "order_by": ["history_cost desc"],
                        "page": 2,
                        "page_size": 100,
                    },
                )

                self.assertEqual("success", result["status"])
                self.assertEqual("POST", transport.calls[0][0])
                self.assertEqual(paths[operation_id], transport.calls[0][1])
                body = dict(transport.calls[0][2]["body"])
                self.assertEqual(2, body["page"])
                self.assertEqual(100, body["page_size"])
                self.assertEqual(["history_cost desc"], body["order_by"])
                row = result["data"]["list"][0]
                self.assertEqual("safe title", row["title"])
                self.assertEqual(99, row["cid"])
                self.assertEqual(88, row["create_user_id"])
                self.assertEqual("hidden operator", row["create_user_name"])
                self.assertEqual(77, row["update_user_id"])

    def test_last_3_day_metrics_are_marked_unreliable(self) -> None:
        for operation_id in OPERATION_IDS:
            with self.subTest(operation_id=operation_id):
                client = GravityInsightClient._from_manifest_for_tests(
                    manifest(operation_id), transport=RecordingTransport()
                )
                notes = client.describe(operation_id)["response_projection"][
                    "unreliable_item_keys"
                ]
                self.assertIn("last_3_day_click_rate", notes)
                self.assertIn("last_3_day_cost", notes)
                self.assertIn("material.report.query", notes["last_3_day_click_rate"]["use_instead"])
                self.assertIn("material.report.query", notes["last_3_day_cost"]["use_instead"])

    def test_invalid_controls_fail_before_network(self) -> None:
        invalid_inputs = (
            {"page_size": 101},
            {
                "filters": [
                    {"field": "create_user_id", "operator": 6, "values": [88]}
                ]
            },
            {"order_by": ["history_cost desc; drop"]},
        )
        for operation_id in OPERATION_IDS:
            for inputs in invalid_inputs:
                with self.subTest(operation_id=operation_id, inputs=inputs):
                    transport = RecordingTransport()
                    client = GravityInsightClient._from_manifest_for_tests(
                        manifest(operation_id), transport=transport
                    )
                    with self.assertRaises(InputValidationError):
                        client.read(operation_id, inputs)
                    self.assertEqual([], transport.calls)

    def test_title_packages_require_integer_app_and_expose_title_contents(self) -> None:
        paths = {
            PACKAGE_OPERATION_IDS[0]: (
                "/turbo_engine/api/v1/bytedance/asset/text/title_package/list/"
            ),
            PACKAGE_OPERATION_IDS[1]: (
                "/turbo_engine/api/v1/bytedance/std/asset/text/title_package/list/"
            ),
        }

        def handler(
            _method: str, _path: str, _kwargs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            return {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": 7,
                            "app_id": 101,
                            "cid": 99,
                            "title_package_name": "safe package",
                            "title_num": 12,
                            "history_cost": 34.5,
                            "title_list": ["hidden title"],
                            "create_user_id": 88,
                            "create_user_name": "hidden operator",
                            "update_user_id": 77,
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

        for operation_id in PACKAGE_OPERATION_IDS:
            with self.subTest(operation_id=operation_id):
                transport = RecordingTransport(handler)
                client = GravityInsightClient._from_manifest_for_tests(
                    manifest(operation_id), transport=transport
                )
                result = client.read(
                    operation_id,
                    {
                        "app_id": 101,
                        "filters": [
                            {
                                "field": "title_package_name",
                                "operator": 8,
                                "values": ["safe"],
                            }
                        ],
                        "order_by": ["history_cost desc"],
                    },
                )

                self.assertEqual("success", result["status"])
                self.assertEqual(("POST", paths[operation_id]), transport.calls[0][:2])
                body = dict(transport.calls[0][2]["body"])
                self.assertEqual(101, body["app_id"])
                self.assertEqual(["history_cost desc"], body["order_by"])
                row = result["data"]["list"][0]
                self.assertEqual("safe package", row["title_package_name"])
                self.assertEqual(99, row["cid"])
                self.assertEqual(["hidden title"], row["title_list"])
                self.assertEqual(88, row["create_user_id"])
                self.assertEqual("hidden operator", row["create_user_name"])
                self.assertEqual(77, row["update_user_id"])

    def test_title_packages_reject_missing_or_invalid_app_before_network(self) -> None:
        for operation_id in PACKAGE_OPERATION_IDS:
            for inputs in ({}, {"app_id": "abc"}, {"app_id": 101, "page_size": 101}):
                with self.subTest(operation_id=operation_id, inputs=inputs):
                    transport = RecordingTransport()
                    client = GravityInsightClient._from_manifest_for_tests(
                        manifest(operation_id), transport=transport
                    )
                    with self.assertRaises(InputValidationError):
                        client.read(operation_id, inputs)
                    self.assertEqual([], transport.calls)

    def test_read_all_stops_at_reported_total_page(self) -> None:
        def handler(
            _method: str, _path: str, kwargs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            page = int(kwargs["body"]["page"])
            return {
                "code": 0,
                "data": {
                    "list": [{"id": page, "title": f"title-{page}"}],
                    "page_info": {
                        "page": page,
                        "page_size": 1,
                        "total_page": 2,
                        "total_number": 2,
                    },
                },
            }

        transport = RecordingTransport(handler)
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(OPERATION_IDS[0]), transport=transport
        )
        result = client.read_all(
            OPERATION_IDS[0], {"page_size": 1}, max_pages=3, max_items=10
        )

        self.assertEqual("success", result["status"])
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual(2, len(transport.calls))


if __name__ == "__main__":
    unittest.main()
