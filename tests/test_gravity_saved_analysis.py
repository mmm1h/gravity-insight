from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from gravity_sdk import Credential, GravityInsightClient
from gravity_sdk.errors import (
    ContractChangedError,
    InputValidationError,
    PaginationError,
    UnsupportedOperationError,
)
from gravity_sdk.saved_analysis import (
    GET_OPERATION_ID,
    LIST_OPERATION_ID,
    compile_saved_analysis_definition,
    execute_saved_analysis,
    inspect_saved_analysis,
    list_saved_analyses,
    resolve_saved_analysis,
)
from gravity_sdk.saved_analysis_result import saved_result_item_count
from gravity_sdk.domains import ANALYSIS_QUERY_OPERATIONS
from gravity_sdk.http_runtime import GravityHttpRuntime
from gravity_sdk.workspace import Workspace, WorkspaceDefaults


class NetworkForbiddenSession:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls += 1
        raise AssertionError("offline validation reached HTTP")


class StaticCredentials:
    def get(self, *, force_refresh: bool = False) -> Credential:
        return Credential("opaque")


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


def web_definition(**updates: Any) -> dict[str, Any]:
    event = {
        "cond_logic": "AND",
        "conditions": [],
        "custom_name": "purchase",
        "event_index": 0,
        "event_label": "purchase",
        "event_name": "purchase",
        "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
    }
    value = definition(
        config={
            "calculateBody": {
                "query_item_list": [event],
                "group_by_list": [
                    {
                        "type": "default_event",
                        "field": "create_time",
                        "group_by": "day",
                    }
                ],
            },
            "groupByCreateTime": {"value": "day"},
            "tableShowType": "table",
            "aggregate_config": {},
            "date_list": [
                {"start_date": "2025-01-01", "end_date": "2025-01-02"}
            ],
            "queryItemList": [],
        }
    )
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
            "data": {"list": [{"value": 7, "values": [1, 2]}]},
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
        self.assertTrue(result["items"][0]["replay_supported"])
        self.assertEqual("unchecked", result["items"][0]["replay_status"])
        self.assertNotIn("config", result["items"][0])
        self.assertEqual(
            [("read_all", LIST_OPERATION_ID, {"app_id": "101", "page": 1, "page_size": 1_000})],
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
        with self.assertRaises(ContractChangedError):
            resolve_saved_analysis(
                Client([client.rows[0], {**client.rows[0], "name": "conflict"}]),
                {"id": "8"}, "main", workspace=workspace(),
            )

        truncated = Client()
        truncated.read_all = lambda *args, **kwargs: {
            "status": "success", "data": {"list": truncated.rows},
            "error": None, "truncated": True, "next_page_input": {"page": 2},
        }
        with self.assertRaises(PaginationError):
            resolve_saved_analysis(
                truncated, {"id": "8"}, "main", workspace=workspace(),
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
            result["result"]["data"]["list"][0],
        )

        empty_error = Client()
        empty_error.read = lambda operation_id, inputs: {
            "status": "success", "data": {"list": []}, "error": {}
        }
        self.assertTrue(execute_saved_analysis(
            empty_error, definition=definition(), app="main", workspace=workspace()
        )["ok"])

        families = {
            "event": {"list": [{}, {}]},
            "property": {"list": [{}, {}]},
            "retention": {"total": [{}, {}]},
            "funnel": {"aggregate_by_date": {"one": {}, "two": {}}},
            "scatter": {"aggregate_date": [[1], [2]]},
        }
        for kind, data in families.items():
            self.assertEqual(2, saved_result_item_count(
                ANALYSIS_QUERY_OPERATIONS[kind], {"data": data}
            ))
        with self.assertRaises(ContractChangedError):
            saved_result_item_count(
                ANALYSIS_QUERY_OPERATIONS["funnel"], {"data": {"aggregate_by_date": 7}}
            )
        self.assertEqual(500, saved_result_item_count(
            ANALYSIS_QUERY_OPERATIONS["event"], {"data": {"list": [[{}] * 500]}}
        ))
        with self.assertRaises(ContractChangedError):
            saved_result_item_count(
                ANALYSIS_QUERY_OPERATIONS["event"], {"data": {"list": [], "raw": "x"}}
            )

    def test_web_artifact_requires_window_then_compiles_through_shared_boundary(self) -> None:
        invalid = Client()
        with self.assertRaises(InputValidationError):
            inspect_saved_analysis(
                invalid, {"id": "8"}, "main", workspace=workspace(), start="2026-08-01"
            )
        self.assertEqual([], invalid.calls)
        client = Client()
        # Replace the catalog detail with a proven persisted Web artifact.
        client.read = lambda operation_id, inputs: (
            {
                "status": "success",
                "data": {
                    "name": "daily purchases",
                    "config": json.dumps(web_definition()["config"]),
                },
                "error": None,
            }
            if operation_id == GET_OPERATION_ID
            else Client.read(client, operation_id, inputs)
        )
        inspected = inspect_saved_analysis(
            client, {"id": "8"}, "main", workspace=workspace()
        )
        self.assertEqual("web_artifact", inspected["artifact_mode"])
        self.assertEqual("requires_window", inspected["replay_status"])
        self.assertFalse(inspected["saved_analysis"]["replay_supported"])
        self.assertIsNone(inspected["date_range"])

        prepared = compile_saved_analysis_definition(
            client,
            web_definition(),
            "main",
            workspace=workspace(),
            start="2026-08-01",
            end="2026-08-07",
        )
        self.assertEqual("web_artifact", prepared["artifact_mode"])
        self.assertIsNone(prepared["compiled_input"])
        self.assertTrue(prepared["input_values_redacted"])
        self.assertEqual("2026-08-01", prepared["date_range"]["start"])
        session = NetworkForbiddenSession()
        runtime = GravityHttpRuntime(session=session, credentials=StaticCredentials())
        real_client = GravityInsightClient.from_env(runtime=runtime, attempts=1)
        real_prepared = compile_saved_analysis_definition(
            real_client, web_definition(), "main", workspace=workspace(),
            start="2026-08-01", end="2026-08-07",
        )
        self.assertEqual(
            ["analysis.event.list", "analysis.event_property.list"],
            real_prepared["validation"]["live_metadata_dependencies"],
        )
        self.assertEqual(0, session.calls)

    def test_web_artifact_unknown_semantics_and_query_errors_are_safe(self) -> None:
        client = Client()
        bad = web_definition()
        bad["config"]["future_semantic"] = {"private": "secret"}
        with self.assertRaises(UnsupportedOperationError):
            compile_saved_analysis_definition(
                client,
                bad,
                "main",
                workspace=workspace(),
                start="2026-08-01",
                end="2026-08-07",
            )

        client.read = lambda operation_id, inputs: {
            "status": "error",
            "request": {"secret": "must-not-leak"},
            "error": {
                "code": "UPSTREAM_UNAVAILABLE",
                "category": "upstream",
                "message": "C:/private/raw-error.txt",
            },
        }
        result = execute_saved_analysis(
            client,
            definition=web_definition(),
            app="main",
            workspace=workspace(),
            start="2026-08-01",
            end="2026-08-07",
        )
        encoded = json.dumps(result)
        self.assertFalse(result["ok"])
        self.assertNotIn("raw-error", encoded)
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn("calculateBody", encoded)
        self.assertIsNone(result["result"]["data"])


if __name__ == "__main__":
    unittest.main()
