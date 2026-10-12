from __future__ import annotations

import json
import threading
from threading import Barrier
import unittest
from unittest.mock import patch

from gravity_insight import GravityInsightClient
from gravity_insight import runtime
from gravity_insight.errors import ManifestError
from gravity_insight.models import ReadResult
from gravity_insight.pagination_audit import pagination_audit
from gravity_insight.pagination_completeness import aggregate_completeness, page_completeness
from gravity_insight.pagination_policy import has_next_page


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
            "completeness": "complete",
            "pagination_evidence": "production",
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


def _identity_operation() -> dict:
    operation = _operation()
    operation["operation_id"] = "analysis.order_detail.list"
    operation["resource"] = "order_detail"
    operation["response_projection"]["item_keys"] = ["id", "event_pay_id"]
    operation["pagination"]["record_identity_field"] = "event_pay_id"
    return operation


class _NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("pagination unit tests replace _execute_result")


def _legacy_full_page_heuristic(
    item_count: int,
    page_number: int | None,
    page_size: int | None,
    total_pages: int | None,
) -> bool:
    if page_number is not None and total_pages is not None:
        return page_number < total_pages
    return bool(page_size and item_count >= page_size)


def _page(
    page: int,
    rows: list[dict],
    total_pages: int | None,
    *,
    status: str | None = None,
    operation_id: str = "example.concurrent.list",
) -> ReadResult:
    page_info = {"page": page, "page_size": 1}
    if total_pages is not None:
        page_info["total_page"] = total_pages
    return ReadResult(
        "gravity-insight.read.v1",
        status if status is not None else ("success" if rows else "empty"),
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
        operation_id,
        items=tuple(rows),
        page_info=page_info,
    )


class GravityInsightPaginationTests(unittest.TestCase):
    def test_aggregate_completeness_consumes_object_shaped_pagination_audit(self) -> None:
        result = {
            "pagination_audit": {
                "completeness": {
                    "criterion": "has_more=false and returned_items=total_items",
                    "status": "complete",
                    "has_more": False,
                    "returned_items": 2,
                    "total_items": 2,
                }
            }
        }

        self.assertEqual("complete", aggregate_completeness(result))

    def test_complete_contract_without_runtime_page_evidence_stays_unknown(self) -> None:
        self.assertEqual(
            "unknown",
            page_completeness("complete", None, all_pages=True),
        )

    def test_order_identity_duplicates_preserve_rows_but_block_complete_claim(self) -> None:
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [_identity_operation()]},
            transport=_NeverTransport(),
        )

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            return _page(
                page,
                [{"id": page, "event_pay_id": "private-record-key"}],
                2,
                operation_id="analysis.order_detail.list",
            )

        with patch.object(client, "_execute_result", side_effect=execute):
            result = client.read_all(
                "analysis.order_detail.list", max_workers=1
            )

        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("complete", result["structural_completeness"])
        self.assertEqual("unknown", result["completeness"])
        self.assertEqual("unknown", aggregate_completeness(result))
        self.assertEqual(
            {
                "status": "unknown",
                "criterion": (
                    "record identities are missing or repeated; "
                    "unique-record completeness is unknown"
                ),
                "identity_field": "event_pay_id",
                "item_count": 2,
                "identified_item_count": 2,
                "unidentified_item_count": 0,
                "duplicate_identity_count": 1,
                "duplicate_item_count": 1,
            },
            result["record_completeness"],
        )
        audit = pagination_audit(result, {}, all_pages=True)
        self.assertEqual("complete", audit["structural_completeness"]["status"])
        self.assertEqual("unknown", audit["completeness"]["status"])
        self.assertEqual(1, audit["record_completeness"]["duplicate_item_count"])
        self.assertNotIn("private-record-key", json.dumps(audit))

    def test_order_identity_unique_rows_retain_complete_claim(self) -> None:
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [_identity_operation()]},
            transport=_NeverTransport(),
        )

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            return _page(
                page,
                [{"id": page, "event_pay_id": f"record-{page}"}],
                2,
                operation_id="analysis.order_detail.list",
            )

        with patch.object(client, "_execute_result", side_effect=execute):
            result = client.read_all(
                "analysis.order_detail.list", max_workers=1
            )

        self.assertEqual("complete", result["completeness"])
        self.assertEqual("complete", result["record_completeness"]["status"])
        self.assertEqual(0, result["record_completeness"]["duplicate_item_count"])
        self.assertEqual(
            "event_pay_id",
            client.schema("analysis.order_detail.list")["pagination"][
                "record_identity_field"
            ],
        )

    def test_order_identity_missing_from_projection_is_unknown(self) -> None:
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [_identity_operation()]},
            transport=_NeverTransport(),
        )
        with patch.object(
            client,
            "_execute_result",
            return_value=_page(
                1, [{"id": 1}], 1,
                operation_id="analysis.order_detail.list",
            ),
        ):
            result = client.read_all("analysis.order_detail.list", max_workers=1)

        self.assertEqual("unknown", result["completeness"])
        self.assertEqual(1, result["record_completeness"]["unidentified_item_count"])

    def test_record_identity_must_name_a_projected_item_key(self) -> None:
        operation = _identity_operation()
        operation["response_projection"]["item_keys"] = ["id"]
        with self.assertRaisesRegex(
            ManifestError, "record_identity_field must name a projected item key"
        ):
            GravityInsightClient._from_manifest_for_tests(
                {"manifest_version": 1, "operations": [operation]},
                transport=_NeverTransport(),
            )

    def setUp(self) -> None:
        self.client = GravityInsightClient._from_manifest_for_tests(
            {
                "manifest_version": 1,
                "operations": [_operation(), _detail_operation()],
            },
            transport=_NeverTransport(),
        )

    def test_known_page_range_runs_concurrently_and_preserves_order(self) -> None:
        lock, rendezvous = threading.Lock(), Barrier(3, timeout=20)
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
                rendezvous.wait()
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
        self.assertEqual("complete", result["completeness"])

    def test_all_pages_audit_counts_worker_http_requests(self) -> None:
        from gravity_insight.receipt import (
            PRODUCTION_HTTP_KIND,
            count_http_requests,
            record_http_request,
        )

        def execute(_operation_id, inputs):
            record_http_request(kind=PRODUCTION_HTTP_KIND)
            page = int(inputs.get("page", 1))
            return _page(page, [{"id": page}], 4)

        with count_http_requests() as counter:
            with patch.object(self.client, "_execute_result", side_effect=execute):
                result = self.client.read_all(
                    "example.concurrent.list", max_workers=3
                )
            audit = pagination_audit(
                result, {}, all_pages=True, http_requests_made=counter.count
            )
        self.assertEqual(4, result["page"]["pages_fetched"])
        self.assertEqual(4, audit["operation_requests_made"])
        self.assertEqual(4, audit["http_requests_made"])

    def test_unknown_total_stays_serial_until_a_short_page(self) -> None:
        calls: list[int] = []

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            calls.append(page)
            return _page(page, [{"id": page}] if page < 3 else [], None)

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all(
                "example.concurrent.list",
                max_workers=4,
                continue_without_total=True,
            )

        self.assertEqual([1, 2, 3], calls)
        self.assertEqual([1, 2], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("serial_unknown_total", result["page"]["fetch_strategy"])

    def test_full_page_without_total_does_not_continue_by_default(self) -> None:
        calls: list[int] = []

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            calls.append(page)
            return _page(page, [{"id": page}], None)

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all(
                "example.concurrent.list", max_workers=4
            )

        self.assertEqual([1], calls)
        self.assertEqual([1], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("stopped_missing_total_page", result["page"]["fetch_strategy"])
        self.assertIsNone(result["page"]["has_more"])
        self.assertIsNone(result["page"]["total_pages"])
        self.assertEqual("unknown", result["completeness"])
        with patch.object(self.client, "_execute_result", side_effect=execute):
            limited = self.client.read_limited(
                "example.concurrent.list", max_pages=2, max_items=2
            )
        self.assertEqual([1, 1], calls)
        self.assertIsNone(limited["page"]["has_more"])
        self.assertIsNone(limited["next_page_input"])
        self.assertFalse(limited["truncated"])
        # Pre-fix: missing total_page fell through to item_count >= page_size.
        self.assertTrue(_legacy_full_page_heuristic(1, 1, 1, None))
        self.assertFalse(has_next_page(1, 1, 1, None))
        self.assertTrue(has_next_page(1, 1, 1, None, continue_without_total=True))
        audit = pagination_audit(result, {}, all_pages=True)
        self.assertEqual("unknown", audit["completeness"]["status"])
        self.assertIn("total_page absent", audit["completeness"]["criterion"])

    def test_limited_known_range_is_parallel_ordered_and_resumable(self) -> None:
        lock, rendezvous = threading.Lock(), Barrier(2, timeout=20)
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
                rendezvous.wait()
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
        self.assertEqual("prefix", result["completeness"])

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
                continue_without_total=True,
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

    def test_shape_a_known_total_still_pages_without_opt_in(self) -> None:
        calls: list[int] = []

        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            calls.append(page)
            return _page(page, [{"id": page}], 3)

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all(
                "example.concurrent.list", max_workers=1
            )

        self.assertEqual([1, 2, 3], calls)
        self.assertEqual([1, 2, 3], [row["id"] for row in result["data"]["list"]])
        self.assertEqual("serial_known_total", result["page"]["fetch_strategy"])
        self.assertFalse(result["page"]["has_more"])

    def test_merged_ok_reflects_a_later_page_breaking_contract_change(self) -> None:
        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            if page == 1:
                return _page(1, [{"id": 1}], 2)
            return _page(2, [{"id": 2}], 2, status="contract_changed")

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all("example.concurrent.list", max_workers=1)

        # Pre-fix: merge_pages seeded `ok` from page 1 alone (`to_dict()`)
        # and never re-derived it once a later page's status overrode the
        # merged `status`, so a breaking drift on page 2+ still read `ok=True`.
        self.assertEqual("contract_changed", result["status"])
        self.assertFalse(result["ok"])

    def test_merged_ok_stays_true_for_a_later_page_additive_contract_change(
        self,
    ) -> None:
        def execute(_operation_id, inputs):
            page = int(inputs.get("page", 1))
            if page == 1:
                return _page(1, [{"id": 1}], 2)
            return _page(2, [{"id": 2}], 2, status="contract_changed_additive")

        with patch.object(self.client, "_execute_result", side_effect=execute):
            result = self.client.read_all("example.concurrent.list", max_workers=1)

        self.assertEqual("contract_changed_additive", result["status"])
        self.assertTrue(result["ok"])

    def test_page_info_schema_exposes_wire_fields(self) -> None:
        schema = self.client.schema("example.concurrent.list")
        self.assertEqual(
            {
                "kind": "page_info",
                "completeness": "complete",
                "pagination_evidence": "production",
                "page_field": "page",
                "page_size_field": "page_size",
                "total_page_field": "total_page",
                "list_path": "data.list",
                "page_info_path": "data.page_info",
                "default_page_size": 1,
                "max_page_size": 100,
            },
            schema["pagination"],
        )
        none_schema = self.client.schema("example.concurrent.detail")
        self.assertEqual("none", none_schema["pagination"]["kind"])
        self.assertEqual("page", none_schema["pagination"]["page_field"])


if __name__ == "__main__":
    unittest.main()
