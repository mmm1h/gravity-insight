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


RESULT_SCHEMA_VERSION = "gravity.mcp-tool-result.v1"
ERROR_SCHEMA_VERSION = "gravity.mcp-error.v1"


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
        wrapper = _budget_error(tool_name, max_bytes)
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
) -> dict[str, Any]:
    domain = _exception_envelope(error)
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


def _exception_envelope(error: BaseException) -> dict[str, Any]:
    if isinstance(error, GravityInsightError):
        detail = error_detail_from_exception(error)
        return {
            "schema_version": ERROR_SCHEMA_VERSION,
            "ok": False,
            "status": "error",
            "exit_code": exit_code_for_error(detail),
            "error": detail.to_dict(),
            "network_called": False,
        }
    category = (
        ErrorCategory.CALLER
        if isinstance(error, (ValueError, TypeError, AgentRuntimeContractError))
        else ErrorCategory.LOCAL
    )
    code = "MCP_INPUT_INVALID" if category is ErrorCategory.CALLER else "MCP_ADAPTER_FAILED"
    return {
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
        "network_called": False,
    }


def _budget_error(tool_name: str, maximum: int) -> dict[str, Any]:
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
        },
        "network_called": False,
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "tool": tool_name,
        "ok": False,
        "status": "error",
        "result": domain,
    }


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
