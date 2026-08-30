"""Offline input contract for Promotion Performance v1."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import re
from typing import Any

from ._field_policy_shared import (
    is_direct_personal_response_field,
    is_sensitive_analysis_field,
    is_sensitive_control_key,
)
from .composite_batch import validate_composite_bounds
from .errors import InputValidationError
from .promotion_performance_result import (
    PROMOTION_NON_METRIC_FIELDS,
    SUPPORTED_PLATFORMS,
)
from .actionable_error_values import actual_value
from .process_limits import MAX_CONCURRENCY


INPUT_SCHEMA_VERSION = "gravity-insight.promotion-performance-input.v1"
DEFAULT_CONCURRENCY = 6
MAX_METRICS = 500
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_METRIC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")


def validate_promotion_performance_request(
    app_id: str | int,
    start: str,
    end: str,
    *,
    platforms: Sequence[str],
    metrics: Sequence[str],
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> tuple[
    str,
    tuple[str, str],
    tuple[str, ...],
    tuple[str, ...],
    int,
    int,
    int,
]:
    """Validate all request shape and budget rules without constructing a client."""

    app = normalize_promotion_app(app_id)
    window = normalize_promotion_window(start, end)
    selected_platforms = normalize_promotion_platforms(platforms)
    selected_metrics = normalize_promotion_metrics(metrics)
    workers = normalize_promotion_workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages,
        max_items,
        minimum_items=len(selected_platforms),
    )
    return (
        app,
        window,
        selected_platforms,
        selected_metrics,
        workers,
        pages,
        items,
    )


def promotion_performance_input_schema() -> dict[str, Any]:
    """Return a fresh machine schema for the closed core request."""

    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": ["app_id", "start", "end", "platforms", "metrics"],
        "properties": {
            "app_id": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": "^[0-9]+$", "maxLength": 128},
                ]
            },
            "start": {"type": "string", "format": "date"},
            "end": {"type": "string", "format": "date"},
            "platforms": {
                "type": "array",
                "minItems": 1,
                "maxItems": len(SUPPORTED_PLATFORMS),
                "uniqueItems": True,
                "items": {"type": "string", "enum": list(SUPPORTED_PLATFORMS)},
            },
            "metrics": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_METRICS,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "pattern": _METRIC_NAME.pattern,
                },
            },
            "max_workers": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_CONCURRENCY,
                "default": DEFAULT_CONCURRENCY,
            },
            "max_pages": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1_000,
                "default": 1_000,
            },
            "max_items": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100_000,
                "default": 100_000,
            },
        },
    }


def normalize_promotion_app(value: str | int) -> str:
    """Normalize a resolved positive App id to its canonical decimal string."""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _input_error(
            f"actual value: {actual_value(value)}; " + ("promotion performance app_id must be a positive App id"), "app_id"
        )
    if isinstance(value, int) and (value <= 0 or value.bit_length() > 426):
        raise _input_error(
            f"actual value: {actual_value(value)}; " + ("promotion performance app_id must be a positive App id"), "app_id"
        )
    rendered = str(value)
    if (
        not rendered
        or len(rendered) > 128
        or rendered != rendered.strip()
        or not rendered.isascii()
        or not rendered.isdecimal()
        or int(rendered) <= 0
    ):
        raise _input_error(
            f"actual value: {actual_value(rendered)}; " + ("promotion performance app_id must be a positive App id"), "app_id"
        )
    return str(int(rendered))


def normalize_promotion_window(start: Any, end: Any) -> tuple[str, str]:
    """Return an inclusive canonical ISO date pair."""

    if not all(
        isinstance(value, str) and _ISO_DATE.fullmatch(value)
        for value in (start, end)
    ):
        raise _input_error(
            f"actual value: {actual_value((start, end))}; " + ("promotion performance dates must use YYYY-MM-DD"), "start/end"
        )
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise _input_error(
            f"actual value: {actual_value((start, end))}; " + ("promotion performance dates must use YYYY-MM-DD"), "start/end"
        ) from None
    if first > last:
        raise _input_error(
            f"actual value: {actual_value((start, end))}; " + ("promotion performance start must not follow end"), "start/end"
        )
    normalized = first.isoformat(), last.isoformat()
    if normalized != (start, end):
        raise _input_error(
            f"actual value: {actual_value(normalized)}; " + ("promotion performance dates must use YYYY-MM-DD"), "start/end"
        )
    return normalized


def normalize_promotion_platforms(values: Sequence[str]) -> tuple[str, ...]:
    """Validate the closed 21-platform set while preserving declaration order."""

    if isinstance(values, (str, bytes, bytearray, memoryview)) or not isinstance(
        values, Sequence
    ):
        raise _input_error(
            f"actual value: {actual_value(values)}; " + ("promotion performance platforms must be an array"), "platforms"
        )
    selected: list[str] = []
    for value in values:
        if not isinstance(value, str) or value not in SUPPORTED_PLATFORMS:
            raise _input_error(
                f"actual value: {actual_value(value)}; promotion performance platform "
                "is outside the supported set; must be one of the supported platforms",
                "platforms",
            )
        if value in selected:
            raise _input_error(
                f"actual value: {actual_value(value)}; " + ("promotion performance platforms must be unique"), "platforms"
            )
        selected.append(value)
    if not selected:
        raise _input_error(
            f"actual value: {actual_value(selected)}; " + ("promotion performance requires at least one platform"), "platforms"
        )
    return tuple(selected)


def normalize_promotion_metrics(values: Sequence[str]) -> tuple[str, ...]:
    """Validate physical metric names without accepting static row dimensions."""

    if isinstance(values, (str, bytes, bytearray, memoryview)) or not isinstance(
        values, Sequence
    ):
        raise _input_error(
            f"actual value: {actual_value(values)}; " + ("promotion performance metrics must be an array"), "metrics"
        )
    selected: list[str] = []
    for value in values:
        if (
            not isinstance(value, str)
            or not _METRIC_NAME.fullmatch(value)
            or is_direct_personal_response_field(value)
            or is_sensitive_analysis_field(value)
            or is_sensitive_control_key(value)
            or _credential_field(value)
            or value in PROMOTION_NON_METRIC_FIELDS
        ):
            raise _input_error(
                f"actual value: {actual_value(value)}; " + ("promotion performance metrics must be safe physical metric names"),
                "metrics",
            )
        if value in selected:
            raise _input_error(
                f"actual value: {actual_value(value)}; " + ("promotion performance metrics must be unique"), "metrics"
            )
        selected.append(value)
    if not 1 <= len(selected) <= MAX_METRICS:
        raise _input_error(
            f"actual value: {actual_value(selected)}; " + (f"promotion performance metrics must contain 1 through {MAX_METRICS} values"),
            "metrics",
        )
    return tuple(selected)


def _credential_field(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    if any(
        marker in compact
        for marker in (
            "authorization", "credential", "password", "secret", "token",
            "cookie", "callbackurl", "clickurl", "postbackurl",
        )
    ) or compact.startswith("auth") or compact in {
        "session", "sessionid", "sessionkey",
    }:
        return True
    return any(
        compact == f"{prefix}{suffix}"
        for prefix in ("api", "access", "private", "signing", "client")
        for suffix in ("key", "header", "secret", "id")
    )


def normalize_promotion_workers(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_CONCURRENCY:
        raise _input_error(
            f"actual value: {actual_value(value)}; " + (f"promotion performance max_workers must be between 1 and {MAX_CONCURRENCY}"),
            "max_workers",
        )
    return value


def _input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action=(
            "Use the Promotion Performance input schema and retry with explicit values."
        ),
    )


__all__ = [
    "DEFAULT_CONCURRENCY",
    "INPUT_SCHEMA_VERSION",
    "MAX_CONCURRENCY",
    "MAX_METRICS",
    "normalize_promotion_app",
    "normalize_promotion_metrics",
    "normalize_promotion_platforms",
    "normalize_promotion_window",
    "normalize_promotion_workers",
    "promotion_performance_input_schema",
    "validate_promotion_performance_request",
]
