"""Map observed upstream read rejections to reviewed, caller-safe remedies.

The caller surface never receives the raw ``extra.error`` sentence.  Only exact
strings that this repository has reproduced and reviewed become a classified
remedy.  Unknown text falls back to the fixed rejection sentence plus
SDK-owned request-shape context.
"""

from __future__ import annotations

from typing import Any, Mapping

from .actionable_error_values import actual_value
from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import SemanticRejectedError


# Exact extra.error strings reproduced on App 29034827 (2026-08-18).
# Do not add synonyms or guessed translations.
REVIEWED_READ_REJECTIONS: dict[str, tuple[str, str]] = {
    "入参错误：group_by_list为list且不能为空": (
        "group_by_list",
        "actual value: group_by_list=[]; allowed next action: send create_time/day "
        "(compact time_grain=day, or omit time_grain on retention so the compiler "
        "writes it); do not retry with an empty group_by_list",
    ),
    "groupBy类型(user_property)不合法": (
        "group_by_list[].type",
        "actual value: type=user_property; allowed next action: retry with wire "
        "type=user (compact group_by.source=user already compiles to type=user)",
    ),
}
# One observed sentence embeds the caller's group_by payload after this prefix.
REVIEWED_READ_REJECTION_PREFIXES: tuple[tuple[str, str, str], ...] = (
    (
        "入参错误：group_by_list缺失create_time",
        "group_by_list",
        "actual value: group_by_list lacks create_time; allowed next action: add "
        "create_time/day (compact time_grain=day) before other groups; do not retry "
        "the same group_by_list",
    ),
)

_FALLBACK_MESSAGE = "Gravity rejected the read operation"
_RETENTION_QUERY = ANALYSIS_QUERY_OPERATIONS["retention"]
_GROUP_TYPE_HINT = (
    "compact group_by.source=user compiles to wire type=user; "
    "type=user_property is rejected on event, funnel, and retention"
)
_TIME_GRAIN_HINT = (
    "retention requires a create_time/day group; omit time_grain and the "
    "compiler now writes that group automatically"
)


def classify_read_rejection(
    payload: Mapping[str, Any],
    *,
    operation_id: str | None,
    request_inputs: Mapping[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Return (field, message, next_action) that never echo upstream text."""

    extra_error = _extra_error_text(payload)
    reviewed = _reviewed_remedy(extra_error)
    if reviewed is not None:
        field, next_action = reviewed
        return (
            field,
            f"Gravity rejected the read operation; classified extra.error={field}",
            next_action,
        )
    field = _inferred_field(operation_id, request_inputs)
    return (
        field,
        _FALLBACK_MESSAGE,
        _unclassified_next_action(operation_id, request_inputs, field),
    )


def raise_read_rejection(
    payload: Mapping[str, Any],
    *,
    operation_id: str | None,
    request_inputs: Mapping[str, Any] | None = None,
    http_receipts: Any = (),
) -> None:
    field, message, next_action = classify_read_rejection(
        payload, operation_id=operation_id, request_inputs=request_inputs
    )
    raise SemanticRejectedError(
        f"actual value: {actual_value(field)}; {message}",
        field=field,
        next_action=next_action,
        http_receipts=http_receipts,
    )


def _reviewed_remedy(extra_error: str) -> tuple[str, str] | None:
    if not extra_error:
        return None
    exact = REVIEWED_READ_REJECTIONS.get(extra_error)
    if exact is not None:
        return exact
    for prefix, field, next_action in REVIEWED_READ_REJECTION_PREFIXES:
        if extra_error.startswith(prefix):
            return field, next_action
    return None


def _extra_error_text(payload: Mapping[str, Any]) -> str:
    extra = payload.get("extra")
    value = extra.get("error") if isinstance(extra, Mapping) else None
    if isinstance(value, str):
        return " ".join(value.splitlines()).strip()
    return ""


def _inferred_field(
    operation_id: str | None, request_inputs: Mapping[str, Any] | None
) -> str:
    if not request_inputs:
        return "input"
    groups = request_inputs.get("group_by_list")
    if isinstance(groups, (list, tuple)):
        for item in groups:
            if isinstance(item, Mapping) and item.get("type") == "user_property":
                return "group_by_list[].type"
        if operation_id == _RETENTION_QUERY and not any(
            isinstance(item, Mapping) and item.get("field") == "create_time"
            for item in groups
        ):
            return "group_by_list"
    if operation_id in ANALYSIS_QUERY_OPERATIONS.values():
        return "group_by_list"
    return "input"


def _unclassified_next_action(
    operation_id: str | None,
    request_inputs: Mapping[str, Any] | None,
    field: str,
) -> str:
    operation = operation_id or "<operation-id>"
    sent = _sent_shape(request_inputs)
    hints = []
    if field == "group_by_list[].type":
        hints.append(_GROUP_TYPE_HINT)
    if field == "group_by_list" and operation_id == _RETENTION_QUERY:
        hints.append(_TIME_GRAIN_HINT)
    hint = f" known analysis shape: {'; '.join(hints)}." if hints else ""
    return (
        f"actual value: operation={actual_value(operation)} field={actual_value(field)} "
        f"sent_keys={actual_value(sent)}; allowed next action: run "
        f"`gravity insight operations describe {operation}` and retry with the "
        f"documented input; the SDK does not echo unreviewed upstream extra.error."
        f"{hint}"
    )


def _sent_shape(request_inputs: Mapping[str, Any] | None) -> list[str]:
    if not request_inputs:
        return []
    keys: list[str] = []
    for key, value in request_inputs.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, (list, tuple)):
            keys.append(f"{key}[{len(value)}]")
        elif isinstance(value, Mapping):
            keys.append(f"{key}{{{len(value)}}}")
        else:
            keys.append(key)
    return keys[:20]


__all__ = [
    "REVIEWED_READ_REJECTION_PREFIXES",
    "REVIEWED_READ_REJECTIONS",
    "classify_read_rejection",
    "raise_read_rejection",
]
