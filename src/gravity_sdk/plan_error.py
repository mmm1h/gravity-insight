"""Caller-safe Plan error details that keep a next step without echoing request values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ErrorCategory, ErrorDetail, exit_code_for_error


def detail_exit_code(detail: ErrorDetail) -> int:
    return exit_code_for_error(detail)


def category_action(category: str, code: str) -> str:
    if code.startswith("AUTH_") or "AUTH" in code:
        return "Run `gravity auth status`; refresh or configure credentials, then retry."
    if code == "CONTRACT_CHANGED":
        return "Stop automation until the governed contract is re-verified."
    if category == ErrorCategory.CALLER.value:
        return "Correct this node request, then retry."
    if category == ErrorCategory.UPSTREAM.value:
        return "Retry the failed node after checking Gravity availability and permissions."
    return "Inspect the controlled adapter and its governed contract before retrying."


def safe_detail(code: str, category: str) -> ErrorDetail:
    return ErrorDetail.create(
        code,
        "Plan adapter failed locally." if category == "local" else "Plan adapter failed.",
        category=category,
        next_action=category_action(category, code),
    )


def safe_native_error(result: Mapping[str, Any]) -> ErrorDetail:
    candidates: list[Any] = [result.get("error")]
    nested = result.get("result")
    if isinstance(nested, Mapping):
        candidates.append(nested.get("error"))
    candidate = next((item for item in candidates if isinstance(item, Mapping)), None)
    if candidate is None:
        return safe_detail("PLAN_ADAPTER_FAILED", ErrorCategory.LOCAL.value)
    category = normalized_category(candidate.get("category"))
    code = candidate.get("code")
    message = candidate.get("message")
    next_action = candidate.get("next_action")
    return ErrorDetail.create(
        str(code) if isinstance(code, str) and code else "PLAN_ADAPTER_FAILED",
        message if isinstance(message, str) and message.strip() else "Plan adapter reported a failure.",
        category=category,
        field=candidate.get("field") if isinstance(candidate.get("field"), str) else None,
        retryable=candidate.get("retryable") if isinstance(candidate.get("retryable"), bool) else None,
        retry_after_ms=candidate.get("retry_after_ms") if type(candidate.get("retry_after_ms")) is int else None,
        next_action=(
            next_action
            if isinstance(next_action, str) and next_action.strip()
            else category_action(category, str(code or ""))
        ),
    )


def normalized_category(value: Any) -> str:
    if value in {item.value for item in ErrorCategory}:
        return str(value)
    if value in {"input", "authentication"}:
        return ErrorCategory.CALLER.value
    if value == "runtime":
        return ErrorCategory.UPSTREAM.value
    return ErrorCategory.LOCAL.value


__all__ = [
    "category_action",
    "detail_exit_code",
    "normalized_category",
    "safe_detail",
    "safe_native_error",
]
