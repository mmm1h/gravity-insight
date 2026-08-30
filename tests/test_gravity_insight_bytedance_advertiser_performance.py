from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.prober.privacy import classify_candidate_field
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.bytedance.advertiser_performance.list"
TARGET_PATH = "/turbo_engine/api/v1/bytedance/advertiser/list/"


def manifest() -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_insight"
        / "contracts"
        / "operations"
        / f"{OPERATION_ID}.json"
    )
    operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
    return {"manifest_version": 1, "operations": [operation]}


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
                            "advertiser_agent_id": 11,
                            "advertiser_agent_name": "synthetic agency",
                            "advertiser_balance": 100.5,
                            "advertiser_budget": "UNLIMITED",
                            "advertiser_budget_mode": "INFINITE",
                            "advertiser_id": "advertiser-1",
                            "advertiser_name": "hidden account name",
                            "advertiser_remark": "hidden free text",
                            "advertiser_system_status": "STATUS_ENABLE",
                            "app_id": 21,
                            "app_name": "synthetic app",
                            "company": "hidden company",
                            "delay": 0,
                            "operator_id": 31,
                            "operator_name": "hidden operator",
                            "project_list": [{"project_id": "hidden"}],
                            "stat_cost": "12.34",
                            "new_upstream_field": "hidden by default",
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 10,
                        "total_number": 23,
                        "total_page": 3,
                    },
                    "total": [
                        {
                            "advertiser_id": "hidden by nested projection",
                            "stat_cost": "12.34",
                        }
                    ],
                    "update_at": "2026-08-11 12:00:00",
                    "new_data_field": "hidden by default",
                },
            },
            "2026-08-11T04:36:33Z",
        )


class BytedanceAdvertiserPerformanceOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_safe_first_page_request_and_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(
            OPERATION_ID,
            {"date_list": ["2026-08-10", "2026-08-11"]},
        )

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({}, dict(kwargs["query"]))
        body = dict(kwargs["body"])
        self.assertEqual(
            {
                "date_list": ["2026-08-10", "2026-08-11"],
                "filtering": {},
                "filters": [
                    {"field": "put_status", "operator": 1, "values": [1]},
                    {"field": "grant_type", "operator": 1, "values": [2]},
                ],
                "order_by": [],
                "page": 1,
                "page_size": 10,
                "query_fields": [],
            },
            body,
        )
        self.assertNotIn("real_data", body)
        self.assertEqual(
            {
                "advertiser_agent_id",
                "advertiser_agent_name",
                "advertiser_balance",
                "advertiser_budget",
                "advertiser_budget_mode",
                "advertiser_id",
                "advertiser_name",
                "advertiser_remark",
                "advertiser_system_status",
                "app_id",
                "app_name",
                "company",
                "delay",
                "operator_id",
                "operator_name",
                "project_list",
                "stat_cost",
            },
            set(result["data"]["list"][0]),
        )
        self.assertEqual([{"stat_cost": "12.34"}], result["data"]["total"])
        self.assertEqual(
            {"list", "page_info", "total", "update_at"}, set(result["data"])
        )

    def test_unverified_inputs_fail_before_network(self) -> None:
        invalid_inputs = (
            {},
            {"date_list": ["2026-08-11"]},
            {"date_list": ["2026-08-09", "2026-08-10", "2026-08-11"]},
            {"date_list": ["2026/08/10", "2026-08-11"]},
            {"date_list": ["2026-08-11", "2026-08-10"]},
            {
                "date_list": ["2026-08-10", "2026-08-11"],
                "page_size": 11,
            },
            {
                "date_list": ["2026-08-10", "2026-08-11"],
                "real_data": 1,
            },
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)

    def test_route_specific_financial_and_ambiguous_fields_are_reviewed(self) -> None:
        for field in (
            "advertiser_balance",
            "advertiser_budget",
            "advertiser_budget_mode",
            "stat_cost",
        ):
            self.assertEqual(
                ("non_sensitive", "route_specific_field_review"),
                classify_candidate_field(
                    f"data.list[].{field}", operation_id=OPERATION_ID
                ),
            )
        for field in ("advertiser_remark", "delay"):
            self.assertEqual(
                ("non_sensitive", "route_specific_field_review"),
                classify_candidate_field(
                    f"data.list[].{field}", operation_id=OPERATION_ID
                ),
            )


if __name__ == "__main__":
    unittest.main()
