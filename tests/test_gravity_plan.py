from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.agent import run_agent_command
from gravity_sdk.agent_batch import capabilities_many
from gravity_sdk.plan import (
    PlanAdapter,
    PlanAdapters,
    PlanValidationError,
    execute_plan,
    validate_plan,
)
from gravity_sdk.plan_adapters import build_plan_adapters
from gravity_sdk.workspace import load_workspace


def _plan(*nodes, budget=None):
    value = {"schema_version": "gravity.plan.v1", "nodes": list(nodes)}
    if budget is not None:
        value["budget"] = budget
    return value


def _node(node_id, request=None, **values):
    return {
        "id": node_id,
        "kind": values.pop("kind", "run"),
        "request": dict(request or {"selector": node_id}),
        **values,
    }


def _adapter(execute, validate=lambda request, context: None, project=None):
    return PlanAdapter(execute=execute, validate=validate, project=project)


class PlanValidationTests(unittest.TestCase):
    def test_preflight_rejects_cycle_pointer_workspace_and_budget_offline(self):
        invalid = [
            _plan(
                _node("a", depends_on=["b"]),
                _node("b", depends_on=["a"]),
            ),
            _plan(
                _node(
                    "a",
                    depends_on=["b"],
                    bindings=[{"from": "b", "source": "bad", "target": "/x"}],
                ),
                _node("b"),
            ),
            _plan(_node("a", {"selector": "a", "workspace": "elsewhere"})),
            _plan(
                _node("a", foreach={"from": "b", "source": "/result/x", "target": "/x"}),
                _node("b"),
                budget={"max_total_items": 10},
            ),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(PlanValidationError):
                validate_plan(value)

    def test_adapter_preflight_runs_for_every_node_before_any_execute(self):
        executions = []
        validations = []

        def validate(request, context):
            validations.append(context.node_id)
            if context.node_id == "b":
                raise RuntimeError("Bearer highly-secret-token")

        adapter = _adapter(lambda request, context: executions.append(request), validate)
        with self.assertRaises(PlanValidationError) as raised:
            execute_plan(
                _plan(_node("a"), _node("b")),
                adapters=PlanAdapters(run=adapter),
                workspace=object(),
            )
        self.assertEqual(validations, ["a", "b"])
        self.assertEqual(executions, [])
        self.assertNotIn("secret", str(raised.exception))

    def test_dry_run_calls_validation_but_never_execution(self):
        calls = {"validate": 0, "execute": 0}

        def validate(request, context):
            calls["validate"] += 1

        def execute(request, context):
            calls["execute"] += 1
            return {"ok": True}

        result = execute_plan(
            _plan(_node("a")),
            adapters=PlanAdapters(run=_adapter(execute, validate)),
            workspace=object(),
            dry_run=True,
        )
        self.assertEqual(result["status"], "validated")
        self.assertEqual(calls, {"validate": 1, "execute": 0})


class PlanExecutionTests(unittest.TestCase):
    def test_same_layer_is_concurrent_and_output_keeps_declaration_order(self):
        lock = threading.Lock()
        active = 0
        peak = 0

        def execute(request, context):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {"ok": True, "status": "success", "name": context.node_id}

        result = execute_plan(
            _plan(_node("first"), _node("second"), budget={"max_workers": 2}),
            adapters=PlanAdapters(run=_adapter(execute)),
            workspace=object(),
        )
        self.assertGreaterEqual(peak, 2)
        self.assertEqual([item["node_id"] for item in result["results"]], ["first", "second"])
        self.assertEqual(result["exit_code"], 0)

    def test_scalar_binding_and_single_foreach_are_correlated(self):
        requests = []

        def execute(request, context):
            requests.append(request)
            if context.node_id == "source":
                return {"ok": True, "status": "success", "values": [11, 12]}
            return {"ok": True, "status": "success", "selected": request["value"]}

        result = execute_plan(
            _plan(
                _node("source"),
                _node(
                    "fanout",
                    {"selector": "child"},
                    depends_on=["source"],
                    foreach={
                        "from": "source",
                        "source": "/result/values",
                        "target": "/value",
                        "max_items": 2,
                    },
                ),
            ),
            adapters=PlanAdapters(run=_adapter(execute)),
            workspace=object(),
        )
        fanout = [item for item in result["results"] if item["node_id"] == "fanout"]
        self.assertEqual([item["execution_id"] for item in fanout], ["fanout[0]", "fanout[1]"])
        self.assertEqual([item["result"]["selected"] for item in fanout], [11, 12])
        self.assertEqual(result["expanded_count"], 3)

    def test_non_scalar_binding_fails_without_echo_and_dependent_skips(self):
        secret = "Bearer private-bound-value"

        def execute(request, context):
            return {"ok": True, "status": "success", "value": {"secret": secret}}

        result = execute_plan(
            _plan(
                _node("source"),
                _node(
                    "bad",
                    depends_on=["source"],
                    bindings=[{
                        "from": "source", "source": "/result/value", "target": "/value",
                    }],
                ),
                _node("blocked", depends_on=["bad"]),
            ),
            adapters=PlanAdapters(run=_adapter(execute)),
            workspace=object(),
        )
        bad, blocked = result["results"][1:]
        self.assertIsNone(bad["result"])
        self.assertEqual(bad["exit_code"], 2)
        self.assertEqual(blocked["status"], "skipped")
        self.assertNotIn(secret, str(bad))

    def test_failure_isolated_sanitized_and_local_exit_wins(self):
        def execute(request, context):
            if context.node_id == "local":
                raise RuntimeError("password=hunter2")
            if context.node_id == "caller":
                return {
                    "ok": False,
                    "error": {"category": "caller", "code": "INPUT_INVALID", "message": "token"},
                }
            return {"ok": True, "status": "empty", "rows": []}

        result = execute_plan(
            _plan(_node("local"), _node("caller"), _node("sibling")),
            adapters=PlanAdapters(run=_adapter(execute)),
            workspace=object(),
        )
        self.assertEqual(result["exit_code"], 4)
        self.assertEqual(result["success_count"], 1)
        self.assertIsNone(result["results"][0]["result"])
        self.assertNotIn("hunter2", str(result))
        self.assertNotIn('"message": "token"', str(result))

    def test_output_fields_are_projected_by_adapter_after_execution(self):
        projected = []

        def project(result, fields, context):
            projected.append((fields, context.max_workers))
            return {name: result[name] for name in fields}

        result = execute_plan(
            _plan(_node("a", output_fields=["safe"])),
            adapters=PlanAdapters(
                run=_adapter(
                    lambda request, context: {"ok": True, "safe": 1, "private": 2},
                    project=project,
                )
            ),
            workspace=object(),
        )
        self.assertEqual(result["results"][0]["result"], {"safe": 1})
        self.assertEqual(projected, [(('safe',), 1)])

    @patch("gravity_sdk.plan_metadata_adapter.search_table_lineage")
    @patch("gravity_sdk.plan_metadata_adapter.search_metadata")
    def test_production_adapters_execute_all_four_engines(self, metadata, lineage):
        workspace = load_workspace(
            Path(__file__).resolve().parents[1] / "examples" / "workspace" / "gravity.toml"
        )

        class Insight:
            def operations(self, **_options):
                return [{"operation_id": "app.list", "stability": "stable"}]

            def describe(self, operation_id):
                return {"operation_id": operation_id, "input_schema": {}}

            def validate(self, _operation_id, _inputs):
                return {"ok": True}

        class SDK:
            insight = Insight()

            def run(self, *_args, **_options):
                return {"ok": True, "result": {"status": "success", "data": {"list": [{}]}}}

            def query_sql_products(self, *_args, **_options):
                return {"ok": True, "status": "success", "exit_code": 0, "results": []}

            def analysis_context(self, *_args, **_options):
                return {"ok": True, "status": "success", "results": [{"ok": True}] * 13}

        metadata.return_value = {
            "ok": True, "status": "success", "results": [{"kind": "event", "name": "open"}]
        }
        lineage.return_value = {
            "ok": True, "status": "success", "offline": True, "scope": "account",
            "observed": True, "database": "C:/private/catalog.sqlite3",
            "results": [{"table_id": "7", "versions": [], "operations": []}],
        }
        plan = _plan(
            _node("insight", {"selector": "app.list"}, limits={"max_items": 1}),
            _node(
                "sql", {"product": "daily-event-summary", "start": "2026-08-01", "end": "2026-08-02"},
                kind="sql_product", limits={"max_items": 100},
            ),
            _node(
                "metadata", {"query": "open", "kind": "event", "limit": 1},
                kind="metadata_search", limits={"max_items": 1},
            ),
            _node(
                "lineage", {"kind": "table_lineage", "limit": 1},
                kind="metadata_search", limits={"max_items": 1},
            ),
            _node(
                "context", {"name": "analysis_context", "app": "demo"},
                kind="composite", limits={"max_items": 13},
            ),
        )

        result = execute_plan(
            plan,
            adapters=build_plan_adapters(SDK(), workspace=workspace),
            workspace=workspace,
        )
        self.assertEqual(5, result["success_count"])
        lineage_result = result["results"][3]["result"]
        self.assertEqual(("account", "7"), (lineage_result["scope"], lineage_result["results"][0]["table_id"]))
        self.assertNotIn("database", lineage_result)


class AgentBatchTests(unittest.TestCase):
    class Client:
        def __init__(self):
            self.inventory_calls = 0

        def operations(self, **kwargs):
            self.inventory_calls += 1
            return [{
                "operation_id": "analysis.daily.summary.list",
                "domain": "analysis",
                "resource": "daily-summary",
                "action": "list",
                "stability": "stable",
                "description": "daily event summary",
            }]

        def describe(self, operation_id):
            return {
                "operation_id": operation_id,
                "domain": "analysis",
                "stability": "stable",
                "input_schema": {},
            }

    @staticmethod
    def workspace():
        return SimpleNamespace(recipes={}, products={}, datasources={}, apps={})

    @patch("gravity_sdk.agent_batch_sources.search_metadata")
    def test_capabilities_many_scans_sources_once_and_returns_plan_nodes(self, metadata):
        metadata.return_value = {"results": []}
        client = self.Client()
        result = capabilities_many(
            ["daily event summary", {"id": "second", "query": "daily summary"}],
            client=client,
            workspace=self.workspace(),
        )
        self.assertEqual(client.inventory_calls, 1)
        self.assertEqual(metadata.call_count, 1)
        self.assertEqual([item["question_id"] for item in result["results"]], ["question-1", "second"])
        cards = [item["result"]["candidates"][0] for item in result["results"]]
        self.assertTrue(all(card["plan_node"]["kind"] == "run" for card in cards))

    @patch("gravity_sdk.agent_batch.capabilities_many")
    def test_agent_input_routes_to_batch_without_positional_query(self, batch):
        batch.return_value = {"schema_version": "gravity.agent-batch.v1", "ok": True}
        args = SimpleNamespace(
            query=None, input={"questions": ["daily"]}, continuation=None,
            domain=None, platform=None, limit=3,
        )
        result = run_agent_command(args, self.Client())
        self.assertEqual(result["schema_version"], "gravity.agent-batch.v1")
        batch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
