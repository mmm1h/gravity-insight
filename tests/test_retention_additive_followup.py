from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from gravity_insight._field_policy_analysis import validate_analysis_shape
from gravity_insight._field_policy_retention import (
    RetentionAdditiveFollowupUnavailableError,
)
from gravity_insight._field_policy_shared import (
    RETENTION_ADDITIVE_FOLLOWUP_GAP_CODE,
)
from gravity_insight.analysis_spec import compile_query_spec, prepare_query_spec
from gravity_insight.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/retention_additive_followup.json").read_text(
        encoding="utf-8"
    )
)


class CountingInsight:
    def __init__(self, result: Mapping[str, Any] | None = None) -> None:
        self.result = deepcopy(result) if result is not None else None
        self.validations: list[tuple[str, Mapping[str, Any]]] = []
        self.reads: list[tuple[str, Mapping[str, Any]]] = []

    def validate(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.validations.append((operation_id, inputs))
        return {"ok": True, "status": "valid", "live_metadata_dependencies": []}

    def read(
        self, operation_id: str, inputs: Mapping[str, Any], **_options: Any
    ) -> dict[str, Any]:
        self.reads.append((operation_id, inputs))
        if self.result is None:
            raise AssertionError("preflight gap must stop before read")
        return deepcopy(self.result)


class RetentionAdditiveFollowupTests(unittest.TestCase):
    def test_before_after_sumcount_preflight_returns_named_aggregate_only_gap(
        self,
    ) -> None:
        insight = CountingInsight()

        gap = prepare_query_spec(
            insight,
            "retention",
            FIXTURES["before_after_sumcount"],
            app=101,
        )

        self.assertEqual(
            (
                False,
                "capability_gap",
                RETENTION_ADDITIVE_FOLLOWUP_GAP_CODE,
                "query_item_before_after.after.target.name",
                False,
            ),
            (
                gap["ok"],
                gap["status"],
                gap["code"],
                gap["field"],
                gap["network_called"],
            ),
        )
        self.assertEqual(
            {"projection": "aggregate_only", "user_level_rows": False},
            gap["privacy"],
        )
        self.assertEqual([], insight.validations)
        self.assertEqual([], insight.reads)
        self.assertNotIn("fixture-private-value", repr(gap))
        self.assertIn("Ordinary two-event Retention", gap["reason"])
        self.assertIn("rejecting component is not known", gap["reason"])
        self.assertIn("Do not retry", gap["next_action"])

    def test_both_sumcount_shapes_raise_typed_non_retryable_error_before_sdk_io(
        self,
    ) -> None:
        for fixture_name, field in (
            (
                "before_after_sumcount",
                "query_item_before_after.after.target.name",
            ),
            ("second_step_sumcount", "query_item_list[1].target.name"),
        ):
            insight = CountingInsight()
            sdk = GravitySDK(insight=insight, workspace="examples/workspace")
            with self.subTest(fixture=fixture_name), self.assertRaises(
                RetentionAdditiveFollowupUnavailableError
            ) as caught:
                sdk.analysis_query(
                    "retention", FIXTURES[fixture_name], app="demo"
                )
            detail = caught.exception.to_error_detail(
                operation_id="analysis.retention.query"
            )
            self.assertEqual(
                (RETENTION_ADDITIVE_FOLLOWUP_GAP_CODE, "local", field, False),
                (detail.code, detail.category, detail.field, detail.retryable),
            )
            self.assertEqual([], insight.validations)
            self.assertEqual([], insight.reads)

    def test_raw_second_step_sumcount_hits_the_same_preflight(self) -> None:
        ordinary = compile_query_spec(
            "retention", FIXTURES["ordinary_count"], app=101
        ).inputs
        raw = deepcopy(ordinary)
        raw["query_item_list"][1]["target"] = {
            "field": "pay_amount",
            "name": "SumCount",
        }

        with self.assertRaises(
            RetentionAdditiveFollowupUnavailableError
        ) as caught:
            validate_analysis_shape("retention", raw)

        self.assertEqual("query_item_list[1].target.name", caught.exception.field)

    def test_legal_zero_count_is_measured_while_sumcount_is_unmeasured(self) -> None:
        insight = CountingInsight(FIXTURES["ordinary_zero_response"])
        result = GravitySDK(
            insight=insight, workspace="examples/workspace"
        ).analysis_query("retention", FIXTURES["ordinary_count"], app="demo")
        measured_zero = result["data"]["y"]["2026-08-01"][0]["values"][1]

        gap = prepare_query_spec(
            CountingInsight(),
            "retention",
            FIXTURES["second_step_sumcount"],
            app=101,
        )

        self.assertEqual(0, measured_zero)
        self.assertEqual("measured", result["interpretation"]["count_measurement"]["status"])
        self.assertEqual(
            {"status": "unmeasured", "value": None},
            {
                "status": gap["measurement"]["status"],
                "value": gap["measurement"]["value"],
            },
        )
        additive = result["interpretation"]["additive_followup_measurement"]
        self.assertIs(False, additive["zero_means_measured_zero"])
        self.assertIs(False, additive["candidate_paths_verified"])
        self.assertEqual(1, len(insight.validations))
        self.assertEqual(1, len(insight.reads))


if __name__ == "__main__":
    unittest.main()
