"""Fail-closed nested validation for exact Kanban mutation wires."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .kanban_mutation_contracts import (
    DASHBOARD_COPY,
    DASHBOARD_CREATE,
    DASHBOARD_MOVE,
    DASHBOARD_ORDER,
    DASHBOARD_UPDATE,
    KANBAN_MUTATION_OPERATIONS,
    NOTE_DELETE,
    SPACE_CREATE,
)
from .segment_mutation_support import MARKER_PREFIX


def validate_kanban_wire(operation_id: str, values: Mapping[str, Any]) -> None:
    if operation_id not in KANBAN_MUTATION_OPERATIONS:
        return
    for field, value in values.items():
        if field in {
            "app_id", "space_id", "id", "dashboard_id", "folder_id", "uid",
            "form_space_id", "form_folder_id", "to_space_id", "to_folder_id",
        }:
            minimum = 0 if field in {"folder_id", "to_folder_id"} else 1
            _integer(value, field, minimum)
    _identity_arrays(operation_id, values)
    if operation_id in {SPACE_CREATE, DASHBOARD_CREATE, DASHBOARD_COPY}:
        _owned_name(values.get("name"))
    if operation_id == DASHBOARD_MOVE:
        _dashboard_moves(values.get("dashboards"))
    if operation_id == DASHBOARD_UPDATE:
        _dashboard_content(values)
    if operation_id == DASHBOARD_ORDER:
        _bounded_objects(values.get("order_detail"), "order_detail", maximum=1_000)
    if operation_id == NOTE_DELETE:
        note_id = values.get("i")
        if not isinstance(note_id, str) or not note_id.startswith("notes_") or len(note_id) > 64:
            raise InputValidationError(
                f"actual value: {actual_value(note_id)}; allowed value: a notes_ identifier of at most 64 characters",
                field="i",
                next_action="Use the exact SDK note `i` returned by dashboard detail and run dry-run again.",
            )


def _integer(value: Any, field: str, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: an integer at least {minimum}",
            field=field,
            next_action="Use exact integer coordinates from the latest Kanban tree/detail and run dry-run again.",
        )


def _identity_arrays(operation_id: str, values: Mapping[str, Any]) -> None:
    if "dashboard_ids" in values:
        _integer_array(values["dashboard_ids"], "dashboard_ids")
    if "ids" not in values:
        return
    _integer_array(values["ids"], "ids")


def _integer_array(value: Any, field: str) -> None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not 1 <= len(value) <= 100
        or any(type(item) is not int or item < 1 for item in value)
        or len(set(value)) != len(value)
    ):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: 1 through 100 unique positive integer IDs",
            field=field,
            next_action="Use unique IDs from the latest Kanban readback and run dry-run again.",
        )


def _owned_name(value: Any) -> None:
    if not isinstance(value, str) or MARKER_PREFIX not in value or len(value) > 128:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'contains_marker': isinstance(value, str) and MARKER_PREFIX in value, 'length': len(value) if isinstance(value, str) else None})}; allowed value: a visible name containing GSDK-<12 hex>, at most 128 characters",
            field="name",
            next_action="Generate the create/copy wire through the Kanban product so the SDK marker is added automatically.",
        )


def _dashboard_moves(value: Any) -> None:
    rows = _bounded_objects(value, "dashboards", maximum=100)
    for index, row in enumerate(rows):
        if set(row) != {"dashboard_id", "form_space_id"}:
            raise InputValidationError(
                f"actual value: {actual_value(sorted(row))}; allowed fields: dashboard_id, form_space_id",
                field=f"dashboards[{index}]",
                next_action="Use the Kanban move product to derive the exact batch entry from tree coordinates.",
            )
        _integer(row.get("dashboard_id"), f"dashboards[{index}].dashboard_id", 1)
        _integer(row.get("form_space_id"), f"dashboards[{index}].form_space_id", 1)


def _dashboard_content(values: Mapping[str, Any]) -> None:
    _bounded_objects(values.get("report_list"), "report_list", maximum=20, allow_empty=True)
    raw = values.get("ui_config")
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(raw).__name__, 'length': len(raw) if isinstance(raw, str) else None})}; allowed value: a JSON layout string of at most 100000 characters",
            field="ui_config",
            next_action="Use the Kanban note product to compile a bounded layout, then run dry-run again.",
        )
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            "actual value: invalid ui_config JSON; allowed value: a JSON array",
            field="ui_config",
            next_action="Correct the JSON layout and run dry-run again.",
        ) from exc
    _bounded_objects(decoded, "ui_config", maximum=20, allow_empty=True)


def _bounded_objects(
    value: Any, field: str, *, maximum: int, allow_empty: bool = False
) -> list[Mapping[str, Any]]:
    minimum = 0 if allow_empty else 1
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not minimum <= len(value) <= maximum
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, Sequence) else None})}; allowed value: {minimum} through {maximum} JSON objects",
            field=field,
            next_action=f"Provide a bounded {field} object array from the governed Kanban product and run dry-run again.",
        )
    return list(value)


__all__ = ["validate_kanban_wire"]
