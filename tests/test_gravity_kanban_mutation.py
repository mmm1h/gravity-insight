from __future__ import annotations

import json
import unittest
from pathlib import Path

from gravity_sdk.agent_kanban_mutation import kanban_mutation_cards
from gravity_sdk.cli import build_parser
from gravity_sdk.errors import InputValidationError
from gravity_sdk.kanban_folder_mutation import delete_folder, rename_folder
from gravity_sdk.kanban_space_mutation import delete_space, rename_space
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_kanban_mutation_adapter import validate_kanban_plan
from gravity_sdk.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "src" / "gravity_sdk" / "contracts"
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

class GravityKanbanMutationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
