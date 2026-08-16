"""Immutable contracts used by the Gravity Insight SDK."""

from __future__ import annotations

import json
import math
import re
import string
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .errors import (
    ErrorDetail,
    InputValidationError,
    ManifestError,
    ParentRequiredError,
    is_success_status,
)
from .operation_effect_policy import validate_operation_effect
from .projection_validation import numeric_suffix_schema, validate_projection_bindings
from .result_audit import add_result_audit, result_receipt_references
from .result_source import RAW_OPERATION, result_source


_OPERATION_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
_RESPONSE_FIELD_NAME_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.$-]*$")
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_{}./-]+/$")
_READ_METHODS = frozenset({"GET", "POST"})
_STABILITY_VALUES = frozenset({
    "stable", "experimental", "permission_unavailable", "blocked_privacy",
    "blocked_write", "deprecated",
})
_NON_EXECUTABLE_STABILITIES = frozenset(
    {"permission_unavailable", "blocked_privacy", "blocked_write", "deprecated"}
)
_MISSING = object()

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


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ManifestError(f"{label} must be a list of strings")
    result = tuple(_string(item, label) for item in value)
    if len(result) != len(set(result)):
        raise ManifestError(f"{label} contains duplicate fields")
    return result


def _numeric_path_tuple(value: Any) -> tuple[str, ...]:
    paths = _string_tuple(value, "response_projection.numeric_paths")
    for path in paths:
        segments = path.split(".")
        if any(
            not segment
            or (
                segment not in {"[]", "*"}
                and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", segment)
            )
            for segment in segments
        ):
            raise ManifestError(
                "response_projection.numeric_paths contains an invalid JSON path"
            )
    return paths


def _input_field_names(fields: Sequence["InputField"]) -> list[str]:
    names = [item.name for item in fields]
    if len(names) != len(set(names)):
        raise ManifestError("input_fields contains duplicate names")
    return names


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    frozen = _freeze_json(dict(value or {}))
    if not isinstance(frozen, Mapping):  # pragma: no cover - construction invariant
        raise ManifestError("manifest mapping could not be frozen")
    return frozen


def _freeze_json(value: Any) -> Any:
    """Create a recursively immutable, reference-isolated JSON value."""

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ManifestError("manifest JSON objects must use string keys")
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ManifestError("manifest contract values must be finite JSON values")


def _thaw_json(value: Any) -> Any:
    """Return a fresh mutable JSON tree without exposing internal contract state."""

    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _matches_input_type(value: Any, expected: str) -> bool:
    return {
        "any": _is_bounded_json_value(value),
        "string": isinstance(value, str) and len(value) <= 4_096,
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value)),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, Mapping) and _is_bounded_json_value(value),
    }[expected]


def _is_bounded_json_value(
    value: Any, *, depth: int = 0, max_depth: int = 5
) -> bool:
    if depth > max_depth:
        return False
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= 4_096
    if isinstance(value, Mapping):
        return len(value) <= 100 and all(
            isinstance(key, str)
            and len(key) <= 128
            and _is_bounded_json_value(
                item, depth=depth + 1, max_depth=max_depth
            )
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return len(value) <= 1_000 and all(
            _is_bounded_json_value(
                item, depth=depth + 1, max_depth=max_depth
            )
            for item in value
        )
    return False


def _validate_date_range(values: Sequence[Any]) -> None:
    try:
        start, end = (date.fromisoformat(str(item)) for item in values)
    except (TypeError, ValueError) as exc:
        raise InputValidationError("date_list must contain valid ISO calendar dates") from exc
    if start > end:
        raise InputValidationError("date_list start must not be after end")


def _validate_filters(values: Sequence[Any]) -> None:
    allowed_keys = {"field", "operator", "values", "value"}
    for item in values:
        if not isinstance(item, Mapping):
            raise InputValidationError("filters must contain only objects")
        if set(item) - allowed_keys or "field" not in item or "operator" not in item:
            raise InputValidationError("filter objects do not match the controlled field contract")
        field_name = item.get("field")
        if not isinstance(field_name, str) or not _FIELD_NAME_RE.fullmatch(field_name):
            raise InputValidationError("filter field must be a declared-style field name")
        operator = item.get("operator")
        if isinstance(operator, bool) or not isinstance(operator, (str, int)):
            raise InputValidationError("filter operator must be a string or integer enum")
        raw_values = item.get("values", item.get("value", []))
        if not isinstance(raw_values, (list, tuple)) or len(raw_values) > 100:
            raise InputValidationError("filter values must be a bounded array")
        if any(
            isinstance(value, (Mapping, list, tuple))
            or not _is_bounded_json_value(value)
            for value in raw_values
        ):
            raise InputValidationError("filter values must contain only scalar JSON values")


def _nested_key_mapping(value: Any, label: str) -> Mapping[str, tuple[str, ...]]:
    if value is None:
        return MappingProxyType({})
    config = _mapping(value, label)
    result: dict[str, tuple[str, ...]] = {}
    for name, fields in config.items():
        field_name = _string(name, f"{label} key")
        if not _FIELD_NAME_RE.fullmatch(field_name):
            raise ManifestError(f"invalid nested projection field: {field_name!r}")
        result[field_name] = _string_tuple(fields, f"{label}.{field_name}")
    return MappingProxyType(result)


def _scalar_list_type_mapping(value: Any, label: str) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    config = _mapping(value, label)
    allowed_types = {"string", "integer", "number", "boolean"}
    result: dict[str, str] = {}
    for name, item_type in config.items():
        field_name = _string(name, f"{label} key")
        normalized_type = _string(item_type, f"{label}.{field_name}").lower()
        if (
            not _RESPONSE_FIELD_NAME_RE.fullmatch(field_name)
            or normalized_type not in allowed_types
        ):
            raise ManifestError("invalid scalar-list response projection")
        result[field_name] = normalized_type
    return MappingProxyType(result)


@dataclass(frozen=True)
class InputField:
    name: str
    type: str = "any"
    required: bool = False
    nullable: bool = False
    enum: tuple[Any, ...] = ()
    default: Any = field(default=_MISSING, repr=False)
    description: str = ""
    sensitive: bool = False
    item_type: str | None = None
    item_enum: tuple[Any, ...] = ()
    min_items: int | None = None
    max_items: int | None = None
    max_length: int | None = None
    max_depth: int = 5

    @classmethod
    def from_value(cls, name: str, value: Any) -> "InputField":
        if not _FIELD_NAME_RE.fullmatch(name):
            raise ManifestError(f"invalid input field name: {name!r}")
        if isinstance(value, str):
            value = {"type": value}
        elif value is None:
            value = {}
        config = _mapping(value, f"input_fields.{name}")
        enum_value = config.get("enum", ())
        if enum_value is None:
            enum_value = ()
        if not isinstance(enum_value, Sequence) or isinstance(enum_value, (str, bytes)):
            raise ManifestError(f"input_fields.{name}.enum must be a list")
        item_enum_value = config.get("item_enum", ())
        if item_enum_value is None:
            item_enum_value = ()
        if not isinstance(item_enum_value, Sequence) or isinstance(
            item_enum_value, (str, bytes)
        ):
            raise ManifestError(f"input_fields.{name}.item_enum must be a list")
        normalized_type = str(config.get("type", "any")).strip().lower() or "any"
        default_array = _DEFAULT_ARRAY_CONSTRAINTS.get(name) if normalized_type == "array" else None
        item_type = config.get("item_type", default_array[0] if default_array else None)
        min_items = config.get("min_items", default_array[1] if default_array else None)
        max_items = config.get("max_items", default_array[2] if default_array else None)
        max_length = config.get("max_length", 4_096 if normalized_type == "string" else None)
        max_depth = config.get("max_depth", 5)
        if item_type is not None:
            item_type = str(item_type).strip().lower()
            if item_type not in {"any", "string", "integer", "number", "boolean", "object"}:
                raise ManifestError(f"input_fields.{name}.item_type is unsupported")
        if item_enum_value and normalized_type != "array":
            raise ManifestError(
                f"input_fields.{name}.item_enum is only supported for arrays"
            )
        for bound_name, bound in (("min_items", min_items), ("max_items", max_items)):
            if bound is not None and (
                not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
            ):
                raise ManifestError(f"input_fields.{name}.{bound_name} must be a non-negative integer")
        if min_items is not None and max_items is not None and min_items > max_items:
            raise ManifestError(f"input_fields.{name} has invalid array bounds")
        if max_length is not None and (
            not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1
        ):
            raise ManifestError(f"input_fields.{name}.max_length must be a positive integer")
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
        return cls(
            name=name,
            type=normalized_type,
            required=bool(config.get("required", False)),
            nullable=bool(config.get("nullable", False)),
            enum=tuple(_freeze_json(item) for item in enum_value),
            default=(
                _MISSING
                if config.get("default", _MISSING) is _MISSING
                else _freeze_json(config["default"])
            ),
            description=str(config.get("description", "")),
            sensitive=bool(config.get("sensitive", False)),
            item_type=item_type,
            item_enum=tuple(_freeze_json(item) for item in item_enum_value),
            min_items=min_items,
            max_items=max_items,
            max_length=max_length,
            max_depth=max_depth,
        )

    def validate(self, value: Any) -> Any:
        if value is None:
            if self.nullable:
                return None
            raise InputValidationError(f"input {self.name!r} must not be null")
        expected = self.type
        valid = {
            "any": _is_bounded_json_value(value),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value)),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, (list, tuple)),
            "object": isinstance(value, Mapping),
            "date": isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)),
            "datetime": isinstance(value, str),
        }.get(expected)
        if valid is None:
            raise InputValidationError(f"input {self.name!r} declares unsupported type {expected!r}")
        if not valid:
            raise InputValidationError(f"input {self.name!r} must be {expected}")
        if expected == "object" and not _is_bounded_json_value(
            value, max_depth=self.max_depth
        ):
            raise InputValidationError(f"input {self.name!r} exceeds the nested object limits")
        if self.enum and value not in self.enum:
            raise InputValidationError(f"input {self.name!r} is not an allowed value")
        if expected == "string" and self.max_length is not None and len(value) > self.max_length:
            raise InputValidationError(f"input {self.name!r} exceeds its length limit")
        if expected == "array":
            normalized = list(value)
            if self.min_items is not None and len(normalized) < self.min_items:
                raise InputValidationError(f"input {self.name!r} has too few items")
            if self.max_items is not None and len(normalized) > self.max_items:
                raise InputValidationError(f"input {self.name!r} has too many items")
            if self.item_type and any(
                not _matches_input_type(item, self.item_type) for item in normalized
            ):
                raise InputValidationError(
                    f"input {self.name!r} must contain only {self.item_type} items"
                )
            if self.item_enum and any(item not in self.item_enum for item in normalized):
                raise InputValidationError(
                    f"input {self.name!r} contains an item outside its allowlist"
                )
            if self.name == "date_list" and self.item_type == "string":
                _validate_date_range(normalized)
            if self.name == "filters":
                _validate_filters(normalized)
            return normalized
        return value

    def schema(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.type,
            "required": self.required,
            "nullable": self.nullable,
            "sensitive": self.sensitive,
        }
        if self.enum:
            result["enum"] = _thaw_json(self.enum)
        if self.default is not _MISSING and not self.sensitive:
            result["default"] = _thaw_json(self.default)
        if self.description:
            result["description"] = self.description
        if self.item_type is not None:
            result["item_type"] = self.item_type
        if self.item_enum:
            result["item_enum"] = _thaw_json(self.item_enum)
        if self.min_items is not None:
            result["min_items"] = self.min_items
        if self.max_items is not None:
            result["max_items"] = self.max_items
        if self.max_length is not None:
            result["max_length"] = self.max_length
        if self.max_depth != 5:
            result["max_depth"] = self.max_depth
        return result

@dataclass(frozen=True)
class RequestSpec:
    location: str
    defaults: Mapping[str, Any] = field(default_factory=dict)
    path_fields: tuple[str, ...] = ()
    query_fields: tuple[str, ...] = ()
    body_fields: tuple[str, ...] = ()
    fixed_query: Mapping[str, Any] = field(default_factory=dict)
    fixed_body: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "RequestSpec":
        config = _mapping(value, "request")
        location = _string(config.get("location", "mixed"), "request.location").lower()
        if location not in {"query", "body", "mixed"}:
            raise ManifestError("request.location must be query, body, or mixed")
        defaults = _mapping(config.get("defaults", {}), "request.defaults")
        path_fields = _string_tuple(config.get("path_fields"), "request.path_fields")
        query_fields = _string_tuple(config.get("query_fields"), "request.query_fields")
        body_fields = _string_tuple(config.get("body_fields"), "request.body_fields")
        fixed_query = _mapping(config.get("fixed_query", {}), "request.fixed_query")
        fixed_body = _mapping(config.get("fixed_body", {}), "request.fixed_body")
        if set(query_fields) & set(body_fields):
            raise ManifestError("request fields cannot be both query and body fields")
        if set(fixed_query) & set(query_fields):
            raise ManifestError("fixed_query keys must not be caller-controlled query fields")
        if set(fixed_body) & set(body_fields):
            raise ManifestError("fixed_body keys must not be caller-controlled body fields")
        return cls(
            location,
            _frozen_mapping(defaults),
            path_fields,
            query_fields,
            body_fields,
            _frozen_mapping(fixed_query),
            _frozen_mapping(fixed_body),
        )


@dataclass(frozen=True)
class ResponseProjection:
    data_shape: str = "object"
    data_keys: tuple[str, ...] = ()
    required_data_keys: tuple[str, ...] = ()
    item_keys: tuple[str, ...] = ()
    dynamic_item_fields: tuple[str, ...] = ()
    numeric_suffix_item_fields: tuple[str, ...] = ()
    nested_item_keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    known_omitted_nested_item_keys: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    data_item_keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    scalar_list_item_types: Mapping[str, str] = field(default_factory=dict)
    data_scalar_list_types: Mapping[str, str] = field(default_factory=dict)
    data_path_item_keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    data_dynamic_item_fields: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    data_numeric_suffix_item_fields: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    known_omitted_item_keys: tuple[str, ...] = ()
    recursive_data_item_keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    known_omitted_data_keys: tuple[str, ...] = ()
    known_omitted_data_item_keys: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    numeric_paths: tuple[str, ...] = ()
    empty_object_as_empty_page: bool = False
    empty_object_as_empty_result: bool = False
    opaque_json_item_keys: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "ResponseProjection":
        config = _mapping(value or {}, "response_projection")
        data_shape = str(config.get("data_shape", "object")).strip().lower()
        if data_shape not in {"object", "list"}:
            raise ManifestError("response_projection.data_shape must be object or list")
        return cls(
            data_shape,
            _string_tuple(config.get("data_keys"), "response_projection.data_keys"),
            _string_tuple(
                config.get("required_data_keys"), "response_projection.required_data_keys"
            ),
            _string_tuple(config.get("item_keys"), "response_projection.item_keys"),
            _string_tuple(
                config.get("dynamic_item_fields"),
                "response_projection.dynamic_item_fields",
            ),
            _string_tuple(
                config.get("numeric_suffix_item_fields"),
                "response_projection.numeric_suffix_item_fields",
            ),
            _nested_key_mapping(
                config.get("nested_item_keys"),
                "response_projection.nested_item_keys",
            ),
            _nested_key_mapping(
                config.get("known_omitted_nested_item_keys"),
                "response_projection.known_omitted_nested_item_keys",
            ),
            _nested_key_mapping(
                config.get("data_item_keys"),
                "response_projection.data_item_keys",
            ),
            _scalar_list_type_mapping(
                config.get("scalar_list_item_types"),
                "response_projection.scalar_list_item_types",
            ),
            _scalar_list_type_mapping(
                config.get("data_scalar_list_types"),
                "response_projection.data_scalar_list_types",
            ),
            _nested_key_mapping(
                config.get("data_path_item_keys"),
                "response_projection.data_path_item_keys",
            ),
            _nested_key_mapping(
                config.get("data_dynamic_item_fields"),
                "response_projection.data_dynamic_item_fields",
            ),
            _nested_key_mapping(
                config.get("data_numeric_suffix_item_fields"),
                "response_projection.data_numeric_suffix_item_fields",
            ),
            _string_tuple(
                config.get("known_omitted_item_keys"),
                "response_projection.known_omitted_item_keys",
            ),
            _nested_key_mapping(
                config.get("recursive_data_item_keys"),
                "response_projection.recursive_data_item_keys",
            ),
            _string_tuple(
                config.get("known_omitted_data_keys"),
                "response_projection.known_omitted_data_keys",
            ),
            _nested_key_mapping(
                config.get("known_omitted_data_item_keys"),
                "response_projection.known_omitted_data_item_keys",
            ),
            _numeric_path_tuple(config.get("numeric_paths")),
            bool(config.get("empty_object_as_empty_page", False)),
            bool(config.get("empty_object_as_empty_result", False)),
            _string_tuple(
                config.get("opaque_json_item_keys"),
                "response_projection.opaque_json_item_keys",
            ),
        )


@dataclass(frozen=True)
class PaginationSpec:
    kind: str = "none"
    page_field: str = "page"
    page_size_field: str = "page_size"
    items_field: str = "list"
    page_info_field: str = "page_info"
    total_page_field: str = "total_page"
    list_path: str = "data.list"
    page_info_path: str = "data.page_info"
    default_page_size: int | None = None
    max_page_size: int | None = None

    @classmethod
    def from_dict(cls, value: Any) -> "PaginationSpec":
        if value in (None, False):
            return cls()
        config = _mapping(value, "pagination")
        kind = str(config.get("kind", "none")).strip().lower()
        if kind not in {"none", "page_info"}:
            raise ManifestError("pagination.kind must be none or page_info")
        default_size = config.get("default_page_size")
        max_size = config.get("max_page_size")
        for label, item in (("default_page_size", default_size), ("max_page_size", max_size)):
            if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item <= 0):
                raise ManifestError(f"pagination.{label} must be a positive integer")
        if default_size and max_size and default_size > max_size:
            raise ManifestError("pagination.default_page_size exceeds max_page_size")
        return cls(
            kind=kind,
            page_field=str(config.get("page_field", "page")),
            page_size_field=str(config.get("page_size_field", "page_size")),
            items_field=str(config.get("items_field", "list")),
            page_info_field=str(config.get("page_info_field", "page_info")),
            total_page_field=str(config.get("total_page_field", "total_page")),
            list_path=str(config.get("list_path", "data.list")),
            page_info_path=str(config.get("page_info_path", "data.page_info")),
            default_page_size=default_size,
            max_page_size=max_size,
        )


@dataclass(frozen=True)
class SemanticErrorRule:
    path: str
    operator: str = "truthy"
    value: Any = None
    values: tuple[Any, ...] = ()
    message: str = "Gravity rejected the read operation"

    @classmethod
    def from_dict(cls, value: Any) -> "SemanticErrorRule":
        if isinstance(value, str):
            return cls(path=_string(value, "semantic_error_rules[]"))
        config = _mapping(value, "semantic_error_rules[]")
        path = _string(config.get("path", config.get("field")), "semantic error path")
        operator = str(config.get("operator", "truthy")).strip().lower()
        if operator not in {"equals", "not_equals", "exists", "truthy", "falsy", "in", "not_in"}:
            raise ManifestError(f"unsupported semantic error operator: {operator}")
        values = config.get("values", ())
        if values is None:
            values = ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ManifestError("semantic error values must be a list")
        message = str(config.get("message", "Gravity rejected the read operation"))
        # Messages are manifest-owned, but keep control characters out of error logs.
        message = " ".join(message.splitlines()).strip() or "Gravity rejected the read operation"
        return cls(
            path,
            operator,
            _freeze_json(config.get("value")),
            tuple(_freeze_json(item) for item in values),
            message[:240],
        )


@dataclass(frozen=True)
class PrivacyPolicy:
    classification: str = "internal"
    redact_fields: tuple[str, ...] = (
        "authorization",
        "password",
        "token",
        "gravity_email",
    )

    @classmethod
    def from_value(cls, value: Any) -> "PrivacyPolicy":
        if value is None:
            return cls()
        if isinstance(value, str):
            return cls(classification=value)
        config = _mapping(value, "privacy_policy")
        redact = config.get(
            "redact_fields", config.get("redact_keys", config.get("deny_fields"))
        )
        base = cls().redact_fields
        return cls(
            classification=str(config.get("classification", config.get("mode", "internal"))),
            redact_fields=tuple(dict.fromkeys((*base, *_string_tuple(redact, "privacy_policy.redact_fields")))),
        )


@dataclass(frozen=True)
class RequiredParent:
    operation_id: str | None = None
    input_field: str | None = None

    @classmethod
    def from_value(cls, value: Any) -> "tuple[RequiredParent, ...]":
        if value in (None, False) or value == []:
            return ()
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
            return tuple(
                cls(operation_id=_string(item, "required_parent[]"))
                if isinstance(item, str)
                else cls._from_mapping(_mapping(item, "required_parent[]"))
                for item in value
            )
        if isinstance(value, str):
            return (cls(operation_id=value),)
        if value is True:
            return (cls(),)
        config = _mapping(value, "required_parent")
        return (cls._from_mapping(config),)

    @classmethod
    def _from_mapping(cls, config: Mapping[str, Any]) -> "RequiredParent":
        return cls(
            operation_id=str(config["operation_id"]) if config.get("operation_id") else None,
            input_field=str(config.get("input_field", config.get("field")))
            if config.get("input_field", config.get("field"))
            else None,
        )


@dataclass(frozen=True)
class LiveProbe:
    enabled: bool = False
    inputs: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "LiveProbe":
        if value in (None, False):
            return cls()
        if value is True:
            return cls(enabled=True)
        config = _mapping(value, "live_probe")
        return cls(
            bool(config.get("enabled", True)),
            _frozen_mapping(config.get("inputs", config.get("input", {}))),
        )


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    domain: str
    resource: str
    action: str
    contract_version: str
    upstream_method: str
    path_template: str
    auth_profile: str
    stability: str
    input_fields: tuple[InputField, ...]
    request: RequestSpec
    response_projection: ResponseProjection
    pagination: PaginationSpec
    semantic_error_rules: tuple[SemanticErrorRule, ...]
    privacy_policy: PrivacyPolicy
    required_parent: tuple[RequiredParent, ...] = ()
    live_probe: LiveProbe = field(default_factory=LiveProbe)
    platform: str | None = None
    description: str = ""
    effect: str = "read"
    executable: bool = True
    block_reason: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationSpec":
        config = _mapping(value, "operation")
        operation_id = _string(config.get("operation_id"), "operation_id")
        if not _OPERATION_ID_RE.fullmatch(operation_id):
            raise ManifestError(f"invalid operation_id: {operation_id!r}")
        method = _string(config.get("upstream_method"), "upstream_method").upper()
        if method not in _READ_METHODS:
            raise ManifestError("upstream_method must be GET or read-semantic POST")
        path = _string(config.get("path_template"), "path_template")
        if not _SAFE_PATH_RE.fullmatch(path) or "//" in path or "/../" in path or "/./" in path:
            raise ManifestError("path_template must be a normalized absolute API path ending in /")

        raw_fields = config.get("input_fields", {})
        fields: list[InputField] = []
        if isinstance(raw_fields, Mapping):
            fields = [InputField.from_value(str(name), item) for name, item in raw_fields.items()]
        elif isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)):
            for item in raw_fields:
                if isinstance(item, str):
                    fields.append(InputField.from_value(item, {}))
                else:
                    item_config = _mapping(item, "input_fields[]")
                    name = _string(item_config.get("name"), "input_fields[].name")
                    fields.append(InputField.from_value(name, item_config))
        else:
            raise ManifestError("input_fields must be an object or list")
        names = _input_field_names(fields)

        request = RequestSpec.from_dict(config.get("request", {}))
        placeholders = tuple(field_name for _, field_name, _, _ in string.Formatter().parse(path) if field_name)
        undeclared_placeholders = set(placeholders) - set(names)
        if undeclared_placeholders:
            raise ManifestError("path_template placeholders must be declared input fields")
        if request.path_fields and tuple(request.path_fields) != placeholders:
            raise ManifestError("request.path_fields must exactly match path_template placeholders")
        request_names = (
            set(request.path_fields)
            | set(request.query_fields)
            | set(request.body_fields)
            | set(request.defaults)
        )
        undeclared_request = request_names - set(names)
        if undeclared_request:
            raise ManifestError("request references undeclared input fields")

        response_projection = ResponseProjection.from_dict(config.get("response_projection", {}))
        validate_projection_bindings(response_projection, names)

        raw_rules = config.get("semantic_error_rules", ())
        if raw_rules is None:
            raw_rules = ()
        if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, (str, bytes)):
            raise ManifestError("semantic_error_rules must be a list")
        stability = _string(config.get("stability"), "stability").lower()
        if stability not in _STABILITY_VALUES:
            raise ManifestError(f"unsupported operation stability: {stability}")
        executable = config.get("executable", True)
        if not isinstance(executable, bool):
            raise ManifestError("operation executable must be a boolean")
        block_reason = str(config.get("block_reason", "")).strip() or None
        if not executable and not block_reason:
            raise ManifestError("non-executable operations must declare block_reason")
        effect = str(config.get("effect", "read")).strip()
        pagination = PaginationSpec.from_dict(config.get("pagination"))
        if response_projection.empty_object_as_empty_page and (
            pagination.kind != "page_info"
            or not {"list", "page_info"}.issubset(response_projection.data_keys)
        ):
            raise ManifestError(
                "empty-object page normalization requires an explicit paginated list contract"
            )
        if response_projection.empty_object_as_empty_result and (
            response_projection.data_shape != "object"
            or response_projection.required_data_keys
        ):
            raise ManifestError(
                "empty-object result normalization requires an object response with no required keys"
            )
        if stability == "stable" and pagination.kind == "page_info":
            if pagination.default_page_size is None or pagination.max_page_size is None:
                raise ManifestError(
                    "stable paginated operations must declare default_page_size and max_page_size"
                )
        required_parent = RequiredParent.from_value(config.get("required_parent"))
        undeclared_parent_inputs = {
            parent.input_field
            for parent in required_parent
            if parent.input_field and parent.input_field not in names
        }
        if undeclared_parent_inputs:
            raise ManifestError("required_parent input fields must be declared operation inputs")
        live_probe = LiveProbe.from_value(config.get("live_probe"))
        validate_operation_effect(
            stability=stability, effect=effect, executable=executable,
            non_executable_stability=stability in _NON_EXECUTABLE_STABILITIES,
            response_projection=response_projection, live_probe=live_probe,
        )
        if set(live_probe.inputs) - set(names):
            raise ManifestError("live_probe inputs must reference declared operation inputs")
        required_probe_inputs = {field.name for field in fields if field.required}
        if live_probe.enabled and not required_probe_inputs <= (
            set(live_probe.inputs) | set(request.defaults)
        ):
            raise ManifestError("live_probe is missing required minimum inputs")
        return cls(
            operation_id=operation_id,
            domain=_string(config.get("domain"), "domain"),
            resource=_string(config.get("resource"), "resource"),
            action=_string(config.get("action"), "action"),
            contract_version=str(config.get("contract_version", "1")),
            upstream_method=method,
            path_template=path,
            auth_profile=_string(config.get("auth_profile"), "auth_profile"),
            stability=stability,
            input_fields=tuple(fields),
            request=request,
            response_projection=response_projection,
            pagination=pagination,
            semantic_error_rules=tuple(SemanticErrorRule.from_dict(item) for item in raw_rules),
            privacy_policy=PrivacyPolicy.from_value(config.get("privacy_policy")),
            required_parent=required_parent,
            live_probe=live_probe,
            platform=str(config["platform"]) if config.get("platform") else None,
            description=str(config.get("description", "")),
            effect=effect,
            executable=executable,
            block_reason=block_reason,
        )

    @property
    def fields(self) -> Mapping[str, InputField]:
        return MappingProxyType({item.name: item for item in self.input_fields})

    @property
    def path_fields(self) -> tuple[str, ...]:
        return tuple(name for _, name, _, _ in string.Formatter().parse(self.path_template) if name)

    def validate_inputs(self, supplied: Mapping[str, Any] | None) -> dict[str, Any]:
        if supplied is None:
            supplied = {}
        if not isinstance(supplied, Mapping):
            raise InputValidationError("operation inputs must be an object")
        unknown = set(supplied) - set(self.fields)
        if unknown:
            raise InputValidationError("unknown operation input fields: " + ", ".join(sorted(unknown)))
        values = dict(self.request.defaults)
        values.update(supplied)
        for spec in self.input_fields:
            if spec.name not in values and spec.default is not _MISSING:
                values[spec.name] = spec.default
            if spec.name not in values:
                if spec.required:
                    raise InputValidationError(f"missing required input: {spec.name}")
                continue
            values[spec.name] = spec.validate(values[spec.name])
        for required_parent in self.required_parent:
            if required_parent.input_field:
                parent = required_parent.input_field
                if parent not in values or values[parent] in (None, "", [], {}):
                    raise ParentRequiredError(f"operation requires parent input: {parent}")
        if self.pagination.kind == "page_info":
            page = values.get(self.pagination.page_field)
            size = values.get(self.pagination.page_size_field)
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                raise InputValidationError("page must be a positive integer")
            if not isinstance(size, int) or isinstance(size, bool) or size < 1:
                raise InputValidationError("page_size must be a positive integer")
            if self.pagination.max_page_size and size > self.pagination.max_page_size:
                raise InputValidationError("requested page size exceeds the operation limit")
        thawed = _thaw_json(values)
        if not isinstance(thawed, dict):  # pragma: no cover - construction invariant
            raise InputValidationError("operation inputs could not be isolated")
        return thawed

    def render_path(self, values: Mapping[str, Any]) -> str:
        replacements: dict[str, str] = {}
        for name in self.path_fields:
            if name not in values:
                raise InputValidationError(f"missing path input: {name}")
            replacements[name] = quote(str(values[name]), safe="")
        path = self.path_template.format(**replacements)
        if not _SAFE_PATH_RE.fullmatch(path) or "//" in path or "/../" in path or "/./" in path:
            raise InputValidationError("rendered operation path is unsafe")
        return path

    def matches_path(self, path: str) -> bool:
        pattern = re.escape(self.path_template)
        for name in self.path_fields:
            pattern = pattern.replace(re.escape("{" + name + "}"), r"[^/]+")
        return bool(re.fullmatch(pattern, path))

    def schema(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id, "domain": self.domain,
            "resource": self.resource, "action": self.action,
            "contract_version": self.contract_version,
            "stability": self.stability,
            "platform": self.platform,
            "description": self.description,
            "executable": self.executable,
            "block_reason": self.block_reason,
            "auth_profile": self.auth_profile,
            "input_fields": {item.name: item.schema() for item in self.input_fields},
            "request": {
                "location": self.request.location,
                "path_fields": list(self.request.path_fields),
                "query_fields": list(self.request.query_fields),
                "body_fields": list(self.request.body_fields),
            },
            "response_projection": {
                "leaf_contract": "json_scalar",
                "data_shape": self.response_projection.data_shape,
                "data_keys": list(self.response_projection.data_keys),
                "required_data_keys": list(self.response_projection.required_data_keys),
                "item_keys": list(self.response_projection.item_keys),
                "dynamic_item_fields": list(self.response_projection.dynamic_item_fields),
                **numeric_suffix_schema(self.response_projection),
                "nested_item_keys": {
                    name: list(fields)
                    for name, fields in self.response_projection.nested_item_keys.items()
                },
                "known_omitted_nested_item_keys": {
                    name: list(fields)
                    for name, fields in (
                        self.response_projection.known_omitted_nested_item_keys.items()
                    )
                },
                "data_item_keys": {
                    name: list(fields)
                    for name, fields in self.response_projection.data_item_keys.items()
                },
                "scalar_list_item_types": dict(self.response_projection.scalar_list_item_types),
                "data_scalar_list_types": dict(
                    self.response_projection.data_scalar_list_types
                ),
                "data_path_item_keys": {
                    name: list(fields)
                    for name, fields in self.response_projection.data_path_item_keys.items()
                },
                "data_dynamic_item_fields": {
                    name: list(fields)
                    for name, fields in self.response_projection.data_dynamic_item_fields.items()
                },
                "known_omitted_item_keys": list(
                    self.response_projection.known_omitted_item_keys
                ),
                "recursive_data_item_keys": {
                    name: list(fields)
                    for name, fields in self.response_projection.recursive_data_item_keys.items()
                },
                "known_omitted_data_keys": list(
                    self.response_projection.known_omitted_data_keys
                ),
                "known_omitted_data_item_keys": {
                    name: list(fields)
                    for name, fields in (
                        self.response_projection.known_omitted_data_item_keys.items()
                    )
                },
                "numeric_paths": list(self.response_projection.numeric_paths),
                "empty_object_as_empty_page": (
                    self.response_projection.empty_object_as_empty_page
                ),
                "empty_object_as_empty_result": (
                    self.response_projection.empty_object_as_empty_result
                ),
                "opaque_json_item_keys": list(
                    self.response_projection.opaque_json_item_keys
                ),
            },
            "pagination": {
                "kind": self.pagination.kind,
                "page_field": self.pagination.page_field,
                "page_size_field": self.pagination.page_size_field,
            },
            "privacy": {"classification": self.privacy_policy.classification},
            "required_parent": [
                {
                    "operation_id": parent.operation_id,
                    "input_field": parent.input_field,
                }
                for parent in self.required_parent
            ],
            "live_probe": {
                "enabled": self.live_probe.enabled,
                "inputs": {
                    key: "[REDACTED]"
                    if self.fields.get(key) is not None and self.fields[key].sensitive
                    else _thaw_json(value)
                    for key, value in self.live_probe.inputs.items()
                },
            },
        }

    def operation_summary(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "domain": self.domain,
            "resource": self.resource,
            "action": self.action,
            "contract_version": self.contract_version,
            "stability": self.stability,
            "platform": self.platform,
            "description": self.description,
            "executable": self.executable,
            "block_reason": self.block_reason,
            "required_parent": bool(self.required_parent),
            "paginated": self.pagination.kind != "none",
        }


@dataclass(frozen=True)
class ReadResult:
    schema_version: str
    status: str
    source: Mapping[str, Any]
    fetched_at: str
    schema_fingerprint: str
    contract_version: str
    request: Mapping[str, Any]
    page: Mapping[str, Any] | None
    data: Any
    operation_id: str
    warnings: tuple[str, ...] = ()
    error: Mapping[str, Any] | None = None
    items: tuple[Any, ...] = ()
    page_info: Mapping[str, Any] = field(default_factory=dict)
    http_receipts: tuple[Mapping[str, str], ...] = ()
    response_drift: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return add_result_audit({
            "schema_version": self.schema_version,
            "result_source": result_source(RAW_OPERATION),
            "ok": is_success_status(self.status),
            "status": self.status,
            "source": dict(self.source),
            "fetched_at": self.fetched_at,
            "schema_fingerprint": self.schema_fingerprint,
            "operation_id": self.operation_id,
            "contract_version": self.contract_version,
            "request": dict(self.request),
            "page": dict(self.page) if self.page is not None else None,
            "data": self.data,
            "warnings": list(self.warnings),
            "error": dict(self.error) if self.error is not None else None,
        }, self.http_receipts, response_drift=self.response_drift)


@dataclass(frozen=True)
class BatchRequest:
    operation_id: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    read_all: bool = False


@dataclass(frozen=True)
class BatchResult:
    operation_id: str
    ok: bool
    status: str
    data: Any = None
    request_id: str | None = None
    error: ErrorDetail | Mapping[str, Any] | None = None
    http_receipts: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = {
            "operation_id": self.operation_id,
            "result_source": result_source(RAW_OPERATION),
            "ok": self.ok,
            "status": self.status,
            "data": self.data,
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.error is not None:
            result["error"] = (
                self.error.to_dict() if isinstance(self.error, ErrorDetail) else dict(self.error)
            )
        return add_result_audit(result, [*self.http_receipts, *result_receipt_references(self.data)])


def load_operation_manifest(
    source: str | Path | Mapping[str, Any] | Sequence[Any],
) -> tuple[OperationSpec, ...]:
    """Load a JSON operation manifest without accepting executable formats."""

    raw: Any
    if isinstance(source, Path):
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError("could not load the operation manifest") from exc
    elif isinstance(source, str):
        candidate = Path(source)
        if candidate.is_file():
            return load_operation_manifest(candidate)
        try:
            raw = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ManifestError("manifest string must contain JSON or name an existing file") from exc
    else:
        raw = source

    if isinstance(raw, Mapping) and "operations" in raw:
        raw = raw["operations"]
    elif isinstance(raw, Mapping) and "operation_id" in raw:
        raw = [raw]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ManifestError("manifest must be an operation list or an object containing operations")
    operations = tuple(OperationSpec.from_dict(_mapping(item, "operations[]")) for item in raw)
    if not operations:
        raise ManifestError("manifest must contain at least one operation")
    ids = [item.operation_id for item in operations]
    if len(ids) != len(set(ids)):
        raise ManifestError("manifest contains duplicate operation_id values")
    return operations
