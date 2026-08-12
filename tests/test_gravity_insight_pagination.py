from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from gravity_sdk import GravityInsightClient
from gravity_sdk import runtime
from gravity_sdk.models import ReadResult


def _operation() -> dict:
    return {
        "operation_id": "example.concurrent.list",
        "domain": "example",
        "resource": "concurrent",
        "action": "list",
        "contract_version": 1,
        "upstream_method": "GET",
        "path_template": "/report/api/v3/concurrent/",
        "auth_profile": "gravity_authorization",
        "stability": "stable",
        "input_fields": {
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 1},
        },
        "request": {
            "path_fields": [],
            "query_fields": ["page", "page_size"],
            "body_fields": [],
            "defaults": {"page": 1, "page_size": 1},
            "fixed_query": {},
            "fixed_body": {},
        },
        "response_projection": {
            "data_shape": "object",
            "data_keys": ["list", "page_info"],
            "required_data_keys": ["list"],
            "item_keys": ["id"],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "page_info",
            "page_field": "page",
            "page_size_field": "page_size",
            "list_path": "data.list",
            "page_info_path": "data.page_info",
            "total_page_field": "total_page",
            "default_page_size": 1,
            "max_page_size": 100,
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "configuration",
            "redact_keys": ["authorization", "token", "cookie"],
        },
        "required_parent": [],
        "live_probe": {"enabled": True, "input": {}},
    }


def _detail_operation() -> dict:
    operation = _operation()
    operation.update(
        operation_id="example.concurrent.detail",
        resource="concurrent_detail",
        action="get",
        path_template="/report/api/v3/concurrent/detail/",
        input_fields={},
        request={
            "path_fields": [],
            "query_fields": [],
            "body_fields": [],
            "defaults": {},
            "fixed_query": {},
            "fixed_body": {},
        },
        response_projection={
            "data_shape": "object",
            "data_keys": ["id"],
            "required_data_keys": ["id"],
            "item_keys": [],
            "dynamic_item_fields": [],
        },
        pagination={"kind": "none"},
    )
    return operation


class _NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("pagination unit tests replace _execute_result")


def _page(page: int, rows: list[dict], total_pages: int | None) -> ReadResult:
    page_info = {"page": page, "page_size": 1}
    if total_pages is not None:
        page_info["total_page"] = total_pages
    return ReadResult(
        "gravity-insight.read.v1",
        "success" if rows else "empty",
        {},
        "2026-08-11T00:00:00Z",
        "a" * 64,
        "1",
        {"page": page, "page_size": 1},
        {
            "number": page,
            "size": 1,
            "item_count": len(rows),
            "total_items": total_pages,
        },
        {"list": rows, "page_info": page_info},
        "example.concurrent.list",
        items=tuple(rows),
        page_info=page_info,
    )


class GravityInsightPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = GravityInsightClient._from_manifest_for_tests(
            {
                "manifest_version": 1,
                "operations": [_operation(), _detail_operation()],
            },
            transport=_NeverTransport(),
        )

    def test_known_page_range_runs_concurrently_and_preserves_order(self) -> None:
        lock = threading.Lock()
        active = 0
        peak = 0

        def execute(_operation_id, inputs):
            nonlocal active, peak
            page = int(inputs.get("page", 1))
            if page == 1:
                return _page(1, [{"id": 1}], 4)
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.04)
                return _page(page, [{"id": page}], 4)
            finally:
                with lock:
                    active -= 1

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all(
                "example.concurrent.list", max_workers=3
            )

        self.assertGreaterEqual(peak, 2)
        self.assertEqual([1, 2, 3, 4], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("parallel_known_total", result["page"]["fetch_strategy"])
        self.assertEqual(4, result["page"]["pages_fetched"])

    def test_unknown_total_stays_serial_until_a_short_page(self) -> None:
        calls: list[int] = []

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            calls.append(page)
            return _page(page, [{"id": page}] if page < 3 else [], None)

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all(
                "example.concurrent.list", max_workers=4
            )

        self.assertEqual([1, 2, 3], calls)
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("serial_unknown_total", result["page"]["fetch_strategy"])

    def test_limited_known_range_is_parallel_ordered_and_resumable(self) -> None:
        lock = threading.Lock()
        active = 0
        peak = 0

        def execute(_operation_id, inputs):
            nonlocal active, peak
            page = int(inputs.get("page", 1))
            if page == 1:
                return _page(1, [{"id": 1}], 4)
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.04)
                return _page(page, [{"id": page}], 4)
            finally:
                with lock:
                    active -= 1

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_limited(
                "example.concurrent.list",
                max_pages=3,
                max_items=3,
                max_workers=2,
            )

        self.assertGreaterEqual(peak, 2)
        self.assertEqual([1, 2, 3], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("parallel_known_total", result["page"]["fetch_strategy"])
        self.assertEqual({"page": 4, "page_size": 1}, result["next_page_input"])
        self.assertTrue(result["truncated"])

    def test_limited_unknown_total_stays_serial_and_returns_next_page(self) -> None:
        calls: list[int] = []

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            calls.append(page)
            return _page(page, [{"id": page}], None)

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_limited(
                "example.concurrent.list",
                max_pages=2,
                max_items=2,
                max_workers=4,
            )

        self.assertEqual([1, 2], calls)
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("serial_unknown_total", result["page"]["fetch_strategy"])
        self.assertEqual({"page": 3, "page_size": 1}, result["next_page_input"])

    def test_batch_avoids_nested_page_worker_pools(self) -> None:
        envelope = {
            "status": "success",
            "page": {"item_count": 0},
            "data": {"list": []},
        }
        with patch.object(self.client, "read_all", return_value=envelope) as read_all:
            result = self.client.batch(
                [
                    {
                        "operation_id": "example.concurrent.list",
                        "read_all": True,
                    }
                ],
                max_workers=4,
            )

        self.assertTrue(result[0]["ok"])
        self.assertEqual(1, read_all.call_args.kwargs["max_workers"])

    def test_runtime_forwards_page_concurrency_when_client_supports_it(self) -> None:
        captured: dict[str, int] = {}

        class Client:
            def read_all(
                self,
                _operation_id,
                _inputs,
                *,
                max_pages,
                max_items,
                max_workers,
            ):
                captured.update(
                    max_pages=max_pages,
                    max_items=max_items,
                    max_workers=max_workers,
                )
                return {"status": "success"}

        runtime.call_read(
            Client(),
            "example.concurrent.list",
            {},
            read_all=True,
            max_pages=4,
            max_items=20,
            max_workers=3,
        )
        self.assertEqual(
            {"max_pages": 4, "max_items": 20, "max_workers": 3},
            captured,
        )

    def test_nonpaginated_object_preserves_reported_item_count(self) -> None:
        detail = ReadResult(
            "gravity-insight.read.v1",
            "success",
            {},
            "2026-08-11T00:00:00Z",
            "a" * 64,
            "1",
            {},
            {"number": 1, "item_count": 1},
            {"id": "detail-1"},
            "example.concurrent.detail",
        )
        with patch.object(self.client, "_execute_result", return_value=detail):
            result = self.client.read_limited("example.concurrent.detail")

        self.assertEqual({"id": "detail-1"}, result["data"])
        self.assertEqual(1, result["total"]["items"])
        self.assertEqual(1, result["total"]["returned_items"])


if __name__ == "__main__":
    unittest.main()
