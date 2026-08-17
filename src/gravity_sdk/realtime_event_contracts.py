"""Exact operation identities for the realtime-event warehousing family."""

from __future__ import annotations

from .composite_catalog import stable_operation


def _operation(resource: str, action: str) -> str:
    return stable_operation("app", resource, action=action).operation_id


REALTIME_EVENT_LIST = _operation("realtime_event", "list")
REALTIME_EVENT_UPDATE = _operation("user_realtime_event", "update")
REALTIME_EVENT_MUTATIONS = frozenset({REALTIME_EVENT_UPDATE})


__all__ = [
    "REALTIME_EVENT_LIST",
    "REALTIME_EVENT_MUTATIONS",
    "REALTIME_EVENT_UPDATE",
]
