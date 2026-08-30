"""Database-enforced read-only SQLite adapter for SQL Explorer."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .sql_explorer_contract import (
    DIALECT,
    PARSER_NAME,
    PARSER_VERSION,
    SESSION_SCHEMA_VERSION,
    SqlExplorerContractError,
    session_digest,
    validate_sql_explorer_session,
)
from .sql_explorer_policy import CompiledExplorerStatement


Clock = Callable[[], float]
_MIN_SQLITE_VERSION = (3, 40, 0)
_ALLOWED_ACTIONS = frozenset(
    value
    for value in (
        getattr(sqlite3, "SQLITE_SELECT", None),
        getattr(sqlite3, "SQLITE_RECURSIVE", None),
    )
    if isinstance(value, int)
)


class SqliteExplorerAdapter:
    """Open a new database-enforced read-only connection for every operation."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or time.monotonic

    def inspect(
        self, statement: CompiledExplorerStatement
    ) -> dict[str, Any]:
        with _SqliteReadOnlySession(statement, self._clock) as session:
            try:
                session.inspect()
            except SqlExplorerContractError as exc:
                exc.session = session.metadata(statement_executed=False)
                raise
            return session.metadata(statement_executed=False)

    def execute(
        self, statement: CompiledExplorerStatement
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
        with _SqliteReadOnlySession(statement, self._clock) as session:
            try:
                rows, output_bytes = session.execute()
            except SqlExplorerContractError as exc:
                exc.session = session.metadata(
                    statement_executed=exc.statement_executed
                )
                raise
            return session.metadata(statement_executed=True), rows, output_bytes


class _SqliteReadOnlySession:
    """One private SQLite connection whose database identity cannot write."""

    def __init__(
        self, statement: CompiledExplorerStatement, clock: Clock
    ) -> None:
        self.statement = statement
        self.clock = clock
        self._connection: sqlite3.Connection | None = None
        self._deadline = 0.0
        self._progress_calls = 0
        self._interrupt_reason: str | None = None
        self._authorized_relations: set[str] = set()
        self._authorized_functions: set[str] = set()

    def __enter__(self) -> "_SqliteReadOnlySession":
        self._open()
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.set_progress_handler(None, 0)
            connection.set_authorizer(None)
            connection.rollback()
        except sqlite3.Error:
            pass
        finally:
            connection.close()

    def inspect(self) -> None:
        connection = self._require_connection()
        sql = "EXPLAIN QUERY PLAN " + self._bounded_sql()
        try:
            connection.execute(sql, self.statement.parameters).fetchall()
        except sqlite3.Error as exc:
            raise self._database_error(exc, statement_executed=False) from None

    def execute(self) -> tuple[list[dict[str, Any]], int]:
        connection = self._require_connection()
        try:
            cursor = connection.execute(
                self._bounded_sql(), self.statement.parameters
            )
            return self._bounded_rows(cursor)
        except SqlExplorerContractError:
            raise
        except sqlite3.Error as exc:
            raise self._database_error(exc, statement_executed=True) from None

    def metadata(self, *, statement_executed: bool) -> dict[str, Any]:
        budgets = {
            **self.statement.budgets.as_dict(),
            "scan_or_resource_budget": "sqlite_vm_steps",
        }
        result = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "dialect": DIALECT,
            "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
            "engine": {"name": "sqlite", "version": sqlite3.sqlite_version},
            "statement_sha256": self.statement.statement_sha256,
            "policy_sha256": self.statement.policy_sha256,
            "database_key_sha256": self.statement.database_key_sha256,
            "identity": {
                "identity_class": "sqlite_uri_mode_ro+query_only",
                "database_open_mode": "read_only",
                "query_only": True,
                "authorizer": True,
                "engine_limits": True,
                "progress_handler": True,
            },
            "transaction_mode": "sqlite_deferred_on_read_only_connection",
            "budgets": budgets,
            "used_relation_count": len(
                set(self.statement.used_relations) | self._authorized_relations
            ),
            "used_function_count": len(
                set(self.statement.used_functions) | self._authorized_functions
            ),
            "output_columns": list(self.statement.output_columns),
            "parameter_count": len(self.statement.parameters),
            "statement_executed": statement_executed,
            "runtime_transport_requests": 0,
        }
        result["session_sha256"] = session_digest(result)
        return validate_sql_explorer_session(result)

    def _open(self) -> None:
        _runtime_capabilities()
        uri = self.statement.database_path.as_uri() + "?mode=ro"
        timeout = min(self.statement.budgets.statement_timeout_ms / 1000, 5.0)
        try:
            connection = sqlite3.connect(
                uri,
                uri=True,
                isolation_level=None,
                timeout=timeout,
                check_same_thread=True,
            )
            self._connection = connection
            self._configure(connection)
        except SqlExplorerContractError:
            self.__exit__(None, None, None)
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self.__exit__(None, None, None)
            raise SqlExplorerContractError(
                "SQL_EXPLORER_READ_ONLY_IDENTITY_UNPROVEN",
                "the database-enforced read-only connection could not be established",
                stage="identity",
                field="database_path",
                category="local",
                next_action="Provide an existing readable SQLite database file and retry.",
            ) from exc

    def _configure(self, connection: sqlite3.Connection) -> None:
        _engine_limits(connection, self.statement)
        connection.execute("PRAGMA trusted_schema=OFF")
        trusted_schema = connection.execute("PRAGMA trusted_schema").fetchone()
        connection.execute("PRAGMA mmap_size=0")
        mmap_size = connection.execute("PRAGMA mmap_size").fetchone()
        connection.execute("PRAGMA query_only=ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if trusted_schema != (0,) or mmap_size != (0,) or query_only != (1,):
            raise SqlExplorerContractError(
                "SQL_EXPLORER_READ_ONLY_IDENTITY_UNPROVEN",
                "SQLite security settings could not be proved",
                stage="identity",
                category="local",
            )
        connection.execute("BEGIN")
        connection.set_authorizer(self._authorize)
        self._deadline = self.clock() + (
            self.statement.budgets.statement_timeout_ms / 1000
        )
        connection.set_progress_handler(
            self._progress,
            self.statement.budgets.progress_ops,
        )

    def _authorize(
        self,
        action: int,
        first: str | None,
        second: str | None,
        database: str | None,
        source: str | None,
    ) -> int:
        if action in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            relation = _relation(database, first)
            source_relation = _relation(database, source)
            if relation in self.statement.allowed_relations or (
                source_relation in self.statement.allowed_relations
            ):
                self._authorized_relations.add(
                    source_relation
                    if source_relation in self.statement.allowed_relations
                    else relation
                )
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            function = str(second or first or "").casefold()
            if function in self.statement.allowed_functions:
                self._authorized_functions.add(function)
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY

    def _progress(self) -> int:
        self._progress_calls += 1
        if self.clock() >= self._deadline:
            self._interrupt_reason = "timeout"
            return 1
        steps = self._progress_calls * self.statement.budgets.progress_ops
        if steps >= self.statement.budgets.max_vm_steps:
            self._interrupt_reason = "vm_steps"
            return 1
        return 0

    def _bounded_sql(self) -> str:
        limit = self.statement.budgets.max_rows + 1
        return (
            'SELECT * FROM ('
            + self.statement.canonical_sql
            + ') AS "_gravity_explorer" LIMIT '
            + str(limit)
        )

    def _bounded_rows(
        self, cursor: sqlite3.Cursor
    ) -> tuple[list[dict[str, Any]], int]:
        columns = [str(item[0]) for item in cursor.description or ()]
        if columns != list(self.statement.output_columns):
            raise SqlExplorerContractError(
                "SQL_EXPLORER_OUTPUT_CONTRACT_CHANGED",
                "database output columns changed after AST inspection",
                stage="output",
                category="policy",
                statement_executed=True,
            )
        rows: list[dict[str, Any]] = []
        output_bytes = 2
        while True:
            raw = cursor.fetchone()
            if raw is None:
                return rows, output_bytes
            if len(rows) >= self.statement.budgets.max_rows:
                raise SqlExplorerContractError(
                    "SQL_EXPLORER_ROW_BUDGET_EXCEEDED",
                    "query exceeded the enforced row output budget",
                    stage="output",
                    category="budget",
                    statement_executed=True,
                    next_action="Narrow the query or raise the reviewed row budget.",
                )
            row = dict(zip(columns, raw, strict=True))
            encoded = _row_bytes(row, self.statement)
            output_bytes += len(encoded) + (1 if rows else 0)
            if output_bytes > self.statement.budgets.max_output_bytes:
                raise SqlExplorerContractError(
                    "SQL_EXPLORER_BYTE_BUDGET_EXCEEDED",
                    "query exceeded the enforced byte output budget",
                    stage="output",
                    category="budget",
                    statement_executed=True,
                    next_action="Narrow the query or raise the reviewed byte budget.",
                )
            rows.append(row)

    def _database_error(
        self, error: sqlite3.Error, *, statement_executed: bool
    ) -> SqlExplorerContractError:
        if self._interrupt_reason == "timeout":
            return SqlExplorerContractError(
                "SQL_EXPLORER_STATEMENT_TIMEOUT",
                "SQLite interrupted the statement at its timeout budget",
                stage="budget",
                category="budget",
                statement_executed=statement_executed,
                next_action="Reduce query work or raise the reviewed timeout budget.",
            )
        if self._interrupt_reason == "vm_steps":
            return SqlExplorerContractError(
                "SQL_EXPLORER_RESOURCE_BUDGET_EXCEEDED",
                "SQLite interrupted the statement at its VM-step budget",
                stage="budget",
                category="budget",
                statement_executed=statement_executed,
                next_action="Reduce query work or raise the reviewed VM-step budget.",
            )
        message = str(error).casefold()
        if "not authorized" in message or "prohibited" in message:
            return SqlExplorerContractError(
                "SQL_EXPLORER_ENGINE_AUTHORIZATION_DENIED",
                "SQLite authorizer rejected the statement",
                stage="policy",
                category="policy",
                statement_executed=False,
            )
        if "readonly" in message or "read-only" in message:
            return SqlExplorerContractError(
                "SQL_EXPLORER_DATABASE_READ_ONLY",
                "SQLite read-only identity rejected a mutation",
                stage="identity",
                category="policy",
                statement_executed=False,
            )
        if "too big" in message or "too many" in message:
            return SqlExplorerContractError(
                "SQL_EXPLORER_ENGINE_LIMIT_EXCEEDED",
                "SQLite rejected the statement at an engine resource limit",
                stage="budget",
                category="budget",
                statement_executed=statement_executed,
            )
        if "no such table" in message or "no such column" in message:
            return SqlExplorerContractError(
                "SQL_EXPLORER_DATABASE_OBJECT_UNAVAILABLE",
                "an allowlisted database object is unavailable",
                stage="policy",
                category="policy",
                statement_executed=False,
            )
        return SqlExplorerContractError(
            "SQL_EXPLORER_ENGINE_ERROR",
            "SQLite could not execute the governed exploratory statement",
            stage="execute",
            category="runtime",
            status="error",
            statement_executed=statement_executed,
            next_action="Inspect the database locally; no automatic fallback is available.",
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLite Explorer session is not open")
        return self._connection


def _runtime_capabilities() -> None:
    methods = ("set_authorizer", "set_progress_handler", "setlimit", "getlimit")
    if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION or any(
        not hasattr(sqlite3.Connection, method) for method in methods
    ):
        raise SqlExplorerContractError(
            "SQL_EXPLORER_RESOURCE_BUDGET_UNAVAILABLE",
            "SQLite cannot prove the required identity and resource controls",
            stage="budget",
            category="local",
            next_action="Use a Python SQLite build with authorizer, progress, and limit APIs.",
        )


def _engine_limits(
    connection: sqlite3.Connection, statement: CompiledExplorerStatement
) -> None:
    limits = {
        sqlite3.SQLITE_LIMIT_LENGTH: statement.budgets.max_cell_bytes,
        sqlite3.SQLITE_LIMIT_SQL_LENGTH: 131072,
        sqlite3.SQLITE_LIMIT_COLUMN: 256,
        sqlite3.SQLITE_LIMIT_EXPR_DEPTH: 100,
        sqlite3.SQLITE_LIMIT_COMPOUND_SELECT: 1,
        sqlite3.SQLITE_LIMIT_FUNCTION_ARG: 32,
        sqlite3.SQLITE_LIMIT_ATTACHED: 0,
        sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH: 1000,
        sqlite3.SQLITE_LIMIT_TRIGGER_DEPTH: 0,
        sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER: max(1, len(statement.parameters)),
        sqlite3.SQLITE_LIMIT_VDBE_OP: statement.budgets.max_vm_steps,
        sqlite3.SQLITE_LIMIT_WORKER_THREADS: 0,
    }
    try:
        for category, value in limits.items():
            connection.setlimit(category, value)
            if connection.getlimit(category) > value:
                raise ValueError("SQLite limit was not lowered")
    except (AttributeError, sqlite3.Error, TypeError, ValueError) as exc:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_RESOURCE_BUDGET_UNAVAILABLE",
            "SQLite engine limits could not be enforced",
            stage="budget",
            category="local",
            next_action="Use a SQLite build that exposes enforceable runtime limits.",
        ) from exc


def _relation(database: str | None, name: str | None) -> str:
    if not name:
        return ""
    return f"{str(database or 'main').casefold()}.{str(name).casefold()}"


def _row_bytes(
    row: dict[str, Any], statement: CompiledExplorerStatement
) -> bytes:
    for value in row.values():
        if not (
            value is None
            or isinstance(value, (bool, int, float, str))
        ) or isinstance(value, float) and not math.isfinite(value):
            raise SqlExplorerContractError(
                "SQL_EXPLORER_OUTPUT_TYPE_UNSUPPORTED",
                "SQLite returned a non-JSON scalar value",
                stage="output",
                category="policy",
                statement_executed=True,
            )
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > statement.budgets.max_cell_bytes:
            raise SqlExplorerContractError(
                "SQL_EXPLORER_CELL_BUDGET_EXCEEDED",
                "SQLite output exceeded the per-cell byte budget",
                stage="output",
                category="budget",
                statement_executed=True,
            )
    return json.dumps(
        row,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


__all__ = ["SqliteExplorerAdapter"]
