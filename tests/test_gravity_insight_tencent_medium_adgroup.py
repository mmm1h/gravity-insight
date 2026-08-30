from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import (
    GravityInsightClient,
    InputValidationError,
)
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.tencent.medium_adgroup.list"
PARENT_OPERATION_ID = "promotion.tencent.adgroup_filter.list"
CONTRACT_ROOT = ROOT / "src" / "gravity_insight" / "contracts" / "operations"


def manifest() -> dict[str, Any]:
    operations = []
    for operation_id in (PARENT_OPERATION_ID, OPERATION_ID):
        source = json.loads(
            (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        operations.append(source["operation"])
    return {"manifest_version": 1, "operations": operations}


class RecordingTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []
        self.payload = payload or {
            "code": 0,
            "data": {
                "list": [
                    {
                        "adgroup_id": 7,
                        "adgroup_name": "safe adgroup",
                        "configured_status": "AD_STATUS_NORMAL",
                        "begin_date": "2026-08-01",
                        "end_date": "2026-08-31",
                        "bid_amount": 100,
                        "bid_mode": "BID_MODE_OCPC",
                        "daily_budget": 500,
                        "total_budget": 1000,
                    }
                ]
            },
        }

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, dict(self.payload), "2026-08-11T00:00:00Z")


class TencentMediumAdgroupOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        return (
            GravityInsightClient._from_manifest_for_tests(
                manifest(), transport=transport
            ),
            transport,
        )

    def test_verified_route_defaults_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"advertiser_id": "123456"})

        self.assertEqual("success", result["status"])
        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/medium/adgroup/list/",
            transport.calls[0][1],
        )
        self.assertEqual(
            {"advertiser_id": "123456", "api_version": "v3.0"},
            dict(transport.calls[0][2]["body"]),
        )
        row = result["data"]["list"][0]
        self.assertEqual("safe adgroup", row["adgroup_name"])
        for field in ("bid_amount", "bid_mode", "daily_budget", "total_budget"):
            self.assertNotIn(field, row)

    def test_parent_and_version_validation_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertFalse(result["ok"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"advertiser_id": "123456", "api_version": "v2.0"},
            {"advertiser_id": "123456", "fields": ["bid_amount"]},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


class TencentAdgroupReportAndCreativeTests(unittest.TestCase):
    def test_adgroup_report_sends_frontend_load_shape_and_exposes_observed_fields(self) -> None:
        transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "adgroup_id": "7",
                            "adgroup_name": "safe adgroup",
                            "cost": "1.2",
                            "project_list": [{"id": 1}],
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 1,
                        "total_number": 1,
                        "total_page": 1,
                    },
                    "total": [{"cost": "1.2"}],
                    "update_at": "2026-08-17 00:00:00",
                },
            }
        )
        client = GravityInsightClient._from_manifest_for_tests(
            _operations_manifest(
                "promotion.tencent.tencent_adgroup_v2.list",
            ),
            transport=transport,
        )

        result = client.read(
            "promotion.tencent.tencent_adgroup_v2.list",
            {
                "date_list": ["2026-08-17", "2026-08-17"],
                "filters": [
                    {"field": "put_status", "operator": 1, "values": [1]},
                    {"field": "grant_type", "operator": 1, "values": [2]},
                ],
                "page": 1,
                "page_size": 1,
            },
        )

        self.assertEqual("success", result["status"])
        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/adgroup/list/v2/",
            transport.calls[0][1],
        )
        body = dict(transport.calls[0][2]["body"])
        self.assertEqual(["2026-08-17", "2026-08-17"], body["date_list"])
        self.assertEqual("behavior", body["time_line"])
        self.assertEqual("v3.0", body["version"])
        self.assertNotIn("real_data", body)
        row = result["data"]["list"][0]
        self.assertEqual("safe adgroup", row["adgroup_name"])
        self.assertIn("cost", row)
        self.assertNotIn("project_list", row)

    def test_medium_creative_requires_parent_and_keeps_components_opaque(self) -> None:
        transport = RecordingTransport(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "dynamic_creative_id": 9,
                            "dynamic_creative_name": "safe creative",
                            "configured_status": "AD_STATUS_NORMAL",
                            "creative_components": {"video_id": "v1"},
                        }
                    ]
                },
            }
        )
        client = GravityInsightClient._from_manifest_for_tests(
            _operations_manifest(
                "promotion.tencent.adgroup_filter.list",
                "material.tencent_medium_creative.list",
            ),
            transport=transport,
        )
        result = client.read("material.tencent_medium_creative.list", {})
        self.assertEqual("parent_required", result["status"])
        self.assertEqual([], transport.calls)

        result = client.read(
            "material.tencent_medium_creative.list",
            {"advertiser_id": "123456"},
        )
        self.assertEqual("success", result["status"])
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/medium/creative/list/",
            transport.calls[0][1],
        )
        row = result["data"]["list"][0]
        self.assertEqual(9, row["dynamic_creative_id"])
        self.assertEqual({"video_id": "v1"}, row["creative_components"])

    def test_empty_tencent_kuaishou_reads_stay_confirmed_and_uninvented(self) -> None:
        from gravity_insight.agents.unavailable_promotion import unavailable_promotion_gap
        from gravity_insight.prober.read_semantics import (
            CONFIRMATIONS_PATH,
            confirmation_keys,
        )

        keys = confirmation_keys(CONFIRMATIONS_PATH)
        self.assertTrue(
            {
                ("POST", "/turbo_engine/api/v1/tencent/asset/text/title/list/"),
                ("POST", "/turbo_engine/api/v1/kuaishou/campaign/list/"),
                ("POST", "/turbo_engine/api/v1/kuaishou/creative/list/"),
            }
            <= keys
        )
        hierarchy = unavailable_promotion_gap("下钻非巨量平台的计划、组和创意表现。")
        creative = unavailable_promotion_gap("深查各平台专属素材和创意字段。")
        self.assertEqual("NON_BYTEDANCE_HIERARCHY_PARENT_MISSING", hierarchy["code"])
        self.assertIn("Kuaishou campaign", hierarchy["reason"])
        self.assertEqual("PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING", creative["code"])
        self.assertIn("title-library", creative["reason"])


def _operations_manifest(*operation_ids: str) -> dict[str, Any]:
    operations = []
    for operation_id in operation_ids:
        source = json.loads(
            (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        operations.append(source["operation"])
    return {"manifest_version": 1, "operations": operations}


if __name__ == "__main__":
    unittest.main()
