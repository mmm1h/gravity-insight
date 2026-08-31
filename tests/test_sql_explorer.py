"""R15 isolated SQL Explorer policy, database, privacy, and promotion gates."""

from __future__ import annotations

import copy
from datetime import date
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import (
    GravitySDK,
    SqlExplorerService,
    validate_sql_explorer_promotion,
    validate_sql_explorer_request,
    validate_sql_explorer_result,
)
from gravity_insight.capability_trust import CapabilityTrustService
from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.sql.__main__ import build_parser
from gravity_insight.sql.products import build_sql, day_window
from gravity_insight.sql_explorer_contract import (
    SqlExplorerContractError,
    promotion_digest, promotion_source_digest,
    result_digest, session_digest,
    validate_promotion_source,
)
from gravity_insight.sql_explorer_policy import compile_sql_explorer_statement
from gravity_insight.sql_explorer_sqlite import _SqliteReadOnlySession
import gravity_insight.sql_explorer_sqlite as sqlite_adapter_module
import gravity_insight.workspace_sql_product_install as workspace_install_module
from gravity_insight.workspace import (
    load_workspace,
    validate_registered_sql_product_definition,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_WORKSPACE = ROOT / "examples" / "workspace"
PRIVATE_PARAMETER = "private-filter-token"


def _budgets(**overrides):
    values = {
        "statement_timeout_ms": 1000,
        "max_vm_steps": 1_000_000,
        "progress_ops": 100,
        "max_rows": 100,
        "max_output_bytes": 65536,
        "max_cell_bytes": 4096,
    }
    values.update(overrides)
    return values


def _request(database: Path, **overrides):
    value = {
        "schema_version": "gravity.sql-explorer-request.v1",
        "dialect": "sqlite",
        "database_path": str(database),
        "sql": (
            "SELECT category, COUNT(*) AS total FROM main.events "
            "WHERE kind = ? GROUP BY category ORDER BY category"
        ),
        "parameters": [PRIVATE_PARAMETER],
        "policy": {
            "allowed_relations": ["main.events"],
            "allowed_functions": ["count"],
            "output_columns": ["category", "total"],
            "budgets": _budgets(),
        },
    }
    for key, item in overrides.items():
        if key == "budgets":
            value["policy"]["budgets"] = _budgets(**item)
        elif key in {"allowed_relations", "allowed_functions", "output_columns"}:
            value["policy"][key] = item
        else:
            value[key] = item
    return value


def _registered_product():
    return {
        "kind": "custom-sql",
        "datasource": "demo",
        "apps": ["demo"],
        "forbidden_claims": ["user-level identity or causal claims"],
        "sql": (
            "SELECT category, COUNT(*) AS total FROM `default`.`event` "
            "WHERE app_id IN ({app_ids}) AND create_time >= {start} "
            "AND create_time < {end} GROUP BY category LIMIT {limit}"
        ),
        "output_fields": ["category", "total"],
        "output_semantics": {
            "category": "reviewed aggregate category",
            "total": "reviewed aggregate row count",
        },
        "privacy": "aggregate",
        "max_rows": 100,
    }


def _promotion_request(source, *, name="explored-summary-v1"):
    return {
        "schema_version": "gravity.sql-explorer-promotion-request.v1",
        "source": copy.deepcopy(source),
        "approval": {
            "decision": "approved",
            "review_evidence_sha256": "a" * 64,
            "product_name": name,
            "contract_version": "1",
            "registered_product": _registered_product(),
        },
    }


class SqlExplorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = (Path(self.temporary.name) / "explorer.db").resolve()
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE events(id INTEGER, category TEXT, kind TEXT, payload TEXT)"
        )
        connection.execute(
            "CREATE VIEW event_counts AS "
            "SELECT category, COUNT(*) AS total FROM events GROUP BY category"
        )
        rows = [
            (
                index,
                "alpha" if index % 2 == 0 else "beta",
                PRIVATE_PARAMETER if index < 40 else "other",
                "p" * 64,
            )
            for index in range(120)
        ]
        connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", rows)
        connection.commit()
        connection.close()
        self.workspace_root = Path(self.temporary.name) / "workspace"
        shutil.copytree(EXAMPLE_WORKSPACE, self.workspace_root)
        self.workspace_path = self.workspace_root / "gravity.toml"
        self.cache_root = Path(self.temporary.name) / "cache"
        self.service = SqlExplorerService()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inspect_and_execute_are_bounded_exploratory_and_value_private(self) -> None:
        request = _request(self.database)
        inspected = self.service.inspect(request)
        executed = self.service.execute(request)

        self.assertEqual(inspected, validate_sql_explorer_result(inspected))
        self.assertEqual(executed, validate_sql_explorer_result(executed))
        self.assertEqual(("ready", False, []), (
            inspected["status"],
            inspected["session"]["statement_executed"],
            inspected["rows"],
        ))
        self.assertEqual(
            [{"category": "alpha", "total": 20}, {"category": "beta", "total": 20}],
            executed["rows"],
        )
        self.assertEqual(("exploratory", "unknown", [], False, False), (
            executed["trust"],
            executed["completeness"],
            executed["allowed_claims"],
            executed["stable_dependency_allowed"],
            executed["network_called"],
        ))
        identity = executed["session"]["identity"]
        self.assertEqual(("read_only", True, True, True), (
            identity["database_open_mode"],
            identity["query_only"],
            identity["authorizer"],
            identity["engine_limits"],
        ))
        self.assertEqual(0, executed["session"]["runtime_transport_requests"])
        rendered = json.dumps(executed, sort_keys=True)
        self.assertNotIn(str(self.database), rendered)
        self.assertNotIn(PRIVATE_PARAMETER, rendered)
        self.assertNotIn(request["sql"], rendered)
        source_rendered = json.dumps(executed["promotion_source"], sort_keys=True)
        self.assertNotIn("alpha", source_rendered)
        self.assertNotIn("beta", source_rendered)

    def test_ast_attack_corpus_fails_before_caller_statement_execution(self) -> None:
        safe = _request(self.database)["sql"]
        cases = (
            ("INSERT INTO events VALUES (1, 'a', 'b', 'c')", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            ("DELETE FROM events", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            ("CREATE TABLE injected(value TEXT)", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            (safe + "; SELECT 1 AS total", "SQL_EXPLORER_MULTIPLE_STATEMENTS"),
            ("/* hidden */ " + safe, "SQL_EXPLORER_COMMENTS_FORBIDDEN"),
            ("PRAGMA query_only", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            ("ATTACH DATABASE ? AS other", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            ("SELECT category AS category, 1 AS total FROM main.events UNION SELECT 'x', 2", "SQL_EXPLORER_STATEMENT_FORBIDDEN"),
            ("SELECT * FROM main.events", "SQL_EXPLORER_STAR_PROJECTION_FORBIDDEN"),
            ("SELECT category, COUNT(*) AS total FROM main.other GROUP BY category", "SQL_EXPLORER_RELATION_FORBIDDEN"),
            ("SELECT category, RANDOM() AS total FROM main.events", "SQL_EXPLORER_FUNCTION_FORBIDDEN"),
            (safe.replace("category,", "category AS changed,"), "SQL_EXPLORER_OUTPUT_CONTRACT_INVALID"),
            (safe.replace("?", ":kind"), "SQL_EXPLORER_PLACEHOLDER_MISMATCH"),
        )
        for sql, code in cases:
            result = self.service.execute(_request(self.database, sql=sql))
            with self.subTest(code=code):
                self.assertEqual("blocked", result["status"])
                self.assertEqual(code, result["error"]["code"])
                self.assertFalse(result["error"]["statement_executed"])
                self.assertEqual([], result["rows"])
                self.assertFalse(result["network_called"])

        invalid_dialect = _request(self.database, dialect="postgres")
        result = self.service.execute(invalid_dialect)
        self.assertEqual("SQL_EXPLORER_DIALECT_UNSUPPORTED", result["error"]["code"])

        for path in (Path("relative.db"), Path(self.temporary.name) / "missing.db"):
            result = self.service.execute(_request(path))
            with self.subTest(path=path):
                self.assertEqual(
                    "SQL_EXPLORER_DATABASE_PATH_INVALID",
                    result["error"]["code"],
                )
                self.assertFalse(result["error"]["statement_executed"])

    def test_database_remains_read_only_even_with_ast_and_authorizer_bypassed(self) -> None:
        statement = compile_sql_explorer_statement(_request(self.database))
        with _SqliteReadOnlySession(statement, lambda: 0.0) as session:
            connection = session._connection
            self.assertIsNotNone(connection)
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("DELETE FROM events")
            connection.set_authorizer(None)
            with self.assertRaises(sqlite3.OperationalError) as raised:
                connection.execute("DELETE FROM events")
            self.assertIn("readonly", str(raised.exception).casefold())

        connection = sqlite3.connect(self.database)
        count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        connection.close()
        self.assertEqual(120, count)

    def test_exact_view_and_hidden_function_are_authorized_by_the_database(self) -> None:
        request = _request(
            self.database,
            sql=(
                "SELECT category AS category, total AS total "
                "FROM main.event_counts ORDER BY category"
            ),
            parameters=[],
            allowed_relations=["main.event_counts"],
            allowed_functions=["count"],
        )
        result = self.service.execute(request)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(
            [{"category": "alpha", "total": 60}, {"category": "beta", "total": 60}],
            result["rows"],
        )
        self.assertEqual((1, 1), (
            result["session"]["used_relation_count"],
            result["session"]["used_function_count"],
        ))

    def test_engine_and_output_budgets_fail_closed_without_partial_rows(self) -> None:
        row_request = _request(
            self.database,
            sql="SELECT id AS id FROM main.events ORDER BY id",
            parameters=[],
            allowed_functions=[],
            output_columns=["id"],
            budgets={"max_rows": 2},
        )
        row_result = self.service.execute(row_request)
        self.assertEqual("SQL_EXPLORER_ROW_BUDGET_EXCEEDED", row_result["error"]["code"])
        self.assertEqual([], row_result["rows"])
        self.assertTrue(row_result["error"]["statement_executed"])

        byte_request = _request(
            self.database,
            sql="SELECT id AS id, payload AS payload FROM main.events ORDER BY id",
            parameters=[],
            allowed_functions=[],
            output_columns=["id", "payload"],
            budgets={"max_output_bytes": 256, "max_cell_bytes": 1024},
        )
        byte_result = self.service.execute(byte_request)
        self.assertEqual("SQL_EXPLORER_BYTE_BUDGET_EXCEEDED", byte_result["error"]["code"])
        self.assertEqual([], byte_result["rows"])

        cell_request = _request(
            self.database,
            sql="SELECT payload AS payload FROM main.events ORDER BY id",
            parameters=[],
            allowed_functions=[],
            output_columns=["payload"],
            budgets={"max_cell_bytes": 64},
        )
        cell_result = self.service.execute(cell_request)
        self.assertEqual("SQL_EXPLORER_ENGINE_LIMIT_EXCEEDED", cell_result["error"]["code"])
        self.assertEqual([], cell_result["rows"])

        work_sql = (
            "SELECT COUNT(*) AS total FROM main.events AS a "
            "CROSS JOIN main.events AS b CROSS JOIN main.events AS c"
        )
        resource = self.service.execute(
            _request(
                self.database,
                sql=work_sql,
                parameters=[],
                output_columns=["total"],
                budgets={"max_vm_steps": 1000, "progress_ops": 1},
            )
        )
        self.assertEqual("SQL_EXPLORER_RESOURCE_BUDGET_EXCEEDED", resource["error"]["code"])
        self.assertEqual([], resource["rows"])

    def test_fake_clock_timeout_and_missing_runtime_controls_are_blocked(self) -> None:
        class Tick:
            value = 0.0

            def __call__(self):
                self.value += 0.01
                return self.value

        work_sql = (
            "SELECT COUNT(*) AS total FROM main.events AS a "
            "CROSS JOIN main.events AS b CROSS JOIN main.events AS c"
        )
        timeout_service = SqlExplorerService(clock=Tick())
        timed = timeout_service.execute(
            _request(
                self.database,
                sql=work_sql,
                parameters=[],
                output_columns=["total"],
                budgets={
                    "statement_timeout_ms": 1,
                    "max_vm_steps": 10_000_000,
                    "progress_ops": 1,
                },
            )
        )
        self.assertEqual("SQL_EXPLORER_STATEMENT_TIMEOUT", timed["error"]["code"])
        self.assertEqual([], timed["rows"])

        with patch.object(
            sqlite_adapter_module.sqlite3, "sqlite_version_info", (3, 39, 0)
        ):
            unsupported = self.service.execute(_request(self.database))
        self.assertEqual(
            "SQL_EXPLORER_RESOURCE_BUDGET_UNAVAILABLE",
            unsupported["error"]["code"],
        )
        self.assertFalse(unsupported["error"]["statement_executed"])

    def test_parser_and_result_tamper_fail_closed(self) -> None:
        with patch("gravity_insight.sql_explorer_policy.sqlglot.__version__", "0.0.0"):
            unavailable = self.service.inspect(_request(self.database))
        self.assertEqual("SQL_EXPLORER_PARSER_UNAVAILABLE", unavailable["error"]["code"])

        result = self.service.execute(_request(self.database))
        changed = copy.deepcopy(result)
        changed["session"]["identity"]["query_only"] = False
        changed["session"]["session_sha256"] = session_digest(changed["session"])
        changed["result_sha256"] = result_digest(changed)
        with self.assertRaises(SqlExplorerContractError):
            validate_sql_explorer_result(changed)

        changed = copy.deepcopy(result)
        changed["rows"][0]["total"] += 1
        with self.assertRaises(SqlExplorerContractError):
            validate_sql_explorer_result(changed)

    def test_promotion_installs_normal_product_but_never_stable_identity(self) -> None:
        workspace = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )
        service = SqlExplorerService(workspace)
        executed = service.execute(_request(self.database))
        original_names = workspace.product_names
        promoted = service.promote(_promotion_request(executed["promotion_source"]))
        installed = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )

        self.assertEqual(promoted, validate_sql_explorer_promotion(promoted))
        definition = promoted["product"]["definition"]
        self.assertEqual(
            definition,
            validate_registered_sql_product_definition(
                workspace, promoted["product"]["name"], definition
            ),
        )
        self.assertEqual(("1", "aggregate", "a" * 64), (
            definition["contract_version"],
            definition["privacy"],
            definition["review_evidence_sha256"],
        ))
        self.assertEqual("installed", promoted["status"])
        self.assertEqual(
            tuple(sorted((*original_names, "explored-summary-v1"))),
            installed.product_names,
        )
        self.assertEqual(definition, installed.product("explored-summary-v1"))
        start_at, end_at = day_window(date(2026, 8, 1))
        rendered_sql = build_sql(
            "explored-summary-v1", start_at, end_at, (), installed
        )
        self.assertIn("app_id IN (1001)", rendered_sql)
        self.assertIn("LIMIT 101", rendered_sql)
        self.assertEqual((False, False, False), (
            promoted["installation"]["automatic"],
            promoted["trust"]["stable_identity_granted"],
            promoted["trust"]["stable_dependency_allowed"],
        ))
        self.assertEqual(original_names, workspace.product_names)
        missing = CapabilityTrustService().trust(
            "product", "sql-product:explored-summary-v1"
        )
        self.assertNotEqual("stable", missing["trust_status"])

        with self.assertRaises(SqlExplorerContractError) as raised:
            service.promote(_promotion_request(executed["promotion_source"]))
        self.assertEqual("SQL_EXPLORER_PROMOTION_PRODUCT_EXISTS", raised.exception.code)

    def test_promotion_readback_failure_rolls_back_workspace_install(self) -> None:
        # Caller spelling may differ from the canonical install path (for
        # example a Windows short temp path); exercise that on every platform.
        self.workspace_path = (
            self.workspace_root / ".." / self.workspace_root.name / "gravity.toml"
        )
        workspace = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )
        self.assertNotEqual(self.workspace_path, workspace.path)
        service = SqlExplorerService(workspace)
        source = service.execute(_request(self.database))["promotion_source"]
        original = self.workspace_path.read_bytes()
        replace = workspace_install_module.replace_atomic_durable
        corrupted = False

        def corrupt_first_commit(source_path, target_path):
            nonlocal corrupted
            replace(source_path, target_path)
            if target_path == workspace.path and not corrupted:
                corrupted = True
                target_path.write_text("schema_version =", encoding="utf-8")

        with patch(
            "gravity_insight.workspace_sql_product_install.replace_atomic_durable",
            side_effect=corrupt_first_commit,
        ), self.assertRaises(SqlExplorerContractError) as raised:
            service.promote(_promotion_request(source, name="rollback-summary-v1"))

        self.assertEqual(
            "SQL_EXPLORER_PROMOTION_INSTALL_FAILED", raised.exception.code
        )
        self.assertTrue(corrupted)
        self.assertEqual(original, self.workspace_path.read_bytes())
        restored = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )
        self.assertNotIn("rollback-summary-v1", restored.product_names)

    def test_promotion_semantic_tamper_fails_even_after_digest_recomputation(self) -> None:
        workspace = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )
        service = SqlExplorerService(workspace)
        source = service.execute(_request(self.database))["promotion_source"]
        promoted = service.promote(_promotion_request(source))

        changed = copy.deepcopy(promoted)
        changed["consumer_contract"]["output_fields"] = ["total", "category"]
        changed["promotion_sha256"] = promotion_digest(changed)
        with self.assertRaises(SqlExplorerContractError):
            validate_sql_explorer_promotion(changed)

        changed = copy.deepcopy(promoted)
        changed["product"]["definition"]["promotion_source_sha256"] = "b" * 64
        changed["product"]["definition_sha256"] = canonical_digest(
            changed["product"]["definition"]
        )
        changed["promotion_sha256"] = promotion_digest(changed)
        with self.assertRaises(SqlExplorerContractError):
            validate_sql_explorer_promotion(changed)

    def test_lazy_sdk_and_root_exports_do_not_construct_gravity_clients(self) -> None:
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("Explorer must not construct Insight"),
            sql_factory=lambda: self.fail("Explorer must not construct registered SQL"),
            workspace=EXAMPLE_WORKSPACE,
        )
        self.assertIs(sdk.sql_explorer, sdk.sql_explorer)
        inspected = sdk.sql_explorer.inspect(_request(self.database))
        self.assertEqual("ready", inspected["status"])

        import gravity_insight

        self.assertIs(gravity_insight.SqlExplorerService, SqlExplorerService)
        self.assertIs(
            gravity_insight.validate_sql_explorer_request,
            validate_sql_explorer_request,
        )
        self.assertIs(
            gravity_insight.validate_sql_explorer_result,
            validate_sql_explorer_result,
        )
        self.assertIs(
            gravity_insight.validate_sql_explorer_promotion,
            validate_sql_explorer_promotion,
        )

    def test_registered_sql_success_and_failure_never_fall_back_to_explorer(self) -> None:
        class RegisteredSql:
            def __init__(self, fails=False):
                self.fails = fails

            def execute_sql(self, _sql):
                if self.fails:
                    raise RuntimeError("registered fixture failure")
                return [
                    {"app_id": 1001, "event_name": "safe", "event_count": 1}
                ]

        request = {
            "product": "daily-event-summary",
            "start": "2026-08-01T00:00:00+08:00",
            "end": "2026-08-02T00:00:00+08:00",
            "app_id": 1001,
        }
        with patch.object(
            SqlExplorerService,
            "execute",
            side_effect=AssertionError("registered SQL must not fall back"),
        ):
            success = GravitySDK(
                sql=RegisteredSql(), workspace=EXAMPLE_WORKSPACE
            ).query_sql_products(request)
            failure = GravitySDK(
                sql=RegisteredSql(fails=True), workspace=EXAMPLE_WORKSPACE
            ).query_sql_products(request)
        self.assertTrue(success["ok"])
        self.assertFalse(failure["ok"])

    def test_cli_is_explicit_offline_and_works_without_registered_products(self) -> None:
        parsed = build_parser(()).parse_args(
            ["explorer", "execute", "--input", "request.json"]
        )
        self.assertFalse(parsed.network_required)
        request_path = Path(self.temporary.name) / "request.json"
        request_path.write_text(
            json.dumps(_request(self.database)), encoding="utf-8"
        )
        environment = os.environ.copy()
        environment.pop("GRAVITY_WORKSPACE", None)
        environment["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gravity_insight",
                "sql",
                "explorer",
                "execute",
                "--input",
                str(request_path),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("success", payload["status"])
        self.assertFalse(payload["network_called"])

    def test_cli_promotion_installs_workspace_and_writes_explicit_artifact(self) -> None:
        source = self.service.execute(_request(self.database))["promotion_source"]
        promotion_input = Path(self.temporary.name) / "promotion.json"
        promotion_output = Path(self.temporary.name) / "reviewed-product.json"
        promotion_input.write_text(
            json.dumps(_promotion_request(source)), encoding="utf-8"
        )
        environment = os.environ.copy()
        environment["GRAVITY_WORKSPACE"] = str(self.workspace_path)
        environment["GRAVITY_CACHE_HOME"] = str(self.cache_root)
        environment["PYTHONPATH"] = str(ROOT / "src")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gravity_insight",
                "sql",
                "explorer",
                "promote",
                "--input",
                str(promotion_input),
                "--output",
                str(promotion_output),
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = json.loads(result.stdout)
        artifact = json.loads(promotion_output.read_text(encoding="utf-8"))
        self.assertTrue(receipt["ok"])
        self.assertEqual("installed", artifact["status"])
        installed = load_workspace(
            self.workspace_path, environ={}, cache_root=self.cache_root
        )
        self.assertIn("explored-summary-v1", installed.product_names)
        self.assertNotIn(artifact["product"]["definition"]["sql"], result.stdout)
        self.assertEqual(
            (False, False),
            (
                artifact["installation"]["automatic"],
                artifact["trust"]["stable_identity_granted"],
            ),
        )

    def test_unknown_gravity_dialect_source_requires_reviewed_promotion_path(self) -> None:
        source = self.service.execute(_request(self.database))["promotion_source"]
        source["dialect"] = "unknown"
        source["source_sha256"] = promotion_source_digest(source)

        self.assertEqual(source, validate_promotion_source(source))
        self.assertEqual("unknown", source["dialect"])


if __name__ == "__main__":
    unittest.main()
