from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Callable

from gravity_insight.drift import ProjectionDrift, projection_drift_status
from gravity_insight.executor import _project
from gravity_insight.models import OperationSpec


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_insight" / "contracts" / "operations"


def _contract(operation_id: str) -> dict[str, Any]:
    path = CONTRACT_ROOT / f"{operation_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))["operation"]


def _operation(operation_id: str) -> OperationSpec:
    return OperationSpec.from_dict(_contract(operation_id))


class AnalysisResponseDriftDeclarationTests(unittest.TestCase):
    def test_every_evidence_supported_batch_field_has_the_correct_declaration(self) -> None:
        item_keys = {
            "analysis.monetization_detail.list": {
                "AdCid",
                "AdClickTime",
                "AdGid",
                "CSite",
                "Channel",
                "LatestLoginDay",
                "Version",
                "id",
                "modify_time",
            },
            "analysis.order_detail.list": {
                "user$pay_amount_sum",
                "user$pay_max_amount",
            },
        }
        data_keys = {
            "analysis.event.query": {"filter_agg_type"},
            "analysis.scatter.query": {
                "aggregate_by_date",
                "aggregate_date_group",
                "date_list",
                "total",
                "x",
                "y",
            },
            "analysis.segment.evaluate_percent": {"zone_offset"},
        }
        omitted_data_keys = {
            "analysis.default_val.list": {"Android"},
            "analysis.segment.evaluate_percent": {"extra_data"},
        }

        for operation_id, expected in item_keys.items():
            with self.subTest(operation_id=operation_id, declaration="item_keys"):
                projection = _contract(operation_id)["response_projection"]
                self.assertLessEqual(expected, set(projection["item_keys"]))
        for operation_id, expected in data_keys.items():
            with self.subTest(operation_id=operation_id, declaration="data_keys"):
                projection = _contract(operation_id)["response_projection"]
                self.assertLessEqual(expected, set(projection["data_keys"]))
        for operation_id, expected in omitted_data_keys.items():
            with self.subTest(
                operation_id=operation_id, declaration="known_omitted_data_keys"
            ):
                projection = _contract(operation_id)["response_projection"]
                self.assertLessEqual(
                    expected, set(projection["known_omitted_data_keys"])
                )

        event_paths = _contract("analysis.event.info")["response_projection"][
            "data_path_item_keys"
        ]
        for path in (
            "properties.common",
            "properties.custom",
            "properties.preset",
        ):
            with self.subTest(operation_id="analysis.event.info", path=path):
                self.assertIn("remark", event_paths[path])

    def test_unknown_shape_top_level_containers_are_acknowledged_and_omitted(self) -> None:
        cases: tuple[
            tuple[str, dict[str, Any], str, Callable[[dict[str, Any]], None]], ...
        ] = (
            (
                "analysis.default_val.list",
                {"api": [], "cocoscreator": [], "Android": []},
                "Android",
                lambda projected: self.assertEqual(
                    {"api": [], "cocoscreator": []}, projected
                ),
            ),
            (
                "analysis.segment.evaluate_percent",
                {
                    "part": 1,
                    "percent": 0.5,
                    "total": 2,
                    "extra_data": {"uncontracted": []},
                    "zone_offset": "+08:00",
                },
                "extra_data",
                lambda projected: self.assertEqual(
                    {"part": 1, "percent": 0.5, "total": 2, "zone_offset": "+08:00"},
                    projected,
                ),
            ),
        )

        for operation_id, data, omitted, assert_projected in cases:
            with self.subTest(operation_id=operation_id):
                projected, _warnings, drift, audit = _project(
                    _operation(operation_id), {"data": data}, {}
                )
                self.assertIs(ProjectionDrift.NONE, drift)
                self.assertIsNone(audit)
                self.assertNotIn(omitted, projected)
                assert_projected(projected)

    def test_dynamic_nested_fields_without_contract_vocabulary_remain_audited(self) -> None:
        cases = (
            (
                "analysis.funnel.query",
                {
                    "aggregate_date": {"group": {"2026-09-04": {}}},
                    "window_funnel_mode": 4,
                },
                "/data/aggregate_date/group/2026-09-04",
            ),
            (
                "analysis.scatter.query",
                {"aggregate_date": [], "zone_tags": {"unit": "day"}},
                "/data/zone_tags/unit",
            ),
        )

        for operation_id, data, expected_path in cases:
            with self.subTest(operation_id=operation_id):
                _projected, _warnings, drift, audit = _project(
                    _operation(operation_id), {"data": data}, {}
                )
                self.assertIs(ProjectionDrift.ADDITIVE, drift)
                self.assertEqual(
                    [expected_path],
                    [field["path"] for field in audit["fields"]],
                )

    def test_declared_container_still_rejects_non_json_values_as_contract_changed(self) -> None:
        projected, _warnings, drift, _audit = _project(
            _operation("analysis.scatter.query"),
            {
                "data": {
                    "aggregate_date": [],
                    "zone_tags": {},
                    "x": [float("nan")],
                }
            },
            {},
        )

        self.assertIs(ProjectionDrift.BREAKING, drift)
        self.assertEqual("contract_changed", projection_drift_status(drift))
        self.assertEqual([], projected["x"])


if __name__ == "__main__":
    unittest.main()
