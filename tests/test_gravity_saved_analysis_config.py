from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk.analysis_spec import compile_query_spec
from gravity_sdk.dashboard_artifact import compile_dashboard_chart
from gravity_sdk.dashboard_artifact_contract import BODY_FIELDS, UI_FIELDS
from gravity_sdk.errors import UnsupportedOperationError
from gravity_sdk.saved_analysis_config import generate_saved_analysis_config
from gravity_sdk.workspace import Workspace, WorkspaceDefaults


def _workspace() -> Workspace:
    root = Path.cwd()
    return Workspace(
        path=None,
        root=root,
        state_root=root,
        apps={"main": 101},
        defaults=WorkspaceDefaults(
            app="main", timezone="Asia/Shanghai", time_window=None
        ),
        datasources={},
        products={},
        recipes={},
    )


def _metric(*, property_metric: bool = False) -> dict[str, str]:
    value = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    if property_metric:
        value["data_type"] = "INT"
    return value


def _step(event: str) -> dict[str, Any]:
    return {"event": event, "metric": _metric()}


class _Validator:
    @staticmethod
    def validate(_operation_id: str, _inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "valid_offline"}


def _semantic_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    normalized.pop("query_id", None)
    for key, empty in (
        ("custom_query_item_list", []),
        ("aggregate_config", {}),
        ("return_hierarchy_list", False),
        ("split_event", {}),
    ):
        if normalized.get(key) == empty:
            normalized.pop(key)
    return normalized


class SavedAnalysisConfigTests(unittest.TestCase):
    def test_five_subjects_generate_registered_semantic_round_trips(self) -> None:
        dated = {"app": "main", "start": "2026-08-01", "end": "2026-08-02"}
        cases = {
            "event": {
                **dated,
                "steps": [_step("open")],
                "time_grain": "day",
                "calculate_layer_y": True,
            },
            "funnel": {
                **dated,
                "steps": [_step("open"), _step("purchase")],
                "window": {"unit": "day", "value": 1},
                "calculate_each_day": True,
            },
            "retention": {
                **dated,
                "steps": [_step("open"), _step("return")],
                "offset": 11,
                "period_calc_method": "SUM",
                "custom_before_method": "SUM",
                "total_calc_type": "WEEK",
                "week_first_day": 2,
            },
            "property": {
                "app": "main",
                "property": _metric(property_metric=True),
            },
            "scatter": {
                **dated,
                "steps": [_step("purchase")],
                "time_grain": "day",
            },
        }
        subjects = {
            "event": "analysis_event",
            "funnel": "analysis_funnel",
            "retention": "analysis_retention",
            "property": "analysis_user_property",
            "scatter": "analysis_scatter",
        }
        for kind, spec in cases.items():
            with self.subTest(kind=kind):
                direct = compile_query_spec(kind, spec, workspace=_workspace())
                config = generate_saved_analysis_config(
                    kind, spec, workspace=_workspace(), app="101"
                )
                self.assertEqual(
                    set(config), set(config) & UI_FIELDS[kind]
                )
                self.assertEqual(
                    set(config["calculateBody"]),
                    set(config["calculateBody"]) & BODY_FIELDS[kind],
                )
                if kind == "event":
                    self.assertEqual(101, config["calculateBody"]["app_id"])
                    self.assertEqual([], config["calculateBody"]["custom_query_item_list"])
                replay = compile_dashboard_chart(
                    _Validator(),
                    {
                        "report_id": "local",
                        "name": "generated",
                        "subject": subjects[kind],
                        "config": config,
                    },
                    app_id="101",
                    start="2026-08-01",
                    end="2026-08-02",
                )
                self.assertEqual(
                    _semantic_inputs(direct.inputs),
                    _semantic_inputs(replay.inputs),
                )

    def test_non_reversible_compact_controls_fail_before_mutation(self) -> None:
        dated = {"app": "main", "start": "2026-08-01", "end": "2026-08-02"}
        cases = {
            "event": {**dated, "steps": [_step("open")]},
            "retention": {
                **dated,
                "steps": [_step("open"), _step("return")],
                "offset": 7,
                "period_calc_method": "SUM",
                "custom_before_method": "SUM",
                "total_calc_type": "DAY",
                "week_first_day": 1,
                "group_by": [{"field": "$os", "source": "user"}],
            },
            "scatter": {**dated, "steps": [_step("purchase")]},
        }
        for kind, spec in cases.items():
            with self.subTest(kind=kind), self.assertRaises(UnsupportedOperationError):
                generate_saved_analysis_config(
                    kind, spec, workspace=_workspace(), app="101"
                )


if __name__ == "__main__":
    unittest.main()
