"""Sequential, resumable Evidence verification over configured SQL products."""

from __future__ import annotations

from datetime import date
from typing import Any

from gravity_insight.http_runtime import SQL_PROFILE
from gravity_insight.sql import products
from gravity_insight.workspace import Workspace, load_workspace

import copy
import hashlib
import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel, ParseError, SqlglotError


VERIFICATION_RUN_VERSION = products.VERIFICATION_RUN_VERSION
VERIFICATION_RESUME_POLICY = products.VERIFICATION_RESUME_POLICY
VERIFICATION_CONCURRENCY = products.VERIFICATION_CONCURRENCY
VERIFICATION_MIN_BACKOFF_MS = products.VERIFICATION_MIN_BACKOFF_MS
VERIFICATION_MAX_BACKOFF_MS = products.VERIFICATION_MAX_BACKOFF_MS


def verify_all(
    client: Any,
    day: date,
    *,
    max_workers: int = products.VERIFICATION_CONCURRENCY,
    workspace: Workspace | None = None,
    resume: Mapping[str, Any] | None = None,
    sleeper: Any = time.sleep,
    clock: Any = None,
) -> dict[str, Any]:
    selected = load_workspace() if workspace is None else workspace
    return products.execute_sql_verification(
        products, client, day, max_workers=max_workers, workspace=selected,
        resume=resume, sleeper=sleeper, clock=clock,
    )


def write_verification_checkpoint(
    value: Mapping[str, Any], day: date, *, workspace: Workspace | None = None
) -> Path:
    selected = load_workspace() if workspace is None else workspace
    return products.write_verification_checkpoint(products, value, day, selected)


def read_verification_checkpoint(
    day: date, *, workspace: Workspace | None = None
) -> dict[str, Any]:
    selected = load_workspace() if workspace is None else workspace
    return products.read_verification_checkpoint(products, day, selected)


def clear_verification_checkpoint(
    day: date, *, workspace: Workspace | None = None
) -> None:
    selected = load_workspace() if workspace is None else workspace
    products.clear_verification_checkpoint(products, day, selected)


def verification_checkpoint_path(
    day: date, *, workspace: Workspace | None = None
) -> Path:
    selected = load_workspace() if workspace is None else workspace
    return products.verification_checkpoint_path(products, day, selected)


def is_incomplete_verification(value: Any) -> bool:
    return products.is_incomplete_verification(value)


def run_verification_cli(
    client: Any, day: date, workspace: Workspace, **options: Any
) -> int:
    return products.run_verification_cli(
        products, client, day, workspace, **options
    )


FAST_LANE_REQUEST_VERSION = "gravity.sql-fast-lane-request.v1"
FAST_LANE_RESULT_VERSION = "gravity.sql-fast-lane-result.v1"
FAST_LANE_PROMOTION_SOURCE_VERSION = "gravity.sql-explorer-promotion-source.v1"
FAST_LANE_DIALECT = "unknown"
FAST_LANE_PATH = "/custom_sql/api/sql/execute"
_FAST_LANE_METHOD = "POST"
_FAST_LANE_HOST = "api-insight.gravity-engine.com"
_FAST_LANE_AUTH_CODES = frozenset({2001, 10000, 10001})
_FAST_LANE_PARSER_VERSION = "30.17.0"
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RELATION = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$"
)
_FORBIDDEN_AST = frozenset(
    {
        "Alter", "Analyze", "Attach", "Cache", "Command", "Commit", "Copy",
        "Create", "Delete", "Detach", "Drop", "Execute", "Grant", "Insert",
        "Kill", "LoadData", "Lock", "Merge", "Pragma", "Procedure", "Revoke",
        "Rollback", "Set", "Transaction", "TruncateTable", "Uncache", "Unlock",
        "Update", "Use",
    }
)
_SAFETY = {
    "independent_read_only_identity": "unavailable_shared_web_session",
    "ast": "enforced",
    "single_statement": "enforced",
    "select_with_only": "enforced",
    "relation_function_output_allowlists": "enforced",
    "read_only_transaction": "unavailable_upstream_contract",
    "timeout": "enforced",
    "scan_budget": "unavailable_upstream_contract",
    "row_byte_column_budget": "enforced",
    "in_flight_cancellation": "unavailable_timeout_only",
}


class SqlFastLaneError(ValueError):
    def __init__(
        self, code: str, message: str, *, stage: str, category: str,
        field: str | None = None, retryable: bool = False,
        reached_sql_engine: str = "no", next_action: str,
    ) -> None:
        self.code, self.safe_message = code, message
        self.sql_stage, self.sql_category, self.field = stage, category, field
        self.retryable, self.reached_sql_engine = retryable, reached_sql_engine
        self.next_action = next_action
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, repr=False)
class FastLaneStatement:
    sql: str
    outputs: tuple[str, ...]
    budgets: dict[str, int]
    statement_sha256: str
    policy_sha256: str
    route_sha256: str
    relations: tuple[str, ...]
    functions: tuple[str, ...]


class GravitySqlExplorerAdapter:
    """One explicit exploratory Gravity SQL adapter; it never grants Stable trust."""

    def __init__(self, runtime: Any | None = None, *, runtime_factory: Any = None,
                 clock: Any = None) -> None:
        self._runtime = runtime
        self._runtime_factory = runtime_factory
        self._clock = clock or time.monotonic

    def inspect(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._run("inspect", request)

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._run("execute", request)

    def _run(self, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
        started, statement, called = self._clock(), None, False
        try:
            statement = compile_fast_lane_statement(request)
            if operation == "inspect":
                return _fast_lane_success(operation, statement, [], 0, started, self._clock(), False)
            if self._runtime is None and self._runtime_factory is not None:
                try:
                    self._runtime = self._runtime_factory()
                except Exception as exc:
                    raise _execution_error(exc) from None
            if self._runtime is None:
                raise _error(
                    "SQL_FAST_LANE_RUNTIME_REQUIRED", "Gravity SQL runtime is unavailable",
                    "execute", "runtime", reached="no",
                    next_action="Construct the Adapter with the shared governed Runtime, then retry.",
                )
            called = True
            try:
                response = self._runtime.request(
                    SQL_PROFILE, _FAST_LANE_METHOD, FAST_LANE_PATH,
                    json_body={"sql": statement.sql, "tabId": "1"},
                    semantic_auth_codes=_FAST_LANE_AUTH_CODES,
                    timeout=statement.budgets["statement_timeout_ms"] / 1000,
                    attempts=1,
                )
            except Exception as exc:
                raise _execution_error(exc) from None
            rows, size = _project_fast_lane_response(response, statement)
            return _fast_lane_success(operation, statement, rows, size, started, self._clock(), True)
        except SqlFastLaneError as exc:
            return _fast_lane_failure(operation, statement, exc, started, self._clock(), called)


def validate_sql_fast_lane_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "sql", "policy"}:
        raise _bind_error("SQL Fast Lane request must contain only schema_version, sql, and policy")
    selected = copy.deepcopy(dict(value))
    if selected["schema_version"] != FAST_LANE_REQUEST_VERSION:
        raise _bind_error("SQL Fast Lane request schema version is unsupported", "schema_version")
    if not isinstance(selected["sql"], str) or not selected["sql"].strip() or len(selected["sql"]) > 65536:
        raise _bind_error("SQL Fast Lane sql must be a bounded non-empty string", "sql")
    policy = selected["policy"]
    fields = {"allowed_relations", "allowed_functions", "output_columns", "budgets"}
    if not isinstance(policy, Mapping) or set(policy) != fields:
        raise _bind_error("SQL Fast Lane policy shape is invalid", "policy")
    _validate_string_list(policy["allowed_relations"], _RELATION, 128, True, "policy.allowed_relations")
    _validate_string_list(policy["allowed_functions"], _NAME, 128, True, "policy.allowed_functions")
    _validate_string_list(policy["output_columns"], _NAME, 256, False, "policy.output_columns")
    budgets = policy["budgets"]
    bounds = {
        "statement_timeout_ms": (1, 30000), "max_rows": (1, 1000),
        "max_output_bytes": (1, 8388608), "max_cell_bytes": (1, 1048576),
        "max_columns": (1, 256),
    }
    if not isinstance(budgets, Mapping) or set(budgets) != set(bounds):
        raise _bind_error("SQL Fast Lane budget shape is invalid", "policy.budgets")
    if any(type(budgets[key]) is not int or not low <= budgets[key] <= high
           for key, (low, high) in bounds.items()):
        raise _bind_error("SQL Fast Lane budget is outside its fixed bound", "policy.budgets")
    if len(policy["output_columns"]) > budgets["max_columns"]:
        raise _bind_error("declared outputs exceed max_columns", "policy.output_columns")
    return selected


def _validate_string_list(value: Any, pattern: re.Pattern[str], limit: int,
                          allow_empty: bool, field: str) -> None:
    valid = isinstance(value, list) and (allow_empty or bool(value)) and len(value) <= limit
    valid = valid and len(value) == len(set(value)) if isinstance(value, list) else False
    valid = valid and all(isinstance(item, str) and pattern.fullmatch(item) for item in value)
    if not valid:
        raise _bind_error("SQL Fast Lane allowlist is invalid", field)


def compile_fast_lane_statement(request: Mapping[str, Any]) -> FastLaneStatement:
    selected, route_sha = validate_sql_fast_lane_request(request), _registered_route_sha256()
    if sqlglot.__version__ != _FAST_LANE_PARSER_VERSION:
        raise _compile_error("SQL_FAST_LANE_PARSER_UNAVAILABLE", "governed sqlglot version is unavailable")
    try:
        statements = sqlglot.parse(selected["sql"], error_level=ErrorLevel.RAISE)
    except (ParseError, SqlglotError, TypeError, ValueError):
        raise _compile_error("SQL_FAST_LANE_PARSE_FAILED", "SQL is invalid under the generic grammar") from None
    if len(statements) != 1 or statements[0] is None:
        raise _compile_error("SQL_FAST_LANE_MULTIPLE_STATEMENTS", "exactly one SQL statement is required")
    tree = statements[0]
    _validate_read_ast(tree)
    policy = selected["policy"]
    relations, functions, outputs = _ast_relations(tree), _ast_functions(tree), _ast_outputs(tree)
    if not set(relations) <= {item.casefold() for item in policy["allowed_relations"]}:
        raise _compile_error("SQL_FAST_LANE_RELATION_FORBIDDEN", "SQL uses a relation outside the allowlist")
    if not set(functions) <= {item.casefold() for item in policy["allowed_functions"]}:
        raise _compile_error("SQL_FAST_LANE_FUNCTION_FORBIDDEN", "SQL uses a function outside the allowlist")
    if outputs != tuple(policy["output_columns"]):
        raise _compile_error("SQL_FAST_LANE_OUTPUT_CONTRACT_INVALID", "SQL outputs differ from the allowlist")
    _validate_limit(tree, policy["budgets"]["max_rows"])
    rendered = _canonical_sql(tree)
    normalized_policy = {**copy.deepcopy(dict(policy)), "dialect": FAST_LANE_DIALECT,
                         "route_sha256": route_sha}
    return FastLaneStatement(
        rendered, outputs, dict(policy["budgets"]),
        _digest({"dialect": FAST_LANE_DIALECT, "sql": rendered}),
        _digest(normalized_policy), route_sha, relations, functions,
    )


def _validate_read_ast(tree: exp.Expression) -> None:
    forbidden = not isinstance(tree, exp.Select) or tree.args.get("into") is not None
    forbidden = forbidden or any(tree.find_all(exp.SetOperation))
    forbidden = forbidden or any(type(node).__name__ in _FORBIDDEN_AST for node in tree.walk())
    if forbidden:
        raise _compile_error("SQL_FAST_LANE_STATEMENT_FORBIDDEN", "only SELECT or WITH ... SELECT is allowed")
    if any(getattr(node, "comments", None) for node in tree.walk()):
        raise _compile_error("SQL_FAST_LANE_COMMENTS_FORBIDDEN", "SQL comments are unavailable")
    if any(star.find_ancestor(exp.Count) is None for star in tree.find_all(exp.Star)):
        raise _compile_error("SQL_FAST_LANE_STAR_PROJECTION_FORBIDDEN", "star output is unavailable")


def _ast_relations(tree: exp.Expression) -> tuple[str, ...]:
    ctes = {item.alias_or_name.casefold() for item in tree.find_all(exp.CTE) if item.alias_or_name}
    values = []
    for table in tree.find_all(exp.Table):
        if table.name.casefold() in ctes and not table.db and not table.catalog:
            continue
        parts = [part.name for part in table.parts if isinstance(part, exp.Identifier)]
        if len(parts) != len(table.parts) or not 1 <= len(parts) <= 3:
            raise _compile_error("SQL_FAST_LANE_RELATION_FORBIDDEN", "relation identity is dynamic")
        values.append(".".join(parts).casefold())
    return tuple(sorted(set(values)))


def _ast_functions(tree: exp.Expression) -> tuple[str, ...]:
    values = []
    for function in tree.find_all(exp.Func):
        name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        normalized = str(name or "").strip().casefold()
        if not _NAME.fullmatch(normalized):
            raise _compile_error("SQL_FAST_LANE_FUNCTION_FORBIDDEN", "function identity is dynamic")
        values.append(normalized)
    return tuple(sorted(set(values)))


def _ast_outputs(tree: exp.Select) -> tuple[str, ...]:
    values = tuple(item.alias_or_name for item in tree.selects)
    if not values or len(values) != len(set(values)) or any(not isinstance(item, str) or not _NAME.fullmatch(item) for item in values):
        raise _compile_error("SQL_FAST_LANE_OUTPUT_CONTRACT_INVALID", "every output needs a unique safe name")
    return values


def _validate_limit(tree: exp.Select, maximum: int) -> None:
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if not isinstance(value, exp.Literal) or not value.is_int or int(value.this) > maximum:
        raise _compile_error("SQL_FAST_LANE_LIMIT_REQUIRED", "literal outer LIMIT must fit max_rows")
    if tree.args.get("offset") is not None:
        raise _compile_error("SQL_FAST_LANE_OFFSET_FORBIDDEN", "OFFSET is unavailable")


def _canonical_sql(tree: exp.Expression) -> str:
    try:
        rendered = tree.sql(comments=False, pretty=False, unsupported_level=ErrorLevel.RAISE)
        repeated = sqlglot.parse_one(rendered, error_level=ErrorLevel.RAISE).sql(
            comments=False, pretty=False, unsupported_level=ErrorLevel.RAISE)
    except (ParseError, SqlglotError, TypeError, ValueError):
        raise _compile_error("SQL_FAST_LANE_CANONICALIZATION_FAILED", "generic AST is unstable") from None
    if not rendered or rendered != repeated:
        raise _compile_error("SQL_FAST_LANE_CANONICALIZATION_FAILED", "generic AST is unstable")
    return rendered


def _registered_route_sha256() -> str:
    root = Path(__file__).resolve().parents[1] / "contracts" / "routes"
    try:
        registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
        routes = [item for item in registry["routes"]
                  if item.get("method") == _FAST_LANE_METHOD and item.get("path") == FAST_LANE_PATH]
        confirmations = json.loads((root / "probe-read-confirmations.json").read_text(encoding="utf-8"))
        confirmed = [item for item in confirmations["confirmations"]
                     if item.get("method") == _FAST_LANE_METHOD and item.get("path") == FAST_LANE_PATH]
        if len(routes) != 1 or len(confirmed) != 1:
            raise KeyError
        route = routes[0].get("route_contract", {})
        route_sha = _digest(route)
        observed = (
            routes[0].get("classification"), routes[0].get("disposition"),
            routes[0].get("host"), routes[0].get("dialect"),
            routes[0].get("route_sha256"),
            route.get("api_origin"), route.get("method"), route.get("path"),
        )
        expected = (
            "read", "governed_sql_fast_lane", _FAST_LANE_HOST,
            "unknown", route_sha, f"https://{_FAST_LANE_HOST}",
            _FAST_LANE_METHOD, FAST_LANE_PATH,
        )
        if observed != expected or not _valid_read_confirmation(confirmed[0]):
            raise KeyError
        return route_sha
    except Exception:
        raise _compile_error("SQL_FAST_LANE_ROUTE_UNREGISTERED", "exact route registration is invalid") from None


def _valid_read_confirmation(value: Mapping[str, Any]) -> bool:
    try:
        reviewed = date.fromisoformat(value.get("reviewed_at", "")).isoformat()
    except (TypeError, ValueError):
        return False
    evidence = value.get("evidence")
    return (
        value.get("decision") == "confirmed_read"
        and reviewed == value.get("reviewed_at")
        and bool(str(value.get("reviewer", "")).strip())
        and isinstance(evidence, list)
        and bool(evidence)
        and all(isinstance(item, Mapping)
                and bool(str(item.get("source", "")).strip())
                and bool(str(item.get("detail", "")).strip()) for item in evidence)
    )


def _project_fast_lane_response(response: Any, statement: FastLaneStatement) -> tuple[list[dict[str, Any]], int]:
    payload = _response_payload(response)
    query = payload["data"] if isinstance(payload.get("data"), Mapping) else payload
    state = str(query.get("status", query.get("state", ""))).casefold()
    if query.get("error") or any(token in state for token in ("fail", "error", "reject")):
        raise _error("SQL_FAST_LANE_PLAN_FAILED", "SQL engine rejected the read", "plan", "upstream",
                     reached="yes", next_action="Correct or simplify the SELECT; do not retry unchanged.")
    result = query.get("result")
    if not isinstance(result, Mapping):
        raise _shape_error("tabular result object is missing")
    columns = _column_names(result.get("columns"))
    if tuple(columns) != statement.outputs or len(columns) > statement.budgets["max_columns"]:
        raise _shape_error("output columns changed or exceeded max_columns")
    raw_rows = result.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) > statement.budgets["max_rows"]:
        raise _shape_error("rows changed shape or exceeded max_rows", category="budget")
    rows = [_normalize_row(row, columns) for row in raw_rows]
    size = _output_bytes(rows, statement.budgets)
    return rows, size


def _response_payload(response: Any) -> Mapping[str, Any]:
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        raise _shape_error("HTTP status shape changed")
    if status >= 300:
        raise _error("SQL_FAST_LANE_HTTP_FAILED", "SQL HTTP request failed", "execute", "upstream",
                     retryable=status in {408, 429, 500, 502, 503, 504}, reached="unknown",
                     next_action="Retry once only when retryable; otherwise re-verify the route.")
    payload = getattr(response, "payload", None)
    if not isinstance(payload, Mapping):
        raise _shape_error("response is not an object")
    if payload.get("code") != 200:
        raise _error("SQL_FAST_LANE_PLAN_FAILED", "protocol code rejected the read", "plan", "upstream",
                     reached="yes", next_action="Do not retry unchanged.")
    return payload


def _column_names(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _shape_error("columns are missing")
    names = [item if isinstance(item, str) else item.get("name", item.get("columnName"))
             if isinstance(item, Mapping) else None for item in value]
    if len(names) != len(set(names)) or any(not isinstance(item, str) or not _NAME.fullmatch(item) for item in names):
        raise _shape_error("column identity changed")
    return names


def _normalize_row(value: Any, columns: list[str]) -> dict[str, Any]:
    if isinstance(value, list) and len(value) == len(columns):
        row = dict(zip(columns, value, strict=True))
    elif isinstance(value, Mapping) and set(value) == set(columns):
        row = {column: value[column] for column in columns}
    else:
        raise _shape_error("row shape changed")
    scalars = all(item is None or isinstance(item, (str, bool, int))
                  or isinstance(item, float) and math.isfinite(item) for item in row.values())
    if not scalars:
        raise _shape_error("cell shape changed")
    return row


def _output_bytes(rows: list[dict[str, Any]], budgets: Mapping[str, int]) -> int:
    total = 0
    for row in rows:
        if any(len(_json_bytes(item)) > budgets["max_cell_bytes"] for item in row.values()):
            raise _shape_error("cell exceeded max_cell_bytes", category="budget")
        total += len(_json_bytes(row))
        if total > budgets["max_output_bytes"]:
            raise _shape_error("output exceeded max_output_bytes", category="budget")
    return total


def _fast_lane_success(operation: str, statement: FastLaneStatement, rows: list[dict[str, Any]],
                       size: int, started: float, finished: float, called: bool) -> dict[str, Any]:
    result = _base_fast_lane_result(operation, statement, started, finished, called)
    result.update(ok=True, status="ready" if operation == "inspect" else "success",
                  rows=copy.deepcopy(rows), row_count=len(rows), output_bytes=size, error=None,
                  promotion_source=_promotion_source(statement, len(rows), size) if called else None)
    return _finalize_fast_lane_result(result)


def _fast_lane_failure(operation: str, statement: FastLaneStatement | None, error: SqlFastLaneError,
                       started: float, finished: float, called: bool) -> dict[str, Any]:
    result = _base_fast_lane_result(operation, statement, started, finished, called)
    result.update(ok=False, status="blocked" if error.sql_stage in {"bind", "compile"} else "error",
                  rows=[], row_count=0, output_bytes=0, promotion_source=None,
                  error={"stage": error.sql_stage, "category": error.sql_category,
                         "code": error.code, "field": error.field, "message": error.safe_message,
                         "next_action": error.next_action, "retryable": error.retryable,
                         "reached_sql_engine": error.reached_sql_engine})
    return _finalize_fast_lane_result(result)


def _base_fast_lane_result(operation: str, statement: FastLaneStatement | None,
                           started: float, finished: float, called: bool) -> dict[str, Any]:
    return {
        "schema_version": FAST_LANE_RESULT_VERSION, "operation": operation,
        "trust": "exploratory", "completeness": "unknown", "allowed_claims": [],
        "stable_dependency_allowed": False, "dialect": FAST_LANE_DIALECT,
        "parser": {"name": "sqlglot", "version": _FAST_LANE_PARSER_VERSION,
                   "dialect_mode": "generic_conservative_only"},
        "safety": copy.deepcopy(_SAFETY),
        "statement_sha256": statement.statement_sha256 if statement else None,
        "policy_sha256": statement.policy_sha256 if statement else None,
        "output_columns": list(statement.outputs) if statement else [], "network_called": called,
        "execution": {"request_count": int(called),
                      "elapsed_ms": min(900000, max(0, int((finished - started) * 1000))),
                      "statement_executed": called},
    }


def validate_sql_fast_lane_result(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    fixed = (selected.get("trust"), selected.get("completeness"), selected.get("allowed_claims"),
             selected.get("stable_dependency_allowed"), selected.get("dialect"))
    if fixed != ("exploratory", "unknown", [], False, "unknown"):
        raise _shape_error("result trust boundary changed")
    if selected.get("row_count") != len(selected.get("rows", [])):
        raise _shape_error("result row count changed")
    digest = selected.pop("result_sha256", None)
    if digest != _digest(selected):
        raise _shape_error("result digest changed")
    selected["result_sha256"] = digest
    return selected


def _finalize_fast_lane_result(value: dict[str, Any]) -> dict[str, Any]:
    value["result_sha256"] = _digest(value)
    return validate_sql_fast_lane_result(value)


def _promotion_source(statement: FastLaneStatement, row_count: int, size: int) -> dict[str, Any]:
    source = {"schema_version": FAST_LANE_PROMOTION_SOURCE_VERSION, "dialect": "unknown",
              "statement_sha256": statement.statement_sha256, "policy_sha256": statement.policy_sha256,
              "session_sha256": _digest({"route": statement.route_sha256, "rows": row_count, "bytes": size}),
              "output_columns": list(statement.outputs), "execution_verified": True,
              "trust": "exploratory", "completeness": "unknown"}
    source["source_sha256"] = _digest(source)
    return source


def _execution_error(exc: Exception) -> SqlFastLaneError:
    retryable = type(exc).__name__ in {"TransportError", "Timeout", "ReadTimeout", "ConnectTimeout"}
    return _error("SQL_FAST_LANE_EXECUTION_FAILED", "SQL execution failed", "execute", "runtime",
                  retryable=retryable, reached="unknown",
                  next_action="Retry once only when retryable; otherwise inspect route health.")


def _bind_error(message: str, field: str | None = None) -> SqlFastLaneError:
    return _error("SQL_FAST_LANE_BIND_FAILED", message, "bind", "input", field=field,
                  next_action="Correct the request; no network request was sent.")


def _compile_error(code: str, message: str) -> SqlFastLaneError:
    return _error(code, message, "compile", "policy",
                  next_action="Correct the SQL AST or allowlist; no network request was sent.")


def _shape_error(message: str, *, category: str = "contract") -> SqlFastLaneError:
    return _error("SQL_FAST_LANE_SHAPE_FAILED", message, "shape", category, reached="yes",
                  next_action="Stop automation and re-verify the response projection.")


def _error(code: str, message: str, stage: str, category: str, *, field: str | None = None,
           retryable: bool = False, reached: str = "no", next_action: str) -> SqlFastLaneError:
    return SqlFastLaneError(code, message, stage=stage, category=category, field=field,
                            retryable=retryable, reached_sql_engine=reached, next_action=next_action)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


# Keep the long-standing products.verify_all re-export as the only products ->
# verification import site. Tests can discover the new owner without growing
# the import graph; normal SDK callers import GravitySqlExplorerAdapter here.
verify_all.GravitySqlExplorerAdapter = GravitySqlExplorerAdapter
verify_all.clear_verification_checkpoint = clear_verification_checkpoint
verify_all.is_incomplete_verification = is_incomplete_verification
verify_all.read_verification_checkpoint = read_verification_checkpoint
verify_all.run_cli = run_verification_cli
verify_all.write_verification_checkpoint = write_verification_checkpoint
