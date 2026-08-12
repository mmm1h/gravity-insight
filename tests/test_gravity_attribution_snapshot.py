from __future__ import annotations

import unittest

from gravity_sdk.attribution import attribution_snapshot
from gravity_sdk.domains import (
    ATTRIBUTION_PAGINATED_OPERATIONS,
    ATTRIBUTION_SNAPSHOT_OPERATIONS,
)
from gravity_sdk.errors import InputValidationError


class _Client:
    def __init__(self, *, fail_operation: str | None = None, results=None) -> None:
        self.fail_operation = fail_operation
        self.results = results
        self.calls: list[tuple[list[dict], int]] = []

    def batch(self, requests, concurrency=6):
        values = [dict(item) for item in requests]
        self.calls.append((values, concurrency))
        results = [
            {
                "operation_id": item["operation_id"],
                "request_id": item["request_id"],
                "ok": item["operation_id"] != self.fail_operation,
                "status": (
                    "success" if item["operation_id"] != self.fail_operation else "error"
                ),
                **(
                    {}
                    if item["operation_id"] != self.fail_operation
                    else {
                        "error": {
                            "category": "upstream",
                            "code": "UPSTREAM_UNAVAILABLE",
                        }
                    }
                ),
            }
            for item in values
        ]
        return self.results(results) if self.results is not None else results


class AttributionSnapshotTests(unittest.TestCase):
    def test_snapshot_covers_all_stable_operations_with_only_two_paged_reads(self) -> None:
        self.assertEqual(8, len(ATTRIBUTION_SNAPSHOT_OPERATIONS))
        self.assertEqual(
            {
                "attribution.postback_map.list",
                "attribution.postback_map_collect.list",
            },
            set(ATTRIBUTION_PAGINATED_OPERATIONS),
        )
        client = _Client()

        result = attribution_snapshot(client, "101", concurrency=8)

        self.assertEqual("gravity-insight.attribution-snapshot.v1", result["schema_version"])
        self.assertEqual(8, result["operation_count"])
        self.assertEqual(2, result["paginated_operation_count"])
        self.assertEqual(8, result["success_count"])
        requests, concurrency = client.calls[0]
        self.assertEqual(8, concurrency)
        self.assertEqual(
            list(ATTRIBUTION_SNAPSHOT_OPERATIONS),
            [item["operation_id"] for item in requests],
        )
        self.assertTrue(all(item["inputs"] == {"app_id": "101"} for item in requests))
        self.assertEqual(
            set(ATTRIBUTION_PAGINATED_OPERATIONS),
            {item["operation_id"] for item in requests if item["read_all"]},
        )

    def test_snapshot_preserves_partial_results_and_aggregates_exit_code(self) -> None:
        failed = ATTRIBUTION_SNAPSHOT_OPERATIONS[3]
        result = attribution_snapshot(
            _Client(fail_operation=failed), "101", concurrency=4
        )

        self.assertFalse(result["ok"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(7, result["success_count"])
        self.assertEqual(1, result["failure_count"])
        self.assertEqual(3, result["exit_code"])
        self.assertEqual(
            list(ATTRIBUTION_SNAPSHOT_OPERATIONS),
            [item["operation_id"] for item in result["results"]],
        )

    def test_empty_and_short_batch_results_become_local_missing_failures(self) -> None:
        empty = attribution_snapshot(
            _Client(results=lambda _items: []), "101", concurrency=4
        )
        self.assertEqual(empty["operation_count"], empty["total_count"])
        self.assertEqual(8, empty["failure_count"])
        self.assertEqual(4, empty["exit_code"])
        self.assertTrue(
            all(
                item["error"]["code"] == "BATCH_RESULT_MISSING"
                for item in empty["results"]
            )
        )

        short = attribution_snapshot(
            _Client(results=lambda items: items[:2]), "101", concurrency=4
        )
        self.assertEqual(short["operation_count"], short["total_count"])
        self.assertEqual(2, short["success_count"])
        self.assertEqual(6, short["failure_count"])
        self.assertEqual(
            list(ATTRIBUTION_SNAPSHOT_OPERATIONS),
            [item["operation_id"] for item in short["results"]],
        )

    def test_reordered_batch_results_are_joined_to_the_declared_order(self) -> None:
        result = attribution_snapshot(
            _Client(results=lambda items: list(reversed(items))), "101", concurrency=4
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["operation_count"], result["total_count"])
        self.assertEqual(
            list(ATTRIBUTION_SNAPSHOT_OPERATIONS),
            [item["operation_id"] for item in result["results"]],
        )

    def test_duplicate_and_unknown_batch_identities_are_rejected_without_echo(self) -> None:
        duplicate = _Client(results=lambda items: [*items, items[0]])
        with self.assertRaisesRegex(RuntimeError, "invalid result identity") as raised:
            attribution_snapshot(duplicate, "101")
        self.assertNotIn(ATTRIBUTION_SNAPSHOT_OPERATIONS[0], str(raised.exception))

        def unknown(items):
            items[0] = {
                **items[0],
                "operation_id": "secret.unknown.operation",
                "request_id": "secret-request",
            }
            return items

        with self.assertRaisesRegex(RuntimeError, "invalid result identity") as raised:
            attribution_snapshot(_Client(results=unknown), "101")
        self.assertNotIn("secret", str(raised.exception))

    def test_app_id_requires_a_positive_integer_before_batch_execution(self) -> None:
        for invalid in ("alias", "-1", -1, 0, True, ""):
            with self.subTest(app_id=invalid):
                client = _Client()
                with self.assertRaises(InputValidationError) as raised:
                    attribution_snapshot(client, invalid)
                self.assertEqual([], client.calls)
                self.assertEqual(
                    "attribution snapshot app_id must be a positive integer",
                    str(raised.exception),
                )


if __name__ == "__main__":
    unittest.main()
