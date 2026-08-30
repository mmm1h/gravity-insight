"""Fail-closed validation for frontend-proven metadata-template wires."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .metadata_template_contracts import (
    TEMPLATE_APPEND,
    TEMPLATE_EVENT_REMOVE,
    TEMPLATE_MASTER,
    TEMPLATE_PROPERTY_REMOVE,
)


TEMPLATE_TYPES = frozenset({"meta_property", "event_property", "user_property"})


def validate_metadata_template_wire(
    operation_id: str, values: Mapping[str, Any]
) -> None:
    if operation_id == TEMPLATE_MASTER:
        _master(values)
    elif operation_id == TEMPLATE_APPEND:
        _append(values)
    elif operation_id == TEMPLATE_EVENT_REMOVE:
        _remove(values, "event_id_list")
    elif operation_id == TEMPLATE_PROPERTY_REMOVE:
        _remove(values, "property_id_list")


def _master(values: Mapping[str, Any]) -> None:
    if values.get("is_deleted") == 1:
        expected = {"id", "name", "template_type", "is_deleted"}
        _fields(values, expected, "template delete")
        _identifier(values.get("id"), "id")
    else:
        expected = {
            "name", "template_type", "target_id_list", "need_common", "remark"
        }
        if values.get("need_common") is True:
            expected.add("app_id")
        _fields(values, expected, "template create")
        _identifiers(values.get("target_id_list"), "target_id_list")
    _name(values.get("name"))
    _template_type(values.get("template_type"))


def _append(values: Mapping[str, Any]) -> None:
    expected = {
        "id", "name", "template_type", "target_id_list", "need_common", "remark"
    }
    if values.get("need_common") is True:
        expected.add("app_id")
    _fields(values, expected, "template append")
    _identifier(values.get("id"), "id")
    _identifiers(values.get("target_id_list"), "target_id_list")
    _template_type(values.get("template_type"))
    if values.get("name") != "" or values.get("remark") != "":
        raise metadata_template_wire_error(
            actual_value({"name": values.get("name"), "remark": values.get("remark")}),
            "empty name and remark for the frontend append branch",
            "name/remark",
            "Generate the append wire through the governed metadata-template product.",
        )


def _remove(values: Mapping[str, Any], member_field: str) -> None:
    _fields(values, {"template_id", member_field}, "template member remove")
    _identifier(values.get("template_id"), "template_id")
    _identifiers(values.get(member_field), member_field)


def _fields(values: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(values) != expected:
        raise metadata_template_wire_error(
            actual_value(sorted(values)),
            actual_value(sorted(expected)),
            "input",
            f"Regenerate the exact {label} wire through the governed product.",
        )


def _template_type(value: Any) -> str:
    if value not in TEMPLATE_TYPES:
        raise metadata_template_wire_error(
            actual_value(value),
            actual_value(sorted(TEMPLATE_TYPES)),
            "template_type",
            "Choose the template type returned by the current template catalog.",
        )
    return str(value)


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise metadata_template_wire_error(
            actual_value(value),
            "non-empty template text of at most 128 characters",
            "name",
            "Choose a shorter template name and rerun the dry-run.",
        )
    return value


def _identifier(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise metadata_template_wire_error(
            actual_value(value),
            "a positive integer returned by the current metadata catalog",
            field,
            f"Refresh the current catalog and choose one exact {field}.",
        )
    return value


def _identifiers(value: Any, field: str) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 100
        or any(type(item) is not int or item < 1 for item in value)
        or len(set(value)) != len(value)
    ):
        raise metadata_template_wire_error(
            actual_value(value),
            "1..100 unique positive integer IDs from the current metadata catalog",
            field,
            f"Refresh the current catalog, deduplicate {field}, and rerun the dry-run.",
        )
    return tuple(value)


def metadata_template_wire_error(
    actual: str, allowed: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual}; allowed value: {allowed}",
        field=field,
        next_action=next_action,
    )


__all__ = [
    "TEMPLATE_TYPES", "metadata_template_wire_error",
    "validate_metadata_template_wire",
]
