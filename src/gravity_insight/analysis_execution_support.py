"""Evidence-backed execution support limits for Analysis query compilers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError


SEGMENT_EVENT_RULE_GAP_CODE = "SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN"
SEGMENT_EVENT_RULE_GAP_MESSAGE = (
    "Gravity rejected a locally valid Segment static-count event rule; metadata "
    "validity does not establish event-specific Segment acceptance."
)
SEGMENT_EVENT_RULE_GAP_REASON = (
    "Event and ordinary Retention accepted the two consumer-observed, "
    "metadata-valid custom events, while Segment evaluation rejected their "
    "locally valid did=true, PresetAllCount/GTE 1, static-window rules. Issue "
    "#15 separately proves only $MPShow and $PayEvent unsupported and records "
    "one accepted metadata-backed custom control. The repository proves neither "
    "an all-custom-event exclusion nor a locally predictable accepted subset."
)
SEGMENT_EVENT_RULE_GAP_NEXT_ACTION = (
    "Do not retry unchanged or infer that all custom events fail. Close this gap "
    "with a sanitized current-main paired Segment receipt using identical "
    "did=true, PresetAllCount/GTE 1, and static windows: one metadata-valid "
    "custom event accepted and the target event rejected, plus metadata kind, "
    "HTTP status, and sanitized extra.error. Event or ordinary Retention success "
    "is a different product boundary, not an equivalent first-exposure result."
)
SEGMENT_FIRST_EXPOSURE_GAP_NEXT_ACTION = (
    "Do not substitute ordinary event-date Retention. Close this gap only with a "
    "sanitized current-main paired Segment receipt using the same positive and "
    "negative static-window shape: one metadata-valid custom event accepted and "
    "the target event rejected, plus metadata kind, HTTP status, and sanitized "
    "extra.error. Until then an aggregate-only first-exposure cohort requires an "
    "existing set-once first-occurrence property; without one the read-only "
    "surfaces cannot compute the required NOT-before intersection."
)


_SEGMENT_EVENT_SUPPORT = {
    "$MPShow": {
        "status": "unsupported",
        "reason": "segment_endpoint_rejected",
        "alternative": "event_with_segment_acceptance_evidence",
    },
    "$PayEvent": {
        "status": "unsupported",
        "reason": "segment_endpoint_rejected",
        "alternative": "event_with_segment_acceptance_evidence",
    },
}


def segment_event_support_metadata() -> dict[str, Any]:
    """Return caller-safe, value-free Segment endpoint support evidence."""

    return {
        "default_status": "requires_live_metadata_and_event_specific_acceptance",
        "metadata_validity_proves_endpoint_acceptance": False,
        "acceptance_gap": {
            "code": SEGMENT_EVENT_RULE_GAP_CODE,
            "reason": SEGMENT_EVENT_RULE_GAP_REASON,
            "next_action": SEGMENT_EVENT_RULE_GAP_NEXT_ACTION,
        },
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
        f"actual value: {actual_value(event)}; the registered event is unsupported "
        "by Segment evaluation",
        field=field,
        next_action=(
            "Remove the event rule or replace this preset only with an event that "
            "has a successful Segment-evaluation receipt; metadata listing alone "
            "does not prove endpoint acceptance; do not retry the unchanged request."
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
            f"actual value: {actual_value(group.get('field'))}; Property Analysis "
            "does not support grouping by an acquisition ID",
            field=f"{field_root}[{index}].field",
            next_action=(
                "Run `gravity metadata properties \"\"` and select "
                "a listed non-acquisition user property, or remove this group; changing "
                "the group type is not a supported workaround."
            ),
        )


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


__all__ = [
    "SEGMENT_EVENT_RULE_GAP_CODE",
    "SEGMENT_EVENT_RULE_GAP_MESSAGE",
    "SEGMENT_EVENT_RULE_GAP_NEXT_ACTION",
    "SEGMENT_EVENT_RULE_GAP_REASON",
    "SEGMENT_FIRST_EXPOSURE_GAP_NEXT_ACTION",
    "reject_unsupported_property_groups",
    "reject_unsupported_segment_event",
    "segment_event_support_metadata",
    "validate_segment_event_support_inputs",
]
