from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch
from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_input_catalogs import live_catalog_for_card
from gravity_sdk.agent_input_resolution import resolve_capabilities
from gravity_sdk.agent_analysis_task import analysis_task_cards
from gravity_sdk.agent_handoff import attach_plan_node
from gravity_sdk.cli import build_parser, main
from gravity_sdk.domains import MULTIDIM_METADATA_OPERATIONS
from gravity_sdk.errors import InputValidationError, UpstreamError
from gravity_sdk.plan import validate_plan
from gravity_sdk.saved_analysis_catalog import LIST_OPERATION_ID
from gravity_sdk.segment_snapshot import LIST_OPERATION as SEGMENT_LIST_OPERATION
from gravity_sdk.template_replay import TEMPLATE_OPERATIONS

class _NoOperations:
    def search_operations(self, *_args, **_options):
        return {"operations": [], "continuation_token": None}

class _Cache:
    def __init__(self) -> None: self.clears = 0
    def clear(self) -> None: self.clears += 1

class _Workspace:
    def resolve_app(self, value): return 7 if value == "main" else int(value)

class _CatalogClient:
    def __init__(self) -> None: self.batch_requests = []

    def read(self, _operation_id, _inputs):
        return {"ok": True, "status": "success", "data": [{"id": 1, "name": "space",
            "folder_or_dashboard": [{"id": 42, "name": "Growth", "space_id": 1}]}]}

    def read_all(self, operation_id, inputs, **_options):
        if operation_id == LIST_OPERATION_ID:
            rows = [{"id": 8, "app_id": inputs["app_id"], "name": "Saved", "subject": "event"}]
        elif operation_id in TEMPLATE_OPERATIONS.values():
            rows = [{"id": 9, "name": "Template"}]
        elif operation_id == SEGMENT_LIST_OPERATION:
            rows = [{"segment_id": 10, "segment_name": "Buyers", "app_id": inputs["app_id"]}]
        else:
            raise AssertionError(operation_id)
        return {"ok": True, "status": "success", "data": {"list": rows},
                "truncated": False, "next_page_input": None}

    def batch(self, requests):
        self.batch_requests = requests
        results = []
        for request in requests:
            operation_id = request["operation_id"]
            if operation_id == MULTIDIM_METADATA_OPERATIONS[0]:
                data = {"my_template": [{"id": 1, "name": "Mine"}], "share_template": []}
            elif operation_id == MULTIDIM_METADATA_OPERATIONS[1]:
                data = {"bytedance": {"optimization_goal": [{"code": 2, "name": "Install"}]}}
            else:
                data = {"list": [{"name": "cost"}]}
            results.append({"ok": True, "status": "success", "data": data})
        return results

def _scenario(card: dict, scenario_id: str) -> dict:
    return next(item for item in card["call_bound"]["scenarios"]
                if item["id"] == scenario_id)

def _catalog() -> dict:
    return {"schema_version": "gravity.agent-input-catalog.v1", "status": "success",
            "complete": True, "observed": "live", "selection": "caller_exact",
            "execution_revalidates": True,
            "catalogs": [{"selector": "safe.catalog", "count": 1,
                          "items": [{"id": "42"}]}]}

class AgentInputResolutionTests(unittest.TestCase):
    def test_seven_live_catalog_paths_lower_only_the_resolved_scenario(self) -> None:
        cases = (
            ("composite:saved_analysis", {"app": "1"}, "unknown_reference"),
            ("composite:dashboard_analysis", {"app": "1"}, "unknown_reference"),
            ("composite:dashboard_snapshot", {"app": "1"}, "unknown_reference"),
            ("composite:segment_snapshot", {"app": "1"}, "unknown_reference"),
            ("composite:analysis_template", {}, "unknown_reference"),
            ("composite:multidim", {}, "unknown_physical_inputs"),
            ("composite:promotion_performance", {"platforms": ["bytedance"]},
             "unknown_physical_inputs"),
        )
        for query, known_inputs, scenario_id in cases:
            with self.subTest(query=query), patch(
                "gravity_sdk.agent_input_resolution.live_catalog_for_card",
                return_value=_catalog(),
            ):
                client = _NoOperations()
                client._metadata_cache = _Cache()
                result = resolve_capabilities(query, known_inputs=known_inputs, client=client)
                card = result["candidates"][0]
                scenario = _scenario(card, scenario_id)
                self.assertEqual((2, 0), (scenario["minimum_calls"],
                                          scenario["discovery_calls"]))
                self.assertEqual("caller_exact", scenario["selection"])
                self.assertTrue(card["input_catalog"]["complete"])
                self.assertEqual(card["call_bound"], card["plan_node"]["call_bound"])
                validate_plan({"schema_version": "gravity.plan.v1",
                               "nodes": [card["plan_node"]]})
                self.assertFalse(result["offline"])
                self.assertTrue(result["network_called"])
                self.assertEqual(2, client._metadata_cache.clears)

    def test_default_offline_card_retains_the_three_call_bound(self) -> None:
        card = discover_capabilities("composite:saved_analysis",
                                     client=_NoOperations())["candidates"][0]
        self.assertEqual(3, _scenario(card, "unknown_reference")["minimum_calls"])

    def test_live_catalogs_return_complete_safe_candidates(self) -> None:
        client = _CatalogClient()
        dashboard = live_catalog_for_card({"composite": "dashboard_snapshot"},
            client=client, workspace=_Workspace(), known_inputs={"app": "main"})
        self.assertEqual(
            [{"id": "42", "name": "Growth", "space_id": "1"}],
            dashboard["catalogs"][0]["items"],
        )
        multidim = live_catalog_for_card({"composite": "multidim"}, client=client,
                                          workspace=None, known_inputs={})
        self.assertTrue(multidim["complete"])
        self.assertEqual(len(MULTIDIM_METADATA_OPERATIONS), len(multidim["catalogs"]))
        self.assertEqual("my_template", multidim["catalogs"][0]["items"][0]["catalog_path"])
        self.assertEqual("bytedance.optimization_goal",
                         multidim["catalogs"][1]["items"][0]["catalog_path"])
        promotion = live_catalog_for_card({"composite": "promotion_performance"},
            client=client, workspace=None, known_inputs={"platforms": ["apple", "tencent"]})
        self.assertEqual(["apple", "tencent"],
                         [item["scope"] for item in promotion["catalogs"]])
        self.assertEqual("asa", client.batch_requests[0]["inputs"]["media_type"])
        self.assertEqual("behavior", client.batch_requests[1]["inputs"]["metric_type"])

        for composite, known, fields in (
            ("saved_analysis", {"app": "main"}, ["id"]),
            ("analysis_template", {}, ["scope", "id"]),
            ("segment_snapshot", {"app": "main"}, ["id"]),
        ):
            with self.subTest(composite=composite):
                catalog = live_catalog_for_card(
                    {"composite": composite}, client=client,
                    workspace=_Workspace(), known_inputs=known,
                )
                self.assertTrue(catalog["complete"])
                self.assertEqual(fields, catalog["catalogs"][0]["two_call_selection_fields"])

    def test_explicit_refresh_closes_a_missing_local_catalog_in_first_call(self) -> None:
        missing = {"candidates": [{"kind": "analysis_task", "catalog_missing": True}]}
        card = attach_plan_node(
            analysis_task_cards("purchase trend", metadata_rows=[])[0], "purchase trend"
        )
        available = {"candidates": [card]}
        sync_result = {"schema_version": "gravity-insight.metadata-sync.v1", "ok": True,
                       "status": "success", "synced_at": "2026-08-14T00:00:00Z",
                       "app_count": 1, "operation_count": 13, "rows_written": 2,
                       "vocabulary_rows_written": 1}
        with patch(
            "gravity_sdk.agent_input_resolution._discover",
            side_effect=[missing, available],
        ), patch(
            "gravity_sdk.agent_catalog_refresh.refresh_complete_catalog",
            return_value=sync_result,
        ) as sync:
            result = resolve_capabilities("purchase trend",
                known_inputs={"catalog_policy": "refresh"}, client=_NoOperations())
        sync.assert_called_once_with(ANY, include_table_lineage=False)
        self.assertEqual("success", result["input_resolution"]["catalog_refresh"]["status"])
        refreshed = _scenario(result["candidates"][0], "catalog_refreshed")
        self.assertEqual((2, 0), (refreshed["minimum_calls"], refreshed["discovery_calls"]))

        table = discover_capabilities("table versions", client=None)["candidates"][0]
        with patch("gravity_sdk.agent_input_resolution._discover",
                   side_effect=[{"candidates": [table]}, {"candidates": [table]}]), patch(
            "gravity_sdk.agent_catalog_refresh.refresh_complete_catalog",
            return_value=sync_result,
        ) as table_sync:
            table_result = resolve_capabilities("table versions",
                known_inputs={"catalog_policy": "refresh"}, client=_NoOperations())
        table_sync.assert_called_once_with(ANY, include_table_lineage=True)
        self.assertEqual(2, _scenario(
            table_result["candidates"][0], "catalog_refreshed"
        )["minimum_calls"])
        validate_plan({"schema_version": "gravity.plan.v1",
                       "nodes": [table_result["candidates"][0]["plan_node"]]})

    def test_partial_refresh_and_unrequested_refresh_fail_closed(self) -> None:
        metadata = {"candidates": [{"kind": "metadata", "selector": "metadata:event"}]}
        with patch("gravity_sdk.agent_input_resolution._discover", return_value=metadata):
            with self.assertRaises(InputValidationError):
                resolve_capabilities("event", known_inputs={}, client=_NoOperations())
        partial = {"ok": False, "status": "partial"}
        client = _NoOperations()
        client._metadata_cache = _Cache()
        with patch("gravity_sdk.agent_input_resolution._discover", return_value=metadata), patch(
            "gravity_sdk.agent_catalog_refresh.refresh_complete_catalog",
            return_value=partial,
        ):
            with self.assertRaises(UpstreamError):
                resolve_capabilities("event", known_inputs={"catalog_policy": "refresh"},
                                     client=client)
        self.assertEqual(2, client._metadata_cache.clears)

    def test_sdk_and_cli_expose_the_additive_online_mode(self) -> None:
        args = build_parser().parse_args(["agent", "saved analysis", "--resolve-inputs",
                                          '{"app":"main"}', "--output", "catalog.json"])
        self.assertEqual('{"app":"main"}', args.resolve_inputs)
        client, expected = object(), {"ok": True}
        sdk = GravitySDK(insight=client, workspace=object())
        with patch(
            "gravity_sdk.agent_input_resolution.resolve_capabilities",
            return_value=expected,
        ) as resolve:
            self.assertIs(expected, sdk.resolve_capabilities(
                "saved analysis", known_inputs={"app": "main"}))
        self.assertIs(client, resolve.call_args.kwargs["client"])

    def test_cli_requires_and_atomically_writes_a_complete_json_catalog(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["agent", "saved analysis", "--resolve-inputs", '{"app":"main"}'])
        self.assertEqual(2, code)
        self.assertIn('"field": "output"', stderr.getvalue())

        payload = {"schema_version": "gravity.agent.v1", "ok": True, "status": "success",
                   "candidates": [{"input_catalog": {"complete": True,
                   "catalogs": [{"items": [{"id": str(i)} for i in range(201)]}]}}]}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalog.json"
            stdout = io.StringIO()
            with patch("gravity_sdk.cli.run_agent_command", return_value=payload), \
                    contextlib.redirect_stdout(stdout):
                code = main(["agent", "saved analysis", "--resolve-inputs", '{"app":"main"}',
                             "--output", str(output)])
            written = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0, code)
        self.assertEqual(201, len(written["candidates"][0]["input_catalog"]["catalogs"][0]["items"]))
        self.assertEqual("written", json.loads(stdout.getvalue())["status"])
if __name__ == "__main__":
    unittest.main()
