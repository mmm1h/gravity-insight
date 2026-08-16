from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from gravity_sdk.agent_custom_metric import (
    SELECTORS,
    custom_metric_capability_inventory,
    custom_metric_cards,
)
from gravity_sdk.cli import build_parser
from gravity_sdk.custom_metric_contracts import (
    CUSTOM_METRIC_DELETE,
    CUSTOM_METRIC_UPSERT,
)
from gravity_sdk.custom_metric_mutation import (
    create_custom_metric,
    delete_custom_metric,
    update_custom_metric,
)
from gravity_sdk.custom_metric_wire import validate_custom_metric_wire
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_custom_metric_adapter import validate_custom_metric_plan
from gravity_sdk.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "src" / "gravity_sdk" / "contracts"


class _Client:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])
        self.reads = 0
        self.writes = 0

    def _preview_mutation(self, operation_id, inputs):
        return {
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "effect": "mutation",
            "offline": True,
            "network_called": False,
            "attempts": 0,
            "request": {"method": "POST", "body": dict(inputs)},
        }

    def _execute_mutation(self, operation_id, inputs):
        self.writes += 1
        if operation_id == CUSTOM_METRIC_UPSERT:
            existing = next(
                (
                    item
                    for item in self.rows
                    if item.get("id") == inputs.get("id")
                ),
                {},
            )
            row = {
                **existing,
                "id": inputs.get("id", "metric_41"),
                "cname": inputs["cname"],
                "tip": inputs["tip"],
                "formula": inputs["formula"],
                "display_format": inputs["display_format"],
                "config": inputs["config"],
                "exclusion_dims": [],
                "tag_ids": [],
            }
            self.rows = [item for item in self.rows if item.get("id") != row["id"]]
            self.rows.append(row)
        elif operation_id == CUSTOM_METRIC_DELETE:
            self.rows = [item for item in self.rows if item.get("id") != inputs["id"]]
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
            "http_receipts": [{"receipt_id": f"write-{self.writes}"}],
        }

    def read_all(self, operation_id, inputs, **options):
        self.reads += 1
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "data": {"list": [dict(item) for item in self.rows], "page_info": {"total_page": 1}},
            "truncated": False,
            "next_page_input": None,
        }

    def _current_principal_id(self):
        return "7"


class GravityCustomMetricMutationTests(unittest.TestCase):
    def test_frontend_upsert_and_hash_delete_are_registered_without_replacing_old_routes(self) -> None:
        operation_root = CONTRACTS / "operations"
        reservation_root = CONTRACTS / "reservations"
        upsert = json.loads((operation_root / "report.confmetric.custom.metric.update.json").read_text(encoding="utf-8"))["operation"]
        current_delete = json.loads((operation_root / "report.confmetric.custom.metric.8ef6d12d.delete.json").read_text(encoding="utf-8"))["operation"]
        current_list = json.loads((operation_root / "report.custom_metric.list.json").read_text(encoding="utf-8"))["operation"]
        old_list = json.loads((operation_root / "report.multidim.custom_metric.list.json").read_text(encoding="utf-8"))["operation"]
        old_delete = json.loads((reservation_root / "report.confmetric.custom.metric.delete.json").read_text(encoding="utf-8"))["operation"]

        self.assertEqual("/turbo_engine/api/v3/confmetric/custom_metric/edit/", upsert["path_template"])
        self.assertFalse(upsert["input_fields"]["id"].get("required", False))
        self.assertEqual("string", upsert["input_fields"]["id"]["type"])
        self.assertEqual("/turbo_engine/api/v3/confmetric/custom_metric/delete/", current_delete["path_template"])
        self.assertEqual("8ef6d12d", hashlib.sha256(b"POST /turbo_engine/api/v3/confmetric/custom_metric/delete/").hexdigest()[:8])
        self.assertEqual("/turbo_engine/api/v3/confmetric/custom_metric/list/", current_list["path_template"])
        self.assertEqual(5000, current_list["pagination"]["max_page_size"])
        self.assertEqual("/report/api/v3/confmetric/custom_metric/list/", old_list["path_template"])
        self.assertEqual("/report/api/v3/confmetric/custom_metric/delete/", old_delete["path_template"])

    def test_permission_and_role_metric_config_remain_blocked_reservations(self) -> None:
        root = CONTRACTS / "reservations"
        create = json.loads((root / "metadata.engine.datamanageconfig.metrics.create.json").read_text(encoding="utf-8"))["operation"]
        permission = json.loads((root / "report.engine.confmetric.permission.update.json").read_text(encoding="utf-8"))["operation"]

        self.assertEqual("/turbo_engine/api/v2/datamanageconfig/report_metrics/create/", create["path_template"])
        self.assertFalse(create["executable"])
        self.assertEqual("/turbo_engine/api/v3/confmetric/permission/edit/", permission["path_template"])
        self.assertFalse(permission["executable"])

    def test_create_update_delete_round_trip_marker_and_reuse_owner_gate(self) -> None:
        client = _Client()
        created = create_custom_metric(
            client, name="SDK口径", formula="ap_cost", description="contract",
            idempotency_key="roundtrip", execute=True,
        )
        metric_id = created["target"]["id"]
        updated = update_custom_metric(
            client, metric_id=metric_id, name="SDK口径v2", formula="ap_cost+0",
            description="updated", display_format=2, execute=True,
        )
        deleted = delete_custom_metric(client, metric_id=metric_id, execute=True)

        self.assertRegex(created["target"]["tip"], r"GSDK-[0-9a-f]{12}")
        self.assertEqual("sdk_source_marker", updated["target"]["ownership"]["basis"])
        self.assertEqual("sdk_source_marker", deleted["target"]["ownership"]["basis"])
        self.assertEqual([], client.rows)
        self.assertEqual(3, client.writes)
        self.assertEqual(6, client.reads)

    def test_dry_run_is_offline_and_unmarked_delete_fails_before_write(self) -> None:
        client = _Client()
        preview = create_custom_metric(client, name="Preview", formula="ap_cost")
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["network_called"])
        self.assertEqual(0, client.reads)
        self.assertEqual(0, client.writes)
        client.rows = [{"id": "metric_9", "cname": "Foreign", "tip": "none", "formula": "ap_cost", "display_format": 1}]
        with self.assertRaises(InputValidationError) as captured:
            delete_custom_metric(client, metric_id="metric_9", execute=True)
        self.assertEqual("OWNERSHIP_REQUIRED", captured.exception.code)
        self.assertEqual(0, client.writes)
        client.rows[0]["create_user_id"] = 7
        updated = update_custom_metric(
            client, metric_id="metric_9", name="Owned", formula="ap_cost+0",
            execute=True,
        )
        owned = delete_custom_metric(client, metric_id="metric_9", execute=True)
        self.assertEqual("upstream_owner", updated["target"]["ownership"]["basis"])
        self.assertEqual("", updated["target"]["tip"])
        self.assertNotIn("GSDK-", updated["target"]["tip"])
        self.assertEqual("upstream_owner", owned["target"]["ownership"]["basis"])
        self.assertEqual(2, client.writes)

    def test_wire_rejects_config_drift(self) -> None:
        with self.assertRaises(InputValidationError) as captured:
            validate_custom_metric_wire(CUSTOM_METRIC_UPSERT, {
                "cname": "One", "tip": "GSDK-0123456789ab", "formula": "ap_cost",
                "display_format": 1, "config": "{}",
            })
        self.assertEqual("config", captured.exception.field)
        self.assertIn("Generate config", captured.exception.next_action)

    def test_sdk_cli_plan_and_four_agent_cards_expose_distinct_actions(self) -> None:
        client = _Client()
        sdk = GravitySDK(insight=client)
        preview = sdk.custom_metric_mutation("create", {"name": "SDK", "formula": "ap_cost"})
        request = {
            "name": "custom_metric_mutation", "mode": "preview",
            "inputs": {"action": "create", "inputs": {"name": "SDK", "formula": "ap_cost"}},
        }
        context = AdapterContext("metric", "test", "composite", None, (), (), 5, 20)
        validate_custom_metric_plan(request, context)
        parsed = build_parser().parse_args(["reports", "custom-metrics", "schema"])
        cards = custom_metric_capability_inventory()

        self.assertTrue(preview["dry_run"])
        self.assertEqual("schema", parsed.custom_metric_command)
        self.assertEqual(set(SELECTORS.values()), {card["selector"] for card in cards})
        self.assertEqual(4, len(cards))
        self.assertEqual("execute", custom_metric_cards("custom_metric.delete", domain=None, platform=None)[0]["next"]["then_plan_node"]["request"]["mode"])


if __name__ == "__main__":
    unittest.main()
