"""Strict machine contracts for isolated exploratory SQL sessions."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)


REQUEST_SCHEMA_VERSION = "gravity.sql-explorer-request.v1"
RESULT_SCHEMA_VERSION = "gravity.sql-explorer-result.v1"
SESSION_SCHEMA_VERSION = "gravity.sql-explorer-session.v1"
PROMOTION_SOURCE_SCHEMA_VERSION = "gravity.sql-explorer-promotion-source.v1"
PROMOTION_REQUEST_SCHEMA_VERSION = "gravity.sql-explorer-promotion-request.v1"
PROMOTION_SCHEMA_VERSION = "gravity.sql-explorer-promotion.v1"
PARSER_NAME = "sqlglot"
PARSER_VERSION = "30.17.0"
DIALECT = "sqlite"
_REQUEST_SCHEMA = "sql-explorer-request-v1.schema.json"
_RESULT_SCHEMA = "sql-explorer-result-v1.schema.json"
_PROMOTION_REQUEST_SCHEMA = "sql-explorer-promotion-request-v1.schema.json"
_PROMOTION_SCHEMA = "sql-explorer-promotion-v1.schema.json"
_SHA_FIELDS = {
    "statement_sha256",
    "policy_sha256",
    "database_key_sha256",
    "session_sha256",
}
_SESSION_FIELDS = {
    "schema_version",
    "dialect",
    "parser",
    "engine",
    "statement_sha256",
    "policy_sha256",
    "database_key_sha256",
    "identity",
    "transaction_mode",
    "budgets",
    "used_relation_count",
    "used_function_count",
    "output_columns",
    "parameter_count",
    "statement_executed",
    "runtime_transport_requests",
    "session_sha256",
}
_SOURCE_FIELDS = {
    "schema_version",
    "dialect",
    "statement_sha256",
    "policy_sha256",
    "session_sha256",
    "output_columns",
    "execution_verified",
    "trust",
    "completeness",
    "source_sha256",
}


class SqlExplorerContractError(AgentRuntimeContractError):
    """One Explorer request, result, or promotion is invalid."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        field: str | None = None,
        category: str = "policy",
        status: str = "blocked",
        statement_executed: bool = False,
        next_action: str = "Correct the Explorer request and retry.",
    ) -> None:
        self.code = code
        self.safe_message = message
        self.stage = stage
        self.field = field
        self.category = category
        self.status = status
        self.statement_executed = statement_executed
        self.next_action = next_action
        super().__init__(f"{code}: {message}")


def validate_sql_explorer_request(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer request", stage="input")
    _validate_schema(selected, _REQUEST_SCHEMA, "SQL Explorer request", stage="input")
    if selected["dialect"] != DIALECT:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_DIALECT_UNSUPPORTED",
            "only the explicitly governed SQLite dialect is available",
            stage="parse",
            field="dialect",
            category="input",
            next_action="Set dialect to sqlite and use a governed local database.",
        )
    budgets = selected["policy"]["budgets"]
    if budgets["progress_ops"] > budgets["max_vm_steps"]:
        _invalid(
            "SQL_EXPLORER_BUDGET_INVALID",
            "progress_ops cannot exceed max_vm_steps",
            stage="budget",
            field="policy.budgets.progress_ops",
        )
    for index, item in enumerate(selected["parameters"]):
        if isinstance(item, float) and not math.isfinite(item):
            _invalid(
                "SQL_EXPLORER_PARAMETER_INVALID",
                "parameters must be finite JSON scalars",
                stage="input",
                field=f"parameters[{index}]",
            )
    return selected


def validate_sql_explorer_result(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer result", stage="result")
    _validate_schema(selected, _RESULT_SCHEMA, "SQL Explorer result", stage="result")
    session = selected["session"]
    if session is not None:
        session = validate_sql_explorer_session(session)
        selected["session"] = session
    _validate_result_state(selected)
    _validate_rows(selected, session)
    source = selected["promotion_source"]
    if source is not None:
        selected["promotion_source"] = validate_promotion_source(source)
    if selected["result_sha256"] != result_digest(selected):
        _invalid(
            "SQL_EXPLORER_RESULT_INVALID",
            "result digest changed",
            stage="result",
        )
    return selected


def validate_sql_explorer_session(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer session", stage="result")
    if set(selected) != _SESSION_FIELDS:
        _invalid(
            "SQL_EXPLORER_SESSION_INVALID",
            "session shape changed",
            stage="result",
        )
    if selected["schema_version"] != SESSION_SCHEMA_VERSION:
        _session_invalid("session schema version changed")
    if selected["dialect"] != DIALECT:
        _session_invalid("session dialect changed")
    if selected["parser"] != {"name": PARSER_NAME, "version": PARSER_VERSION}:
        _session_invalid("session parser binding changed")
    engine = selected["engine"]
    if not isinstance(engine, Mapping) or set(engine) != {"name", "version"}:
        _session_invalid("session engine binding is invalid")
    if engine.get("name") != "sqlite" or not isinstance(engine.get("version"), str):
        _session_invalid("session engine is not SQLite")
    if any(not _is_sha256(selected.get(field)) for field in _SHA_FIELDS):
        _session_invalid("session digest binding is invalid")
    if selected["identity"] != {
        "identity_class": "sqlite_uri_mode_ro+query_only",
        "database_open_mode": "read_only",
        "query_only": True,
        "authorizer": True,
        "engine_limits": True,
        "progress_handler": True,
    }:
        _session_invalid("read-only identity proof changed")
    if selected["transaction_mode"] != "sqlite_deferred_on_read_only_connection":
        _session_invalid("read transaction mode changed")
    _validate_session_counts(selected)
    if selected["session_sha256"] != session_digest(selected):
        _session_invalid("session digest changed")
    return selected


def validate_promotion_source(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer promotion source", stage="promotion")
    if set(selected) != _SOURCE_FIELDS:
        _promotion_invalid("promotion source shape changed")
    valid = selected["schema_version"] == PROMOTION_SOURCE_SCHEMA_VERSION
    # A reviewed Gravity Fast Lane exploration may be promoted even while the
    # upstream engine dialect remains explicitly unknown. Promotion does not
    # grant stable identity or stable-dependency status.
    valid = valid and selected["dialect"] in {DIALECT, "unknown"}
    valid = valid and all(
        _is_sha256(selected.get(field))
        for field in ("statement_sha256", "policy_sha256", "session_sha256")
    )
    valid = valid and _output_columns(selected.get("output_columns"))
    valid = valid and selected["execution_verified"] is True
    valid = valid and selected["trust"] == "exploratory"
    valid = valid and selected["completeness"] == "unknown"
    if not valid or selected.get("source_sha256") != promotion_source_digest(selected):
        _promotion_invalid("promotion source binding changed")
    return selected


def validate_sql_explorer_promotion_request(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer promotion request", stage="promotion")
    _validate_schema(
        selected,
        _PROMOTION_REQUEST_SCHEMA,
        "SQL Explorer promotion request",
        stage="promotion",
    )
    selected["source"] = validate_promotion_source(selected["source"])
    product = selected["approval"]["registered_product"]
    fields = product["output_fields"]
    if set(product["output_semantics"]) != set(fields):
        _promotion_invalid("registered output semantics must cover every output field")
    if fields != selected["source"]["output_columns"]:
        _promotion_invalid("registered output fields changed from the explored output")
    return selected


def validate_sql_explorer_promotion(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    selected = _mapping(value, "SQL Explorer promotion", stage="promotion")
    _validate_schema(
        selected,
        _PROMOTION_SCHEMA,
        "SQL Explorer promotion",
        stage="promotion",
    )
    selected["source"] = validate_promotion_source(selected["source"])
    _validate_promotion_shape(selected)
    if selected["promotion_sha256"] != promotion_digest(selected):
        _promotion_invalid("promotion digest changed")
    return selected


def result_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("result_sha256", None)
    return canonical_digest(selected)


def session_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("session_sha256", None)
    return canonical_digest(selected)


def promotion_source_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("source_sha256", None)
    return canonical_digest(selected)


def promotion_digest(value: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(value))
    selected.pop("promotion_sha256", None)
    return canonical_digest(selected)


def _validate_result_state(value: Mapping[str, Any]) -> None:
    ok = value["ok"]
    status = value["status"]
    operation = value["operation"]
    error = value["error"]
    source = value["promotion_source"]
    valid_success = ok and error is None and status in {"ready", "success"}
    valid_failure = not ok and isinstance(error, Mapping) and status in {"blocked", "error"}
    if not (valid_success or valid_failure):
        _result_invalid("result status, ok, and error contradict each other")
    if status == "ready" and operation != "inspect":
        _result_invalid("only inspection can return ready")
    if status == "success" and operation != "execute":
        _result_invalid("only execution can return success")
    if source is not None and status != "success":
        _result_invalid("only successful execution can provide a promotion source")
    if error is not None:
        _validate_error(error)


def _validate_rows(
    value: Mapping[str, Any], session: Mapping[str, Any] | None
) -> None:
    rows = value["rows"]
    if value["row_count"] != len(rows):
        _result_invalid("row count changed")
    if not value["ok"] and rows:
        _result_invalid("failed results cannot expose partial rows")
    if value["operation"] == "inspect" and rows:
        _result_invalid("inspection cannot return rows")
    columns = session["output_columns"] if session is not None else []
    for row in rows:
        _validate_row(row, columns)
    if session is None and (rows or value["row_count"] or value["output_bytes"]):
        _result_invalid("a result without a session cannot contain output")


def _validate_row(row: Mapping[str, Any], columns: list[str]) -> None:
    if list(row) != columns:
        _result_invalid("row columns changed from the inspected output")
    if any(
        isinstance(item, float) and not math.isfinite(item)
        for item in row.values()
    ):
        _result_invalid("row values must be finite JSON scalars")


def _validate_error(value: Mapping[str, Any]) -> None:
    fields = {
        "category",
        "code",
        "stage",
        "field",
        "message",
        "next_action",
        "statement_executed",
    }
    if set(value) != fields:
        _result_invalid("error shape changed")
    if value.get("category") not in {"input", "policy", "local", "budget", "runtime"}:
        _result_invalid("error category changed")
    if value.get("stage") not in {"input", "parse", "policy", "identity", "budget", "execute", "output"}:
        _result_invalid("error stage changed")
    for field in ("code", "message", "next_action"):
        if not isinstance(value.get(field), str) or not value[field]:
            _result_invalid("error text is invalid")
    if value.get("field") is not None and not isinstance(value["field"], str):
        _result_invalid("error field is invalid")
    if type(value.get("statement_executed")) is not bool:
        _result_invalid("error execution state is invalid")


def _validate_session_counts(value: Mapping[str, Any]) -> None:
    budgets = value["budgets"]
    required = {
        "statement_timeout_ms",
        "max_vm_steps",
        "progress_ops",
        "max_rows",
        "max_output_bytes",
        "max_cell_bytes",
        "scan_or_resource_budget",
    }
    if not isinstance(budgets, Mapping) or set(budgets) != required:
        _session_invalid("session budgets changed")
    if budgets.get("scan_or_resource_budget") != "sqlite_vm_steps":
        _session_invalid("session resource budget is not engine-enforced VM steps")
    for field in ("used_relation_count", "used_function_count", "parameter_count"):
        if type(value[field]) is not int or value[field] < 0:
            _session_invalid("session count is invalid")
    if not _output_columns(value["output_columns"]):
        _session_invalid("session output columns are invalid")
    if type(value["statement_executed"]) is not bool:
        _session_invalid("session execution state is invalid")
    if value["runtime_transport_requests"] != 0:
        _session_invalid("local SQLite cannot report Runtime transport requests")


def _validate_promotion_shape(value: Mapping[str, Any]) -> None:
    product = value["product"]
    expected_product = {"name", "contract_version", "definition", "definition_sha256"}
    if not isinstance(product, Mapping) or set(product) != expected_product:
        _promotion_invalid("promotion product shape changed")
    if product["definition_sha256"] != canonical_digest(product["definition"]):
        _promotion_invalid("promoted product digest changed")
    definition = product["definition"]
    if not isinstance(definition, Mapping):
        _promotion_invalid("promoted product definition is invalid")
    if definition.get("contract_version") != product["contract_version"]:
        _promotion_invalid("promoted product version binding changed")
    if definition.get("promotion_source_sha256") != value["source"]["source_sha256"]:
        _promotion_invalid("promoted product source binding changed")
    if definition.get("review_evidence_sha256") != value["review"]["evidence_sha256"]:
        _promotion_invalid("promoted product review binding changed")
    consumer = value["consumer_contract"]
    required_consumer = {
        "schema_version",
        "selector",
        "request_schema_version",
        "required_inputs",
        "output_fields",
        "output_semantics",
        "privacy",
        "forbidden_claims",
    }
    if not isinstance(consumer, Mapping) or set(consumer) != required_consumer:
        _promotion_invalid("consumer contract shape changed")
    expected_consumer = {
        "schema_version": "gravity.registered-sql-product-consumer.v1",
        "selector": f"sql-product:{product['name']}",
        "request_schema_version": "gravity-sql.query.v1",
        "required_inputs": ["start", "end"],
        "output_fields": definition.get("output_fields"),
        "output_semantics": definition.get("output_semantics"),
        "privacy": definition.get("privacy"),
        "forbidden_claims": definition.get("forbidden_claims"),
    }
    if consumer != expected_consumer:
        _promotion_invalid("consumer contract changed from the registered product")
    installation = value["installation"]
    if installation != {
        "automatic": False,
        "target": f"workspace.products.{product['name']}",
        "replaces_existing": False,
    }:
        _promotion_invalid("promotion installation boundary changed")
    if value["trust"] != {
        "trust_status": "not_evaluated",
        "stable_identity_granted": False,
        "stable_dependency_allowed": False,
        "next_action": "Create same-layer Validation before stable Skill or Journey use.",
    }:
        _promotion_invalid("promotion Trust boundary changed")


def _output_columns(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _validate_schema(
    value: Mapping[str, Any], schema: str, label: str, *, stage: str
) -> None:
    try:
        validate_schema(value, schema, label)
    except AgentRuntimeContractError as exc:
        raise SqlExplorerContractError(
            "SQL_EXPLORER_CONTRACT_INVALID",
            f"{label} does not match its machine schema",
            stage=stage,
            category="input" if stage == "input" else "policy",
        ) from exc


def _mapping(value: Mapping[str, Any], label: str, *, stage: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SqlExplorerContractError(
            "SQL_EXPLORER_CONTRACT_INVALID",
            f"{label} must be an object",
            stage=stage,
            category="input" if stage == "input" else "policy",
        )
    return copy.deepcopy(dict(value))


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _invalid(
    code: str,
    message: str,
    *,
    stage: str,
    field: str | None = None,
) -> None:
    raise SqlExplorerContractError(code, message, stage=stage, field=field)


def _session_invalid(message: str) -> None:
    _invalid("SQL_EXPLORER_SESSION_INVALID", message, stage="result")


def _result_invalid(message: str) -> None:
    _invalid("SQL_EXPLORER_RESULT_INVALID", message, stage="result")


def _promotion_invalid(message: str) -> None:
    _invalid("SQL_EXPLORER_PROMOTION_INVALID", message, stage="promotion")


__all__ = [
    "DIALECT",
    "PARSER_NAME",
    "PARSER_VERSION",
    "PROMOTION_REQUEST_SCHEMA_VERSION",
    "PROMOTION_SCHEMA_VERSION",
    "PROMOTION_SOURCE_SCHEMA_VERSION",
    "REQUEST_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "SqlExplorerContractError",
    "promotion_digest",
    "promotion_source_digest",
    "result_digest",
    "session_digest",
    "validate_promotion_source",
    "validate_sql_explorer_promotion",
    "validate_sql_explorer_promotion_request",
    "validate_sql_explorer_request",
    "validate_sql_explorer_result",
    "validate_sql_explorer_session",
]
