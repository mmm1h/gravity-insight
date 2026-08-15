"""Actionable scalar and container validation for compact Analysis specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value, allowed_values
from .errors import InputValidationError


def reject_keys(
    value: Mapping[str, Any], allowed: set[str] | frozenset[str], field: str
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise InputValidationError(
            f"actual value: {actual_value(unknown)}; allowed fields: "
            f"{allowed_values(allowed)}",
            field=field,
        )


def mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: object", field=field
        )
    return value


def list_items(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed type: array", field=field
        )
    items = list(value)
    if len(items) > maximum:
        raise InputValidationError(
            f"actual value: {len(items)} items; allowed maximum: {maximum} items",
            field=field,
        )
    return items


def bounded_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a non-empty string "
            "of at most 256 characters",
            field=field,
        )
    return value.strip()


def optional_string(value: Any, field: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or len(value) > 256:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a string of at most "
            "256 characters",
            field=field,
        )
    return value


def boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: true, false", field=field
        )
    return value


def logic(value: Any, field: str) -> str:
    return choice(value, {"AND", "OR"}, field)


def choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed values: "
            f"{allowed_values(allowed)}",
            field=field,
        )
    return value


def integer_range(value: Any, minimum: int, maximum: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: integer from "
            f"{minimum} through {maximum}",
            field=field,
        )
    return value
