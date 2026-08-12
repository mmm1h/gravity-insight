from __future__ import annotations

import argparse
import json
import unittest
from unittest.mock import patch

from gravity_sdk.errors import InputValidationError, PaginationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_user_journey_adapter import (
    execute_user_journey_plan,
    project_user_journey_result,
    validate_user_journey_plan,
)
from gravity_sdk.user_journey import USER_JOURNEY_OPERATIONS, user_journey
from gravity_sdk.user_journey_cli import add_user_journey_command


class _BatchClient:
    def __init__(self, *, omit: str | None = None, duplicate: bool = False, event_count: int = 0, error_message: str | None = None) -> None:
        self.omit = omit
        self.duplicate = duplicate
        self.event_count = event_count
        self.error_message = error_message
        self.calls: list[tuple[list[dict], int, int, int]] = []

    def batch(
        self, requests, *, max_workers=6, max_pages=1_000, max_total_items=100_000
    ):
        copied = [dict(item) for item in requests]
        self.calls.append((copied, max_workers, max_pages, max_total_items))
        results = []
        for request in reversed(copied):
            if request["request_id"] == self.omit:
                continue
            if request["request_id"] == "events" and self.error_message:
                results.append({"operation_id": request["operation_id"], "request_id": "events", "ok": False, "status": "error", "data": None, "error": {"category": "local", "code": "LOCAL_IO_ERROR", "message": self.error_message, "next_action": self.error_message}})
                continue
            payload = {"list": [{"source": request["request_id"], "ClientID": "north-secret", "note": "seen north-secret"}]}
            if request["request_id"] == "events" and self.event_count:
                payload = {"event_timeline": [{"list": list(range(self.event_count))}]}
            if request["request_id"] == "postbacks":
                payload["list"][0].update({"event_type": "paid", "trace_id": "grid"})
            results.append(
                {
                    "operation_id": request["operation_id"],
                    "request_id": request["request_id"],
                    "ok": True,
                    "status": "success",
                    "data": {
                        "status": "success",
                        "data": payload,
                    },
                }
            )
        if self.duplicate:
            results.append(dict(results[0]))
        return results


class _Workspace:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def resolve_app(self, value):
        self.calls.append(value)
        return 17


def _context(workspace, *, targets=(), fields=()):
    return AdapterContext(
        node_id="journey",
        execution_id="journey",
        kind="composite",
        workspace=workspace,
        output_fields=tuple(fields),
        dynamic_targets=tuple(targets),
        max_pages=1,
        max_items=100,
    )


class UserJourneyTests(unittest.TestCase):
    def test_batch_is_keyed_ordered_partial_and_secret_free(self):
        client = _BatchClient(omit="postbacks")
        result = user_journey(
            client, 17, "north-secret", date_value="2026-08-12", max_workers=8
        )

        self.assertEqual(
            [item[0] for item in USER_JOURNEY_OPERATIONS],
            [item["source"] for item in result["results"]],
        )
        self.assertEqual("BATCH_RESULT_MISSING", result["results"][2]["error"]["code"])
        self.assertEqual("partial", result["status"])
        requests, workers, pages, _items = client.calls[0]
        self.assertEqual((3, 1), (workers, pages))
        self.assertEqual("2026-08-12", requests[0]["inputs"]["date"])
        self.assertNotIn("north-secret", json.dumps(result))
        self.assertNotIn("request_id", json.dumps(result))
        rendered = json.dumps(user_journey(_BatchClient(error_message=r"C:\\Users\\alice\\secret.txt: original boom"), 17, "id", date_value="2026-08-12"))
        self.assertNotIn("alice", rendered)
        self.assertIn("paid", rendered)
        self.assertIn("grid", rendered)
        with self.assertRaises(RuntimeError):
            user_journey(
                _BatchClient(duplicate=True),
                17,
                "north-secret",
                date_value="2026-08-12",
            )
        with self.assertRaises(PaginationError):
            user_journey(
                _BatchClient(event_count=10), 17, "north-secret",
                date_value="2026-08-12", max_items=3,
            )

    def test_dates_and_explicit_event_page_follow_source_contracts(self):
        client = _BatchClient()
        result = user_journey(
            client,
            "17",
            "north-secret",
            start="2026-08-01",
            end="2026-08-12",
            page=4,
            page_size=25,
            events=("purchase",),
        )

        by_source = {item["request_id"]: item["inputs"] for item in client.calls[0][0]}
        self.assertNotIn("date_list", by_source["profile"])
        self.assertEqual(
            ["2026-08-01", "2026-08-12"], by_source["events"]["date_list"]
        )
        self.assertEqual((4, 25), (by_source["events"]["page"], by_source["events"]["page_size"]))
        self.assertFalse(result["continuation"]["automatic"])
        with self.assertRaises(InputValidationError):
            user_journey(client, 17, "north-secret", start="2026-08-12")

    def test_cli_helper_resolves_app_once_and_delegates(self):
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command", required=True)
        add_user_journey_command(commands, int, int)
        args = parser.parse_args(
            [
                "user", "journey", "--app", "main", "--client-id", "north-secret",
                "--start", "2026-08-01", "--end", "2026-08-12",
                "--event", "open,purchase", "--page", "2",
            ]
        )
        with (
            patch("gravity_sdk.user_journey_cli.load_workspace") as load,
            patch("gravity_sdk.user_journey_cli.resolve_workspace_app", return_value=17) as resolve,
            patch("gravity_sdk.user_journey_cli.runtime.build_client", return_value=object()),
            patch("gravity_sdk.user_journey_cli.user_journey", return_value={"ok": True}) as run,
        ):
            result = args._gravity_handler(args, lambda _value: {})

        self.assertTrue(result["ok"])
        resolve.assert_called_once_with(load.return_value, "main")
        self.assertEqual(("open", "purchase"), run.call_args.kwargs["events"])

    def test_plan_preflight_bindings_execution_and_projection_are_safe(self):
        workspace = _Workspace()
        dynamic = _context(workspace, targets=("/app", "/client_id"), fields=("results",))
        validate_user_journey_plan(
            {"name": "user_journey", "date": "2026-08-12"}, dynamic, workspace
        )
        with self.assertRaises(InputValidationError):
            validate_user_journey_plan(
                {"name": "user_journey", "date": "2026-08-12"},
                _context(workspace, targets=("/page",)),
                workspace,
            )

        sdk = type("Sdk", (), {"insight": _BatchClient()})()
        literal = _context(workspace, fields=("results",))
        request = {
            "name": "user_journey",
            "app": "main",
            "client_id": "north-secret",
            "date": "2026-08-12",
        }
        validate_user_journey_plan(request, literal, workspace)
        result = execute_user_journey_plan(sdk, request, literal)
        projected = project_user_journey_result(result, ("results",), literal)
        self.assertEqual(3, len(projected["results"]))
        self.assertEqual(1, sdk.insight.calls[0][1])
        self.assertNotIn("north-secret", json.dumps(projected))
        self.assertNotIn("client_id", json.dumps(projected).casefold())


if __name__ == "__main__":
    unittest.main()
