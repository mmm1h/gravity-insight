from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.cli import build_parser
from gravity_sdk.agent_capabilities import composite_capability_cards
from gravity_sdk.agent_handoff import attach_plan_node
from gravity_sdk.errors import PaginationLimitError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_dashboard_adapter import (
    execute_dashboard_plan,
    validate_dashboard_plan,
)
from gravity_sdk.sdk import GravitySDK
from gravity_sdk.template_replay import (
    list_analysis_templates,
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
    def test_catalog_pagination_limit_uses_shared_caller_exit(self) -> None:
        with patch(
            "gravity_sdk.template_replay.call_read",
            side_effect=PaginationLimitError("catalog exceeded max_items"),
        ):
            result = list_analysis_templates(_Client(), scope="own")

        self.assertEqual("error", result["status"])
        self.assertEqual(2, result["exit_code"])
        self.assertEqual("PAGINATION_LIMIT", result["components"][0]["error"]["code"])

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
                    "groupByCreateTime": {"value": "day"},
                    "filterCondition": "and",
                    "splitEvent": [],
                    "splitEventOtherData": {},
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
        self.assertIn("config.originParams.groupByCreateTime", fields)
        self.assertIn("config.originParams.filterCondition", fields)
        self.assertIn("config.originParams.splitEvent", fields)
        self.assertIn("config.originParams.splitEventOtherData", fields)
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

    def test_cli_sdk_and_plan_share_the_governed_surface(self) -> None:
        args = build_parser().parse_args(
            [
                "analysis", "template", "run", "--scope", "internal",
                "--app", "main", "--ref", "template-1",
                "--start", "2026-08-01", "--end", "2026-08-02",
            ]
        )
        self.assertEqual("run", args.template_command)

        expected = {"schema_version": "gravity-insight.analysis-template-replay.v1"}
        sdk = GravitySDK(insight=object(), workspace=_workspace())
        with patch(
            "gravity_sdk.template_replay_surface.run_analysis_template",
            return_value=expected,
        ) as delegated:
            self.assertIs(
                expected,
                sdk.run_analysis_template(
                    "main", "template-1", scope="internal",
                    start="2026-08-01", end="2026-08-02",
                ),
            )
        self.assertEqual(101, delegated.call_args.kwargs["app"])

        request = {
            "name": "analysis_template", "scope": "internal", "app": "main",
            "ref": "template-1", "mode": "run",
            "start": "2026-08-01", "end": "2026-08-02",
        }
        context = AdapterContext(
            node_id="template", execution_id="test", kind="composite",
            workspace=_workspace(), output_fields=(), dynamic_targets=(),
            max_pages=2, max_items=10,
        )
        gap = {
            "schema_version": "gravity-insight.analysis-template-replay.v1",
            "ok": False, "status": "capability_gap", "exit_code": 2,
            "network_called": True, "definition_network_called": True,
            "query_executed": False,
            "template": {
                "scope": "internal", "id": "template-1", "name": "Template",
                "template_type": "report", "sub_type": "event",
                "modify_time": None, "replay_supported": False, "app_id": "101",
            },
            "artifact_mode": "origin_params", "kind": None,
            "operation_id": None,
            "date_range": {"start": "2026-08-01", "end": "2026-08-02", "inclusive": True},
            "date_override_applied": False, "limitations": [], "validation": None,
            "quarantine": [{
                "field": "config.originParams.queryItemList",
                "disposition": "quarantined",
                "reason": "formula_token_semantics_unproven",
            }],
            "next_action": "Keep this template non-executable.",
        }
        calls: list[dict] = []
        plan_sdk = SimpleNamespace(run_analysis_template=lambda *_args, **kwargs: calls.append(kwargs) or gap)
        validate_dashboard_plan(request, context, context.workspace)
        result = execute_dashboard_plan(plan_sdk, request, context)
        self.assertEqual(("capability_gap", 1), (result["status"], len(calls)))
        self.assertEqual(1, calls[0]["max_workers"])
        self.assertNotIn("config", result["template"])

    def test_agent_card_is_fillable_and_rejects_ui_or_write_intent(self) -> None:
        for query in ("run analysis template", "重放分析模板"):
            with self.subTest(query=query):
                cards = composite_capability_cards(query, domain=None, platform=None)
                self.assertEqual(["analysis_template"], [item["composite"] for item in cards])
                card = attach_plan_node(cards[0], query)
                self.assertEqual(
                    ["scope", "app", "ref", "start", "end"],
                    card["missing_inputs"],
                )
                self.assertEqual("analysis_template", card["plan_node"]["request"]["name"])
                self.assertFalse(card["natural_language_auto_execute"])
        for query in ("create analysis template", "分析模板分享权限", "saved analysis template"):
            with self.subTest(query=query):
                self.assertNotIn(
                    "analysis_template",
                    [item["composite"] for item in composite_capability_cards(
                        query, domain=None, platform=None
                    )],
                )


if __name__ == "__main__":
    unittest.main()
