from __future__ import annotations

import unittest

import json
from pathlib import Path
from typing import Any


from gravity_sdk import GravityInsightClient, InputValidationError
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "operations"
    / "report.hour_comparison.query.json"
)
ROUTE = "/report/api/v2/app/hour_comparison/"


class RecordingTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            {
                "code": 0,
                "data": {
                    "columns": {
                        "AdCost": "cost",
                        "AppRevenueReco": "revenue",
                    },
                    "today": [
                        {
                            "hour": "10",
                            "AppRealRegisterCnt": 12,
                            "AppRevenueReco": 34,
                        }
                    ],
                    "yesterday": [
                        {
                            "hour": "10",
                            "AppRealRegisterCnt": 10,
                            "AppRevenueReco": 30,
                        }
                    ],
                },
            },
            "2026-08-11T00:00:00Z",
        )


def client_for(transport: RecordingTransport) -> GravityInsightClient:
    operation = json.loads(CONTRACT.read_text(encoding="utf-8"))["operation"]
    return GravityInsightClient._from_manifest_for_tests(
        {"manifest_version": 1, "operations": [operation]},
        transport=transport,
    )



class GravityInsightHourComparisonTests(unittest.TestCase):
    def test_hour_comparison_uses_fixed_global_scope_and_nested_allowlists(self):
        transport = RecordingTransport()

        result = client_for(transport).read("report.hour_comparison.query", {})

        assert result["status"] == "success"
        assert len(transport.calls) == 1
        method, path, kwargs = transport.calls[0]
        assert (method, path) == ("POST", ROUTE)
        assert kwargs["body"] == {"app_ids": []}
        assert result["data"] == {
            "columns": {"AdCost": "cost", "AppRevenueReco": "revenue"},
            "today": [
                {"hour": "10", "AppRealRegisterCnt": 12, "AppRevenueReco": 34}
            ],
            "yesterday": [
                {"hour": "10", "AppRealRegisterCnt": 10, "AppRevenueReco": 30}
            ],
        }


    def test_hour_comparison_rejects_unverified_app_filters_before_network(self):
        transport = RecordingTransport()

        with self.assertRaises(InputValidationError):
            client_for(transport).read(
                "report.hour_comparison.query", {"app_ids": [1]}
            )

        assert transport.calls == []
