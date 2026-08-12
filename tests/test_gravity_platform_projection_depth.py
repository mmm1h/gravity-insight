from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]


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


class StaticTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-08-11T00:00:00Z")


def _client(operation_id: str, payload: Mapping[str, Any]) -> GravityInsightClient:
    return GravityInsightClient._from_manifest_for_tests(
        {"manifest_version": 1, "operations": [_contract(operation_id)]},
        transport=StaticTransport(payload),
    )


def _event_property(**overrides: Any) -> dict[str, Any]:
    item = {
        "cid": 7,
        "cname": "设备类型",
        "create_time": "2026-08-08 20:00:00",
        "data_type": "string",
        "id": 11,
        "is_common": True,
        "is_preset": False,
        "modify_time": "2026-08-08 21:00:00",
        "name": "device_type",
        "template_id": 17,
    }
    item.update(overrides)
    return item


class PlatformProjectionDepthTests(unittest.TestCase):
    def test_report_overview_projects_only_reviewed_column_labels(self) -> None:
        operation_id = "report.overview.query"
        columns = {
            "AdCost": "广告消耗",
            "AppActivePayAmountSumReco": "活跃付费金额",
            "AppAdFirstDayRevenueReco": "首日广告收入",
            "AppAdRevenueReco": "广告收入",
            "AppDAUReco": "活跃用户",
            "AppFirstDayPayAmountStandardReco": "首日付费金额",
            "AppROIReco": "ROI",
            "AppRealRegisterCnt": "注册数",
            "AppRevenueReco": "总收入",
        }
        client = _client(
            operation_id,
            {
                "code": 0,
                "data": {
                    "columns": {
                        **columns,
                        "future_metric": "must stay hidden",
                        "operator_name": "must stay hidden",
                    }
                },
            },
        )

        result = client.read(
            operation_id,
            {
                "app_ids": [],
                "date_list": ["2026-08-09", "2026-08-09"],
                "use_cache": 0,
                "verbose": False,
            },
        )

        self.assertEqual("contract_changed_additive", result["status"])
        self.assertEqual({"columns": columns}, result["data"])

    def test_bilibili_account_total_is_projected_fail_closed(self) -> None:
        operation_id = "promotion.bilibili.account.list"
        total = {
            "average_cost_per_thousand": 1.5,
            "click_count": 8,
            "click_rate": 0.25,
            "cost_per_click": 0.75,
            "san_lian_launch_total_consume": 2.5,
            "show_count": 32,
            "total_cash_consume": 10.0,
            "total_consume": 12.0,
            "total_red_packet_consume": 1.0,
            "total_special_red_packet_consume": 1.0,
        }
        client = _client(
            operation_id,
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "advertiser_id": 7,
                            "product_name": "fixture",
                            "advertiser_name": "must stay hidden",
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 20,
                        "total_number": 1,
                        "total_page": 1,
                    },
                    "total": {**total, "future_total_field": "hidden"},
                },
            },
        )

        result = client.read(operation_id, {"page": 1, "page_size": 20})

        self.assertEqual("contract_changed_additive", result["status"])
        self.assertEqual(total, result["data"]["total"])
        self.assertEqual(
            {"advertiser_id": 7, "product_name": "fixture"},
            result["data"]["list"][0],
        )

    def test_material_tag_tree_projects_only_tag_id_and_name(self) -> None:
        operation_id = "material.tag_category.tree"
        client = _client(
            operation_id,
            {
                "code": 0,
                "data": [
                    {
                        "id": 1,
                        "is_system": 1,
                        "name": "创意类型",
                        "source": "system",
                        "tag_list": [
                            {
                                "id": 11,
                                "name": "视频",
                                "operator_name": "must stay hidden",
                                "future_tag_field": "hidden",
                            }
                        ],
                    }
                ],
            },
        )

        result = client.read(operation_id, {})

        self.assertEqual("contract_changed", result["status"])
        self.assertEqual(
            [
                {
                    "id": 1,
                    "is_system": 1,
                    "name": "创意类型",
                    "source": "system",
                    "tag_list": [{"id": 11, "name": "视频"}],
                }
            ],
            result["data"],
        )

    def test_event_property_template_projects_nested_branches_and_empty_custom(self) -> None:
        operation_id = "metadata.event_property_template_event_list.list"
        common = _event_property()
        preset = _event_property(id=12, is_common=False, is_preset=True)
        client = _client(
            operation_id,
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": 1,
                            "name": "launch",
                            "properties": {
                                "common": [common],
                                "custom": [],
                                "preset": [preset],
                            },
                        },
                        {
                            "id": 2,
                            "name": "purchase",
                            "properties": {
                                "common": [],
                                "custom": None,
                                "preset": [],
                            },
                        },
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 20,
                        "total_number": 2,
                        "total_page": 1,
                    },
                },
            },
        )

        result = client.read(operation_id, {"page": 1, "page_size": 20})

        self.assertEqual("success", result["status"])
        self.assertEqual(
            {"common": [common], "custom": [], "preset": [preset]},
            result["data"]["list"][0]["properties"],
        )
        self.assertEqual(
            {"common": [], "custom": None, "preset": []},
            result["data"]["list"][1]["properties"],
        )

    def test_event_property_template_nested_text_and_unknown_fields_fail_closed(self) -> None:
        operation_id = "metadata.event_property_template_event_list.list"
        safe_property = _event_property()
        client = _client(
            operation_id,
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "id": 1,
                            "name": "launch",
                            "properties": {
                                "common": [
                                    {
                                        **safe_property,
                                        "remark": "must stay hidden",
                                        "free_text": "must stay hidden",
                                        "future_field": "must stay hidden",
                                    }
                                ],
                                "custom": [],
                                "preset": [],
                            },
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 20,
                        "total_number": 1,
                        "total_page": 1,
                    },
                },
            },
        )

        result = client.read(operation_id, {"page": 1, "page_size": 20})

        self.assertEqual("contract_changed", result["status"])
        self.assertEqual(
            safe_property,
            result["data"]["list"][0]["properties"]["common"][0],
        )


if __name__ == "__main__":
    unittest.main()
