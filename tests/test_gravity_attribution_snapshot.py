from __future__ import annotations

import unittest

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.attribution import (
    PERFORMANCE_OPERATION_ID,
    PERFORMANCE_PROFILES,
    attribution_performance,
    attribution_snapshot,
)
from gravity_sdk.domains import (
    ATTRIBUTION_PAGINATED_OPERATIONS,
    ATTRIBUTION_SNAPSHOT_OPERATIONS,
)
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_attribution_adapter import (
    execute_attribution_performance_plan,
    validate_attribution_performance_plan,
)


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

    def test_performance_uses_the_four_frontend_profiles_in_one_batch(self) -> None:
        def with_data(items):
            return [
                {
                    **item,
                    "data": {
                        "operation_id": item["operation_id"],
                        "status": "success",
                        "data": {"items": [], "total": []},
                    },
                }
                for item in items
            ]

        client = _Client(results=with_data)
        result = attribution_performance(
            client, "101", "2026-08-15", "2026-08-15", max_workers=3
        )

        requests, concurrency = client.calls[0]
        self.assertEqual((4, 3), (len(requests), concurrency))
        self.assertEqual(
            [profile[0] for profile in PERFORMANCE_PROFILES],
            [request["request_id"] for request in requests],
        )
        self.assertTrue(
            all(request["operation_id"] == PERFORMANCE_OPERATION_ID for request in requests)
        )
        for request, profile in zip(requests, PERFORMANCE_PROFILES, strict=True):
            _, metrics, dimensions, caliber = profile
            self.assertEqual(
                {
                    "app_id": 101,
                    "date_list": ["2026-08-15", "2026-08-15"],
                    "metrics_list": list(metrics),
                    "dims_list": list(dimensions),
                    "statistics_caliber": caliber,
                },
                request["inputs"],
            )
        self.assertEqual((4, "empty"), (result["source_count"], result["status"]))

    def test_performance_agent_handoff_and_call_bound_are_machine_decidable(self) -> None:
        result = discover_capabilities(
            "汇总上周各渠道的归因新增、激活和付费表现。", client=None
        )

        self.assertEqual((1, 1), (result["count"], result["total"]))
        card = result["candidates"][0]
        self.assertEqual("attribution_performance", card["composite"])
        self.assertEqual(["app", "start", "end"], card["missing_inputs"])
        self.assertEqual(
            "gravity.agent-call-bound.v1", card["call_bound"]["schema_version"]
        )
        self.assertEqual(
            (1, 2),
            (card["call_bound"]["known_inputs"], card["call_bound"]["unknown_capability"]),
        )
        self.assertEqual("attribution_performance", card["plan_node"]["request"]["name"])

    def test_performance_rejects_invalid_bounds_before_batch(self) -> None:
        for options in (
            {"app_id": "bad"},
            {"start": "2026-08-16", "end": "2026-08-15"},
            {"max_workers": 0},
        ):
            with self.subTest(options=options):
                client = _Client()
                values = {
                    "app_id": "101", "start": "2026-08-15",
                    "end": "2026-08-15", **options,
                }
                with self.assertRaises(InputValidationError):
                    attribution_performance(client, **values)
                self.assertEqual([], client.calls)

    def test_performance_plan_uses_the_global_worker_lease(self) -> None:
        class Workspace:
            def resolve_app(self, _value):
                return 101

        class SDK:
            def attribution_performance(self, *args, **kwargs):
                self.call = (args, kwargs)
                return {"schema_version": "gravity-insight.attribution-performance.v1"}

        workspace, sdk = Workspace(), SDK()
        context = AdapterContext(
            "node", "execution", "composite", workspace, (), (), 1, 100_000
        )
        request = {
            "name": "attribution_performance", "app": "main",
            "start": "2026-08-15", "end": "2026-08-15",
        }

        validate_attribution_performance_plan(request, context, workspace)
        result = execute_attribution_performance_plan(sdk, request, context)

        self.assertEqual("gravity-insight.attribution-performance.v1", result["schema_version"])
        self.assertEqual(1, sdk.call[1]["max_workers"])


if __name__ == "__main__":
    unittest.main()
