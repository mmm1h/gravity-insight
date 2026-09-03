from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from gravity_insight.agents.kanban_mutation import (
    kanban_mutation_capability_inventory,
    kanban_mutation_cards,
)
from gravity_insight.cli import build_parser
from gravity_insight.errors import (
    InputValidationError,
    MutationReadbackError,
    error_envelope,
)
from gravity_insight.kanban_dashboard_mutation import (
    copy_dashboard,
    create_dashboard,
    move_dashboard,
    move_dashboard_to_folder,
)
from gravity_insight.kanban_folder_mutation import delete_folder, rename_folder
from gravity_insight.kanban_mutation_contracts import (
    DASHBOARD_COPY,
    DASHBOARD_CREATE,
    DASHBOARD_FOLDER_MOVE,
    DASHBOARD_MOVE,
    DASHBOARD_UPDATE,
    DETAIL,
    REPORT_UNLINK,
)
from gravity_insight.kanban_space_mutation import delete_space, rename_space
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_kanban_mutation_adapter import validate_kanban_plan
from gravity_insight.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "src" / "gravity_insight" / "contracts"
MARKER = "GSDK-0123456789ab"


class _PreviewClient:
    def __init__(self) -> None:
        self.reads = 0
        self.writes = 0

    def _preview_mutation(self, operation_id, inputs):
        return {
            "ok": True,
            "operation_id": operation_id,
            "request": {"inputs": dict(inputs)},
            "network_called": False,
        }

    def _execute_mutation(self, operation_id, inputs):
        self.writes += 1
        raise AssertionError("dry-run must not send a mutation")

    def read(self, operation_id, inputs):
        self.reads += 1
        return {
            "ok": True,
            "status": "success",
            "data": [
                {
                    "id": 10,
                    "name": f"SDK Space | {MARKER}",
                    "folder_or_dashboard": [
                        {
                            "id": -1,
                            "name": "System Ungrouped",
                            "is_folder": True,
                            "dashboards": [],
                        },
                        {
                            "id": 20,
                            "name": f"SDK Folder | {MARKER}",
                            "is_folder": True,
                            "space_id": 10,
                            "dashboards": [
                                {"id": 30, "name": f"One | {MARKER}", "space_id": 10},
                                {"id": 31, "name": f"Two | {MARKER}", "space_id": 10},
                            ],
                        }
                    ],
                }
            ],
        }


class _OwnerPreviewClient(_PreviewClient):
    def __init__(self, *, owner_id: int, principal_id: int) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.principal_id = principal_id

    def _current_principal_id(self):
        return self.principal_id

    def read(self, operation_id, inputs):
        self.reads += 1
        if operation_id == "analysis.dashboard.space_members.list":
            return {
                "ok": True,
                "status": "success",
                "data": {"creator": {"id": self.owner_id, "name": "owner"}, "authUsers": []},
            }
        return {
            "ok": True,
            "status": "success",
            "data": [{
                "id": 10,
                "name": "Manual Space",
                "folder_or_dashboard": [{
                    "id": 20,
                    "name": "Manual Folder",
                    "is_folder": True,
                    "space_id": 10,
                    "dashboards": [],
                }],
            }],
        }


class _LinkClient:
    def __init__(
        self,
        *,
        attached: list[dict] | None = None,
        available: list[dict] | None = None,
        apply_write: bool = True,
        add_report_layout: bool = False,
    ) -> None:
        self.detail = {
            "id": 30,
            "name": f"SDK Dashboard | {MARKER}",
            "space_id": 10,
            "ui_config": '[{"i":"layout-1","x":0,"y":0,"w":2,"h":5}]',
            "even_report": copy.deepcopy(attached or []),
        }
        self.available = copy.deepcopy(available or [])
        for row in self.available:
            row.setdefault("subject", "analysis_event")
        self.apply_write = apply_write
        self.add_report_layout = add_report_layout
        self.previews: list[dict] = []
        self.writes: list[dict] = []

    def read(self, operation_id, inputs):
        return {"ok": True, "status": "success", "data": copy.deepcopy(self.detail)}

    def read_all(self, operation_id, inputs, **options):
        return {
            "ok": True,
            "status": "empty" if not self.available else "success",
            "data": {"list": copy.deepcopy(self.available)},
            "error": None,
        }

    def _preview_mutation(self, operation_id, inputs):
        self.previews.append(copy.deepcopy(inputs))
        return {
            "ok": True,
            "operation_id": operation_id,
            "request": {"inputs": copy.deepcopy(inputs)},
            "network_called": False,
        }

    def _execute_mutation(self, operation_id, inputs):
        self.writes.append(copy.deepcopy(inputs))
        if self.apply_write:
            if operation_id == DASHBOARD_UPDATE:
                self.detail["even_report"] = copy.deepcopy(inputs["report_list"])
                for index, report in enumerate(self.detail["even_report"]):
                    report.setdefault("id", 100 + index)
                self.detail["ui_config"] = inputs["ui_config"]
                if self.add_report_layout:
                    layout = json.loads(self.detail["ui_config"])
                    layout.append({"i": inputs["report_list"][-1]["report_id"], "x": 2, "y": 0})
                    self.detail["ui_config"] = json.dumps(layout)
            elif operation_id == REPORT_UNLINK:
                selected = set(inputs["ids"])
                self.detail["even_report"] = [
                    item
                    for item in self.detail["even_report"]
                    if item["id"] not in selected
                ]
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
        }


class _DashboardHierarchyClient:
    def __init__(self, *, create_fault: str | None = None) -> None:
        self.create_fault = create_fault
        self.writes: list[tuple[str, dict]] = []
        self.next_dashboard_id = 600
        self.tree = [
            {
                "id": 100,
                "name": f"Personal | {MARKER}",
                "folder_or_dashboard": [
                    {
                        "id": -1,
                        "name": "ungrouped",
                        "is_folder": True,
                        "space_id": 100,
                        "dashboards": [
                            {
                                "id": 555,
                                "name": f"Ungrouped source | {MARKER}",
                                "space_id": 100,
                                "folder_id": 0,
                            }
                        ],
                    },
                    {
                        "id": 200,
                        "name": f"Folder A | {MARKER}",
                        "is_folder": True,
                        "space_id": 100,
                        "dashboards": [
                            {
                                "id": 556,
                                "name": f"Grouped source | {MARKER}",
                                "space_id": 100,
                                "folder_id": 200,
                            }
                        ],
                    },
                ],
            },
            {
                "id": 101,
                "name": f"Destination | {MARKER}",
                "folder_or_dashboard": [
                    {
                        "id": -1,
                        "name": "ungrouped",
                        "is_folder": True,
                        "space_id": 101,
                        "dashboards": [],
                    },
                    {
                        "id": 201,
                        "name": f"Folder B | {MARKER}",
                        "is_folder": True,
                        "space_id": 101,
                        "dashboards": [],
                    },
                ],
            },
        ]

    def _preview_mutation(self, operation_id, inputs):
        return {
            "ok": True,
            "operation_id": operation_id,
            "request": {"inputs": copy.deepcopy(inputs)},
            "network_called": False,
        }

    def _execute_mutation(self, operation_id, inputs):
        selected = copy.deepcopy(inputs)
        self.writes.append((operation_id, selected))
        if operation_id in {DASHBOARD_CREATE, DASHBOARD_COPY}:
            destination_space = (
                selected["space_id"]
                if operation_id == DASHBOARD_CREATE
                else selected["to_space_id"]
            )
            destination_folder = selected.get(
                "folder_id" if operation_id == DASHBOARD_CREATE else "to_folder_id",
                0,
            )
            if self.create_fault == "wrong_folder":
                destination_folder = 200
            elif self.create_fault == "wrong_space":
                destination_space = 101
            self._append_dashboard(
                destination_space,
                destination_folder,
                {
                    "id": self.next_dashboard_id,
                    "name": selected["name"],
                    "space_id": destination_space,
                    "folder_id": destination_folder,
                },
            )
            self.next_dashboard_id += 1
        elif operation_id == DASHBOARD_FOLDER_MOVE:
            dashboard = self._remove_dashboard(selected["dashboard_id"])
            dashboard["space_id"] = selected["space_id"]
            dashboard["folder_id"] = selected["folder_id"]
            self._append_dashboard(
                selected["space_id"], selected["folder_id"], dashboard
            )
        elif operation_id == DASHBOARD_MOVE:
            dashboard_id = selected["dashboards"][0]["dashboard_id"]
            dashboard = self._remove_dashboard(dashboard_id)
            dashboard["space_id"] = selected["to_space_id"]
            dashboard["folder_id"] = selected.get("to_folder_id", 0)
            self._append_dashboard(
                selected["to_space_id"], selected.get("to_folder_id", 0), dashboard
            )
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
            "unsafe_extra": {"must_not": "escape"},
        }

    def read(self, operation_id, inputs):
        if operation_id == DETAIL:
            dashboard = self._find_dashboard(int(inputs["id"]))
            return {
                "ok": True,
                "status": "success",
                "data": {
                    **copy.deepcopy(dashboard),
                    "ui_config": "[]",
                    "even_report": [],
                },
            }
        return {
            "ok": True,
            "status": "success",
            "data": copy.deepcopy(self.tree),
        }

    def _append_dashboard(self, space_id: int, folder_id: int, dashboard: dict) -> None:
        space = next(item for item in self.tree if item["id"] == space_id)
        tree_folder_id = -1 if folder_id == 0 else folder_id
        folder = next(
            item
            for item in space["folder_or_dashboard"]
            if item["id"] == tree_folder_id
        )
        folder["dashboards"].append(dashboard)

    def _find_dashboard(self, dashboard_id: int) -> dict:
        for space in self.tree:
            for folder in space["folder_or_dashboard"]:
                for dashboard in folder["dashboards"]:
                    if dashboard["id"] == dashboard_id:
                        return dashboard
        raise AssertionError(f"dashboard {dashboard_id} is missing")

    def _remove_dashboard(self, dashboard_id: int) -> dict:
        dashboard = self._find_dashboard(dashboard_id)
        for space in self.tree:
            for folder in space["folder_or_dashboard"]:
                if dashboard in folder["dashboards"]:
                    folder["dashboards"].remove(dashboard)
                    return dashboard
        raise AssertionError(f"dashboard {dashboard_id} is missing")


class GravityKanbanMutationTests(unittest.TestCase):
    def test_ungrouped_dashboard_create_and_copy_round_trip(self) -> None:
        create_client = _DashboardHierarchyClient()
        created = create_dashboard(
            create_client,
            app_id=1,
            space_id=100,
            folder_id=0,
            name="created",
            idempotency_key="create-ungrouped",
            execute=True,
        )
        copy_client = _DashboardHierarchyClient()
        copied = copy_dashboard(
            copy_client,
            app_id=1,
            dashboard_id=555,
            from_space_id=100,
            to_space_id=100,
            to_folder_id=0,
            name="copied",
            idempotency_key="copy-ungrouped",
            execute=True,
        )

        self.assertEqual(("created", None), (created["status"], created["target"]["folder_id"]))
        self.assertEqual(("copied", None), (copied["status"], copied["target"]["folder_id"]))
        self.assertEqual(0, create_client.writes[0][1]["folder_id"])
        self.assertNotIn("to_folder_id", copy_client.writes[0][1])

    def test_dashboard_moves_to_and_from_ungrouped_round_trip(self) -> None:
        client = _DashboardHierarchyClient()

        ungrouped = move_dashboard_to_folder(
            client,
            app_id=1,
            space_id=100,
            dashboard_id=556,
            folder_id=0,
            execute=True,
        )
        regrouped = move_dashboard(
            client,
            app_id=1,
            dashboard_id=555,
            from_space_id=100,
            to_space_id=101,
            to_folder_id=201,
            execute=True,
        )

        self.assertEqual((100, None), (
            ungrouped["target"]["space_id"], ungrouped["target"]["folder_id"]
        ))
        self.assertEqual((101, 201), (
            regrouped["target"]["space_id"], regrouped["target"]["folder_id"]
        ))

    def test_create_rejects_wrong_folder_and_space_after_acknowledgement(self) -> None:
        for fault in ("wrong_folder", "wrong_space"):
            with self.subTest(fault=fault):
                client = _DashboardHierarchyClient(create_fault=fault)
                with self.assertRaises(MutationReadbackError) as captured:
                    create_dashboard(
                        client,
                        app_id=1,
                        space_id=100,
                        folder_id=0,
                        name="created",
                        idempotency_key=f"create-{fault}",
                        execute=True,
                    )

                detail = error_envelope(
                    captured.exception, operation_id=DASHBOARD_CREATE
                )["error"]
                self.assertEqual(1, len(client.writes))
                self.assertFalse(detail["retryable"])
                self.assertTrue(detail["write_sent"])
                self.assertFalse(detail["automatic_retry"])
                self.assertRegex(detail["marker"], r"^GSDK-[0-9a-f]{12}$")
                self.assertEqual(
                    {
                        "received": True,
                        "operation_id": DASHBOARD_CREATE,
                        "status": "success",
                        "attempts": 1,
                    },
                    detail["acknowledgement"],
                )
                self.assertNotIn("unsafe_extra", detail["acknowledgement"])
                self.assertIn("Do not retry", detail["next_action"])

    def test_parent_delete_preview_reports_relocation_before_write(self) -> None:
        client = _PreviewClient()

        folder = delete_folder(client, app_id=1, space_id=10, folder_id=20)
        space = delete_space(client, app_id=1, space_id=10)

        self.assertEqual(2, folder["cascade"]["dashboards_moved"])
        self.assertEqual(0, folder["cascade"]["dashboards_deleted"])
        self.assertEqual(4, space["cascade"]["descendant_count"])
        self.assertEqual(0, space["cascade"]["dashboards_deleted"])
        self.assertIn("does not delete", space["cascade"]["warning"])
        self.assertEqual(2, client.reads)
        self.assertEqual(0, client.writes)

    def test_hash_routes_are_kept_distinct_and_only_non_share_routes_promote(self) -> None:
        rename = json.loads(
            (CONTRACTS / "operations" / "analysis.datamanageconfig.kanban.dashboard.dc7858a7.update.json").read_text(encoding="utf-8")
        )["operation"]
        share_delete = json.loads(
            (CONTRACTS / "reservations" / "analysis.datamanageconfig.kanban.space.093dd36e.delete.json").read_text(encoding="utf-8")
        )["operation"]
        promoted = list((CONTRACTS / "operations").glob("analysis*kanban*.json"))
        remaining = list((CONTRACTS / "reservations").glob("analysis*kanban*.json"))

        self.assertEqual("/turbo_engine/api/v2/datamanageconfig/kanban/dashboard/rename/", rename["path_template"])
        self.assertEqual("/turbo_engine/api/v2/datamanageconfig/kanban/space/share/delete/", share_delete["path_template"])
        self.assertEqual(18, len(promoted))
        self.assertEqual(3, len(remaining))

    def test_space_owner_allows_unmarked_rename_but_folder_without_owner_fails_closed(self) -> None:
        owned = _OwnerPreviewClient(owner_id=7, principal_id=7)
        self.assertEqual(
            "upstream_owner",
            rename_space(owned, app_id=1, space_id=10, name="Mine")["target"]["ownership"]["basis"],
        )
        foreign = _OwnerPreviewClient(owner_id=8, principal_id=7)
        with self.assertRaises(InputValidationError) as captured:
            rename_space(foreign, app_id=1, space_id=10, name="No")
        self.assertEqual("OWNERSHIP_REQUIRED", captured.exception.code)
        with self.assertRaises(InputValidationError) as folder_error:
            rename_folder(owned, app_id=1, space_id=10, folder_id=20, name="No")
        self.assertIn("without a proven owner", folder_error.exception.next_action)

    def test_sdk_cli_plan_and_agent_expose_the_same_confirmation_boundary(self) -> None:
        client = _PreviewClient()
        sdk = GravitySDK(insight=client)
        preview = sdk.kanban_mutation("space.create", {"app_id": 1, "name": "Roundtrip"})
        request = {
            "name": "kanban_mutation",
            "mode": "preview",
            "inputs": {"action": "space.create", "inputs": {"app_id": 1, "name": "Roundtrip"}},
        }
        context = AdapterContext("kanban", "test", "composite", None, (), (), 5, 20)

        validate_kanban_plan(request, context)
        parsed = build_parser().parse_args(["analysis", "dashboard", "kanban", "schema"])
        card = kanban_mutation_cards("kanban.mutation", domain=None, platform=None)[0]

        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["write_sent"])
        self.assertEqual("schema", parsed.kanban_command)
        self.assertTrue(card["plan_executable"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertEqual("preview", card["next"]["plan_node"]["request"]["mode"])
        self.assertEqual("execute", card["next"]["then_plan_node"]["request"]["mode"])

    def test_link_execute_merges_existing_reports_and_preserves_layout(self) -> None:
        existing = {
            "report_id": 4,
            "name": "Existing",
            "subject": "analysis_event",
            "config": "{}",
            "remark": "keep",
        }
        client = _LinkClient(
            attached=[existing],
            available=[
                {"id": 4, "app_id": 1, "name": "Existing"},
                {"id": 5, "app_id": 1, "name": "New"},
            ],
        )
        layout = client.detail["ui_config"]

        result = GravitySDK(insight=client).kanban_mutation(
            "dashboard.report.link",
            {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [5]},
            execute=True,
        )

        self.assertEqual("updated", result["status"])
        self.assertEqual(1, len(client.writes))
        self.assertEqual(DASHBOARD_UPDATE, result["operation_id"])
        self.assertEqual([existing, {"report_id": "5", "name": "New"}], client.writes[0]["report_list"])
        written_layout = json.loads(client.writes[0]["ui_config"])
        self.assertEqual(json.loads(layout), written_layout[:1])
        self.assertEqual(
            {
                "i": "5", "x": 0, "y": 5, "w": 2, "h": 5,
                "name": "New", "subject": "analysis_event", "isSmall": False,
            },
            written_layout[1],
        )

    def test_link_is_idempotent_when_every_report_is_already_attached(self) -> None:
        client = _LinkClient(
            attached=[{"report_id": 4, "name": "Existing"}],
            available=[{"id": 4, "app_id": 1, "name": "Existing"}],
        )

        result = GravitySDK(insight=client).kanban_mutation(
            "dashboard.report.link",
            {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [4]},
            execute=True,
        )

        self.assertEqual("already_attached", result["status"])
        self.assertFalse(result["write_sent"])
        self.assertEqual([], client.writes)

    def test_link_rejects_union_above_twenty_before_preview_or_write(self) -> None:
        attached = [{"report_id": item, "name": f"Report {item}"} for item in range(1, 21)]
        available = [{"id": item, "app_id": 1, "name": f"Report {item}"} for item in range(1, 22)]
        client = _LinkClient(attached=attached, available=available)

        with self.assertRaises(InputValidationError) as captured:
            GravitySDK(insight=client).kanban_mutation(
                "dashboard.report.link",
                {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [21]},
            )

        self.assertEqual("report_ids", captured.exception.field)
        self.assertEqual([], client.previews)
        self.assertEqual([], client.writes)

    def test_split_link_requests_cannot_bypass_total_layout_capacity(self) -> None:
        available = [
            {"id": item, "app_id": 1, "name": f"Report {item}"}
            for item in range(1, 19)
        ]
        client = _LinkClient(available=available)
        client.detail["ui_config"] = json.dumps(
            [
                {"i": f"notes_{item}", "subject": "notes", "x": 0, "y": item}
                for item in range(3)
            ]
        )
        sdk = GravitySDK(insight=client)

        first = sdk.kanban_mutation(
            "dashboard.report.link",
            {
                "app_id": 1,
                "space_id": 10,
                "dashboard_id": 30,
                "report_ids": list(range(1, 18)),
            },
            execute=True,
        )
        with self.assertRaises(InputValidationError) as captured:
            sdk.kanban_mutation(
                "dashboard.report.link",
                {
                    "app_id": 1,
                    "space_id": 10,
                    "dashboard_id": 30,
                    "report_ids": [18],
                },
            )

        self.assertEqual("updated", first["status"])
        self.assertEqual("report_ids", captured.exception.field)
        self.assertEqual(20, len(json.loads(client.detail["ui_config"])))
        self.assertEqual(1, len(client.writes))

    def test_link_rejects_missing_or_inaccessible_report_before_preview_or_write(self) -> None:
        client = _LinkClient(available=[{"id": 4, "app_id": 1, "name": "Visible"}])

        with self.assertRaises(InputValidationError) as captured:
            GravitySDK(insight=client).kanban_mutation(
                "dashboard.report.link",
                {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [5]},
            )

        self.assertEqual("report_ids", captured.exception.field)
        self.assertEqual([], client.previews)
        self.assertEqual([], client.writes)

    def test_link_raises_when_write_acknowledgement_does_not_round_trip(self) -> None:
        client = _LinkClient(
            available=[{"id": 5, "app_id": 1, "name": "New"}],
            apply_write=False,
        )

        with self.assertRaises(MutationReadbackError):
            GravitySDK(insight=client).kanban_mutation(
                "dashboard.report.link",
                {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [5]},
                execute=True,
            )

        self.assertEqual(1, len(client.writes))

    def test_link_readback_allows_new_layout_item_without_losing_existing_layout(self) -> None:
        client = _LinkClient(
            available=[{"id": "report-new", "app_id": 1, "name": "New"}],
            add_report_layout=True,
        )

        result = GravitySDK(insight=client).kanban_mutation(
            "dashboard.report.link",
            {
                "app_id": 1,
                "space_id": 10,
                "dashboard_id": 30,
                "report_ids": ["report-new"],
            },
            execute=True,
        )

        self.assertEqual("updated", result["status"])
        self.assertEqual("layout-1", json.loads(client.detail["ui_config"])[0]["i"])

    def test_link_action_is_exposed_by_sdk_cli_plan_and_agent(self) -> None:
        action = "dashboard.report.link"
        inputs = {"app_id": 1, "space_id": 10, "dashboard_id": 30, "report_ids": [5]}
        client = _LinkClient(available=[{"id": 5, "app_id": 1, "name": "New"}])
        sdk = GravitySDK(insight=client)
        request = {
            "name": "kanban_mutation",
            "mode": "preview",
            "inputs": {"action": action, "inputs": inputs},
        }
        context = AdapterContext("kanban", "test", "composite", None, (), (), 5, 20)

        preview = sdk.kanban_mutation(action, inputs)
        validate_kanban_plan(request, context)
        parsed = build_parser().parse_args([
            "analysis", "dashboard", "kanban", "mutate", "--action", action,
            "--input", "link.json", "--dry-run",
        ])
        card = next(
            item
            for item in kanban_mutation_capability_inventory()
            if item["mutation_action"] == action
        )

        self.assertTrue(preview["dry_run"])
        self.assertTrue(parsed.kanban_dry_run)
        self.assertEqual([DASHBOARD_UPDATE], card["operation_ids"])
        self.assertEqual("preview", card["next"]["plan_node"]["request"]["mode"])
        self.assertEqual("execute", card["next"]["then_plan_node"]["request"]["mode"])

    def test_opaque_saved_analysis_id_round_trips_through_link_and_unlink(self) -> None:
        report_id = "report-8f4d2c"
        client = _LinkClient(
            available=[{"id": report_id, "app_id": 1, "name": "Owned"}]
        )
        sdk = GravitySDK(insight=client)
        inputs = {
            "app_id": 1,
            "space_id": 10,
            "dashboard_id": 30,
            "report_ids": [report_id],
        }

        linked = sdk.kanban_mutation("dashboard.report.link", inputs, execute=True)
        unlinked = sdk.kanban_mutation("dashboard.report.unlink", inputs, execute=True)
        contract = json.loads(
            (CONTRACTS / "operations" / "analysis.engine.datamanageconfig.kanban.delete.json").read_text(
                encoding="utf-8"
            )
        )["operation"]
        detail_contract = json.loads(
            (CONTRACTS / "operations" / "analysis.dashboard.detail.json").read_text(
                encoding="utf-8"
            )
        )["operation"]

        self.assertEqual("updated", linked["status"])
        self.assertEqual("updated", unlinked["status"])
        self.assertEqual(report_id, client.writes[0]["report_list"][0]["report_id"])
        self.assertEqual([100], client.writes[1]["ids"])
        self.assertEqual("integer", contract["input_fields"]["ids"]["item_type"])
        self.assertIn("id", detail_contract["response_projection"]["data_item_keys"]["even_report"])


if __name__ == "__main__":
    unittest.main()
