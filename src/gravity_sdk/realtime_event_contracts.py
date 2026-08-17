"""Exact operation identities for the realtime-event warehousing family."""

from __future__ import annotations


REALTIME_EVENT_LIST = "app.realtime_event.list"
REALTIME_EVENT_UPDATE = "app.user.realtime.event.update"
REALTIME_EVENT_MUTATIONS = frozenset({REALTIME_EVENT_UPDATE})


__all__ = [
    "REALTIME_EVENT_LIST",
    "REALTIME_EVENT_MUTATIONS",
    "REALTIME_EVENT_UPDATE",
]
