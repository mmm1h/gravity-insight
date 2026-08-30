"""Small shared primitives for deterministic, partially successful composites."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import (
    ErrorCategory,
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    PaginationError,
)
from .export_batch import batch_envelope
from .result_audit import aggregate_result_audit
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value


MAX_COMPOSITE_PAGES = 1_000
MAX_COMPOSITE_ITEMS = 100_000


def normalize_identifier(value: str | int, *, field: str) -> str:
    """Return an opaque, non-empty Gravity identifier without guessing its type."""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _identifier_error(
            field,
            next_action=f"Resolve the workspace alias and retry with its `{field}`.",
        )
    rendered = str(value).strip()
    if not rendered or len(rendered) > 256:
        raise _identifier_error(
            field,
            next_action=f"Resolve the workspace alias and retry with its `{field}`.",
        )
    return rendered


def validate_composite_bounds(
    max_pages: int,
    max_items: int,
    *,
    minimum_items: int,
) -> tuple[int, int]:
    """Validate aggregate composite limits before any client call is made."""

    for field, value, upper in (
        ("max_pages", max_pages, MAX_COMPOSITE_PAGES),
        ("max_items", max_items, MAX_COMPOSITE_ITEMS),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
            raise InputValidationError(
                f"actual value: {actual_value(value)}; " + (f"{field} must be between 1 and {upper}"), field=field
            )
    if max_items < minimum_items:
        raise InputValidationError(
            f"actual value: {actual_value(max_items)}; " + (f"max_items must be at least {minimum_items} for this fixed composite"),
            field="max_items",
        )
    return max_pages, max_items


def enforce_composite_item_budget(
    results: Sequence[Mapping[str, Any]], max_items: int
) -> None:
    """Defend the aggregate row budget even when a compatible client ignores it."""

    used = sum(_batch_result_item_count(result) for result in results)
    if used > max_items:
        raise PaginationError("composite exceeded its aggregate item safety bound")


def ordered_results(
    results: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    component: str,
) -> list[dict[str, Any]]:
    """Join batch output by both identities and restore declaration order."""

    if not isinstance(results, list):
        raise RuntimeError(f"{component} batch client returned an invalid list")
    expected: dict[tuple[str, str], Mapping[str, Any]] = {}
    for request in requests:
        operation_id = request.get("operation_id")
        request_id = request.get("request_id")
        if not isinstance(operation_id, str) or not isinstance(request_id, str):
            raise RuntimeError(f"{component} declared an invalid batch identity")
        key = operation_id, request_id
        if key in expected:
            raise RuntimeError(f"{component} declared a duplicate batch identity")
        expected[key] = request

    joined: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in results:
        if not isinstance(raw, Mapping):
            raise RuntimeError(f"{component} batch client returned an invalid result identity")
        operation_id = raw.get("operation_id")
        request_id = raw.get("request_id")
        if not isinstance(operation_id, str) or not isinstance(request_id, str):
            raise RuntimeError(f"{component} batch client returned an invalid result identity")
        key = operation_id, request_id
        if key not in expected or key in joined:
            raise RuntimeError(f"{component} batch client returned an invalid result identity")
        joined[key] = dict(raw)

    return [
        joined.get(key) or missing_result(key[0], key[1], component=component)
        for key in expected
    ]


def composite_envelope(
    results: Sequence[Mapping[str, Any]],
    *,
    schema_version: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = batch_envelope(list(results))
    next_action = (
        "Consume results in declaration order; continue only from bounded result envelopes."
        if envelope["ok"]
        else "Inspect failed results by source; successful independent sources remain usable."
    )
    return aggregate_result_audit({
        **envelope,
        "schema_version": schema_version,
        "next_action": next_action,
        **dict(extra or {}),
        "result_source": result_source(GOVERNED_PRODUCT),
    }, results)


def annotate_result(
    result: Mapping[str, Any],
    *,
    source: str,
    scope: str,
) -> dict[str, Any]:
    """Add stable composite metadata without rewriting the read envelope."""

    return {
        **dict(result),
        "source": source,
        "scope": scope,
        "continuation": _continuation(result.get("data")),
    }


def missing_result(
    operation_id: str,
    request_id: str,
    *,
    component: str,
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        "BATCH_RESULT_MISSING",
        f"The batch client omitted an expected {component} result.",
        operation_id=operation_id,
        category=ErrorCategory.LOCAL,
        next_action=f"Retry the {component}; inspect the local client if it repeats.",
    )
    return {
        "operation_id": operation_id,
        "request_id": request_id,
        "ok": False,
        "status": "error",
        "data": None,
        "error": detail.to_dict(),
    }


def parent_required_result(
    operation_id: str,
    request_id: str,
    *,
    parent: str,
    component: str,
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.PARENT_REQUIRED,
        f"{component} could not resolve its required parent.",
        operation_id=operation_id,
        field=parent,
        next_action=f"Inspect the selected app and retry after `{parent}` is available.",
    )
    return {
        "operation_id": operation_id,
        "request_id": request_id,
        "ok": False,
        "status": "parent_required",
        "data": None,
        "error": detail.to_dict(),
    }


def _continuation(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    direct = value.get("continuation")
    if direct not in (None, "", {}):
        return direct
    page = value.get("page")
    if isinstance(page, Mapping):
        for key in ("continuation", "next", "next_input"):
            candidate = page.get(key)
            if candidate not in (None, "", {}):
                return candidate
    return None


def _batch_result_item_count(result: Mapping[str, Any]) -> int:
    envelope = result.get("data")
    if not isinstance(envelope, Mapping):
        return 0
    page = envelope.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    data = envelope.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return len(rows)
    return 0


def _identifier_error(field: str, *, next_action: str) -> InputValidationError:
    return InputValidationError(
        f"{field} must be a non-empty Gravity identifier",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "annotate_result",
    "composite_envelope",
    "enforce_composite_item_budget",
    "normalize_identifier",
    "ordered_results",
    "parent_required_result",
    "validate_composite_bounds",
]
