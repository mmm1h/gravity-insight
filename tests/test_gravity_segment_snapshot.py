import json
import unittest

from gravity_sdk.errors import ContractChangedError, InputValidationError, PaginationError
from gravity_sdk.segment_snapshot import SEGMENT_SOURCES, segment_snapshot


def _catalog(*rows, truncated=False):
    return {
        "ok": True,
        "status": "success",
        "data": {"list": list(rows)},
        "truncated": truncated,
        "next_page_input": {"page": 2} if truncated else None,
    }


class _Client:
    def __init__(self, catalog=None, *, failed=None, omit=None, daily_rows=()):
        self.catalog = catalog or _catalog(
            {"segment_id": 8, "id": 8, "segment_name": "Buyers", "app_id": 17}
        )
        self.failed = failed
        self.omit = omit
        self.daily_rows = list(daily_rows)
        self.read_calls = []
        self.batch_calls = []

    def read_limited(
        self, operation_id, inputs, *, max_pages, max_items, max_workers
    ):
        self.read_calls.append((operation_id, inputs, max_pages, max_items, max_workers))
        return self.catalog

    def batch(self, requests, *, max_workers, max_pages, max_total_items):
        if len(requests) > max_total_items: raise ValueError("request budget")
        self.batch_calls.append((requests, max_workers, max_pages, max_total_items))
        results = []
        for request in reversed(requests):
            source = request["request_id"]
            if source == self.omit:
                continue
            failed = source == self.failed
            payload = {
                "detail": {
                    "id": 8,
                    "segment_id": 8,
                    "app_id": 17,
                    "segment_name": "Buyers",
                    "origin_query": {"private": "secret"},
                },
                "history": {
                    "list": [{"version_id": 3, "uid_cnt": 12, "secret": "x"}],
                    "page": 1,
                    "total": 1,
                },
                "daily_result": {
                    "list": self.daily_rows,
                    "page_info": {"page": 1, "total_page": 1, "token": "secret"},
                },
            }[source]
            results.append(
                {
                    "operation_id": request["operation_id"],
                    "request_id": source,
                    "ok": not failed,
                    "status": "error" if failed else "success",
                    "data": None
                    if failed
                    else {"status": "success", "data": payload},
                    "error": {
                        "code": "UPSTREAM_UNAVAILABLE",
                        "category": "upstream",
                        "message": "C:/private/raw boom token=secret",
                    }
                    if failed
                    else None,
                }
            )
        return results


class SegmentSnapshotTests(unittest.TestCase):
    def test_exact_resolution_orders_sources_and_isolates_safe_partial(self):
        catalog = _catalog(
            {"segment_id": 7, "segment_name": "Same", "app_id": 17},
            {"segment_id": 8, "segment_name": "Same", "app_id": 17},
        )
        client = _Client(catalog, failed="history")
        result = segment_snapshot(
            client, 17, 8, date="2026-08-12", max_workers=3, max_pages=5, max_items=20
        )
        requests, workers, pages, items = client.batch_calls[0]
        self.assertEqual((3, 5, 18), (workers, pages, items))
        self.assertEqual(
            ["detail", "history", "daily_result"],
            [row["source"] for row in result["results"]],
        )
        self.assertEqual([source.operation_id for source in SEGMENT_SOURCES],
                         [request["operation_id"] for request in requests])
        self.assertEqual("2026-08-12", requests[2]["inputs"]["date"])
        self.assertEqual({"id": "8", "name": "Same"}, result["segment"])
        self.assertEqual((False, "partial", 3),
                         (result["ok"], result["status"], result["exit_code"]))
        encoded = json.dumps(result).casefold()
        for forbidden in ("origin_query", "secret", "private", "raw boom", "request_id"):
            self.assertNotIn(forbidden, encoded)

    def test_discovery_identity_dates_and_aggregate_budget_fail_closed(self):
        for value, field in (("2026-8-2", "date"), ("", "ref"), (0, "app_id")):
            client = _Client()
            kwargs = {"app_id": 17, "ref": 8, "date": "2026-08-12"}
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(InputValidationError):
                segment_snapshot(client, **kwargs)
            self.assertEqual([], client.read_calls)
        with self.assertRaises(InputValidationError):
            segment_snapshot(_Client(), 17, 8, date="2026-08-12", max_items=3)
        truncated = _Client(_catalog(
            {"segment_id": 8, "segment_name": "Buyers", "app_id": 17},
            truncated=True,
        ))
        with self.assertRaises(PaginationError):
            segment_snapshot(truncated, 17, 8, date="2026-08-12")
        self.assertEqual([], truncated.batch_calls)
        duplicate = _Client(_catalog(
            {"segment_id": 8, "segment_name": "A", "app_id": 17},
            {"segment_id": 8, "segment_name": "B", "app_id": 17},
        ))
        with self.assertRaises(ContractChangedError):
            segment_snapshot(duplicate, 17, 8, date="2026-08-12")
        mismatch = _Client(_catalog(
            {"segment_id": 8, "id": 999, "segment_name": "A", "app_id": 17},
        ))
        with self.assertRaises(ContractChangedError):
            segment_snapshot(mismatch, 17, 8, date="2026-08-12")
        missing = segment_snapshot(
            _Client(omit="history"), 17, 8, date="2026-08-12"
        )
        self.assertEqual("BATCH_RESULT_MISSING", missing["results"][1]["error"]["code"])
        bounded = _Client(daily_rows=[
            {"create_date": "2026-08-12", "user_cnt": 1, "secret": "x"}
        ])
        with self.assertRaises(PaginationError):
            segment_snapshot(bounded, 17, 8, date="2026-08-12", max_items=4)
        with self.assertRaises(InputValidationError) as empty_catalog:
            segment_snapshot(_Client(_catalog()), 17, 8, date="2026-08-12")
        self.assertIn("permission-profile", empty_catalog.exception.next_action)


if __name__ == "__main__":
    unittest.main()
