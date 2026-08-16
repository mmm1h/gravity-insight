"""Exact operation identities for governed event/property templates."""

from __future__ import annotations

from .composite_catalog import stable_operation


def _operation(resource: str, action: str) -> str:
    return stable_operation("metadata", resource, action=action).operation_id


TEMPLATE_MASTER = _operation("event_property_template_master", "update")
TEMPLATE_APPEND = _operation("event_property_template_membership", "update")
TEMPLATE_EVENT_REMOVE = _operation(
    "event_property_template_event_membership", "delete"
)
TEMPLATE_PROPERTY_REMOVE = _operation(
    "event_property_template_property_membership", "delete"
)
TEMPLATE_LIST = _operation("event_property_template_event", "list")
TEMPLATE_EVENT_MEMBERS = _operation("event_property_template_event_list", "list")
TEMPLATE_PROPERTY_MEMBERS = _operation("property", "list")
TEMPLATE_MUTATIONS = frozenset(
    {TEMPLATE_MASTER, TEMPLATE_APPEND, TEMPLATE_EVENT_REMOVE, TEMPLATE_PROPERTY_REMOVE}
)


__all__ = [
    "TEMPLATE_APPEND",
    "TEMPLATE_EVENT_MEMBERS",
    "TEMPLATE_EVENT_REMOVE",
    "TEMPLATE_LIST",
    "TEMPLATE_MASTER",
    "TEMPLATE_MUTATIONS",
    "TEMPLATE_PROPERTY_MEMBERS",
    "TEMPLATE_PROPERTY_REMOVE",
]
