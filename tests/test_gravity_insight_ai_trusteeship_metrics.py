from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient, InputValidationError
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "metadata.metrics.get"
PARENT_OPERATION_ID = "promotion.ai_trusteeship.list"
TARGET_PATH = "/turbo_engine/api/v1/task/ai_trusteeship/get_metrics/"


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
                    "list": [
                        {
                            "name": "delivery",
                            "metrics": [
                                {
                                    "cname": "消耗",
                                    "formula": "cost",
                                    "name": "cost",
                                    "unit": "currency",
                                    "new_upstream_field": "hidden by default",
                                }
                            ],
                            "new_group_field": "hidden by default",
                        }
                    ]
                },
            },
            "2026-08-11T00:00:00Z",
        )


class AiTrusteeshipMetricsOperationTests(unittest.TestCase):
    def client(self) -> tuple[GravityInsightClient, RecordingTransport]:
        transport = RecordingTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            manifest(), transport=transport
        )
        return client, transport

    def test_exact_get_and_nested_metric_projection(self) -> None:
        client, transport = self.client()

        result = client.read(OPERATION_ID, {"media_type": "bytedance"})

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        method, path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual(TARGET_PATH, path)
        self.assertEqual({"media_type": "bytedance"}, dict(kwargs["query"]))
        self.assertEqual({}, dict(kwargs["body"]))
        self.assertEqual(
            {
                "name": "delivery",
                "metrics": [
                    {
                        "cname": "消耗",
                        "formula": "cost",
                        "name": "cost",
                        "unit": "currency",
                    }
                ],
            },
            result["data"]["list"][0],
        )

    def test_missing_wrong_type_and_unknown_inputs_fail_before_network(self) -> None:
        client, transport = self.client()
        result = client.read(OPERATION_ID, {})
        self.assertEqual("parent_required", result["status"])
        self.assertEqual("PARENT_REQUIRED", result["error"]["code"])
        self.assertEqual([], transport.calls)

        invalid_inputs = (
            {"media_type": 1},
            {"media_type": True},
            {"media_type": "bytedance", "unknown": 1},
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs):
                client, transport = self.client()
                with self.assertRaises(InputValidationError):
                    client.read(OPERATION_ID, inputs)
                self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
