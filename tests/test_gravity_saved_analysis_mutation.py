from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from gravity_insight.agents.analysis import analysis_query_spec_cards
from gravity_insight.agents.saved_analysis_mutation import (
    saved_analysis_mutation_capability_inventory,
    saved_analysis_mutation_cards,
)
from gravity_insight.cache import is_metadata_operation
from gravity_insight.errors import (
    ContractChangedError,
    InputValidationError,
    PermissionUnavailableError,
    UnsupportedOperationError,
    UpstreamError,
)
from gravity_insight.mutation_ownership import single_creator_owner
from gravity_insight.saved_analysis_catalog import GET_OPERATION_ID, LIST_OPERATION_ID
from gravity_insight.saved_analysis_mutation import (
    CREATE_UNSUPPORTED_CODE,
    UPDATE_OPERATION_ID,
    create_saved_analysis,
    delete_saved_analysis,
    update_saved_analysis,
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


class _Client:
    def __init__(self, *, retain_deleted: bool = False) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.writes: list[dict[str, Any]] = []
        self.retain_deleted = retain_deleted

    def _preview_mutation(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("preview", copy.deepcopy(inputs)))
        return {
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "network_called": False,
        }

    def _execute_mutation(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("execute", copy.deepcopy(inputs)))
        self.writes.append(copy.deepcopy(inputs))
        object_id = str(inputs.get("id") or "9")
        if inputs.get("is_deleted") is True:
            if not self.retain_deleted:
                self.rows = [row for row in self.rows if row["id"] != object_id]
        else:
            value = {
                **copy.deepcopy(inputs),
                "id": object_id,
                "create_time": "2026-08-01T00:00:00Z",
                "modify_time": "2026-08-02T00:00:00Z",
                "create_user_id": 7,
                "create_user_name": "owner",
                "update_user_id": 7,
                "update_user_name": "owner",
            }
            self.rows = [row for row in self.rows if row["id"] != object_id]
            self.rows.append(value)
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
            "data": {"object": {"id": object_id, "app_id": 101}},
        }

    def read_all(
        self,
        operation_id: str,
        inputs: dict[str, Any],
        **_options: Any,
    ) -> dict[str, Any]:
        self.calls.append((operation_id, copy.deepcopy(inputs)))
        return {
            "ok": True,
            "status": "empty" if not self.rows else "success",
            "data": {"list": copy.deepcopy(self.rows)},
            "error": None,
        }

    def read(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((operation_id, copy.deepcopy(inputs)))
        row = next(row for row in self.rows if row["id"] == str(inputs["id"]))
        return {
            "ok": True,
            "status": "success",
            "data": copy.deepcopy(row),
            "error": None,
        }

    @staticmethod
    def _current_principal_id() -> str:
        return "7"


class _RejectedCreateClient(_Client):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def _execute_mutation(
        self, operation_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("execute", copy.deepcopy(inputs)))
        self.writes.append(copy.deepcopy(inputs))
        raise self.error


class SavedAnalysisMutationTests(unittest.TestCase):
    def test_compact_create_submits_generated_web_config(self) -> None:
        client = _Client()
        create_saved_analysis(
            client,
            app_id=101,
            name="generated",
            subject="analysis_event",
            config=_config(),
            workspace=_workspace(),
        )
        wire_config = json.loads(client.calls[0][1]["config"])
        self.assertIn("calculateBody", wire_config)
        self.assertNotIn("steps", wire_config)

    def test_web_artifact_create_preserves_caller_config(self) -> None:
        client = _Client()
        config = {
            "calculateBody": {
                "query_item_list": [{
                    "cond_logic": "AND",
                    "conditions": [],
                    "custom_name": "open",
                    "event_index": 0,
                    "event_label": "open",
                    "event_name": "open",
                    "target": {
                        "field": "PresetAllCount",
                        "name": "PresetAllCount",
                    },
                }],
                "group_by_list": [],
                "extra_data": {"client_server_time": "CLIENT"},
            },
            "tableShowType": "table",
            "aggregate_config": {},
        }
        create_saved_analysis(
            client,
            app_id=101,
            name="web",
            subject="analysis_event",
            config=config,
            workspace=_workspace(),
            start="2026-08-01",
            end="2026-08-02",
        )
        self.assertEqual(config, json.loads(client.calls[0][1]["config"]))

    def test_create_classifies_only_unresolved_semantic_rejections_as_unsupported(self) -> None:
        cases = (
            InputValidationError(
                "private generic mutation failure",
                field="mutation",
            ),
            UpstreamError("Gravity rejected the mutation without a classified error"),
        )
        for rejection in cases:
            with self.subTest(rejection=type(rejection).__name__):
                receipts = ({"receipt_id": "a" * 32, "storage_status": "stored"},)
                rejection.http_receipt_references = receipts
                client = _RejectedCreateClient(rejection)
                with self.assertRaises(UnsupportedOperationError) as captured:
                    create_saved_analysis(
                        client,
                        app_id=101,
                        name="rejected",
                        subject="analysis_event",
                        config=_config(),
                        workspace=_workspace(),
                        execute=True,
                    )
                error = captured.exception
                self.assertEqual(CREATE_UNSUPPORTED_CODE, error.code)
                self.assertEqual("saved_analysis.create", error.field)
                self.assertEqual("local", error.category)
                self.assertFalse(error.retryable)
                self.assertNotIn("private generic", str(error))
                self.assertEqual(receipts, error.http_receipt_references)
                self.assertEqual(1, len(client.writes))
                self.assertEqual([], client.rows)

        permission = PermissionUnavailableError(
            "the authenticated account cannot perform this mutation",
            field="permission",
        )
        client = _RejectedCreateClient(permission)
        with self.assertRaises(PermissionUnavailableError) as captured:
            create_saved_analysis(
                client,
                app_id=101,
                name="forbidden",
                subject="analysis_event",
                config=_config(),
                workspace=_workspace(),
                execute=True,
            )
        self.assertIs(permission, captured.exception)

    def test_complete_create_update_delete_lifecycle_and_wire_actions(self) -> None:
        client = _Client()
        common = {
            "app_id": 101,
            "name": "daily purchase",
            "subject": "analysis_event",
            "config": _config(),
            "workspace": _workspace(),
        }
        preview = create_saved_analysis(client, **common)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(["preview"], [call[0] for call in client.calls])

        created = create_saved_analysis(client, **common, execute=True)
        self.assertEqual("created", created["status"])
        object_id = created["target"]["id"]
        updated = update_saved_analysis(
            client,
            object_id,
            **{**common, "name": "daily purchase updated", "config": _config(grain="week")},
            execute=True,
        )
        self.assertEqual(("updated", "sdk_source_marker"), (
            updated["status"], updated["target"]["ownership"]["basis"]
        ))
        deleted = delete_saved_analysis(
            client, object_id, app_id=101, workspace=_workspace(), execute=True
        )
        self.assertTrue(deleted["target"]["deleted"])
        self.assertEqual([], client.rows)

        create_wire, update_wire, delete_wire = client.writes
        self.assertNotIn("id", create_wire)
        self.assertNotIn("is_deleted", create_wire)
        self.assertIn("id", update_wire)
        self.assertNotIn("is_deleted", update_wire)
        self.assertTrue(delete_wire["is_deleted"])
        self.assertTrue(create_wire["remark"].startswith("GSDK-"))
        self.assertEqual(UPDATE_OPERATION_ID, created["operation_id"])

    def test_unmarked_owner_delete_is_allowed_and_foreign_is_rejected(self) -> None:
        owned = _Client()
        owned.rows.append({
            "id": "9", "app_id": "101", "name": "web owned",
            "subject": "analysis_event", "config": "{}", "remark": "",
            "create_user_id": 7, "create_user_name": "owner",
        })
        deleted = delete_saved_analysis(
            owned, "9", app_id=101, workspace=_workspace(), execute=True
        )
        self.assertEqual("upstream_owner", deleted["target"]["ownership"]["basis"])
        self.assertTrue(deleted["target"]["deleted"])
        self.assertEqual(1, len(owned.writes))

        marked = _Client()
        marked.rows.append({
            "id": "8", "app_id": "101", "name": "marked",
            "subject": "analysis_event", "config": "{}",
            "remark": "GSDK-aabbccddeeff",
            "create_user_id": 99, "create_user_name": "other",
        })
        kept = delete_saved_analysis(
            marked, "8", app_id=101, workspace=_workspace(), execute=True
        )
        self.assertEqual("sdk_source_marker", kept["target"]["ownership"]["basis"])

        foreign = _Client()
        foreign.rows.append({
            "id": "7", "app_id": "101", "name": "foreign",
            "subject": "analysis_event", "config": "{}", "remark": "",
            "create_user_id": 99, "create_user_name": "other",
        })
        with self.assertRaises(InputValidationError) as captured:
            delete_saved_analysis(
                foreign, "7", app_id=101, workspace=_workspace(), execute=True
            )
        error = captured.exception
        self.assertEqual("OWNERSHIP_REQUIRED", error.code)
        self.assertIn('"object_id":"7"', str(error))
        self.assertIn('"owner_id":"99"', str(error))
        self.assertIn('"current_principal_id":"7"', str(error))
        self.assertEqual(0, len(foreign.writes))

    def test_delete_acknowledgement_without_disappearance_is_contract_change(self) -> None:
        client = _Client(retain_deleted=True)
        client.rows.append({
            "id": "9", "app_id": "101", "name": "owned",
            "subject": "analysis_event", "config": "{}", "remark": "",
            "create_user_id": 7, "create_user_name": "owner",
        })
        with self.assertRaises(ContractChangedError):
            delete_saved_analysis(
                client, "9", app_id=101, workspace=_workspace(), execute=True
            )

    def test_owner_and_cache_evidence_are_exact(self) -> None:
        self.assertEqual("7", single_creator_owner({"id": 7}).owner_id)
        self.assertIsNone(single_creator_owner([{"id": 7}]).owner_id)
        self.assertIsNone(single_creator_owner({"uid": 7}).owner_id)
        for action in ("list", "get"):
            self.assertFalse(is_metadata_operation({
                "domain": "analysis", "resource": "report_config", "action": action
            }))
        self.assertEqual((LIST_OPERATION_ID, GET_OPERATION_ID), (
            "analysis.report_config.list", "analysis.report_config.get"
        ))

    def test_catalog_cards_are_safe_and_comparison_is_projected(self) -> None:
        cards = saved_analysis_mutation_capability_inventory()
        self.assertEqual({"create", "update", "delete"}, {
            card["mutation_action"] for card in cards
        })
        for card in cards:
            self.assertEqual([UPDATE_OPERATION_ID], card["operation_ids"])
            self.assertFalse(card["natural_language_auto_execute"])
            self.assertTrue(card["confirmation_required"])
            self.assertFalse(card["next"]["ready_without_input"])
            if card["mutation_action"] != "delete":
                self.assertEqual(5, len(card["input_schema"]["subject"]["enum"]))
        discovered = saved_analysis_mutation_cards(
            "create saved analysis", domain=None, platform=None
        )
        self.assertEqual("create", discovered[0]["mutation_action"])
        generic = analysis_query_spec_cards(
            "analysis.query.spec", domain=None, platform=None
        )[0]
        self.assertIn("同一分析定义比较两个时期", generic["description"])


if __name__ == "__main__":
    unittest.main()
