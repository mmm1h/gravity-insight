"""Caller-safe Plan error details that keep a next step without echoing request values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ErrorCategory, ErrorCode, ErrorDetail, exit_code_for_error


_DIAGNOSTIC_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class PlanErrorDetail(ErrorDetail):
    """ErrorDetail with bounded Plan-local diagnostics."""

    stage: str | None = None
    cause: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.stage is not None:
            result["stage"] = self.stage
            result["cause"] = self.cause
        return result


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


def safe_detail(
    code: str,
    category: str,
    *,
    stage: str | None = None,
    cause: str | None = None,
    message: str | None = None,
    field: str | None = None,
    next_action: str | None = None,
) -> ErrorDetail:
    if (stage is None) != (cause is None):
        raise ValueError("Plan error stage and cause must be provided together")
    for name, value in (("stage", stage), ("cause", cause)):
        if value is not None and _DIAGNOSTIC_VALUE_RE.fullmatch(value) is None:
            raise ValueError(f"Plan error {name} must be a bounded identifier")
    detail = ErrorDetail.create(
        code,
        message
        or ("Plan adapter failed locally." if category == "local" else "Plan adapter failed."),
        category=category,
        field=field,
        next_action=next_action or category_action(category, code),
    )
    return PlanErrorDetail(
        code=detail.code,
        category=detail.category,
        message=detail.message,
        field=detail.field,
        retryable=detail.retryable,
        retry_after_ms=detail.retry_after_ms,
        next_action=detail.next_action,
        stage=stage,
        cause=cause,
    )


def exception_detail(exc: Exception, *, stage: str, cause: str) -> ErrorDetail:
    """Classify deterministic post-execution incompatibilities without values."""

    contract_stages = {
        "output_projection",
        "output_validation",
        "output_budget",
        "partial_result_validation",
        "result_envelope",
    }
    if stage in contract_stages and isinstance(exc, (KeyError, TypeError, ValueError)):
        selected_cause = (
            "key_error"
            if isinstance(exc, KeyError)
            else "type_error"
            if isinstance(exc, TypeError)
            else "value_error"
        )
        return safe_detail(
            "PLAN_ADAPTER_CONTRACT_INCOMPATIBLE",
            ErrorCategory.LOCAL.value,
            stage=stage,
            cause=selected_cause,
        )
    return safe_detail(
        "PLAN_ADAPTER_EXCEPTION",
        ErrorCategory.LOCAL.value,
        stage=stage,
        cause=cause,
    )


def item_limit_detail() -> ErrorDetail:
    return safe_detail(
        ErrorCode.PAGINATION_LIMIT.value,
        ErrorCategory.CALLER.value,
        stage="output_budget",
        cause="max_items_exceeded",
        message="Plan node result exceeded limits.max_items.",
        field="limits.max_items",
        next_action=(
            "Increase this node's limits.max_items to a reviewed bound or narrow "
            "the requested grouping, then retry."
        ),
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
    "exception_detail",
    "item_limit_detail",
    "normalized_category",
    "safe_detail",
    "safe_native_error",
]
