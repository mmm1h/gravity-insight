"""Input-field parsing and validation for operation manifests.

Split out of operation_manifest_parse.py: that module crossed the 500 SLOC
ratchet once the group/identity invariant and the actual-value error work
landed together. Input fields are a self-contained unit -- they only need
the manifest coercion helpers, never the operation-level parsers -- so the
dependency runs one way and there is no import cycle.

Error types and message text are unchanged by the move.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from .actionable_error_values import actual_value
from .errors import InputValidationError, ManifestError


_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_DATE_VALUE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_DEFAULT_ARRAY_CONSTRAINTS: Mapping[str, tuple[str, int, int]] = {
    "date_list": ("string", 2, 2),
    "app_list": ("string", 1, 1_000),
    "query_fields": ("string", 0, 500),
    "metrics_list": ("string", 0, 500),
    "custom_metrics_list": ("string", 0, 500),
    "data_dims": ("string", 0, 100),
    "relate_dims": ("string", 0, 100),
    "exclusion_dims": ("string", 0, 500),
    "filters": ("object", 0, 100),
    "order_by": ("any", 0, 100),
    "data_list": ("object", 0, 100_000),
}


def mapping_or_error(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{label} must be an object")
    return value


def sequence_or_empty(value: Any, label: str) -> Sequence[Any]:
    if value is None:
        value = ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ManifestError(f"{label} must be a list")
    return value


def parse_input_field(
    cls: Any, name: str, value: Any, *, freeze_json: Any, missing: Any
) -> Any:
    if not _FIELD_NAME_RE.fullmatch(name):
        raise ManifestError(f"invalid input field name: {name!r}")
    if isinstance(value, str):
        value = {"type": value}
    elif value is None:
        value = {}
    config = mapping_or_error(value, f"input_fields.{name}")
    enum_value = sequence_or_empty(config.get("enum"), f"input_fields.{name}.enum")
    item_enum_value = sequence_or_empty(
        config.get("item_enum"), f"input_fields.{name}.item_enum"
    )
    normalized_type = str(config.get("type", "any")).strip().lower() or "any"
    default_array = _DEFAULT_ARRAY_CONSTRAINTS.get(name) if normalized_type == "array" else None
    item_type = config.get("item_type", default_array[0] if default_array else None)
    min_items = config.get("min_items", default_array[1] if default_array else None)
    max_items = config.get("max_items", default_array[2] if default_array else None)
    max_length = config.get("max_length", 4_096 if normalized_type == "string" else None)
    max_depth = config.get("max_depth", 5)
    item_type = _normalized_item_type(name, item_type)
    _validate_item_enum_type(name, normalized_type, item_enum_value)
    _validate_array_bounds(name, min_items, max_items)
    _validate_max_length(name, max_length)
    _validate_max_depth(name, normalized_type, max_depth)
    return cls(
        name=name,
        type=normalized_type,
        required=bool(config.get("required", False)),
        nullable=bool(config.get("nullable", False)),
        enum=tuple(freeze_json(item) for item in enum_value),
        default=(
            missing
            if config.get("default", missing) is missing
            else freeze_json(config["default"])
        ),
        description=str(config.get("description", "")),
        sensitive=bool(config.get("sensitive", False)),
        item_type=item_type,
        item_enum=tuple(freeze_json(item) for item in item_enum_value),
        min_items=min_items,
        max_items=max_items,
        max_length=max_length,
        max_depth=max_depth,
    )


def validate_input_field(
    field: Any,
    value: Any,
    *,
    is_bounded_json_value: Any,
    matches_input_type: Any,
    validate_date_range: Any,
    validate_filters: Any,
) -> Any:
    if value is None:
        if field.nullable:
            return None
        raise InputValidationError(
            f"actual value: {actual_value(value)}; input {field.name!r} must not be null",
            field=field.name,
        )
    expected = field.type
    value = _coerce_declared_identifier(field, value)
    valid = _input_type_valid(expected, value, is_bounded_json_value)
    if valid is None:
        raise InputValidationError(
            f"actual value: {actual_value(expected)}; input {field.name!r} must use a "
            f"supported type, not {expected!r}",
            field=field.name,
        )
    if not valid:
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__)}; input {field.name!r} "
            f"must be {expected}",
            field=field.name,
        )
    _validate_object_and_enum(field, value, expected, is_bounded_json_value)
    if expected == "string" and field.max_length is not None and len(value) > field.max_length:
        raise InputValidationError(
            f"actual value: {actual_value(len(value))}; input {field.name!r} must stay "
            f"at or below its length limit of {field.max_length}",
            field=field.name,
        )
    if expected == "array":
        return _validate_array_value(
            field,
            value,
            matches_input_type=matches_input_type,
            validate_date_range=validate_date_range,
            validate_filters=validate_filters,
        )
    return value


def _normalized_item_type(name: str, item_type: Any) -> Any:
    if item_type is None:
        return None
    item_type = str(item_type).strip().lower()
    if item_type not in {"any", "string", "integer", "number", "boolean", "object"}:
        raise ManifestError(f"input_fields.{name}.item_type is unsupported")
    return item_type


def _validate_item_enum_type(
    name: str, normalized_type: str, item_enum_value: Sequence[Any]
) -> None:
    if item_enum_value and normalized_type != "array":
        raise ManifestError(
            f"input_fields.{name}.item_enum is only supported for arrays"
        )


def _validate_array_bounds(name: str, min_items: Any, max_items: Any) -> None:
    for bound_name, bound in (("min_items", min_items), ("max_items", max_items)):
        if bound is not None and (
            not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
        ):
            raise ManifestError(
                f"input_fields.{name}.{bound_name} must be a non-negative integer"
            )
    if min_items is not None and max_items is not None and min_items > max_items:
        raise ManifestError(f"input_fields.{name} has invalid array bounds")


def _validate_max_length(name: str, max_length: Any) -> None:
    if max_length is not None and (
        not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1
    ):
        raise ManifestError(f"input_fields.{name}.max_length must be a positive integer")


def _validate_max_depth(name: str, normalized_type: str, max_depth: Any) -> None:
    if (
        not isinstance(max_depth, int)
        or isinstance(max_depth, bool)
        or not 1 <= max_depth <= 16
    ):
        raise ManifestError(
            f"input_fields.{name}.max_depth must be an integer between 1 and 16"
        )
    if max_depth != 5 and normalized_type != "object":
        raise ManifestError(
            f"input_fields.{name}.max_depth is only supported for object inputs"
        )


def _coerce_declared_identifier(field: Any, value: Any) -> Any:
    """Normalize identifier wire forms only when the contract already declared a type."""

    if field.name != "app_id":
        return value
    if field.type == "string":
        if isinstance(value, bool) or not isinstance(value, int):
            return value
        if value <= 0:
            raise InputValidationError(
                f"actual value: {actual_value(value)}; "
                f"input {field.name!r} must be a positive integer identifier",
                field=field.name,
            )
        return str(value)
    if field.type != "integer":
        return value
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    rendered = value.strip()
    if not rendered.isascii() or not rendered.isdigit():
        return value
    coerced = int(rendered)
    if coerced <= 0:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; "
            f"input {field.name!r} must be a positive integer identifier",
            field=field.name,
        )
    return coerced


def _input_type_valid(expected: str, value: Any, is_bounded_json_value: Any) -> bool | None:
    return {
        "any": is_bounded_json_value(value),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value)),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, (list, tuple)),
        "object": isinstance(value, Mapping),
        "date": isinstance(value, str) and bool(_DATE_VALUE_RE.fullmatch(value)),
        "datetime": isinstance(value, str),
    }.get(expected)


def _validate_object_and_enum(
    field: Any, value: Any, expected: str, is_bounded_json_value: Any
) -> None:
    if expected == "object" and not is_bounded_json_value(
        value, max_depth=field.max_depth
    ):
        raise InputValidationError(
            f"actual value: {actual_value(type(value).__name__)}; input {field.name!r} "
            "must stay inside the nested object limits",
            field=field.name,
        )
    if field.enum and value not in field.enum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; input {field.name!r} is not an "
            "allowed value",
            field=field.name,
        )


def _validate_array_value(
    field: Any,
    value: Any,
    *,
    matches_input_type: Any,
    validate_date_range: Any,
    validate_filters: Any,
) -> list[Any]:
    normalized = list(value)
    if field.min_items is not None and len(normalized) < field.min_items:
        raise InputValidationError(
            f"actual value: {actual_value(len(normalized))}; input {field.name!r} must "
            f"contain at least {field.min_items} items",
            field=field.name,
        )
    if field.max_items is not None and len(normalized) > field.max_items:
        raise InputValidationError(
            f"actual value: {actual_value(len(normalized))}; input {field.name!r} must "
            f"contain at most {field.max_items} items",
            field=field.name,
        )
    if field.item_type and any(
        not matches_input_type(item, field.item_type) for item in normalized
    ):
        raise InputValidationError(
            f"actual value: {actual_value([type(item).__name__ for item in normalized])}; "
            f"input {field.name!r} must contain only {field.item_type} items",
            field=field.name,
        )
    if field.item_enum and any(item not in field.item_enum for item in normalized):
        raise InputValidationError(
            f"actual value: {actual_value(normalized)}; input {field.name!r} contains "
            "an item outside its allowlist; must use an allowlisted value",
            field=field.name,
        )
    if field.name == "date_list" and field.item_type == "string":
        validate_date_range(normalized)
    if field.name == "filters":
        validate_filters(normalized)
    return normalized


__all__ = [
    "mapping_or_error",
    "parse_input_field",
    "sequence_or_empty",
    "validate_input_field",
]
