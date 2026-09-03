from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from gravity_insight.cli import build_parser
from gravity_insight.errors import InputValidationError
from gravity_insight.kanban_board_plan import prepare_kanban_board
from gravity_insight.kanban_mutation import kanban_mutation_schema
from gravity_insight.saved_analysis_artifact import preflight_saved_definition
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


def _config(*, grain: str = "day") -> dict[str, Any]:
    return {
        "start": "2026-08-01",
        "end": "2026-08-02",
        "time_grain": grain,
        "calculate_layer_y": True,
        "steps": [
            {
                "event": "purchase",
                "metric": {
                    "field": "PresetAllCount",
                    "aggregation": "PresetAllCount",
                },
            }
        ],
    }


def _saved(index: int, **updates: Any) -> dict[str, Any]:
    value = {
        "key": f"chart-{index}",
        "name": f"Chart {index}",
        "subject": "analysis_event",
        "config": _config(),
    }
    value.update(updates)
    return value


def _new_request(chart_count: int, note_count: int) -> dict[str, Any]:
    return {
        "app_id": 101,
        "target": {
            "mode": "new",
            "space_id": 10,
            "folder_id": 0,
            "name": "K87 board",
            "idempotency_key": "k87-board",
        },
        "saved_definitions": [_saved(index) for index in range(chart_count)],
        "notes": [
            {
                "title": f"Note {index}",
                "content": f"Context {index}",
                "idempotency_key": f"note-{index}",
            }
            for index in range(note_count)
        ],
    }


class _Client:
    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        dashboard: dict[str, Any] | None = None,
    ) -> None:
        self.rows = copy.deepcopy(rows or [])
        self.dashboard = copy.deepcopy(dashboard)
        self.read_calls: list[tuple[str, dict[str, Any]]] = []
        self.preview_calls: list[tuple[str, dict[str, Any]]] = []
        self.mutation_calls: list[tuple[str, dict[str, Any]]] = []

    def read_all(
        self, operation_id: str, inputs: dict[str, Any], **_options: Any
    ) -> dict[str, Any]:
        self.read_calls.append((operation_id, copy.deepcopy(inputs)))
        return {
            "ok": True,
            "status": "empty" if not self.rows else "success",
            "data": {"list": copy.deepcopy(self.rows)},
            "error": None,
            "truncated": False,
            "next_page_input": None,
        }

    def read(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.read_calls.append((operation_id, copy.deepcopy(inputs)))
        if operation_id.endswith("dashboard.tree"):
            return {
                "ok": True,
                "status": "success",
                "data": [
                    {"id": 10, "name": "Space", "folder_or_dashboard": []}
                ],
            }
        if operation_id.endswith("dashboard.detail"):
            if self.dashboard is None:
                raise AssertionError("unexpected dashboard detail read")
            return {
                "ok": True,
                "status": "success",
                "data": copy.deepcopy(self.dashboard),
            }
        selected = next(
            row for row in self.rows if str(row["id"]) == str(inputs["id"])
        )
        return {
            "ok": True,
            "status": "success",
            "data": copy.deepcopy(selected),
            "error": None,
        }

    @staticmethod
    def _current_principal_id() -> str:
        return "7"

    def _preview_mutation(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> None:
        self.preview_calls.append((operation_id, copy.deepcopy(inputs)))
        raise AssertionError("board preparation previewed a mutation")

    def _execute_mutation(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> None:
        self.mutation_calls.append((operation_id, copy.deepcopy(inputs)))
        raise AssertionError("board preparation executed a mutation")


class KanbanBoardPlanTests(unittest.TestCase):
    def test_schema_distinguishes_action_batch_and_total_layout_constraints(self) -> None:
        schema = kanban_mutation_schema()
        constraints = schema["constraints"]
        link = constraints["action_batch_limits"][
            "dashboard.report.link.report_ids"
        ]
        layout = constraints["dashboard_layout_capacity"]
        notes = schema["actions"]["dashboard.notes.replace"]["input_schema"][
            "properties"
        ]["notes"]

        self.assertEqual("gravity-insight.kanban-mutation-schema.v2", schema["schema_version"])
        self.assertEqual((1, 20, "single_action_request"), (
            link["minItems"], link["maxItems"], link["scope"]
        ))
        self.assertEqual((20, "dashboard_total_layout"), (
            layout["maxItems"], layout["scope"]
        ))
        self.assertFalse(layout["request_splitting_increases_capacity"])
        self.assertEqual(20, notes["maxItems"])
        self.assertEqual(4_000, notes["items"]["properties"]["content"]["maxLength"])
        self.assertEqual(
            "string",
            schema["actions"]["note.delete"]["input_schema"]["properties"][
                "note_id"
            ]["type"],
        )
        self.assertFalse(constraints["provenance"]["upstream_limit_verified"])

    def test_fresh_sixteen_chart_three_note_plan_has_nineteen_write_upper_bound(self) -> None:
        client = _Client()

        result = prepare_kanban_board(
            client, _new_request(16, 3), workspace=_workspace()
        )

        self.assertTrue(result["ok"])
        self.assertEqual("prepared", result["status"])
        self.assertEqual(
            {"charts": 16, "notes": 3, "layout_items": 19},
            result["counts"]["final"],
        )
        self.assertEqual(1, result["capacity"]["remaining"])
        self.assertEqual(19, len(result["actions"]))
        writes = result["io_estimate"]["planned_execution"]["mutation_writes"]
        self.assertEqual(19, writes["planned_from_snapshot"])
        self.assertEqual(19, writes["maximum"])
        self.assertEqual(0, result["mutation_calls"])
        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)
        link = result["actions"][-1]
        self.assertEqual("dashboard.report.link", link["action"])
        self.assertEqual(16, len(link["deferred_inputs"]["report_ids"]))
        self.assertEqual(
            {"$ref": "target.dashboard_id", "type": "positive_integer"},
            link["deferred_inputs"]["dashboard_id"],
        )

    def test_eighteen_chart_three_note_plan_rejects_before_every_call(self) -> None:
        client = _Client()

        result = prepare_kanban_board(
            client, _new_request(18, 3), workspace=_workspace()
        )

        self.assertFalse(result["ok"])
        self.assertEqual("rejected", result["status"])
        self.assertEqual("INPUT_INVALID", result["error"]["code"])
        self.assertEqual(21, result["capacity"]["used"])
        self.assertFalse(result["capacity"]["request_splitting_increases_capacity"])
        self.assertEqual([], result["actions"])
        self.assertEqual([], client.read_calls)
        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)
        self.assertEqual(0, result["mutation_calls"])

    def test_artifact_rejection_has_safe_structural_path_and_zero_mutations(self) -> None:
        request = _new_request(1, 0)
        private = "private-cohort-value-must-not-leak"
        request["saved_definitions"][0].update(
            {
                "config": {"calculateBody": {"query_item_list": private}},
                "start": "2026-08-01",
                "end": "2026-08-02",
            }
        )
        client = _Client()

        result = prepare_kanban_board(client, request, workspace=_workspace())

        self.assertFalse(result["ok"])
        self.assertEqual(1, len(result["unsupported_items"]))
        path = result["unsupported_items"][0]["error"]["field"]
        self.assertTrue(path.startswith("saved_definitions[0]."), path)
        self.assertNotIn(private, json.dumps(result, ensure_ascii=False))
        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)

    def test_duplicate_materialization_and_unbounded_reads_fail_before_calls(self) -> None:
        duplicate = _new_request(2, 0)
        duplicate["saved_definitions"][1] = copy.deepcopy(
            duplicate["saved_definitions"][0]
        )
        duplicate["saved_definitions"][1]["key"] = "other-key"
        client = _Client()

        with self.assertRaisesRegex(InputValidationError, "name values must be unique"):
            prepare_kanban_board(client, duplicate, workspace=_workspace())
        with self.assertRaisesRegex(InputValidationError, "max_pages"):
            prepare_kanban_board(
                client,
                _new_request(1, 0),
                workspace=_workspace(),
                max_pages=1_001,
            )

        self.assertEqual([], client.read_calls)
        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)

    def test_reuse_update_and_link_decisions_are_deterministic_and_read_only(self) -> None:
        desired = [_saved(1, report_id="1"), _saved(2, report_id="2")]
        exact_config = preflight_saved_definition(
            {"subject": "analysis_event", "config": _config()},
            app="101",
            workspace=_workspace(),
        )
        rows = [
            {
                "id": "1",
                "app_id": "101",
                "name": "Chart 1",
                "subject": "analysis_event",
                "config": json.dumps(exact_config),
                "remark": "",
                "create_user_id": 7,
            },
            {
                "id": "2",
                "app_id": "101",
                "name": "Old chart",
                "subject": "analysis_event",
                "config": json.dumps(exact_config),
                "remark": "",
                "create_user_id": 7,
            },
        ]
        dashboard = {
            "id": 30,
            "space_id": 10,
            "name": "Board | GSDK-aabbccddeeff",
            "ui_config": "[]",
            "even_report": [],
            "create_user_id": 7,
        }
        client = _Client(rows=rows, dashboard=dashboard)
        request = {
            "app_id": 101,
            "target": {"mode": "existing", "space_id": 10, "dashboard_id": 30},
            "saved_definitions": desired,
            "notes": [],
        }

        result = prepare_kanban_board(client, request, workspace=_workspace())

        self.assertEqual(
            ["reuse", "update"],
            [item["decision"] for item in result["saved_definitions"]],
        )
        self.assertEqual(
            ["saved.update", "dashboard.report.link"],
            [item["action"] for item in result["actions"]],
        )
        self.assertEqual(
            "upstream_owner", result["saved_definitions"][1]["ownership"]["basis"]
        )
        self.assertEqual(2, result["io_estimate"]["planned_execution"]["mutation_writes"]["maximum"])
        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)

    def test_existing_report_blocks_note_replacement_without_any_mutation(self) -> None:
        exact_config = preflight_saved_definition(
            {"subject": "analysis_event", "config": _config()},
            app="101",
            workspace=_workspace(),
        )
        row = {
            "id": "1",
            "app_id": "101",
            "name": "Chart 1",
            "subject": "analysis_event",
            "config": json.dumps(exact_config),
            "remark": "",
            "create_user_id": 7,
        }
        dashboard = {
            "id": 30,
            "space_id": 10,
            "name": "Board | GSDK-aabbccddeeff",
            "ui_config": json.dumps(
                [
                    {"i": "1", "subject": "analysis_event"},
                    {
                        "i": "notes_old",
                        "subject": "notes",
                        "name": "Old | GSDK-bbccddeeff00",
                        "content": "Old context",
                    },
                ]
            ),
            "even_report": [{"report_id": "1", "name": "Chart 1"}],
            "create_user_id": 7,
        }
        client = _Client(rows=[row], dashboard=dashboard)
        request = {
            "app_id": 101,
            "target": {"mode": "existing", "space_id": 10, "dashboard_id": 30},
            "saved_definitions": [_saved(1, report_id="1")],
            "notes": [
                {"title": "New", "content": "New context", "idempotency_key": "new"}
            ],
        }

        with self.assertRaisesRegex(
            InputValidationError, "notes differ while reports are attached"
        ):
            prepare_kanban_board(client, request, workspace=_workspace())

        self.assertEqual([], client.preview_calls)
        self.assertEqual([], client.mutation_calls)

    def test_cli_exposes_prepare_without_an_execute_switch(self) -> None:
        parsed = build_parser().parse_args(
            [
                "analysis",
                "dashboard",
                "kanban",
                "prepare",
                "--input",
                "board.json",
            ]
        )

        self.assertEqual("prepare", parsed.kanban_command)
        self.assertTrue(parsed.network_required)
        self.assertFalse(hasattr(parsed, "kanban_execute"))


if __name__ == "__main__":
    unittest.main()
