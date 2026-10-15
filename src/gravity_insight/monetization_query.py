"""Normalized query profile for governed Monetization Detail reads."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actionable_error_values import actual_value, live_metadata_miss
from ._field_policy_shared import parse_iso_calendar_date
from .errors import InputValidationError
from .models import OperationSpec
from .monetization_projection import SAFE_ROW_FIELDS


_LOGIC = frozenset({"AND", "OR"})


@dataclass(frozen=True)
class MonetizationQueryProfile:
    fields: tuple[str, ...]
    global_conditions: tuple[Mapping[str, Any], ...]
    cond_logic: str
    local_conditions: tuple[Mapping[str, Any], ...]
    local_cond_logic: str
    order_by: tuple[Mapping[str, Any], ...]
    segment_id: str | None
    tmp_segment_id: str | None

    def receipt(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "fields": list(self.fields),
            "global_conditions": copy.deepcopy(list(self.global_conditions)),
            "cond_logic": self.cond_logic,
            "local_conditions": copy.deepcopy(list(self.local_conditions)),
            "local_cond_logic": self.local_cond_logic,
            "order_by_list": copy.deepcopy(list(self.order_by)),
        }
        if self.segment_id is not None:
            result["segment_id"] = self.segment_id
            result["tmp_segment_id"] = self.tmp_segment_id
        return result


def normalize_monetization_query(
    *,
    fields: Sequence[str] = SAFE_ROW_FIELDS,
    global_conditions: Sequence[Mapping[str, Any]] = (),
    cond_logic: str = "AND",
    local_conditions: Sequence[Mapping[str, Any]] = (),
    local_cond_logic: str = "AND",
    order_by: Sequence[Mapping[str, Any]] = (),
    segment_id: str | int | None = None,
    tmp_segment_id: str | int | None = None,
) -> MonetizationQueryProfile:
    selected_fields = _fields(fields)
    global_items = _conditions(global_conditions, "global_conditions")
    if any(item.get("field") == "create_time" for item in global_items):
        raise InputValidationError(
            "global_conditions cannot replace the canonical monetization day boundary",
            field="global_conditions",
            next_action="Pass the day through date and remove the create_time condition.",
        )
    local_items = _conditions(local_conditions, "local_conditions")
    global_logic = _logic(cond_logic, "cond_logic")
    local_logic = _logic(local_cond_logic, "local_cond_logic")
    ordering = _order(order_by, selected_fields)
    persisted = _identifier(segment_id, "segment_id")
    temporary = _identifier(tmp_segment_id, "tmp_segment_id")
    if temporary is not None and persisted is None:
        raise InputValidationError(
            "tmp_segment_id requires a same-App persisted segment binding",
            field="tmp_segment_id",
            next_action="Select a persisted segment from the App catalog first.",
        )
    if persisted is not None:
        temporary = temporary or persisted
        if temporary != persisted:
            raise InputValidationError(
                "segment_id and tmp_segment_id must identify the same reviewed segment",
                field="tmp_segment_id",
            )
    return MonetizationQueryProfile(
        selected_fields,
        global_items,
        global_logic,
        local_items,
        local_logic,
        ordering,
        persisted,
        temporary,
    )


def validate_monetization_operation_request(
    _operation: OperationSpec, inputs: Mapping[str, Any]
) -> None:
    """Validate wire-level query bounds before live metadata validation."""

    _validate_operation_fields(inputs.get("fields"))
    parse_iso_calendar_date(inputs.get("date"), "date")
    _reject_time_override(inputs.get("global_conditions", ()))
    _validate_segment_pair(inputs)
    _validate_page(inputs)


def validate_monetization_segment_scope(
    inputs: Mapping[str, Any], segment_ids: set[str]
) -> None:
    segment = inputs.get("segment_id")
    temporary = inputs.get("tmp_segment_id")
    if segment in (None, "") and temporary in (None, ""):
        return
    if segment in (None, "") or temporary in (None, ""):
        raise InputValidationError(
            "monetization segment scope requires both reviewed segment fields",
            field="segment_id" if segment in (None, "") else "tmp_segment_id",
        )
    selected, selected_tmp = str(segment), str(temporary)
    if selected != selected_tmp:
        raise InputValidationError(
            "segment_id and tmp_segment_id must identify the same reviewed segment",
            field="tmp_segment_id",
        )
    if selected not in segment_ids:
        raise InputValidationError(
            live_metadata_miss(actual_value(selected), noun="segment ids"),
            field="segment_id",
            next_action=(
                "Run `gravity analysis metadata --app-id <app-id>` and retry with a "
                "listed segment id."
            ),
        )


def _validate_operation_fields(value: Any) -> None:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(field, str) or not field for field in value)
        or len(value) != len(set(value))
    ):
        observed = (
            actual_value(type(value).__name__)
            if not isinstance(value, (list, tuple))
            else value
        )
        raise InputValidationError(
            f"actual value: {observed}; monetization detail fields must be a "
            "non-empty unique string list; request was not sent",
            field="fields",
        )


def _reject_time_override(value: Any) -> None:
    if any(
        isinstance(item, Mapping) and item.get("field") == "create_time"
        for item in value
    ):
        raise InputValidationError(
            "actual value: create_time; global_conditions cannot contain create_time "
            "because date owns the day boundary",
            field="global_conditions",
            next_action="Remove create_time and pass the canonical day through date.",
        )


def _validate_segment_pair(inputs: Mapping[str, Any]) -> None:
    segment = inputs.get("segment_id")
    temporary = inputs.get("tmp_segment_id")
    if temporary not in (None, "") and segment in (None, ""):
        raise InputValidationError(
            "tmp_segment_id requires segment_id", field="tmp_segment_id"
        )
    if segment not in (None, "") and str(temporary or segment) != str(segment):
        raise InputValidationError(
            "segment_id and tmp_segment_id must match", field="tmp_segment_id"
        )


def _validate_page(inputs: Mapping[str, Any]) -> None:
    page, size = inputs.get("page", 1), inputs.get("page_size", 20)
    if type(page) is int and page >= 1 and type(size) is int and 1 <= size <= 1_000:
        return
    raise InputValidationError(
        f"actual value: {actual_value({'page': page, 'page_size': size})}; "
        "monetization detail page must be >= 1 and page_size must be 1 through "
        "1000; request was not sent",
        field="page_size",
    )


def _fields(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError("monetization fields must be an array", field="fields")
    selected = tuple(value)
    if (
        not 1 <= len(selected) <= 100
        or any(not isinstance(item, str) or item not in SAFE_ROW_FIELDS for item in selected)
        or len(set(selected)) != len(selected)
    ):
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; monetization fields must be unique reviewed fields",
            field="fields",
        )
    return selected


def _conditions(value: Any, field: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(f"{field} must be an array", field=field)
    if len(value) > 100 or any(not isinstance(item, Mapping) for item in value):
        raise InputValidationError(
            f"actual value: {actual_value(len(value))}; {field} must contain at most 100 objects",
            field=field,
        )
    return tuple(copy.deepcopy(dict(item)) for item in value)


def _logic(value: Any, field: str) -> str:
    if value not in _LOGIC:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be AND or OR",
            field=field,
        )
    return str(value)


def _order(
    value: Any, selected_fields: tuple[str, ...]
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError("order_by must be an array", field="order_by")
    if len(value) > 20:
        raise InputValidationError("order_by must contain at most 20 items", field="order_by")
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"field", "sort"}
            or item.get("field") not in selected_fields
            or type(item.get("sort")) is not int
            or item.get("sort") not in {0, 1}
            or item.get("field") in seen
        ):
            raise InputValidationError(
                f"actual value: {actual_value(item)}; order_by must use unique selected fields and sort 0 or 1",
                field="order_by",
            )
        field = str(item["field"])
        seen.add(field)
        result.append({"field": field, "sort": int(item["sort"])})
    return tuple(result)


def _identifier(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise InputValidationError(f"{field} must be a positive integer id", field=field)
    selected = str(value).strip()
    if not selected.isdecimal() or len(selected) > 64 or int(selected) <= 0:
        raise InputValidationError(f"{field} must be a positive integer id", field=field)
    return str(int(selected))


__all__ = [
    "MonetizationQueryProfile",
    "normalize_monetization_query",
    "validate_monetization_operation_request",
    "validate_monetization_segment_scope",
]
