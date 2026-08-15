"""Plan adapter for local, side-effect-free HTTP receipt diagnostics."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .errors import InputValidationError
from .plan import AdapterContext
from .plan_binding import set_pointer
from .receipt_query import get_http_receipt, list_http_receipts
from .result_audit import receipt_reference


_FIELDS = frozenset({"action", "limit", "cursor", "operation_id", "reference"})
_LIST_FIELDS = frozenset({"action", "limit", "cursor", "operation_id"})
_GET_FIELDS = frozenset({"action", "reference"})
_REFERENCE_FIELDS = frozenset({"receipt_id", "storage_status"})
_TARGETS = frozenset(
    {"/cursor", "/operation_id", "/reference/receipt_id", "/reference/storage_status"}
)


def validate_receipt_query(
    request: Mapping[str, Any], context: AdapterContext
) -> None:
    selected = _dynamic_request(request, context)
    if context.output_fields:
        raise _input("receipt_query does not support output_fields", "output_fields")
    if not isinstance(selected, Mapping):
        raise _input("receipt_query request must be an object", None)
    unknown = set(selected) - _FIELDS
    if unknown:
        raise _input("receipt_query request contains unsupported fields", sorted(unknown)[0])
    action = selected.get("action")
    allowed = _LIST_FIELDS if action == "list" else _GET_FIELDS if action == "get" else None
    if allowed is None:
        raise _input("receipt_query action must be list or get", "action")
    extra = set(selected) - allowed
    if extra:
        raise _input("receipt_query action contains unsupported fields", sorted(extra)[0])
    if action == "list":
        _validate_list(selected, context)
        return
    _validate_get(selected)


def _validate_list(selected: Mapping[str, Any], context: AdapterContext) -> None:
    limit = selected.get("limit", min(100, context.max_items))
    if type(limit) is not int or not 1 <= limit <= min(1_000, context.max_items):
        raise _input("receipt_query limit exceeds the node item budget", "limit")
    for field in ("cursor", "operation_id"):
        if selected.get(field) is not None and not isinstance(selected[field], str):
            raise _input(f"receipt_query {field} must be a string", field)


def _validate_get(selected: Mapping[str, Any]) -> None:
    reference = selected.get("reference")
    if not isinstance(reference, Mapping) or set(reference) != _REFERENCE_FIELDS:
        raise _input("receipt_query get requires an exact reference", "reference")
    if not all(isinstance(reference[field], str) for field in _REFERENCE_FIELDS):
        raise _input("receipt_query reference fields must be strings", "reference")
    try:
        receipt_reference(reference["receipt_id"], reference["storage_status"])
    except ValueError as error:
        raise _input(str(error), "reference") from None


def execute_receipt_query(
    request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    validate_receipt_query(
        request,
        replace(context, dynamic_targets=()),
    )
    state_root = context.workspace.state_root
    if request["action"] == "get":
        return get_http_receipt(state_root, request["reference"])
    return list_http_receipts(
        state_root,
        limit=int(request.get("limit", min(100, context.max_items))),
        cursor=request.get("cursor"),
        operation_id=request.get("operation_id"),
    )


def _dynamic_request(
    request: Mapping[str, Any], context: AdapterContext
) -> Mapping[str, Any]:
    selected = copy.deepcopy(dict(request))
    for target in context.dynamic_targets:
        if target not in _TARGETS:
            raise _input("receipt_query binding target is unsupported", "bindings")
        sentinel = (
            "0" * 32
            if target.endswith("receipt_id")
            else "stored"
            if target.endswith("storage_status")
            else "bound"
        )
        set_pointer(selected, target, sentinel)
    return selected


def _input(message: str, field: str | None) -> InputValidationError:
    return InputValidationError(message, field=field)


__all__ = ["execute_receipt_query", "validate_receipt_query"]
