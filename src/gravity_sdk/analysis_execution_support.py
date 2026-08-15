"""Evidence-backed execution support limits for Analysis query compilers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .errors import InputValidationError


_SEGMENT_EVENT_SUPPORT = {
    "$MPShow": {
        "status": "unsupported",
        "reason": "segment_endpoint_rejected",
        "alternative": "custom_event",
    },
    "$PayEvent": {
        "status": "unsupported",
        "reason": "segment_endpoint_rejected",
        "alternative": "custom_event",
    },
}


def segment_event_support_metadata() -> dict[str, Any]:
    """Return caller-safe, value-free Segment endpoint support evidence."""

    return {
        "default_status": "requires_live_metadata",
        "events": {
            name: dict(metadata)
            for name, metadata in sorted(_SEGMENT_EVENT_SUPPORT.items())
        },
    }


def reject_unsupported_segment_event(event: str, field: str) -> None:
    support = _SEGMENT_EVENT_SUPPORT.get(event)
    if support is None or support["status"] != "unsupported":
        return
    raise InputValidationError(
        f"{event} is registered metadata but is unsupported by Segment evaluation",
        field=field,
        next_action=(
            "Replace this preset with a metadata-registered custom event that is "
            "supported by Segment evaluation, or remove the event rule; do not "
            "retry the unchanged request."
        ),
    )


def validate_segment_event_support_inputs(inputs: Mapping[str, Any]) -> None:
    rules = inputs.get("user_event_rules")
    if not isinstance(rules, Mapping):
        return
    groups = rules.get("groups")
    if not _sequence(groups):
        return
    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            continue
        events = group.get("conditions")
        if not _sequence(events):
            continue
        for event_index, event in enumerate(events):
            if isinstance(event, Mapping) and isinstance(event.get("event_name"), str):
                reject_unsupported_segment_event(
                    str(event["event_name"]),
                    f"user_event_rules.groups[{group_index}].conditions[{event_index}].event_name",
                )


def reject_unsupported_property_groups(
    groups: Any, *, field_root: str = "group_by_list"
) -> None:
    if not _sequence(groups):
        return
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping) or group.get("field") != "$ea_gid":
            continue
        raise InputValidationError(
            "Property Analysis does not support grouping by acquisition ID $ea_gid",
            field=f"{field_root}[{index}].field",
            next_action=(
                "Remove this group or select a metadata-backed non-acquisition user "
                "property; changing the group type is not a supported workaround."
            ),
        )


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


__all__ = [
    "reject_unsupported_property_groups",
    "reject_unsupported_segment_event",
    "segment_event_support_metadata",
    "validate_segment_event_support_inputs",
]
