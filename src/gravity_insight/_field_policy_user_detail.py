"""Metadata-free validation for an existing static user-detail read shape."""

from collections.abc import Mapping
from typing import Any

from ._field_policy_operations import ANALYSIS_USER_DETAIL
from .models import OperationSpec


def static_user_detail_request(operation: OperationSpec, inputs: Mapping[str, Any]) -> bool:
    if operation.operation_id != ANALYSIS_USER_DETAIL:
        return False
    fields = inputs.get("fields")
    if not isinstance(fields, (list, tuple)) or not fields:
        return False
    if not all(isinstance(field, str) for field in fields):
        return False
    scalar = set(operation.response_projection.item_keys) - set(
        operation.response_projection.nested_item_keys
    )
    if len(fields) != len(set(fields)) or not set(fields) <= scalar:
        return False
    return _static_controls(inputs)


def _static_controls(inputs: Mapping[str, Any]) -> bool:
    empty_controls = (
        "global_conditions",
        "local_conditions",
        "order_conditions",
        "order_by_list",
        "postback_conditions",
        "user_conditions",
        "event_conditions",
    )
    if any(inputs.get(key) not in (None, (), []) for key in empty_controls):
        return False
    if any(
        inputs.get(key, "AND") != "AND"
        for key in ("user_cond_logic", "order_cond_logic", "postback_cond_logic")
    ):
        return False
    page, size = inputs.get("page", 1), inputs.get("page_size", 20)
    return (
        inputs.get("client_id") in (None, "")
        and inputs.get("date") not in (None, "")
        and type(page) is int
        and page >= 1
        and type(size) is int
        and 1 <= size <= 100
    )
