from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "promotion.ai_trusteeship.detail"
PARENT_OPERATION_ID = "promotion.ai_trusteeship.list"
TARGET_PATH = "/turbo_engine/api/v1/task/ai_trusteeship/detail/"


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
                    "data": {
                        "caliber": "example",
                        "check_fre": 2,
                        "check_type": "periodic",
                        "cid": 3,
                        "condition_type": "threshold",
                        "conditions": [
                            {
                                "day": 1,
                                "metrics_name": "cost",
                                "operator_type": "hidden",
                                "value": "10",
                                "unknown_nested": "hidden",
                            }
                        ],
                        "count": 4,
                        "create_time": "2026-08-11 00:00:00",
                        "create_user_id": 5,
                        "create_user_name": "hidden",
                        "detail_list": [
                            {
                                "advertiser_id": 6,
                                "advertiser_name": "hidden",
                                "count": 7,
                            }
                        ],
                        "frequency": 1.5,
                        "id": 8,
                        "media_type": "bytedance",
                        "name": "Example rule",
                        "operator_values": {
                            "boost_value": 9,
                            "type": "fixed",
                            "value": 10,
                            "unknown_nested": "hidden",
                        },
                        "params_md5": "synthetic-fingerprint",
                        "schedule": {"private": "hidden"},
                        "schedule_type": "daily",
                        "send_way": [{"type": "notice", "values": ["hidden"]}],
                        "status": 1,
                        "target": "advertiser",
                        "target_type": "account",
                        "target_values": {
                            "advertiser_id": "11",
                            "values": ["hidden"],
                        },
                        "new_upstream_field": "hidden by default",
                    }
                },
            },
            "2026-08-11T00:00:00Z",
        )


class AiTrusteeshipDetailOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_request_and_recursive_fail_closed_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"ai_id": 8})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({"ai_id": 8}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))
        detail = result["data"]["data"]
        self.assertEqual(5, detail["create_user_id"])
        self.assertEqual("hidden", detail["create_user_name"])
        self.assertNotIn("schedule", detail)
        self.assertNotIn("new_upstream_field", detail)
        self.assertEqual(
            {"day": 1, "metrics_name": "cost", "value": "10"},
            detail["conditions"][0],
        )
        self.assertEqual(
            {"advertiser_id": 6, "advertiser_name": "hidden", "count": 7},
            detail["detail_list"][0],
        )
        self.assertEqual(
            {"boost_value": 9, "type": "fixed", "value": 10},
            detail["operator_values"],
        )
        self.assertEqual([{"type": "notice"}], detail["send_way"])
        self.assertEqual({"advertiser_id": "11"}, detail["target_values"])

    def test_missing_wrong_type_and_unknown_inputs_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertEqual("PARENT_REQUIRED", result["error"]["code"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"ai_id": "8"},
            {"ai_id": True},
            {"ai_id": 8, "unknown": 1},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
