"""SQLGlot AST policy for the single supported Explorer dialect."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, SqlglotError

from .agent_runtime_contracts import canonical_digest
from .sql_explorer_contract import (
    DIALECT,
    PARSER_NAME,
    PARSER_VERSION,
    SqlExplorerContractError,
    validate_sql_explorer_request,
)


_OUTPUT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FUNCTION_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ExplorerBudgets:
    statement_timeout_ms: int
    max_vm_steps: int
    progress_ops: int
    max_rows: int
    max_output_bytes: int
    max_cell_bytes: int

    def as_dict(self) -> dict[str, int]:
        return {
            "statement_timeout_ms": self.statement_timeout_ms,
            "max_vm_steps": self.max_vm_steps,
            "progress_ops": self.progress_ops,
            "max_rows": self.max_rows,
            "max_output_bytes": self.max_output_bytes,
            "max_cell_bytes": self.max_cell_bytes,
        }


@dataclass(frozen=True, repr=False)
class CompiledExplorerStatement:
    database_path: Path
    canonical_sql: str
    parameters: tuple[Any, ...]
    allowed_relations: frozenset[str]
    allowed_functions: frozenset[str]
    output_columns: tuple[str, ...]
    used_relations: tuple[str, ...]
    used_functions: tuple[str, ...]
    budgets: ExplorerBudgets
    statement_sha256: str
    policy_sha256: str
    database_key_sha256: str

    def __repr__(self) -> str:
        return (
            "<CompiledExplorerStatement "
            f"statement_sha256={self.statement_sha256} "
            f"policy_sha256={self.policy_sha256}>"
        )


def compile_sql_explorer_statement(
    request: dict[str, Any],
) -> CompiledExplorerStatement:
    selected = validate_sql_explorer_request(request)
    _parser_binding()
    database_path = _database_path(selected["database_path"])
    tree = _parse_one(selected["sql"])
    _query_shape(tree)

    policy = selected["policy"]
    allowed_relations = frozenset(
        item.casefold() for item in policy["allowed_relations"]
    )
    allowed_functions = frozenset(
        item.casefold() for item in policy["allowed_functions"]
    )
    used_relations = _relations(tree)
    used_functions = _functions(tree)
    _allowed(
        used_relations,
        allowed_relations,
        code="SQL_EXPLORER_RELATION_FORBIDDEN",
        noun="relation",
        field="policy.allowed_relations",
    )
    _allowed(
        used_functions,
        allowed_functions,
        code="SQL_EXPLORER_FUNCTION_FORBIDDEN",
        noun="function",
        field="policy.allowed_functions",
    )
    outputs = _outputs(tree)
    if outputs != tuple(policy["output_columns"]):
        _policy_error(
            "SQL_EXPLORER_OUTPUT_CONTRACT_INVALID",
            "outer output columns must exactly match policy.output_columns",
            field="policy.output_columns",
        )
    parameters = tuple(selected["parameters"])
    placeholders = tuple(tree.find_all(exp.Placeholder))
    if any(item.name != "?" for item in placeholders) or len(placeholders) != len(
        parameters
    ):
        _policy_error(
            "SQL_EXPLORER_PLACEHOLDER_MISMATCH",
            "only positional placeholders with an exact parameter count are allowed",
            field="parameters",
        )
    canonical_sql = _canonical_sql(tree)
    budgets = ExplorerBudgets(**policy["budgets"])
    normalized_policy = {
        "dialect": DIALECT,
        "allowed_relations": sorted(allowed_relations),
        "allowed_functions": sorted(allowed_functions),
        "output_columns": list(outputs),
        "budgets": budgets.as_dict(),
    }
    return CompiledExplorerStatement(
        database_path=database_path,
        canonical_sql=canonical_sql,
        parameters=parameters,
        allowed_relations=allowed_relations,
        allowed_functions=allowed_functions,
        output_columns=outputs,
        used_relations=tuple(sorted(used_relations)),
        used_functions=tuple(sorted(used_functions)),
        budgets=budgets,
        statement_sha256=canonical_digest({"dialect": DIALECT, "sql": canonical_sql}),
        policy_sha256=canonical_digest(normalized_policy),
        database_key_sha256=canonical_digest({"path": str(database_path)}),
    )


def _parser_binding() -> None:
    if sqlglot.__version__ != PARSER_VERSION:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_PARSER_UNAVAILABLE",
            "the exact governed SQL parser version is unavailable",
            stage="parse",
            category="local",
            next_action=(
                f"Install {PARSER_NAME}=={PARSER_VERSION}, then retry."
            ),
        )


def _database_path(value: str) -> Path:
    selected = Path(value)
    if not selected.is_absolute():
        raise SqlExplorerContractError(
            "SQL_EXPLORER_DATABASE_PATH_INVALID",
            "database_path must be an absolute regular file",
            stage="identity",
            field="database_path",
            category="input",
        )
    try:
        resolved = selected.resolve(strict=True)
    except (OSError, RuntimeError):
        resolved = None
    if resolved is None or resolved != selected or not resolved.is_file():
        raise SqlExplorerContractError(
            "SQL_EXPLORER_DATABASE_PATH_INVALID",
            "database_path must resolve exactly to an existing regular file",
            stage="identity",
            field="database_path",
            category="input",
        )
    return resolved


def _parse_one(sql: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(
            sql,
            read=DIALECT,
            error_level=ErrorLevel.RAISE,
        )
    except (ParseError, SqlglotError, TypeError, ValueError) as exc:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_PARSE_FAILED",
            "statement is not valid in the declared SQLite dialect",
            stage="parse",
            field="sql",
            category="input",
        ) from exc
    if len(statements) != 1 or statements[0] is None:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_MULTIPLE_STATEMENTS",
            "exactly one SQL statement is required",
            stage="parse",
            field="sql",
            category="input",
        )
    return statements[0]


def _query_shape(tree: exp.Expression) -> None:
    if not isinstance(tree, exp.Select):
        _policy_error(
            "SQL_EXPLORER_STATEMENT_FORBIDDEN",
            "only one outer SELECT statement is allowed",
            field="sql",
        )
    if tree.args.get("into") is not None or any(tree.find_all(exp.SetOperation)):
        _policy_error(
            "SQL_EXPLORER_STATEMENT_FORBIDDEN",
            "SELECT INTO and set operations are unavailable",
            field="sql",
        )
    if any(getattr(node, "comments", None) for node in tree.walk()):
        _policy_error(
            "SQL_EXPLORER_COMMENTS_FORBIDDEN",
            "comments are unavailable in Explorer statements",
            field="sql",
        )
    for star in tree.find_all(exp.Star):
        if star.find_ancestor(exp.Count) is None:
            _policy_error(
                "SQL_EXPLORER_STAR_PROJECTION_FORBIDDEN",
                "star output is unavailable; name every outer output",
                field="sql",
            )


def _relations(tree: exp.Expression) -> frozenset[str]:
    ctes = frozenset(
        item.alias_or_name.casefold()
        for item in tree.find_all(exp.CTE)
        if item.alias_or_name
    )
    relations = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier) or not table.name:
            _policy_error(
                "SQL_EXPLORER_RELATION_FORBIDDEN",
                "dynamic or table-valued relations are unavailable",
                field="sql",
            )
        name = table.name.casefold()
        if name in ctes and not table.db and not table.catalog:
            continue
        database = (table.db or "main").casefold()
        if table.catalog or database != "main" or name.startswith("sqlite_"):
            _policy_error(
                "SQL_EXPLORER_RELATION_FORBIDDEN",
                "attached, catalog, and SQLite system relations are unavailable",
                field="sql",
            )
        relations.add(f"main.{name}")
    return frozenset(relations)


def _functions(tree: exp.Expression) -> frozenset[str]:
    names = set()
    for function in tree.find_all(exp.Func):
        rendered = function.sql(
            dialect=DIALECT,
            comments=False,
            unsupported_level=ErrorLevel.RAISE,
        )
        name, separator, _tail = rendered.partition("(")
        selected = name.strip().casefold()
        if not separator or _FUNCTION_RE.fullmatch(selected) is None:
            _policy_error(
                "SQL_EXPLORER_FUNCTION_FORBIDDEN",
                "a function identity could not be proved from the parsed AST",
                field="sql",
            )
        names.add(selected)
    return frozenset(names)


def _outputs(tree: exp.Select) -> tuple[str, ...]:
    values = []
    for projection in tree.selects:
        name = projection.alias_or_name
        if not isinstance(name, str) or _OUTPUT_RE.fullmatch(name) is None:
            _policy_error(
                "SQL_EXPLORER_OUTPUT_CONTRACT_INVALID",
                "every outer expression must have an explicit safe output name",
                field="sql",
            )
        values.append(name)
    if not values or len(values) != len(set(values)):
        _policy_error(
            "SQL_EXPLORER_OUTPUT_CONTRACT_INVALID",
            "outer output names must be non-empty and unique",
            field="sql",
        )
    return tuple(values)


def _canonical_sql(tree: exp.Expression) -> str:
    try:
        rendered = tree.sql(
            dialect=DIALECT,
            comments=False,
            pretty=False,
            unsupported_level=ErrorLevel.RAISE,
        )
        reparsed = sqlglot.parse_one(
            rendered,
            read=DIALECT,
            error_level=ErrorLevel.RAISE,
        )
        repeated = reparsed.sql(
            dialect=DIALECT,
            comments=False,
            pretty=False,
            unsupported_level=ErrorLevel.RAISE,
        )
    except (ParseError, SqlglotError, TypeError, ValueError) as exc:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_CANONICALIZATION_FAILED",
            "parsed statement cannot be represented exactly in SQLite dialect",
            stage="parse",
            field="sql",
            category="input",
        ) from exc
    if not rendered or repeated != rendered:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_CANONICALIZATION_FAILED",
            "SQLite AST canonicalization is not stable",
            stage="parse",
            field="sql",
            category="input",
        )
    return rendered


def _allowed(
    used: frozenset[str],
    allowed: frozenset[str],
    *,
    code: str,
    noun: str,
    field: str,
) -> None:
    if not used.issubset(allowed):
        _policy_error(
            code,
            f"statement uses a {noun} outside the exact policy allowlist",
            field=field,
        )


def _policy_error(code: str, message: str, *, field: str) -> None:
    raise SqlExplorerContractError(
        code,
        message,
        stage="policy",
        field=field,
        category="policy",
        next_action="Correct the exact Explorer policy or statement, then inspect again.",
    )


__all__ = [
    "CompiledExplorerStatement",
    "ExplorerBudgets",
    "compile_sql_explorer_statement",
]
