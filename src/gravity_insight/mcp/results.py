"""Gravity envelope preservation and MCP CallToolResult mapping."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..agent_runtime_contracts import AgentRuntimeContractError
from ..errors import (
    ErrorCategory,
    GravityInsightError,
    error_detail_from_exception,
    exit_code_for_category,
    exit_code_for_error,
)
from .schemas import MAX_OUTPUT_BYTES, validate_output
from ..contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticEvidence, DiagnosticState,
    EnvelopeObligations, ExecutionState, ExecutionStatus, MutationCertainty,
    MutationState, SemanticState, SemanticValidity, serialize_envelope,
)


RESULT_SCHEMA_VERSION = "gravity.mcp-tool-result.v1"
ERROR_SCHEMA_VERSION = "gravity.mcp-error.v2"


def call_tool_result(
    tool_name: str,
    value: Mapping[str, Any],
    *,
    max_bytes: int = MAX_OUTPUT_BYTES,
    execution: bool = False,
) -> dict[str, Any]:
    domain = dict(value)
    ok = _domain_ok(domain)
    status = str(domain.get("status") or ("success" if ok else "error"))
    wrapper = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "tool": tool_name,
        "ok": ok,
        "status": status,
        "result": domain,
    }
    encoded = _canonical_text(wrapper)
    if len(encoded.encode("utf-8")) > max_bytes:
        wrapper = _budget_error(tool_name, max_bytes, domain)
        encoded = _canonical_text(wrapper)
        is_error = True
    else:
        is_error = bool(execution and not ok)
    validate_output(wrapper)
    return {
        "content": [{"type": "text", "text": encoded}],
        "structuredContent": wrapper,
        "isError": is_error,
    }


def exception_tool_result(
    tool_name: str,
    error: BaseException,
    *,
    max_bytes: int = MAX_OUTPUT_BYTES,
    owner_invoked: bool = False,
) -> dict[str, Any]:
    domain = _exception_envelope(error, network_called=None if owner_invoked else False)
    return call_tool_result(
        tool_name,
        domain,
        max_bytes=max_bytes,
        execution=True,
    )


def _domain_ok(value: Mapping[str, Any]) -> bool:
    if isinstance(value.get("ok"), bool):
        return bool(value["ok"])
    exit_code = value.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return exit_code == 0
    return str(value.get("status", "success")) not in {
        "blocked",
        "error",
        "failed",
        "invalid",
        "quarantined",
    }


def _exception_envelope(error: BaseException, *, network_called: bool | None = False) -> dict[str, Any]:
    if isinstance(error, GravityInsightError):
        detail = error_detail_from_exception(error)
        return serialize_envelope({
            "schema_version": ERROR_SCHEMA_VERSION,
            "ok": False,
            "status": "error",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
            "network_called": network_called,
        }, _exception_obligations(network_called))
    category = (
        ErrorCategory.CALLER
        if isinstance(error, (ValueError, TypeError, AgentRuntimeContractError))
        else ErrorCategory.LOCAL
    )
    code = "MCP_INPUT_INVALID" if category is ErrorCategory.CALLER else "MCP_ADAPTER_FAILED"
    return serialize_envelope({
        "schema_version": ERROR_SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": exit_code_for_category(category),
        "error": {
            "category": category.value,
            "code": code,
            "message": (
                "Tool arguments are invalid"
                if category is ErrorCategory.CALLER
                else "MCP adapter execution failed"
            ),
            "retryable": False,
        },
        "network_called": network_called,
    }, _exception_obligations(network_called))


def _exception_obligations(network_called: bool | None) -> EnvelopeObligations:
    reason = "MCP_OWNER_EXCEPTION" if network_called is None else "MCP_INPUT_REJECTED"
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.FAILED if network_called is None else ExecutionState.NOT_STARTED, reason),
        DataCompleteness(CompletenessState.UNKNOWN, "NO_MCP_RESULT_DELIVERED"),
        SemanticValidity(SemanticState.UNKNOWN, (reason,)),
        DiagnosticEvidence(DiagnosticState.INCOMPLETE, (reason,)),
        MutationCertainty(MutationState.NOT_APPLICABLE, "ADAPTER_HAS_NO_BUSINESS_MUTATION"),
    )


def _budget_error(tool_name: str, maximum: int, source: Mapping[str, Any]) -> dict[str, Any]:
    domain = {
        "schema_version": ERROR_SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": exit_code_for_category(ErrorCategory.CALLER),
        "error": {
            "category": ErrorCategory.CALLER.value,
            "code": "MCP_OUTPUT_BUDGET_EXCEEDED",
            "message": "Tool result exceeds the requested MCP output byte budget",
            "retryable": False,
            "maximum_bytes": maximum,
            "next_action": "The owner already returned this result; do not automatically retry. Elect confirmed file output before a future execution when full results may exceed the MCP budget.",
        },
        "network_called": source.get("network_called") if type(source.get("network_called")) is bool else None,
        "owner_result_received": True,
        "source_status": _source_status(source),
        "source_exit_code": source.get("exit_code") if type(source.get("exit_code")) is int else None,
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "tool": tool_name,
        "ok": False,
        "status": "error",
        "result": domain,
    }


def _source_status(source: Mapping[str, Any]) -> str | None:
    value = source.get("status")
    return value if isinstance(value, str) and value in {"success", "empty", "partial", "error", "blocked", "invalid", "capability_gap", "written"} else None


def _canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = [
    "ERROR_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "call_tool_result",
    "exception_tool_result",
]
