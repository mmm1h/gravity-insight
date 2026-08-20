"""Map observed upstream read rejections to reviewed, caller-safe remedies.

The caller surface never receives the raw ``extra.error`` sentence.  Only exact
strings that this repository has reproduced and reviewed become a classified
remedy.  Unknown Analysis query text stays fail-closed but is treated as
retryable upstream until evidence supports assigning it to the caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from .actionable_error_values import actual_value
from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import SemanticRejectedError, UpstreamContradictedRequestError


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
# Upstream sends the sentence above even when create_time/day IS present, once
# query_item_before_after carries a before_custom. Telling that caller to add the
# group loops them through work they already did, so the remedy has to split on
# what was actually sent. See issue #21; the correct wire shape for a custom
# before cohort is not established offline and needs one production request.
_CUSTOM_BEFORE_UNRESOLVED = (
    "actual value: group_by_list already contains create_time/day and the request "
    "still carries query_item_before_after.before_custom; allowed next action: do "
    "NOT re-add the group and do not retry the same request unchanged -- this "
    "combination is a known unresolved upstream contract gap (issue #21). Drop "
    "before_custom to confirm the plain retention path still succeeds, and report "
    "the pair to the SDK maintainer rather than guessing another group_by_list"
)
# Same contradiction without a custom before: the compiler generated the group,
# so the caller has nothing to correct.  Observed intermittently -- the identical
# request succeeded on other runs -- so the honest remedy is to retry unchanged.
# See issue #23.
_CONTRADICTED_GROUP_CLAIM = (
    "actual value: group_by_list already contains create_time/day, which the "
    "compiler generates; allowed next action: do NOT add another group -- upstream "
    "contradicted a grouping you sent correctly, and the identical request has "
    "succeeded on other runs (issue #23). Retry the unchanged request; if it keeps "
    "failing on one specific day, report that day to the SDK maintainer"
)

_FALLBACK_MESSAGE = "Gravity rejected the read operation"
_RETENTION_QUERY = ANALYSIS_QUERY_OPERATIONS["retention"]
_ANALYSIS_QUERIES = frozenset(ANALYSIS_QUERY_OPERATIONS.values())
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
        if field == "group_by_list" and _create_time_already_grouped(request_inputs):
            next_action = (
                _CUSTOM_BEFORE_UNRESOLVED
                if _carries_custom_before(request_inputs)
                else _CONTRADICTED_GROUP_CLAIM
            )
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
    if (
        operation_id in _ANALYSIS_QUERIES
        and _reviewed_remedy(_extra_error_text(payload)) is None
    ):
        raise _UnclassifiedReadRejectionError(
            f"actual value: {actual_value(field)}; {message}",
            field=field,
            next_action=next_action,
            http_receipts=http_receipts,
        )
    if next_action in {_CONTRADICTED_GROUP_CLAIM, _CUSTOM_BEFORE_UNRESOLVED}:
        raise UpstreamContradictedRequestError(
            f"actual value: {actual_value(field)}; {message}",
            field=field,
            next_action=next_action,
            http_receipts=http_receipts,
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


def _create_time_already_grouped(
    request_inputs: Mapping[str, Any] | None
) -> bool:
    """True when the caller already sent the group upstream claims is missing."""

    if not request_inputs:
        return False
    groups = request_inputs.get("group_by_list")
    if not isinstance(groups, (list, tuple)):
        return False
    return any(
        isinstance(item, Mapping) and item.get("field") == "create_time"
        for item in groups
    )


def _carries_custom_before(request_inputs: Mapping[str, Any] | None) -> bool:
    """True when the request also carries the issue #21 custom-before cohort."""

    if not request_inputs:
        return False
    before_after = request_inputs.get("query_item_before_after")
    if not isinstance(before_after, Mapping):
        return False
    custom = before_after.get("before_custom")
    return isinstance(custom, Mapping) and bool(custom)


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
    # Naming group_by_list for every unclassified analysis rejection sent callers
    # to inspect a grouping the compiler generated for them.  See issue #23.
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
    if operation_id in _ANALYSIS_QUERIES:
        return (
            f"actual value: operation={actual_value(operation)} field={actual_value(field)} "
            f"sent_keys={actual_value(sent)}; allowed next action: treat this "
            "unreviewed extra.error as upstream, not caller input. For Analysis "
            "batch issue #24, the same-shape scalar request succeeded; retry with "
            "--concurrency 1 or run the same components through the scalar entry "
            "without increasing request count. If it persists, report sanitized "
            "extra.error, HTTP status, and Retry-After or rate-limit headers."
            f"{hint}"
        )
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


class _UnclassifiedReadRejectionError(UpstreamContradictedRequestError):
    """An unreviewed upstream sentence cannot safely assign caller blame."""


__all__ = [
    "REVIEWED_READ_REJECTION_PREFIXES",
    "REVIEWED_READ_REJECTIONS",
    "classify_read_rejection",
    "raise_read_rejection",
]
