"""Explicit isolated SQL Explorer service and reviewed promotion compiler."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import canonical_digest
from .sql_explorer_contract import (
    PROMOTION_SCHEMA_VERSION,
    PROMOTION_SOURCE_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    SqlExplorerContractError,
    promotion_digest,
    promotion_source_digest,
    result_digest,
    validate_sql_explorer_promotion,
    validate_sql_explorer_promotion_request,
    validate_sql_explorer_request,
    validate_sql_explorer_result,
    validate_sql_explorer_session,
)
from .sql_explorer_policy import compile_sql_explorer_statement
from .sql_explorer_sqlite import Clock, SqliteExplorerAdapter
from .workspace import (
    Workspace,
    WorkspaceError,
    validate_registered_sql_product_definition,
)


class SqlExplorerService:
    """Run only explicit SQLite exploration and compile inert promotions."""

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._workspace = workspace
        self._adapter = SqliteExplorerAdapter(clock)

    def __repr__(self) -> str:
        return "<SqlExplorerService sqlite explicit exploratory only>"

    def inspect(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._run("inspect", request)

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self._run("execute", request)

    def promote(self, request: Mapping[str, Any]) -> dict[str, Any]:
        selected = validate_sql_explorer_promotion_request(request)
        workspace = self._workspace
        if workspace is None or not workspace.configured:
            raise SqlExplorerContractError(
                "SQL_EXPLORER_PROMOTION_WORKSPACE_REQUIRED",
                "promotion requires an explicitly configured workspace",
                stage="promotion",
                field="workspace",
                category="input",
                next_action="Select a workspace, then retry the explicit promotion.",
            )
        approval = selected["approval"]
        name = approval["product_name"]
        if name in workspace.products:
            raise SqlExplorerContractError(
                "SQL_EXPLORER_PROMOTION_PRODUCT_EXISTS",
                "promotion cannot replace an existing registered SQL product",
                stage="promotion",
                field="approval.product_name",
                category="policy",
                next_action="Choose a new versioned product name; do not overwrite automatically.",
            )
        definition = {
            **copy.deepcopy(approval["registered_product"]),
            "contract_version": approval["contract_version"],
            "promotion_source_sha256": selected["source"]["source_sha256"],
            "review_evidence_sha256": approval["review_evidence_sha256"],
        }
        try:
            definition = validate_registered_sql_product_definition(
                workspace, name, definition
            )
        except WorkspaceError as exc:
            raise SqlExplorerContractError(
                "SQL_EXPLORER_PROMOTION_PRODUCT_INVALID",
                "reviewed product does not satisfy the current workspace contract",
                stage="promotion",
                field="approval.registered_product",
                category="policy",
                next_action="Correct the registered SQL product review, then retry.",
            ) from exc
        result = _promotion(selected, name, definition)
        return validate_sql_explorer_promotion(result)

    def _run(
        self, operation: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            selected = validate_sql_explorer_request(request)
            statement = compile_sql_explorer_statement(selected)
            if operation == "inspect":
                session = self._adapter.inspect(statement)
                return _success_result(operation, session, [], 0)
            session, rows, output_bytes = self._adapter.execute(statement)
            return _success_result(operation, session, rows, output_bytes)
        except SqlExplorerContractError as exc:
            session = getattr(exc, "session", None)
            return _error_result(operation, exc, session=session)


def _success_result(
    operation: str,
    session: Mapping[str, Any],
    rows: list[dict[str, Any]],
    output_bytes: int,
) -> dict[str, Any]:
    selected_session = validate_sql_explorer_session(session)
    source = (
        _promotion_source(selected_session)
        if operation == "execute"
        else None
    )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "operation": operation,
        "ok": True,
        "status": "ready" if operation == "inspect" else "success",
        "trust": "exploratory",
        "completeness": "unknown",
        "allowed_claims": [],
        "stable_dependency_allowed": False,
        "session": selected_session,
        "rows": copy.deepcopy(rows),
        "row_count": len(rows),
        "output_bytes": output_bytes,
        "error": None,
        "promotion_source": source,
        "network_called": False,
    }
    result["result_sha256"] = result_digest(result)
    return validate_sql_explorer_result(result)


def _error_result(
    operation: str,
    error: SqlExplorerContractError,
    *,
    session: Mapping[str, Any] | None,
) -> dict[str, Any]:
    selected_session = (
        validate_sql_explorer_session(session) if session is not None else None
    )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "operation": operation,
        "ok": False,
        "status": error.status,
        "trust": "exploratory",
        "completeness": "unknown",
        "allowed_claims": [],
        "stable_dependency_allowed": False,
        "session": selected_session,
        "rows": [],
        "row_count": 0,
        "output_bytes": 0,
        "error": {
            "category": error.category,
            "code": error.code,
            "stage": error.stage,
            "field": error.field,
            "message": error.safe_message,
            "next_action": error.next_action,
            "statement_executed": error.statement_executed,
        },
        "promotion_source": None,
        "network_called": False,
    }
    result["result_sha256"] = result_digest(result)
    return validate_sql_explorer_result(result)


def _promotion_source(session: Mapping[str, Any]) -> dict[str, Any]:
    source = {
        "schema_version": PROMOTION_SOURCE_SCHEMA_VERSION,
        "dialect": session["dialect"],
        "statement_sha256": session["statement_sha256"],
        "policy_sha256": session["policy_sha256"],
        "session_sha256": session["session_sha256"],
        "output_columns": copy.deepcopy(session["output_columns"]),
        "execution_verified": True,
        "trust": "exploratory",
        "completeness": "unknown",
    }
    source["source_sha256"] = promotion_source_digest(source)
    return source


def _promotion(
    request: Mapping[str, Any],
    name: str,
    definition: Mapping[str, Any],
) -> dict[str, Any]:
    approval = request["approval"]
    result = {
        "schema_version": PROMOTION_SCHEMA_VERSION,
        "status": "ready_for_workspace_install",
        "source": copy.deepcopy(request["source"]),
        "review": {
            "decision": "approved",
            "evidence_sha256": approval["review_evidence_sha256"],
        },
        "product": {
            "name": name,
            "contract_version": approval["contract_version"],
            "definition": copy.deepcopy(dict(definition)),
            "definition_sha256": canonical_digest(definition),
        },
        "consumer_contract": {
            "schema_version": "gravity.registered-sql-product-consumer.v1",
            "selector": f"sql-product:{name}",
            "request_schema_version": "gravity-sql.query.v1",
            "required_inputs": ["start", "end"],
            "output_fields": copy.deepcopy(definition["output_fields"]),
            "output_semantics": copy.deepcopy(definition["output_semantics"]),
            "privacy": definition["privacy"],
            "forbidden_claims": copy.deepcopy(definition["forbidden_claims"]),
        },
        "installation": {
            "automatic": False,
            "target": f"workspace.products.{name}",
            "replaces_existing": False,
        },
        "trust": {
            "trust_status": "not_evaluated",
            "stable_identity_granted": False,
            "stable_dependency_allowed": False,
            "next_action": "Install the reviewed product, then create same-layer Validation before stable use.",
        },
        "network_called": False,
    }
    result["promotion_sha256"] = promotion_digest(result)
    return result


__all__ = [
    "SqlExplorerContractError",
    "SqlExplorerService",
    "validate_sql_explorer_promotion",
    "validate_sql_explorer_promotion_request",
    "validate_sql_explorer_request",
    "validate_sql_explorer_result",
]
