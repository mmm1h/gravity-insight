from __future__ import annotations

import unittest
from typing import Any, Mapping

from gravity_sdk import GravityInsightClient
from gravity_sdk.transport import TransportResponse


CONDITIONS_PATH = "/turbo_engine/api/v1/task/ai_trusteeship/conditions_history_list/"
HISTORY_PATH = "/turbo_engine/api/v1/task/ai_trusteeship/history_list/"


class RecordingTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        if path == CONDITIONS_PATH:
            payload: dict[str, Any] = {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "advertiser_id": "ad-1",
                            "advertiser_name": "must remain hidden",
                            "ai_id": 7,
                            "condition_result": [
                                {
                                    "condition": "free-text condition",
                                    "condition_result": True,
                                    "metric_cname": "free-text metric",
                                    "target_id": 99,
                                    "unknown_nested": "hidden",
                                }
                            ],
                            "create_time": "2026-08-08 21:00:27",
                            "history_id": "history-1",
                            "id": 1,
                            "media_type": "bytedance",
                            "message": "free-text message",
                            "operator_result": {"after_value": "hidden"},
                            "operator_type": "UPDATE",
                            "target": "free-text target",
                            "target_id": 101,
                            "target_name": "campaign",
                            "target_type": "promotion",
                            "unknown_top_level": "hidden",
                        }
                    ],
                    "page_info": {"page": 1, "page_size": 20, "total_page": 1},
                },
            }
        elif path == HISTORY_PATH:
            payload = {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "ai_id": 8,
                            "cid": 3,
                            "create_time": "2026-08-08 21:00:29",
                            "detail_list": [
                                {
                                    "advertiser_id": 201,
                                    "advertiser_name": "must remain hidden",
                                }
                            ],
                            "id": "history-2",
                            "media_type": "tencent",
                            "name": "safe operation label",
                            "operator_type": "PAUSE",
                            "target": "free-text target",
                            "target_type": "promotion",
                            "target_values": {
                                "advertiser_id": "202",
                                "values": ["free-text value"],
                                "unknown_nested": "hidden",
                            },
                            "trigger": True,
                            "unknown_top_level": "hidden",
                        }
                    ],
                    "page_info": {"page": 1, "page_size": 20, "total_page": 1},
                },
            }
        else:  # pragma: no cover - test construction invariant
            raise AssertionError(f"unexpected route: {path}")
        return TransportResponse(200, payload, "2026-08-11T00:00:00Z")


class PromotionHistoryProjectionTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        return GravityInsightClient.from_env(transport=transport), transport

    def test_conditions_history_exposes_only_verified_operation_and_nested_target(self) -> None:
        client, transport = self.client()

        result = client.read("promotion.conditions_history.list", {"filters": []})

        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(CONDITIONS_PATH, transport.calls[0][1])
        self.assertEqual(
            {"filters": [], "page": 1, "page_size": 20},
            dict(transport.calls[0][2]["body"]),
        )
        row = result["data"]["list"][0]
        self.assertEqual("UPDATE", row["operator_type"])
        self.assertEqual([{"target_id": 99}], row["condition_result"])
        self.assertNotIn("advertiser_name", row)
        self.assertNotIn("message", row)
        self.assertNotIn("operator_result", row)
        self.assertNotIn("target", row)
        self.assertNotIn("unknown_top_level", row)

    def test_history_exposes_only_verified_operation_and_nested_advertiser(self) -> None:
        client, transport = self.client()

        result = client.read("promotion.history.list", {"filters": []})

        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(HISTORY_PATH, transport.calls[0][1])
        self.assertEqual(
            {"filters": [], "page": 1, "page_size": 20},
            dict(transport.calls[0][2]["body"]),
        )
        row = result["data"]["list"][0]
        self.assertEqual("PAUSE", row["operator_type"])
        self.assertEqual({"advertiser_id": "202"}, row["target_values"])
        self.assertNotIn("detail_list", row)
        self.assertNotIn("target", row)
        self.assertNotIn("values", row["target_values"])
        self.assertNotIn("unknown_nested", row["target_values"])
        self.assertNotIn("unknown_top_level", row)


if __name__ == "__main__":
    unittest.main()
