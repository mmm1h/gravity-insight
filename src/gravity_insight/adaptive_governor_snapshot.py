"""Bounded machine snapshot for the current private Governor scope."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from .adaptive_governor_contract import (
    MAX_SNAPSHOT_LANES,
    POLICY_REVISION,
    SCHEMA_VERSION,
    STATIC,
)
from .agent_runtime_contracts import AgentRuntimeContractError, validate_schema


_SNAPSHOT_SCHEMA = "adaptive-governor-snapshot-v1.schema.json"


class AdaptiveGovernorContractError(AgentRuntimeContractError):
    """An adaptive Governor snapshot is malformed or outside safe bounds."""


def render_adaptive_governor_snapshot(
    *,
    mode: str,
    capacity: Mapping[str, int],
    scope: Any,
    lanes: Iterable[tuple[tuple[str, str, str, str], Any]],
    now: float,
) -> dict[str, Any]:
    lane_values = [_lane_value(key, lane, mode, now) for key, lane in lanes]
    lane_values.sort(
        key=lambda item: (item["host_key"], item["operation_class"], item["profile"])
    )
    truncated = len(lane_values) > MAX_SNAPSHOT_LANES
    lane_values = lane_values[:MAX_SNAPSHOT_LANES]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "policy_revision": POLICY_REVISION,
        "capacity": dict(capacity),
        "scope": {
            "active": scope.active,
            "queued": scope.queued,
            "peak_active": scope.peak_active,
            "rejected": scope.rejected,
            "cancelled": scope.cancelled,
            "coalesced": scope.coalesced,
        },
        "lanes": lane_values,
        "lane_count": len(lane_values),
        "truncated": truncated,
        "network_called": False,
    }


def validate_adaptive_governor_snapshot(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptiveGovernorContractError(
            "Adaptive Governor snapshot must be an object"
        )
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SNAPSHOT_SCHEMA, "Adaptive Governor snapshot")
    except AgentRuntimeContractError as exc:
        raise AdaptiveGovernorContractError(str(exc)) from exc
    if selected["lane_count"] != len(selected["lanes"]):
        raise AdaptiveGovernorContractError(
            "Adaptive Governor snapshot lane count changed"
        )
    return selected


def _lane_value(
    key: tuple[str, str, str, str], lane: Any, mode: str, now: float
) -> dict[str, Any]:
    _scope, host, operation, profile = key
    return {
        "host_key": host,
        "operation_class": operation,
        "profile": profile,
        "concurrency_limit": lane.max_limit if mode == STATIC else lane.limit,
        "max_limit": lane.max_limit,
        "active": lane.active,
        "queued": lane.queued,
        "circuit_state": "closed" if mode == STATIC else lane.state,
        "cooldown_remaining_ms": _cooldown_ms(lane, mode, now),
        "consecutive_failures": (
            0 if mode == STATIC else lane.consecutive_failures
        ),
        "ewma_latency_ms": lane.ewma_latency_ms,
        "counters": copy.deepcopy(lane.counters),
    }


def _cooldown_ms(lane: Any, mode: str, now: float) -> int:
    if mode == STATIC:
        return 0
    return min(30_000, max(0, round((lane.opened_until - now) * 1_000)))


__all__ = [
    "AdaptiveGovernorContractError",
    "render_adaptive_governor_snapshot",
    "validate_adaptive_governor_snapshot",
]
