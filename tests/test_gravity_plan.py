from __future__ import annotations

import threading
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.agent import run_agent_command
from gravity_sdk.agents.batch import capabilities_many
from gravity_sdk.plan import (
    PlanAdapter,
    PlanAdapters,
    PlanValidationError,
    execute_plan,
    plan_schema,
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
        self.assertEqual("raw_operation", result["result_source"]["tier"])
        self.assertEqual(calls, {"validate": 1, "execute": 0})


class PlanExecutionTests(unittest.TestCase):
    def test_same_layer_is_concurrent_and_output_keeps_declaration_order(self):
        lock = threading.Lock()
        rendezvous = threading.Barrier(2, timeout=20)
        rendezvous_failures: list[str] = []
        active = 0
        peak = 0

        def execute(request, context):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                try:
                    rendezvous.wait()
                except threading.BrokenBarrierError as exc:
                    with lock:
                        message = (
                            "same-layer Plan rendezvous timed out or broke after "
                            f"20s: node={context.node_id!r}, active={active}, peak={peak}"
                        )
                        rendezvous_failures.append(message)
                    raise AssertionError(message) from exc
                return {"ok": True, "status": "success", "name": context.node_id}
            finally:
                with lock:
                    active -= 1

        result = execute_plan(
            _plan(_node("first"), _node("second"), budget={"max_workers": 2}),
            adapters=PlanAdapters(run=_adapter(execute)),
            workspace=object(),
        )
        self.assertEqual([], rendezvous_failures)
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
        self.assertEqual(
            ("PLAN_ADAPTER_EXCEPTION", "adapter_execute", "unexpected_exception"),
            tuple(
                result["results"][0]["error"][key]
                for key in ("code", "stage", "cause")
            ),
        )
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
        workspace = load_workspace(Path(__file__).resolve().parents[1] / "examples/workspace")

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

    def test_all_pages_unknown_completeness_is_preserved_capability_gap(self):
        workspace = load_workspace(Path(__file__).resolve().parents[1] / "examples/workspace")

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
                return {"ok": True, "result": {
                    "ok": True, "status": "success", "operation_id": "app.list",
                    "completeness": "unknown", "data": {"list": [{}]},
                }}

        result = execute_plan(
            _plan(_node("all", {"selector": "app.list", "all_pages": True})),
            adapters=build_plan_adapters(SDK(), workspace=workspace),
            workspace=workspace,
        )
        self.assertEqual(("partial", "unknown"), (result["status"], result["completeness"]))
        preserved = result["results"][0]["result"]
        self.assertEqual(("capability_gap", "COMPLETENESS_UNPROVEN"),
                         (preserved["status"], preserved["error"]["code"]))

    def test_metadata_sync_and_status_plan_handoffs_use_bounded_adapters(self):
        workspace = load_workspace(Path(__file__).resolve().parents[1] / "examples/workspace")

        class Insight:
            def operations(self, **_options):
                return []

        class SDK:
            insight = Insight()

            def __init__(self):
                self.options = None

            def sync_metadata_app(self, app_id, **options):
                self.options = (app_id, options)
                return {
                    "schema_version": "gravity-insight.metadata-sync.v1",
                    "ok": True, "status": "success", "scope": "single_app",
                    "app_id": str(app_id), "rows_written": 4,
                }

        sdk = SDK()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            plan = _plan(
                _node(
                    "sync", {"name": "metadata_sync", "app": "demo"},
                    kind="composite", limits={"max_pages": 2, "max_items": 20},
                ),
                _node(
                    "status", {"kind": "status", "app_id": "101"},
                    kind="metadata_search", limits={"max_pages": 1, "max_items": 20},
                ),
            )
            result = execute_plan(
                plan,
                adapters=build_plan_adapters(
                    sdk, workspace=workspace, metadata_database=database
                ),
                workspace=workspace,
            )

        self.assertEqual(2, result["success_count"])
        self.assertEqual((1001, 2), (sdk.options[0], sdk.options[1]["max_pages"]))
        self.assertEqual(4, result["results"][0]["result"]["rows_written"])
        self.assertEqual("missing", result["results"][1]["result"]["status"])
        self.assertFalse(result["results"][1]["result"]["network_called"])

    def test_analysis_query_composite_preflights_and_sanitizes(self):
        workspace = load_workspace(
            Path(__file__).resolve().parents[1] / "examples" / "workspace" / "gravity.toml"
        )
        metric = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
        step = lambda name: {"event": name, "metric": metric}
        dated = {"start": "2026-08-01", "end": "2026-08-02"}
        cases = {
            "event": {**dated, "steps": [step("open")]},
            "funnel": {**dated, "steps": [step("open"), step("pay")],
                       "window": {"unit": "day", "value": 1}},
            "retention": {**dated, "steps": [step("open"), step("return")],
                          "offset": 7, "period_calc_method": "SUM",
                          "custom_before_method": "SUM", "total_calc_type": "DAY",
                          "week_first_day": 1},
            "property": {"property": {"field": "PresetUserCount",
                                       "aggregation": "PresetUserCount", "data_type": "INT"}},
            "scatter": {**dated, "steps": [step("pay")]},
        }

        class Insight:
            def operations(self, **_options): return []
            def validate(self, _operation_id, _inputs): return {"ok": True}
            def schema(self, _operation_id):
                return {"response_projection": {"data_keys": ["list", "target_list"]}}

        class SDK:
            insight = Insight()
            def analysis_query(self, kind, spec, **options):
                from gravity_sdk.analysis_spec import validate_query_spec
                compiled, _ = validate_query_spec(
                    self.insight, kind, spec, workspace=options["workspace"],
                    app=options.get("app"), start=options.get("start"), end=options.get("end"),
                )
                return {"ok": True, "status": "success",
                        "operation_id": compiled.operation_id,
                        "request": {"inputs": deepcopy(compiled.inputs)},
                        "data": {"list": [], "target_list": []},
                        "output_fields": list(options.get("output_fields") or [])}

        sdk = SDK()
        nodes = [
            _node(kind, {"name": "analysis_query", "kind": " EVENT " if kind == "event" else kind,
                         "app": "demo", "spec": spec}, kind="composite")
            for kind, spec in cases.items()
        ]
        nodes[0]["output_fields"] = ["target_list"]
        result = execute_plan(
            _plan(*nodes, budget={"max_workers": 5}),
            adapters=build_plan_adapters(sdk, workspace=workspace), workspace=workspace,
        )
        values = [item["result"] for item in result["results"]]
        self.assertEqual([f"analysis.{kind}.query" for kind in cases],
                         [item["operation_id"] for item in values])
        self.assertTrue(all("request" not in item for item in values))
        self.assertNotIn("open", repr(values))
        self.assertEqual(["target_list"], values[0]["output_fields"])

    def test_analysis_query_composite_offline_guards_binding_dry_run_and_drift(self):
        workspace = load_workspace(Path(__file__).resolve().parents[1] / "examples/workspace")
        private = "private-filter-value"

        class Insight:
            def operations(self, **_options): return []
            def validate(self, _operation_id, _inputs): return {"ok": True}
            def schema(self, _operation_id):
                return {"response_projection": {"data_keys": ["list"]}}

        class SDK:
            insight = Insight()
            calls = 0
            wrong_operation = False
            def analysis_query(self, kind, spec, **_options):
                self.calls += 1
                return {"ok": True, "status": (
                            "success" if self.wrong_operation else "contract_changed"
                        ),
                        "operation_id": (
                            "analysis.scatter.query" if self.wrong_operation
                            else f"analysis.{kind}.query"
                        ),
                        "request": {"inputs": deepcopy(spec)}, "data": {"list": [private]},
                        "error": {"category": "upstream", "code": "DRIFT",
                                  "message": f"secret={private}"}}

        sdk = SDK()
        adapter = build_plan_adapters(sdk, workspace=workspace)
        valid = {"name": "analysis_query", "kind": "event", "app": "demo",
                 "spec": {"start": "2026-08-01", "end": "2026-08-02",
                          "steps": [{"event": "open", "metric": {
                              "field": "PresetAllCount", "aggregation": "PresetAllCount"}}]}}
        invalid = [
            {**valid, "spec": {**valid["spec"], "unknown": private}},
            {**valid, "kind": "unknown"},
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(PlanValidationError) as raised:
                execute_plan(_plan(_node("q", request, kind="composite")),
                             adapters=adapter, workspace=workspace)
            self.assertNotIn(private, str(raised.exception))
        nested = _node("q", valid, kind="composite", depends_on=["source"], bindings=[{
            "from": "source", "source": "/result/value", "target": "/spec/start"}])
        with self.assertRaises(PlanValidationError):
            execute_plan(_plan(_node("source"), nested), adapters=adapter, workspace=workspace)
        dry = execute_plan(_plan(_node("q", valid, kind="composite")),
                           adapters=adapter, workspace=workspace, dry_run=True)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(0, sdk.calls)
        for sdk.wrong_operation in (False, True):
            drift = execute_plan(_plan(_node("q", valid, kind="composite")),
                                 adapters=adapter, workspace=workspace)
            self.assertEqual((False, 3, None),
                             (drift["ok"], drift["exit_code"], drift["results"][0]["result"]))
            self.assertNotIn(private, repr(drift))

    def test_plan_schema_declares_analysis_query_binding_contract(self):
        analysis = plan_schema()["composites"]["analysis_query"]
        self.assertEqual(
            {
                "binding_targets": ["/app"],
                "spec_binding": False,
                "request_fields": [
                    "app",
                    "compare_end",
                    "compare_start",
                    "end",
                    "kind",
                    "metadata_snapshot",
                    "name",
                    "spec",
                    "start",
                ],
            },
            analysis,
        )

    def test_analysis_query_contract_constants_are_adapter_reexports(self):
        from gravity_sdk import plan_analysis_adapter as adapter
        from gravity_sdk import plan_analysis_contract as contract

        for name in (
            "ANALYSIS_QUERY_BINDING_TARGETS",
            "ANALYSIS_QUERY_NAME",
            "ANALYSIS_QUERY_REQUEST_FIELDS",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(contract, name), getattr(adapter, name))

    def test_analysis_query_rejected_binding_lists_allowed_targets(self):
        workspace = load_workspace(Path(__file__).resolve().parents[1] / "examples/workspace")

        class Insight:
            def operations(self, **_options):
                return []

            def validate(self, _operation_id, _inputs):
                return {"ok": True}

            def schema(self, _operation_id):
                return {"response_projection": {"data_keys": ["list"]}}

        class SDK:
            insight = Insight()

        request = {
            "name": "analysis_query",
            "kind": "event",
            "app": "demo",
            "spec": {
                "start": "2026-08-01",
                "end": "2026-08-02",
                "steps": [{
                    "event": "open",
                    "metric": {
                        "field": "PresetAllCount",
                        "aggregation": "PresetAllCount",
                    },
                }],
            },
        }
        nested = _node(
            "q",
            request,
            kind="composite",
            depends_on=["source"],
            bindings=[{
                "from": "source",
                "source": "/result/name",
                "target": "/spec/steps/0/event",
            }],
        )
        with self.assertRaises(PlanValidationError) as raised:
            execute_plan(
                _plan(
                    _node(
                        "source",
                        {"query": "open", "kind": "event", "limit": 1},
                        kind="metadata_search",
                    ),
                    nested,
                ),
                adapters=build_plan_adapters(SDK(), workspace=workspace),
                workspace=workspace,
            )
        message = str(raised.exception)
        self.assertIn("/spec/steps/0/event", message)
        self.assertIn('"/app"', message)
        self.assertEqual("nodes[1].request.bindings", raised.exception.field)


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

    @patch("gravity_sdk.agents.batch_sources.search_metadata")
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
        self.assertTrue(all("complete_collection_count" not in card["allowed_claims"] for card in cards))
        self.assertTrue(all("complete_collection_count" in card["forbidden_claims"] for card in cards))

    @patch("gravity_sdk.agents.batch.capabilities_many")
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
