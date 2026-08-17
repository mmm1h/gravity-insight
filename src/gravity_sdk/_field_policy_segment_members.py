"""Field validation unique to complete Segment member rows."""

from __future__ import annotations

from typing import Any, Mapping

from ._field_policy_metadata import load_view, wire_property_names
from ._field_policy_operations import ANALYSIS_USER_PROPERTY
from ._field_policy_shared import MetadataLoader
from .errors import InputValidationError
from .models import OperationSpec


def validate_segment_member_fields(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    app_id: str,
    loader: MetadataLoader,
) -> None:
    """Accept the fixed response profile plus discoverable user properties."""

    fields = inputs.get("fields", ())
    static = set(operation.response_projection.item_keys)
    if fields in (None, (), []) or _all_registered(fields, static):
        _validate(fields, static)
        return
    properties = load_view(
        ANALYSIS_USER_PROPERTY,
        {"app_id": app_id, "page": 1, "page_size": 2_000},
        loader,
    )
    _validate(fields, static | wire_property_names(properties.rows, "user"))


def _all_registered(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, (list, tuple)) and all(
        isinstance(item, str) and item in allowed for item in value
    )


def _validate(value: Any, allowed: set[str]) -> None:
    if value in (None, (), []):
        return
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or item not in allowed for item in value
    ):
        raise InputValidationError(
            "segment member fields must exist in live user-property metadata; "
            "run `gravity metadata properties \"\"` and retry with a listed field; "
            "request was not sent",
            field="fields",
        )


__all__ = ["validate_segment_member_fields"]
