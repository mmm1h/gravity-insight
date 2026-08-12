from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from gravity_sdk.errors import InputValidationError, UnsupportedOperationError
from gravity_sdk.saved_analysis import (
    GET_OPERATION_ID,
    LIST_OPERATION_ID,
    compile_saved_analysis_definition,
    execute_saved_analysis,
    inspect_saved_analysis,
    list_saved_analyses,
    resolve_saved_analysis,
)
from gravity_sdk.workspace import Workspace, WorkspaceDefaults


def workspace() -> Workspace:
    root = Path.cwd()
    return Workspace(
        path=None,
        root=root,
        state_root=root,
        apps={"main": 101},
        defaults=WorkspaceDefaults(app="main", timezone="Asia/Shanghai", time_window=None),
        datasources={},
        products={},
        recipes={},
    )


def definition(**updates: Any) -> dict[str, Any]:
    value = {
        "id": "8",
        "app_id": "101",
        "name": "daily purchases",
        "subject": "analysis_event",
        "config": {
            "start": "2026-08-01",
            "end": "2026-08-02",
            "steps": [
                {
                    "event": "purchase",
                    "metric": {
                        "field": "PresetAllCount",
                        "aggregation": "PresetAllCount",
                    },
                }
            ],
        },
    }
    value.update(updates)
    return value


class Client:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [
            {key: value for key, value in definition().items() if key != "config"}
        ]
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def read_all(
        self,
        operation_id: str,
        inputs: dict[str, Any],
        *,
        max_pages: int,
        max_items: int,
        max_workers: int,
    ) -> dict[str, Any]:
        self.calls.append(("read_all", operation_id, inputs))
        return {"status": "success", "data": {"list": self.rows}, "error": None}

    def read(self, operation_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("read", operation_id, inputs))
        if operation_id == GET_OPERATION_ID:
            saved = definition()
            return {
                "status": "success",
                "data": {"name": saved["name"], "config": json.dumps(saved["config"])},
                "error": None,
            }
        return {
            "status": "success",
            "request": {"must": "not leak"},
            "data": {"series": [{"value": 7, "values": [1, 2]}]},
            "error": None,
        }

    def validate(self, operation_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("validate", operation_id, inputs))
        return {
            "ok": True,
            "status": "needs_live_metadata",
            "live_metadata_dependencies": ["analysis.event.list"],
        }


class SavedAnalysisTests(unittest.TestCase):
    def test_catalog_is_bounded_and_never_fetches_opaque_config(self) -> None:
        client = Client()
        result = list_saved_analyses(client, "main", workspace=workspace())

        self.assertEqual("success", result["status"])
        self.assertEqual("event", result["items"][0]["kind"])
        self.assertNotIn("config", result["items"][0])
        self.assertEqual(
            [("read_all", LIST_OPERATION_ID, {"app_id": "101", "page": 1, "page_size": 1})],
            client.calls,
        )

    def test_explicit_definition_compiles_offline_and_web_shape_fails_closed(self) -> None:
        client = Client()
        preview = compile_saved_analysis_definition(
            client, definition(), "main", workspace=workspace()
        )

        self.assertFalse(preview["network_called"])
        self.assertFalse(preview["query_executed"])
        self.assertEqual(["validate"], [call[0] for call in client.calls])
        with self.assertRaises(InputValidationError):
            compile_saved_analysis_definition(
                client,
                definition(config={"commonFilter": []}),
                "main",
                workspace=workspace(),
            )
        with self.assertRaises(UnsupportedOperationError):
            compile_saved_analysis_definition(
                client,
                definition(subject="analysis_cash"),
                "main",
                workspace=workspace(),
            )

    def test_exact_name_resolution_and_ambiguity_are_fail_closed(self) -> None:
        client = Client()
        preview = resolve_saved_analysis(
            client, {"name": "daily purchases"}, "main", workspace=workspace()
        )
        self.assertTrue(preview["network_called"])
        self.assertEqual("8", preview["saved_analysis"]["id"])

        duplicate = {**client.rows[0], "id": "9"}
        with self.assertRaises(InputValidationError):
            resolve_saved_analysis(
                Client([client.rows[0], duplicate]),
                {"name": "daily purchases"},
                "main",
                workspace=workspace(),
            )

        web_client = Client()
        web_client.read = lambda operation_id, inputs: {
            "status": "success",
            "data": {"name": "daily purchases", "config": '{"commonFilter":[]}'},
            "error": None,
        }
        inspected = inspect_saved_analysis(
            web_client, {"id": "8"}, "main", workspace=workspace()
        )
        self.assertEqual("unsupported", inspected["replay_status"])
        self.assertFalse(inspected["saved_analysis"]["replay_supported"])
        self.assertEqual("UNSUPPORTED", inspected["blocker"]["code"])
        self.assertNotIn("config", inspected["saved_analysis"])
        self.assertNotIn("commonFilter", json.dumps(inspected))

    def test_execute_preserves_result_values_but_omits_request(self) -> None:
        result = execute_saved_analysis(
            Client(), definition=definition(), app="main", workspace=workspace()
        )

        self.assertTrue(result["query_executed"])
        self.assertNotIn("request", result["result"])
        self.assertEqual(
            {"value": 7, "values": [1, 2]},
            result["result"]["data"]["series"][0],
        )


if __name__ == "__main__":
    unittest.main()
