from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk.template_replay import (
    prepare_analysis_template,
    run_analysis_template,
)
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


class _Client:
    def __init__(self) -> None:
        self.validations: list[tuple[str, dict]] = []

    def validate(self, operation_id: str, inputs: dict) -> dict:
        self.validations.append((operation_id, inputs))
        return {"ok": True, "status": "valid_offline"}


def _template(config: dict, *, sub_type: str = "event") -> dict:
    return {
        "id": "template-1",
        "name": "Synthetic template",
        "template_type": "report",
        "sub_type": sub_type,
        "modify_time": "2026-08-01",
        "config": config,
    }


def _catalog(item: dict) -> dict:
    return {
        "ok": True,
        "status": "success",
        "data": {
            "list": [item],
            "page_info": {"page": 1, "page_size": 1, "total_page": 1},
        },
    }


class AnalysisTemplateReplayTests(unittest.TestCase):
    def test_compact_template_compiles_and_executes_once(self) -> None:
        item = _template(
            {
                "steps": [
                    {
                        "event": "purchase",
                        "metric": {
                            "field": "PresetAllCount",
                            "aggregation": "PresetAllCount",
                        },
                    }
                ],
                "time_grain": "day",
            }
        )
        client = _Client()
        with (
            patch(
                "gravity_sdk.template_replay.call_read",
                return_value=_catalog(item),
            ) as catalog_read,
            patch(
                "gravity_sdk.saved_analysis_result.call_read",
                return_value={
                    "schema_version": "gravity-insight.read.v1",
                    "operation_id": "analysis.event.query",
                    "ok": True,
                    "status": "success",
                    "data": {"list": []},
                    "error": None,
                },
            ) as query_read,
        ):
            result = run_analysis_template(
                client,
                scope="internal",
                reference={"id": "template-1"},
                app="main",
                start="2026-08-01",
                end="2026-08-02",
                workspace=_workspace(),
            )

        self.assertTrue(result["ok"])
        self.assertEqual("compact_spec", result["artifact_mode"])
        self.assertTrue(result["query_executed"])
        self.assertEqual([], result["quarantine"])
        self.assertEqual(1, catalog_read.call_count)
        self.assertEqual(1, query_read.call_count)
        self.assertEqual("101", client.validations[0][1]["app_id"])

    def test_origin_params_reports_each_unproven_part_without_query(self) -> None:
        item = _template(
            {
                "events": [],
                "user_properties": [],
                "originParams": {
                    "Filtering": [{"conditionList": []}],
                    "queryItemList": [{"formulaArr": []}],
                    "groupBy": [{"value": "field"}],
                    "splitEvent": [],
                    "compareList": [{"resultDate": ["start", "end"]}],
                    "dateListFormModel": {"resultDate": ["start", "end"]},
                    "date_extra_data": {"date": ["start", "end"]},
                },
            }
        )
        client = _Client()
        with (
            patch(
                "gravity_sdk.template_replay.call_read",
                return_value=_catalog(item),
            ) as catalog_read,
            patch("gravity_sdk.saved_analysis_result.call_read") as query_read,
        ):
            result = run_analysis_template(
                client,
                scope="internal",
                reference="Synthetic template",
                app="main",
                start="2026-08-01",
                end="2026-08-02",
                workspace=_workspace(),
            )

        fields = {item["field"] for item in result["quarantine"]}
        reasons = {item["reason"] for item in result["quarantine"]}
        self.assertFalse(result["ok"])
        self.assertEqual("capability_gap", result["status"])
        self.assertFalse(result["query_executed"])
        self.assertIn("config.originParams.queryItemList", fields)
        self.assertIn("config.originParams.compareList", fields)
        self.assertIn("period_compare_owned_by_separate_capability", reasons)
        self.assertEqual(1, catalog_read.call_count)
        query_read.assert_not_called()
        self.assertEqual([], client.validations)

    def test_unknown_compact_field_is_quarantined(self) -> None:
        item = _template(
            {
                "steps": [
                    {
                        "event": "purchase",
                        "metric": {
                            "field": "PresetAllCount",
                            "aggregation": "PresetAllCount",
                        },
                    }
                ],
                "future_semantic": {"private": "not returned"},
            }
        )
        with patch(
            "gravity_sdk.template_replay.call_read", return_value=_catalog(item)
        ):
            result = prepare_analysis_template(
                _Client(),
                scope="internal",
                reference={"id": "template-1"},
                app="main",
                start="2026-08-01",
                end="2026-08-02",
                workspace=_workspace(),
            )

        self.assertEqual("capability_gap", result["status"])
        self.assertEqual("config", result["quarantine"][0]["field"])
        self.assertNotIn("private", str(result))


if __name__ == "__main__":
    unittest.main()
