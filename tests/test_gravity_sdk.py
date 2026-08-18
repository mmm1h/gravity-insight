from __future__ import annotations

import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK, InputValidationError, PlanValidationError


class _Insight:
    def __init__(self):
        self.read_calls = []

    def read(self, operation_id, inputs=None):
        self.read_calls.append((operation_id, inputs))
        return {"kind": "read", "operation_id": operation_id, "inputs": inputs}

    def read_all(self, operation_id, inputs=None, **options):
        return {
            "kind": "read_all",
            "operation_id": operation_id,
            "inputs": inputs,
            "options": options,
        }

    def read_limited(self, operation_id, inputs=None, **options):
        return {
            "kind": "read_limited",
            "operation_id": operation_id,
            "inputs": inputs,
            "options": options,
        }

    def batch(self, requests, **options):
        return [{"requests": list(requests), "options": options}]

    def search_operations(self, query, **options):
        return {
            "operations": [
                {
                    "operation_id": "app.list",
                    "description": "List apps",
                    "domain": "app",
                    "platform": "gravity",
                    "stability": "stable",
                    "executable": True,
                    "score": 100,
                    "matched_on": ["operation_id"],
                }
            ],
            "total": 1,
            "continuation_token": None,
            "query": query,
            "options": options,
        }

    def describe(self, operation_id):
        return {
            "operation_id": operation_id,
            "description": "List apps",
            "domain": "app",
            "platform": "gravity",
            "stability": "stable",
            "executable": True,
            "input_schema": {},
            "pagination": {"kind": "page"},
        }


class _Sql:
    def execute_sql(self, sql):
        return [{"sql": sql}]

    def execute_batch(self, requests, **options):
        return [{"requests": list(requests), "options": options}]


class GravitySDKTests(unittest.TestCase):
    def test_clients_are_lazy_and_cached(self) -> None:
        built = {"insight": 0, "sql": 0}

        def insight_factory():
            built["insight"] += 1
            return _Insight()

        def sql_factory():
            built["sql"] += 1
            return _Sql()

        sdk = GravitySDK(
            insight_factory=insight_factory,
            sql_factory=sql_factory,
        )
        self.assertEqual({"insight": 0, "sql": 0}, built)

        self.assertEqual("read", sdk.read("app.list")["kind"])
        self.assertEqual("read_all", sdk.read_all("app.list")["kind"])
        self.assertEqual("read_limited", sdk.read_limited("app.list")["kind"])
        self.assertIs(sdk.insight, sdk.insight)
        self.assertEqual({"insight": 1, "sql": 0}, built)
        from gravity_sdk.cache import MetadataCache

        insight = sdk.insight
        insight._metadata_cache = MetadataCache(["analysis.event.list"])
        self.assertEqual(600.0, sdk.metadata_cache_stats()["ttl_seconds"])
        self.assertEqual(0, sdk.clear_metadata_cache()["entries"])
        self.assertEqual(0, sdk.bypass_metadata_cache(True)["bypassed"])

        self.assertEqual([{"sql": "SELECT 1"}], sdk.sql.execute_sql("SELECT 1"))
        self.assertIs(sdk.sql, sdk.sql)
        self.assertEqual({"insight": 1, "sql": 1}, built)

    def test_table_lineage_missing_catalog_is_safe_and_keeps_clients_lazy(self) -> None:
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("lineage must stay offline"),
            sql_factory=lambda: self.fail("lineage must stay offline"),
        )
        result = sdk.table_lineage(database="missing-lineage.sqlite3")
        self.assertEqual((False, 2, "database"), (
            result["ok"], result["exit_code"], result["error"]["field"]
        ))
        self.assertNotIn("database", result)
        self.assertIn("metadata sync --all-apps", result["error"]["next_action"])

    @patch("gravity_sdk.find_metadata.search_metadata")
    def test_analysis_vocabulary_is_offline_safe_and_strips_database(self, search) -> None:
        search.return_value = {
            "ok": True, "status": "success", "offline": True, "kind": "metric",
            "database": "C:/private/catalog.sqlite3",
            "results": [{"kind": "metric", "scope": "workspace", "name": "users"}],
        }
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("vocabulary must stay offline"),
        )
        result = sdk.analysis_vocabulary("users", kind="metric", limit=3)
        self.assertEqual((0, "users"), (result["exit_code"], result["results"][0]["name"]))
        self.assertNotIn("database", result)
        search.side_effect = InputValidationError(
            "stale C:/private/catalog.sqlite3", field="database"
        )
        failure = sdk.analysis_vocabulary(kind="vocabulary")
        self.assertEqual(7, len(failure["error"]))
        self.assertEqual(
            "Run `gravity metadata sync --all-apps`, then retry the same offline "
            "analysis vocabulary search.",
            failure["error"]["next_action"],
        )
        self.assertNotIn("private", str(failure))

    @patch("gravity_sdk.plan_metadata_adapter.search_metadata")
    def test_metadata_only_plan_keeps_clients_lazy_and_enforces_vocabulary_scope(
        self, search
    ) -> None:
        search.return_value = {
            "ok": True, "database": "private", "results": [],
            "failures": [{"source": "mine_templates", "code": "X", "message": "secret"}],
        }
        sdk = GravitySDK(insight_factory=lambda: self.fail("must stay offline"))
        valid_plan = {
            "schema_version": "gravity.plan.v1",
            "nodes": [{
                "id": "metrics", "kind": "metadata_search",
                "request": {"kind": "metric", "limit": 1},
                "limits": {"max_items": 1},
            }],
        }
        result = sdk.execute_plan(valid_plan, workspace=object())["results"][0]["result"]
        self.assertNotIn("database", result)
        self.assertEqual([{"source": "mine_templates", "code": "X"}], result["failures"])
        valid_plan["nodes"][0]["request"]["app_id"] = "7"
        with self.assertRaises(PlanValidationError) as raised:
            sdk.validate_plan(valid_plan)
        self.assertIn("does not accept app_id", str(raised.exception))

    def test_convenience_methods_preserve_specialized_client_options(self) -> None:
        sdk = GravitySDK(insight=_Insight(), sql=_Sql())
        read = sdk.read_all(
            "app.list",
            {"page": 1},
            max_pages=3,
            max_workers=2,
        )
        self.assertEqual(
            {"max_pages": 3, "max_workers": 2}, read["options"]
        )

        batch = sdk.read_many(
            [{"operation_id": "app.list"}], max_workers=4
        )
        self.assertEqual(4, batch[0]["options"]["max_workers"])
        sql_batch = sdk.sql.execute_batch(["SELECT 1"], max_workers=2)
        self.assertEqual(2, sql_batch[0]["options"]["max_workers"])
        self.assertFalse(hasattr(sdk, "execute_sql"))

    @patch("gravity_sdk.dashboard_snapshot.dashboard_snapshot")
    def test_dashboard_snapshot_facade_resolves_one_bound_app(self, snapshot) -> None:
        workspace = type("Workspace", (), {"resolve_app": lambda _self, value: 17})()
        sdk = GravitySDK(insight=_Insight(), workspace=workspace)
        snapshot.return_value = {"schema_version": "gravity-insight.dashboard-snapshot.v1"}
        self.assertIs(snapshot.return_value, sdk.dashboard_snapshot(
            "main", "Overview", max_workers=4, max_pages=3, max_items=50
        ))
        snapshot.assert_called_once_with(
            sdk.insight, 17, "Overview", max_workers=4, max_pages=3, max_items=50
        )

    def test_dashboard_snapshot_resolves_app_before_lazy_insight_construction(self) -> None:
        order = []

        class Workspace:
            def resolve_app(self, value):
                order.append(("app", value))
                return 17

        insight = _Insight()
        sdk = GravitySDK(
            insight_factory=lambda: (order.append(("insight", None)), insight)[1],
            workspace=Workspace(),
        )
        with patch(
            "gravity_sdk.dashboard_snapshot.dashboard_snapshot",
            return_value={"ok": True},
        ):
            sdk.dashboard_snapshot("main", "Overview")
        self.assertEqual([("app", "main"), ("insight", None)], order)

    def test_segment_spec_sdk_and_plan_share_one_safe_execution_path(self) -> None:
        class SegmentInsight(_Insight):
            def operations(self, **_options):
                return [{
                    "operation_id": "analysis.segment.evaluate_percent",
                    "stability": "stable",
                }]

            def validate(self, operation_id, _inputs):
                return {
                    "ok": True, "status": "needs_live_metadata",
                    "operation_id": operation_id, "network_called": False,
                }

            def schema(self, operation_id):
                return {
                    "operation_id": operation_id,
                    "response_projection": {
                        "data_keys": ["part", "percent", "total"],
                        "numeric_paths": ["part", "percent", "total"],
                    },
                }

        insight = SegmentInsight()
        sdk = GravitySDK(insight=insight, sql=_Sql())
        spec = {"name": "private audience", "start": "2026-08-01"}
        preview = sdk.prepare_segment_evaluation(spec, app=101)
        self.assertEqual((False, []), (
            preview["network_called"], insight.read_calls
        ))
        plan = {
            "schema_version": "gravity.plan.v1",
            "nodes": [{
                "id": "segment", "kind": "composite",
                "request": {"name": "segment_evaluate", "app": 101, "spec": spec},
                "limits": {"max_pages": 1, "max_items": 3},
            }],
        }
        self.assertEqual("validated", sdk.validate_plan(plan)["status"])
        result = sdk.execute_plan(plan)
        self.assertEqual((True, 1), (result["ok"], len(insight.read_calls)))
        self.assertNotIn("private audience", repr(result))
        self.assertNotIn("inputs", result["results"][0]["result"])

    def test_agent_facade_discovers_then_runs_without_cli_argument_ceremony(self) -> None:
        built = {"insight": 0}

        def insight_factory():
            built["insight"] += 1
            return _Insight()

        sdk = GravitySDK(insight_factory=insight_factory, sql=_Sql())
        protocol = sdk.capabilities()
        self.assertEqual("gravity.agent.v1", protocol["schema_version"])
        self.assertEqual({"insight": 0}, built)

        with patch("gravity_sdk.find.search_metadata", return_value={
            "results": [{
                "kind": "metric", "scope": "workspace", "source": "report_metrics",
                "operation_id": "report.multidim.metric.list", "name": "Revenue",
                "cname": "Revenue", "score": 100, "payload": {"name": "Revenue"},
            }],
        }):
            local = sdk.capabilities("Revenue", limit=1)
        self.assertEqual("metric", local["candidates"][0]["metadata_kind"])
        self.assertEqual({"insight": 0}, built)

        with patch("gravity_sdk.agent_batch_sources.search_metadata", return_value={
            "results": [{
                "kind": "metric", "scope": "workspace", "source": "report_metrics",
                "operation_id": "report.multidim.metric.list", "name": "Revenue",
                "cname": "Revenue", "score": 100, "payload": {"name": "Revenue"},
            }],
        }):
            batch = sdk.capabilities_many([{"id": "metric", "query": "Revenue"}])
        self.assertEqual("metric", batch["results"][0]["result"]["candidates"][0]["metadata_kind"])
        self.assertEqual({"insight": 0}, built)

        capabilities = sdk.capabilities("app", domain="app", limit=1)
        self.assertEqual("app.list", capabilities["candidates"][0]["selector"])
        self.assertEqual({"insight": 1}, built)

        resolved = {"schema_version": "gravity.resolve.v1", "ok": True}
        workspace = object()
        with (
            patch("gravity_sdk.workspace.load_workspace", return_value=workspace) as load,
            patch("gravity_sdk.resolver.resolve_and_run", return_value=resolved) as run,
        ):
            result = sdk.run(
                "app.list",
                {"page": 1},
                workspace="gravity.toml",
                max_items=10,
                max_workers=2,
            )

        load.assert_called_once_with("gravity.toml")
        self.assertIs(result, resolved)
        call = run.call_args.kwargs
        self.assertIs(call["client"], sdk.insight)
        self.assertIs(call["workspace"], workspace)
        self.assertEqual({"page": 1}, call["supplied_input"])
        self.assertEqual(5, call["max_pages"])
        self.assertEqual(10, call["max_items"])
        self.assertEqual(2, call["max_workers"])

        with patch("gravity_sdk.resolver.resolve_and_run", return_value=resolved) as run:
            sdk.run("app.list")
        self.assertEqual((None, None), (
            run.call_args.kwargs["max_pages"], run.call_args.kwargs["max_items"]
        ))

    def test_run_many_uses_the_instance_bound_workspace(self) -> None:
        insight = _Insight()
        workspace = object()
        sdk = GravitySDK(insight=insight, sql=_Sql(), workspace=workspace)
        requests = [{"selector": "app.list", "request_id": "apps"}]
        expected = {"schema_version": "gravity-insight.resolver-batch.v1"}

        with patch("gravity_sdk.resolver_batch.run_many", return_value=expected) as run:
            result = sdk.run_many(
                requests,
                max_workers=3,
                max_pages=7,
                max_items=321,
            )

        self.assertIs(expected, result)
        run.assert_called_once_with(
            requests,
            client=insight,
            workspace=workspace,
            max_workers=3,
            max_pages=7,
            max_items=321,
            metadata_database=None,
        )

    def test_factory_and_instance_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            GravitySDK(insight=_Insight(), insight_factory=_Insight)
        with self.assertRaises(ValueError):
            GravitySDK(sql=_Sql(), sql_factory=_Sql)

    def test_governed_sql_product_helpers_use_the_same_lazy_client(self) -> None:
        workspace = object()
        sdk = GravitySDK(insight=_Insight(), sql=_Sql(), workspace=workspace)
        request = {
            "product": "daily-summary",
            "start": "2026-08-01T00:00:00+08:00",
            "end": "2026-08-02T00:00:00+08:00",
        }
        with (
            patch(
                "gravity_sdk.sql.describe_products",
                return_value=[{"name": "daily-summary"}],
            ) as describe,
            patch(
                "gravity_sdk.sql.run_product_queries",
                return_value={"schema_version": "gravity-sql.query.v1"},
            ) as query,
        ):
            self.assertEqual(
                [{"name": "daily-summary"}],
                sdk.describe_sql_products(),
            )
            result = sdk.query_sql_products(request, max_workers=2)

        describe.assert_called_once_with(workspace)
        query.assert_called_once_with(
            sdk.sql,
            [request],
            max_workers=2,
            workspace=workspace,
        )
        self.assertEqual("gravity-sql.query.v1", result["schema_version"])

    def test_from_env_uses_one_configured_runtime_regardless_of_client_order(self) -> None:
        runtime = object()
        insight = object()
        sql = object()
        with (
            patch(
                "gravity_sdk.shared_runtime.get_shared_runtime",
                return_value=runtime,
            ) as get_runtime,
            patch(
                "gravity_sdk.client.GravityInsightClient.from_env",
                return_value=insight,
            ) as insight_factory,
            patch(
                "gravity_sdk.sql.client.GravityClient",
                return_value=sql,
            ) as sql_factory,
        ):
            sdk = GravitySDK.from_env(timeout=7.0, attempts=1)
            self.assertIs(sql, sdk.sql)
            self.assertIs(insight, sdk.insight)

        self.assertEqual(1, get_runtime.call_count)
        self.assertEqual(7.0, get_runtime.call_args.kwargs["timeout"])
        self.assertEqual(1, get_runtime.call_args.kwargs["attempts"])
        sql_factory.assert_called_once_with(runtime)
        insight_factory.assert_called_once_with(
            allow_experimental=False,
            runtime=runtime,
            env_path=None,
        )


if __name__ == "__main__":
    unittest.main()
