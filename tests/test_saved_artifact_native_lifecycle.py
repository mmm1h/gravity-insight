from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight.dashboard_analysis import (
    prepare_dashboard_analysis,
    run_dashboard_analysis,
)
from gravity_insight.dashboard_conditions import SOURCE_OPERATION
from gravity_insight.dashboard_snapshot import TREE_OPERATION
from gravity_insight.domains import ANALYSIS_QUERY_OPERATIONS
from gravity_insight.kanban_mutation_contracts import DASHBOARD_UPDATE, DETAIL
from gravity_insight.kanban_report_link_mutation import link_reports
from gravity_insight.saved_analysis import (
    execute_saved_analysis,
    prepare_saved_analysis,
)
from gravity_insight.saved_analysis_catalog import GET_OPERATION_ID
from gravity_insight.saved_analysis_mutation import (
    UPDATE_OPERATION_ID,
    create_saved_analysis,
)
from gravity_insight.workspace import Workspace, WorkspaceDefaults


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


def _event(name: str, index: int) -> dict[str, Any]:
    return {
        "cond_logic": "AND",
        "conditions": [],
        "custom_name": name,
        "event_index": index,
        "event_label": name,
        "event_name": name,
        "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
    }


def _native_event_config() -> dict[str, Any]:
    return {
        "calculateBody": {
            "app_id": 101,
            "custom_query_item_list": [{
                "custom_name": "formula metric",
                "decimal_point": "two_point",
                "event_index": 1,
                "formula": "x1",
                "query_item_list": [_event("formula operand", 0)],
            }],
            "date_list": [{
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            }],
            "global_cond_logic": "AND",
            "global_conditions": [],
            "group_by_list": [],
            "query_item_list": [_event("base metric", 0)],
        },
        "compareList": [{
            "date_list": {"date_list": ["2026-06-01", "2026-06-02"]},
            "kid": "comparison-1",
        }],
        "currentSelectCompare": 0,
        "date_list": [{
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
        }],
        "tableShowType": "table",
    }


class _LifecycleClient:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.dashboard = {
            "id": 30,
            "app_id": 101,
            "space_id": 10,
            "name": "SDK Dashboard | GSDK-aabbccddeeff",
            "ui_config": "[]",
            "even_report": [],
        }

    def _preview_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "request": {"inputs": copy.deepcopy(dict(inputs))},
            "network_called": False,
        }

    def _execute_mutation(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        if operation_id == UPDATE_OPERATION_ID:
            self.saved = [{
                **copy.deepcopy(dict(inputs)),
                "id": "saved-1",
                "create_time": "2026-08-01T00:00:00Z",
                "modify_time": "2026-08-01T00:00:00Z",
                "create_user_id": 7,
                "create_user_name": "owner",
                "update_user_id": 7,
                "update_user_name": "owner",
            }]
        elif operation_id == DASHBOARD_UPDATE:
            self.dashboard["ui_config"] = inputs["ui_config"]
            reports = []
            for index, linked in enumerate(inputs["report_list"]):
                saved = next(
                    item
                    for item in self.saved
                    if item["id"] == str(linked["report_id"])
                )
                reports.append({
                    "id": 100 + index,
                    "report_id": saved["id"],
                    "name": saved["name"],
                    "subject": saved["subject"],
                    "config": json.loads(saved["config"]),
                })
            self.dashboard["even_report"] = reports
        else:
            raise AssertionError(f"unexpected mutation: {operation_id}")
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
            "data": {"object": {"id": "saved-1", "app_id": 101}},
        }

    def read_all(
        self, _operation_id: str, _inputs: Mapping[str, Any], **_options: Any
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success" if self.saved else "empty",
            "data": {"list": copy.deepcopy(self.saved)},
            "error": None,
        }

    def read(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        if operation_id == GET_OPERATION_ID:
            row = next(item for item in self.saved if item["id"] == str(inputs["id"]))
            return {"ok": True, "status": "success", "data": copy.deepcopy(row)}
        if operation_id == TREE_OPERATION:
            return {
                "ok": True,
                "status": "success",
                "data": [{
                    "id": 10,
                    "name": "SDK Space | GSDK-aabbccddeeff",
                    "folder_or_dashboard": [{
                        "id": 30,
                        "name": self.dashboard["name"],
                        "space_id": 10,
                    }],
                }],
            }
        if operation_id == SOURCE_OPERATION:
            return {
                "ok": True,
                "status": "success",
                "data": {"object": {"config": {"filter": []}}},
            }
        if operation_id == DETAIL:
            return {
                "ok": True,
                "status": "success",
                "data": copy.deepcopy(self.dashboard),
            }
        if operation_id == ANALYSIS_QUERY_OPERATIONS["event"]:
            return {
                "ok": True,
                "status": "success",
                "operation_id": operation_id,
                "data": {"list": [{"value": 7}]},
                "error": None,
            }
        raise AssertionError(f"unexpected read: {operation_id}")

    @staticmethod
    def validate(operation_id: str, _inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "needs_live_metadata",
            "operation_id": operation_id,
            "live_metadata_dependencies": ["analysis.event.list"],
        }

    def batch(
        self,
        requests: list[Mapping[str, Any]],
        *,
        max_workers: int,
        max_pages: int,
        max_total_items: int,
    ) -> list[dict[str, Any]]:
        self.batch_options = (max_workers, max_pages, max_total_items)
        return [{
            "operation_id": request["operation_id"],
            "request_id": request["request_id"],
            "ok": True,
            "status": "success",
            "data": {
                "schema_version": "gravity-insight.read.v1",
                "operation_id": request["operation_id"],
                "status": "success",
                "data": {"list": [{"value": 7}]},
            },
            "error": None,
        } for request in requests]

    @staticmethod
    def _current_principal_id() -> str:
        return "7"


class NativeSavedArtifactLifecycleTests(unittest.TestCase):
    def test_create_prepare_run_link_and_dashboard_run(self) -> None:
        client = _LifecycleClient()
        common = {
            "app_id": 101,
            "name": "native multi metric",
            "subject": "analysis_event",
            "config": _native_event_config(),
            "workspace": _workspace(),
            "start": "2026-08-01",
            "end": "2026-08-02",
        }

        created = create_saved_analysis(client, **common, execute=True)
        prepared = prepare_saved_analysis(
            client,
            app="main",
            reference=created["target"]["id"],
            workspace=_workspace(),
            start="2026-08-01",
            end="2026-08-02",
        )
        replayed = execute_saved_analysis(
            client,
            app="main",
            reference=created["target"]["id"],
            workspace=_workspace(),
            start="2026-08-01",
            end="2026-08-02",
        )
        linked = link_reports(
            client,
            app_id=101,
            space_id=10,
            dashboard_id=30,
            report_ids=[created["target"]["id"]],
            execute=True,
        )
        dashboard_prepared = prepare_dashboard_analysis(
            client,
            101,
            30,
            start="2026-08-01",
            end="2026-08-02",
        )
        dashboard_run = run_dashboard_analysis(
            client,
            101,
            30,
            start="2026-08-01",
            end="2026-08-02",
        )

        self.assertEqual("created", created["status"])
        self.assertEqual("compiled", prepared["status"])
        self.assertTrue(replayed["query_executed"])
        self.assertEqual("updated", linked["status"])
        self.assertEqual((1, 1, 0), (
            dashboard_prepared["chart_count"],
            dashboard_prepared["supported_count"],
            dashboard_prepared["unsupported_count"],
        ))
        self.assertEqual(("success", 1, 0), (
            dashboard_run["status"],
            dashboard_run["success_count"],
            dashboard_run["failure_count"],
        ))
        self.assertTrue(dashboard_run["charts"][0]["query_executed"])


if __name__ == "__main__":
    unittest.main()
