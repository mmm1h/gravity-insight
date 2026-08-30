"""Request-bound Plan adapter for Bilibili account performance."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agents.bilibili_account_performance import (
    BILIBILI_ACCOUNT_PERFORMANCE_NAME,
)
from .bilibili_account_performance import (
    OPERATION_ID,
    normalize_bilibili_account_window,
)
from .bilibili_account_performance_result import (
    SCHEMA_VERSION,
    product_item_count,
    sanitize_product_result,
)
from .errors import InputValidationError
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .actionable_error_values import actual_value


BILIBILI_ACCOUNT_PERFORMANCE_FIELDS = frozenset({"name", "start", "end"})
BILIBILI_ACCOUNT_PERFORMANCE_OUTPUT_FIELDS = frozenset({
    "operation_id",
    "requested_date_range",
    "returned_items",
    "limits",
    "page",
    "data",
})
_TARGETS = frozenset({"/start", "/end"})
_STRUCTURAL = frozenset({
    "schema_version", "ok", "status", "exit_code", "error", "next_action",
    "result_audit",
})


class _VerifiedRows(list[Any]):
    """In-process marker applied after exact request-bound reconstruction."""


def validate_bilibili_account_performance_plan(
    request: Mapping[str, Any],
    context: AdapterContext,
    _workspace: Any,
) -> None:
    if set(request) != BILIBILI_ACCOUNT_PERFORMANCE_FIELDS:
        raise input_error(
            f"actual value: {actual_value(sorted(request))}; bilibili_account_performance "
            "request fields are incomplete or unavailable; must include the required product fields",
            "request",
        )
    if request.get("name") != BILIBILI_ACCOUNT_PERFORMANCE_NAME:
        raise input_error(
            f"actual value: {actual_value(request.get('name'))}; "
            "bilibili_account_performance name is invalid; must match the documented composite name",
            "name",
        )
    validate_exact_targets(context, _TARGETS)
    _validate_dates(request, set(context.dynamic_targets))
    if context.max_items < 1:
        raise input_error(
            f"actual value: {actual_value(context.max_items)}; " + ("bilibili_account_performance requires one item of Plan capacity"),
            "limits.max_items",
        )
    validate_selected_fields(
        context.output_fields,
        BILIBILI_ACCOUNT_PERFORMANCE_OUTPUT_FIELDS,
        "output_fields",
    )


def execute_bilibili_account_performance_plan(
    sdk: Any,
    request: Mapping[str, Any],
    context: AdapterContext,
) -> dict[str, Any]:
    try:
        window = normalize_bilibili_account_window(request["start"], request["end"])
    except (InputValidationError, KeyError):
        raise input_error(
            "bilibili_account_performance bound dates are invalid; must use YYYY-MM-DD and start must not follow end", "start/end"
        ) from None
    value = sdk.bilibili_account_performance(
        window[0],
        window[1],
        max_workers=1,
        max_pages=context.max_pages,
        max_items=context.max_items,
    )
    safe = sanitize_product_result(
        value,
        operation_id=OPERATION_ID,
        window=window,
        max_pages=context.max_pages,
        max_items=context.max_items,
        max_workers=1,
    )
    if product_item_count(safe) > context.max_items:
        raise input_error(
            f"actual value: {actual_value((product_item_count(safe), context.max_items))}; "
            "bilibili_account_performance exceeded its Plan item budget; must stay at or below "
            "this node max_items; raise limits.max_items",
            "limits.max_items",
        )
    data = safe.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("list"), list):
        safe["data"] = {**dict(data), "list": _VerifiedRows(data["list"])}
    return safe


def is_bilibili_account_performance_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION


def project_bilibili_account_performance_result(
    value: Any,
    fields: tuple[str, ...],
    _context: AdapterContext,
) -> dict[str, Any]:
    if not _verified(value):
        raise RuntimeError(
            "Bilibili account performance Plan result was not request-bound"
        )
    selected = copy.deepcopy(dict(value))
    if not fields or value.get("status") == "contract_changed":
        return selected
    allowed = _STRUCTURAL | set(fields)
    return {key: item for key, item in selected.items() if key in allowed}


def _validate_dates(request: Mapping[str, Any], dynamic: set[str]) -> None:
    start = "2026-01-01" if "/start" in dynamic else request.get("start")
    end = "2026-01-02" if "/end" in dynamic else request.get("end")
    try:
        if not dynamic:
            normalize_bilibili_account_window(start, end)
        else:
            normalize_bilibili_account_window(start, start)
            normalize_bilibili_account_window(end, end)
    except InputValidationError as exc:
        raise input_error(("must correct: " + str(str(exc))), "start/end") from None


def _verified(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    data = value.get("data")
    return isinstance(data, Mapping) and isinstance(data.get("list"), _VerifiedRows)


__all__ = [
    "BILIBILI_ACCOUNT_PERFORMANCE_FIELDS",
    "BILIBILI_ACCOUNT_PERFORMANCE_NAME",
    "BILIBILI_ACCOUNT_PERFORMANCE_OUTPUT_FIELDS",
    "execute_bilibili_account_performance_plan",
    "is_bilibili_account_performance_result",
    "project_bilibili_account_performance_result",
    "validate_bilibili_account_performance_plan",
]
