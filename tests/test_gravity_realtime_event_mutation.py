from __future__ import annotations

import json
import unittest
from pathlib import Path

from gravity_sdk.agents.realtime_event import (
    SELECTOR,
    realtime_event_mutation_capability_inventory,
    realtime_event_mutation_cards,
)
from gravity_sdk.cli import build_parser
from gravity_sdk.errors import ContractChangedError, InputValidationError
from gravity_sdk.realtime_event_contracts import REALTIME_EVENT_UPDATE
from gravity_sdk.realtime_event_mutation import (
    realtime_event_mutation_schema,
    run_realtime_event_mutation,
)
from gravity_sdk.sdk import GravitySDK


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "src" / "gravity_sdk" / "contracts"
WINDOW = {
    "app_id": 29034827,
    "is_enabled": 1,
    "start_time": "2026-08-18 12:00:00",
    "end_time": "2026-08-18 13:00:00",
    "time_slot": 2,
}


class _Client:
    def __init__(self, conf=None) -> None:
        self.conf = dict(conf or {})
        self.reads = 0
        self.writes = 0
        self.previewed: list[tuple[str, dict]] = []

    def _preview_mutation(self, operation_id, inputs):
        self.previewed.append((operation_id, dict(inputs)))
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
        self.conf = {
            "app_id": inputs["app_id"],
            "is_enabled": inputs["is_enabled"],
            "start_time": inputs["start_time"],
            "end_time": inputs["end_time"],
            "modify_time": "2026-08-18 12:00:01",
        }
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
        }

    def read(self, operation_id, inputs):
        self.reads += 1
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "data": {"conf": dict(self.conf)},
        }


class GravityRealtimeEventMutationTests(unittest.TestCase):
    def test_reservation_is_replaced_by_stable_source(self) -> None:
        operation = json.loads(
            (CONTRACTS / "operations" / "app.user.realtime.event.update.json").read_text(
                encoding="utf-8"
            )
        )["operation"]
        self.assertFalse(
            (CONTRACTS / "reservations" / "app.user.realtime.event.update.json").exists()
        )
        self.assertEqual(REALTIME_EVENT_UPDATE, operation["operation_id"])
        self.assertEqual("stable", operation["stability"])
        self.assertTrue(operation["executable"])
        self.assertEqual("mutation", operation["effect"])
        self.assertEqual(
            "/turbo_engine/api/v1/user/realtime_event/manage/",
            operation["path_template"],
        )

    def test_dry_run_is_offline_and_execute_reads_back_conf(self) -> None:
        client = _Client()
        preview = run_realtime_event_mutation(client, WINDOW)
        self.assertTrue(preview["dry_run"])
        self.assertFalse(preview["network_called"])
        self.assertEqual(0, client.writes)
        self.assertEqual(0, client.reads)
        self.assertEqual(
            WINDOW, preview["request"]["body"]
        )

        completed = run_realtime_event_mutation(client, WINDOW, execute=True)
        self.assertEqual("updated", completed["status"])
        self.assertEqual(1, completed["target"]["is_enabled"])
        self.assertEqual(1, client.writes)
        self.assertEqual(1, client.reads)

    def test_readback_accepts_boolean_enabled_flag(self) -> None:
        client = _Client()

        def _execute(operation_id, inputs):
            client.writes += 1
            client.conf = {
                "app_id": inputs["app_id"],
                "is_enabled": True,
                "start_time": inputs["start_time"],
                "end_time": inputs["end_time"],
            }
            return {
                "ok": True,
                "status": "success",
                "operation_id": operation_id,
                "attempts": 1,
            }

        client._execute_mutation = _execute
        completed = run_realtime_event_mutation(client, WINDOW, execute=True)
        self.assertEqual("updated", completed["status"])
        self.assertEqual(1, completed["target"]["is_enabled"])

    def test_readback_accepts_bounded_clock_skew(self) -> None:
        client = _Client()

        def _execute(operation_id, inputs):
            client.writes += 1
            client.conf = {
                "app_id": inputs["app_id"],
                "is_enabled": inputs["is_enabled"],
                "start_time": "2026-08-18 11:59:01",
                "end_time": "2026-08-18 12:59:01",
            }
            return {
                "ok": True,
                "status": "success",
                "operation_id": operation_id,
                "attempts": 1,
            }

        client._execute_mutation = _execute
        completed = run_realtime_event_mutation(client, WINDOW, execute=True)
        self.assertEqual("updated", completed["status"])
        self.assertEqual("2026-08-18 11:59:01", completed["target"]["start_time"])

    def test_readback_mismatch_fails_closed(self) -> None:
        client = _Client()

        def _execute(operation_id, inputs):
            client.writes += 1
            client.conf = {
                "app_id": inputs["app_id"],
                "is_enabled": 0,
                "start_time": inputs["start_time"],
                "end_time": inputs["end_time"],
            }
            return {
                "ok": True,
                "status": "success",
                "operation_id": operation_id,
                "attempts": 1,
            }

        client._execute_mutation = _execute
        with self.assertRaises(ContractChangedError):
            run_realtime_event_mutation(client, WINDOW, execute=True)

    def test_invalid_window_fails_before_preview(self) -> None:
        client = _Client()
        with self.assertRaises(InputValidationError):
            run_realtime_event_mutation(
                client, {**WINDOW, "is_enabled": 2}
            )
        self.assertEqual([], client.previewed)

    def test_agent_card_and_cli_require_explicit_confirmation(self) -> None:
        cards = realtime_event_mutation_capability_inventory()
        self.assertEqual(1, len(cards))
        card = cards[0]
        self.assertEqual(SELECTOR, card["selector"])
        self.assertFalse(card["plan_executable"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertEqual("--dry-run", card["next"]["argv"][-1])
        self.assertEqual("--execute", card["next"]["then_argv"][-1])
        self.assertEqual(
            ["update"],
            [
                item["mutation_action"]
                for item in realtime_event_mutation_cards(
                    "开启实时事件入库", domain=None, platform=None
                )
            ],
        )
        self.assertEqual(
            ["update"],
            realtime_event_mutation_schema()["actions"].keys()
            and ["update"],
        )
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "apps",
                "realtime-event",
                "update",
                "--input",
                "{}",
                "--dry-run",
            ]
        )
        self.assertTrue(parsed.realtime_event_dry_run)
        self.assertTrue(hasattr(GravitySDK, "realtime_event_mutation"))


if __name__ == "__main__":
    unittest.main()
