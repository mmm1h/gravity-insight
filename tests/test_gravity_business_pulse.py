import unittest

from gravity_sdk.business_pulse import business_pulse


class RecordingClient:
    def __init__(self, *, fail_business=False):
        self.fail_business = fail_business
        self.calls = []

    def batch(
        self, requests, *, max_workers=6, max_pages=1_000, max_total_items=100_000
    ):
        self.calls.append((requests, max_workers, max_pages, max_total_items))
        results = []
        for request in requests:
            failed = self.fail_business and request["request_id"] == "business"
            results.append(
                {
                    "operation_id": request["operation_id"],
                    "request_id": request["request_id"],
                    "ok": not failed,
                    "status": "error" if failed else "success",
                    "data": None if failed else {"status": "success", "data": {}},
                    "error": (
                        {"code": "LOCAL_ERROR", "category": "local", "message": "failed"}
                        if failed
                        else None
                    ),
                }
            )
        return list(reversed(results))


class BusinessPulseTests(unittest.TestCase):
    def test_fixed_sources_are_ordered_and_optional_hourly_failure_is_isolated(self):
        client = RecordingClient(fail_business=True)
        result = business_pulse(
            client,
            [101, "202"],
            "2026-08-01",
            "2026-08-07",
            include_hourly=True,
            max_workers=9,
            max_pages=7,
            max_items=90,
        )
        requests, workers, pages, items = client.calls[0]
        sources = ["overview", "business", "hourly_comparison"]
        self.assertEqual(sources, [row["source"] for row in result["results"]])
        self.assertEqual("partial", result["status"])
        self.assertEqual((workers, pages, items), (9, 7, 90))
        self.assertEqual(sources, [request["request_id"] for request in requests])
        self.assertEqual(
            [False, True, False], [request["read_all"] for request in requests]
        )
        self.assertEqual(["101", "202"], requests[0]["inputs"]["app_ids"])
        self.assertEqual(["101", "202"], requests[1]["inputs"]["app_list"])
        self.assertEqual(
            ["app", "app", "workspace"],
            [row["scope"] for row in result["results"]],
        )
        self.assertEqual([True, False, True], [row["ok"] for row in result["results"]])

        default = business_pulse(
            RecordingClient(), [101], "2026-08-01", "2026-08-07"
        )
        self.assertEqual(
            ["overview", "business"],
            [row["source"] for row in default["results"]],
        )
