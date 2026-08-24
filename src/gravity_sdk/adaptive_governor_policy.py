"""Deterministic AIMD and circuit transitions for one Governor lane."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .adaptive_governor_contract import (
    ADAPTIVE,
    CIRCUIT_COOLDOWN_SECONDS,
    CIRCUIT_FAILURE_THRESHOLD,
    SLOW_RESPONSE_SECONDS,
)


CAPACITY_FAILURES = frozenset({"rate_limited", "server_error", "transport_error"})


def record_lane_outcome(
    mode: str,
    lane: Any,
    status_class: str,
    latency: float,
    clock: Callable[[], float],
) -> None:
    _record_latency(lane, latency)
    _record_status_counter(lane, status_class)
    if mode != ADAPTIVE:
        return
    if status_class in CAPACITY_FAILURES:
        lane.consecutive_failures += 1
        _decrease(lane, halve=True)
        if lane.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            _open_circuit(lane, clock)
        return
    if status_class in {"success", "client_error", "redirect"}:
        lane.consecutive_failures = 0
        if lane.state == "half_open":
            lane.state = "closed"
            lane.opened_until = 0.0
    if status_class != "success":
        return
    if latency >= SLOW_RESPONSE_SECONDS:
        _decrease(lane, halve=False)
        return
    lane.success_window += 1
    if lane.success_window >= lane.limit and lane.limit < lane.max_limit:
        lane.limit += 1
        lane.success_window = 0
        lane.counters["aimd_increase"] += 1


def reset_lane_circuits(lanes: Iterable[Any]) -> None:
    for lane in lanes:
        lane.state = "closed"
        lane.opened_until = 0.0
        lane.consecutive_failures = 0
        lane.success_window = 0


def _record_latency(lane: Any, latency: float) -> None:
    latency_ms = min(600_000, max(0, round(latency * 1_000)))
    lane.ewma_latency_ms = (
        latency_ms
        if lane.ewma_latency_ms == 0
        else round(lane.ewma_latency_ms * 0.8 + latency_ms * 0.2)
    )


def _record_status_counter(lane: Any, status_class: str) -> None:
    if status_class == "success":
        lane.counters["success"] += 1
    elif status_class == "client_error":
        lane.counters["client_error"] += 1
    elif status_class in CAPACITY_FAILURES:
        lane.counters["capacity_failure"] += 1


def _decrease(lane: Any, *, halve: bool) -> None:
    selected = max(1, lane.limit // 2) if halve else max(1, lane.limit - 1)
    if selected < lane.limit:
        lane.limit = selected
        lane.counters["aimd_decrease"] += 1
    lane.success_window = 0


def _open_circuit(lane: Any, clock: Callable[[], float]) -> None:
    if lane.state != "open":
        lane.counters["circuit_open"] += 1
    lane.state = "open"
    lane.opened_until = clock() + CIRCUIT_COOLDOWN_SECONDS


__all__ = ["CAPACITY_FAILURES", "record_lane_outcome", "reset_lane_circuits"]
