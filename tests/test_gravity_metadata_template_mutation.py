from __future__ import annotations

import json
import unittest
from pathlib import Path

from gravity_sdk.agent_metadata_template import (
    SELECTORS,
    metadata_template_capability_inventory,
)
from gravity_sdk.cli import build_parser
from gravity_sdk.errors import ContractChangedError, InputValidationError
from gravity_sdk.metadata_template_contracts import (
    TEMPLATE_APPEND,
    TEMPLATE_EVENT_MEMBERS,
    TEMPLATE_EVENT_REMOVE,
    TEMPLATE_LIST,
    TEMPLATE_MASTER,
    TEMPLATE_PROPERTY_MEMBERS,
    TEMPLATE_PROPERTY_REMOVE,
)
from gravity_sdk.metadata_template_mutation import (
    append_metadata_template_members,
    create_metadata_template,
    delete_metadata_template,
    remove_metadata_template_members,
)
from gravity_sdk.metadata_template_wire import validate_metadata_template_wire
from gravity_sdk.mutation_client import MutationClientMixin
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_metadata_template_adapter import validate_metadata_template_plan
from gravity_sdk.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]


class _Client:
    def __init__(self) -> None:
        self.templates: list[dict] = []
        self.members: list[dict] = []
        self.targets = [
            {"id": 11, "name": "p11"}, {"id": 12, "name": "p12"},
            {"id": 13, "name": "p13"},
        ]
        self.reads = 0
        self.writes = 0

    def _current_principal_id(self) -> int:
        return 7

    def _preview_mutation(self, operation_id: str, values: dict) -> dict:
        validate_metadata_template_wire(operation_id, values)
        return {
            "ok": True, "status": "preview", "operation_id": operation_id,
            "effect": "mutation", "offline": True, "network_called": False,
            "attempts": 0,
        }

    def _execute_mutation(self, operation_id: str, values: dict) -> dict:
        validate_metadata_template_wire(operation_id, values)
        self.writes += 1
        if operation_id == TEMPLATE_MASTER and values.get("is_deleted") == 1:
            target = values["id"]
            self.templates = [row for row in self.templates if row["id"] != target]
            self.members = [row for row in self.members if row["template_id"] != target]
        elif operation_id == TEMPLATE_MASTER:
            target = 100 + len(self.templates)
            self.templates.append({
                "id": target, "name": values["name"],
                "template_type": values["template_type"], "create_user_id": 7,
            })
            self._add_members(target, values["target_id_list"])
        elif operation_id == TEMPLATE_APPEND:
            self._add_members(values["id"], values["target_id_list"])
        else:
            field = "event_id_list" if operation_id == TEMPLATE_EVENT_REMOVE else "property_id_list"
            removed = set(values[field])
            self.members = [
                row for row in self.members
                if row["template_id"] != values["template_id"] or row["id"] not in removed
            ]
        return {"operation_id": operation_id, "attempts": 1}

    def _add_members(self, template_id: int, ids: list[int]) -> None:
        existing = {(row["template_id"], row["name"]) for row in self.members}
        self.members.extend(
            {"id": item + 1_000, "template_id": template_id, "name": f"p{item}"}
            for item in ids if (template_id, f"p{item}") not in existing
        )

    def read_all(self, operation_id: str, inputs: dict, **_options) -> dict:
        self.reads += 1
        if operation_id == TEMPLATE_LIST:
            rows = list(self.templates)
        elif operation_id in {TEMPLATE_EVENT_MEMBERS, TEMPLATE_PROPERTY_MEMBERS}:
            selected = inputs["filters"][0]["values"][0]
            rows = [row for row in self.members if row["template_id"] == selected]
        else:
            rows = list(self.targets)
        return {
            "status": "success", "error": None, "truncated": False,
            "next_page_input": None, "data": {"list": rows},
        }


class MetadataTemplateMutationTests(unittest.TestCase):
    def test_successful_write_invalidates_metadata_readback_cache(self) -> None:
        class Executor:
            @staticmethod
            def execute(operation_id, _inputs):
                return {"operation_id": operation_id}

        class Cache:
            clears = 0

            def clear(self):
                self.clears += 1

        client = object.__new__(MutationClientMixin)
        client._mutation_executor, client._metadata_cache = Executor(), Cache()
        client._execute_mutation(TEMPLATE_MASTER, {"name": "x"})
        self.assertEqual(1, client._metadata_cache.clears)

    def test_round_trip_marker_append_remove_and_delete_guards(self) -> None:
        client = _Client()
        preview = create_metadata_template(
            client, app_id=9, name="Acceptance", template_type="event_property",
            target_ids=[11], idempotency_key="roundtrip",
        )
        self.assertTrue(preview["dry_run"])
        self.assertEqual((0, 0), (client.reads, client.writes))

        created = create_metadata_template(
            client, app_id=9, name="Acceptance", template_type="event_property",
            target_ids=[11], idempotency_key="roundtrip", execute=True,
        )
        template_id = created["target"]["id"]
        appended = append_metadata_template_members(
            client, app_id=9, template_id=template_id, target_ids=[12], execute=True,
        )
        removed = remove_metadata_template_members(
            client, template_id=template_id, member_ids=[1012], execute=True,
        )
        deleted = delete_metadata_template(client, template_id=template_id, execute=True)

        self.assertRegex(created["target"]["name"], r"GSDK-[0-9a-f]{12}")
        self.assertEqual("sdk_source_marker", appended["target"]["ownership"]["basis"])
        self.assertEqual("sdk_source_marker", removed["target"]["ownership"]["basis"])
        self.assertTrue(deleted["target"]["deleted"])
        self.assertEqual(([], []), (client.templates, client.members))
        self.assertEqual(4, client.writes)

    def test_owner_gate_blocks_foreign_template_before_delete(self) -> None:
        client = _Client()
        client.templates = [{
            "id": 50, "name": "Foreign", "template_type": "event_property",
            "create_user_id": 8,
        }]
        with self.assertRaises(InputValidationError) as captured:
            delete_metadata_template(client, template_id=50, execute=True)
        self.assertEqual("OWNERSHIP_REQUIRED", captured.exception.code)
        self.assertEqual(0, client.writes)
        client.templates[0]["create_user_id"] = 7
        result = delete_metadata_template(client, template_id=50, execute=True)
        self.assertEqual("upstream_owner", result["target"]["ownership"]["basis"])

    def test_delete_guard_rejects_acknowledgement_without_disappearance(self) -> None:
        client = _Client()
        client.templates = [{
            "id": 51, "name": "Guard [GSDK-aabbccddeeff]",
            "template_type": "event_property", "create_user_id": 7,
        }]
        client._execute_mutation = lambda operation_id, _values: {
            "operation_id": operation_id, "attempts": 1,
        }
        with self.assertRaisesRegex(ContractChangedError, "still exists"):
            delete_metadata_template(client, template_id=51, execute=True)

    def test_contracts_cards_cli_sdk_and_plan_are_action_qualified(self) -> None:
        cases = {
            TEMPLATE_MASTER: "/turbo_engine/api/v2/event/property_template/create/",
            TEMPLATE_APPEND: "/turbo_engine/api/v2/event/property_template/append/",
            TEMPLATE_EVENT_REMOVE: "/turbo_engine/api/v2/event/property_template/event_delete/",
            TEMPLATE_PROPERTY_REMOVE: "/turbo_engine/api/v2/event/property_template/property_delete/",
        }
        for operation_id, path in cases.items():
            source = json.loads((ROOT / "src/gravity_sdk/contracts/operations" / f"{operation_id}.json").read_text(encoding="utf-8"))["operation"]
            self.assertEqual(("POST", path, "mutation", "stable", True), (
                source["upstream_method"], source["path_template"], source["effect"],
                source["stability"], source["executable"],
            ))
        cards = metadata_template_capability_inventory()
        self.assertEqual(set(SELECTORS.values()), {card["selector"] for card in cards})
        self.assertTrue(all(card["operation_ids"] for card in cards))
        self.assertTrue(all(card["confirmation_required"] for card in cards))
        self.assertTrue(all(not card["next"]["ready_without_input"] for card in cards))
        parsed = build_parser().parse_args(["metadata", "property-templates", "schema"])
        self.assertEqual("schema", parsed.metadata_template_command)
        sdk = GravitySDK(insight=_Client())
        self.assertTrue(sdk.metadata_template_mutation(
            "delete", {"template_id": 1}
        )["dry_run"])
        request = {
            "name": "metadata_template_mutation", "mode": "preview",
            "inputs": {"action": "delete", "inputs": {"template_id": 1}},
        }
        context = AdapterContext("metadata", "test", "composite", None, (), (), 5, 20)
        validate_metadata_template_plan(request, context)


if __name__ == "__main__":
    unittest.main()
