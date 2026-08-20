from __future__ import annotations

import copy
import unittest

from gravity_sdk.material_performance_result import (
    product_envelope as material_envelope,
)
from gravity_sdk.promotion_performance_result import (
    product_envelope as promotion_envelope,
)


def _success(status: str = "success") -> dict[str, object]:
    return {
        "platform": "tencent",
        "ok": True,
        "status": status,
        "error": None,
    }


def _failure(
    status: str, code: str, category: str
) -> dict[str, object]:
    return {
        "platform": "tencent",
        "ok": False,
        "status": status,
        "error": {
            "code": code,
            "category": category,
            "message": f"controlled {category} failure",
        },
    }


def _material(results: list[dict[str, object]]) -> dict[str, object]:
    return material_envelope(
        copy.deepcopy(results),
        app_count=1,
        window=("2026-08-01", "2026-08-02"),
        platforms=("tencent",),
        max_pages=2,
        max_items=10,
        max_workers=1,
        returned_items=0,
    )


def _promotion(results: list[dict[str, object]]) -> dict[str, object]:
    return promotion_envelope(
        copy.deepcopy(results),
        app_id="test-app",
        window=("2026-08-01", "2026-08-02"),
        platforms=("tencent",),
        metric_count=1,
        max_pages=2,
        max_items=10,
        max_workers=1,
        returned_items=0,
    )


class ComponentAggregateCharacterizationTests(unittest.TestCase):
    def test_material_and_promotion_aggregate_statuses_are_equivalent(self):
        cases = (
            ([], "empty"),
            ([_success()], "success"),
            ([_success("empty")], "empty"),
            ([_success("empty"), _success()], "success"),
            ([_failure("error", "UPSTREAM_UNAVAILABLE", "upstream")], "error"),
            (
                [_success(), _failure("error", "UPSTREAM_UNAVAILABLE", "upstream")],
                "partial",
            ),
            (
                [_success(), _failure("contract_changed", "CONTRACT_CHANGED", "local")],
                "contract_changed",
            ),
        )
        aggregate_fields = (
            "ok",
            "status",
            "exit_code",
            "total_count",
            "success_count",
            "failure_count",
        )
        for results, expected_status in cases:
            with self.subTest(expected_status=expected_status, results=results):
                material = _material(results)
                promotion = _promotion(results)
                self.assertEqual(expected_status, material["status"])
                self.assertEqual(
                    {field: material[field] for field in aggregate_fields},
                    {field: promotion[field] for field in aggregate_fields},
                )

    def test_material_and_promotion_choose_the_same_highest_exit_error(self):
        results = [
            _failure("error", "INPUT_INVALID", "caller"),
            _failure("error", "UPSTREAM_UNAVAILABLE", "upstream"),
            _failure("error", "LOCAL_IO_ERROR", "local"),
        ]
        material = _material(results)
        promotion = _promotion(results)
        self.assertEqual((4, "LOCAL_IO_ERROR"), (
            material["exit_code"], material["error"]["code"]
        ))
        self.assertEqual(
            (material["exit_code"], material["error"]),
            (promotion["exit_code"], promotion["error"]),
        )


if __name__ == "__main__":
    unittest.main()
