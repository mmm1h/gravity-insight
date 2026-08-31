"""Deterministic AIMD and circuit transitions for one Governor lane."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from .adaptive_governor_contract import (
    ADAPTIVE,
    CIRCUIT_COOLDOWN_SECONDS,
    CIRCUIT_FAILURE_THRESHOLD,
    SLOW_RESPONSE_SECONDS,
)


CAPACITY_FAILURES = frozenset({"rate_limited", "server_error", "transport_error"})


def capacity_failure_observation(
    status_class: str,
    result: Any,
    error: BaseException | None,
    attempt: int,
) -> dict[str, Any]:
    status = getattr(result, "status_code", None)
    return {
        "attempt": attempt,
        "status_class": status_class,
        "http_status": status if type(status) is int else None,
        "exception_type": _safe_exception_type(error),
    }


def circuit_rejection(
    lane: Any, request: Any, now: float
) -> tuple[str, dict[str, Any], str]:
    cooldown_remaining_ms = max(
        0, math.ceil((lane.opened_until - now) * 1_000)
    )
    failures = [
        {"failure_index": index, **dict(failure)}
        for index, failure in enumerate(lane.failure_history, start=1)
    ]
    identity = {
        "host": _safe_host(request.target_host),
        "host_key": _safe_hash(request.host_key),
        "operation_class": _safe_label(request.operation_class),
        "profile": _safe_label(request.profile),
    }
    failure_class, classification_reason = _circuit_failure_class(failures)
    diagnostics = {
        "failure_class": failure_class,
        "classification_reason": classification_reason,
        "lane": identity,
        "failures": failures,
        "cooldown_remaining_ms": cooldown_remaining_ms,
    }
    reason = (
        f"lane circuit is open after {len(failures)} consecutive capacity failures; "
        f"host={identity['host']}; operation={identity['operation_class']}; "
        f"profile={identity['profile']}; cooldown_remaining_ms={cooldown_remaining_ms}"
    )
    next_action = (
        f"Wait at least {cooldown_remaining_ms} ms for circuit cooldown, then retry "
        "the same host once. If the circuit opens again, stop the crawl and inspect "
        "the reported status classes and upstream service health."
    )
    return reason, diagnostics, next_action


def local_governor_rejection(
    request: Any, code: str, reason: str
) -> dict[str, Any]:
    failure_class = (
        "local_governor_capacity"
        if code == "GOVERNOR_BACKPRESSURE"
        else "unclassified"
    )
    diagnostics = {
        "failure_class": failure_class,
        "classification_reason": (
            "process_governor_capacity_denied_before_network"
            if failure_class == "local_governor_capacity"
            else "non_capacity_governor_rejection"
        ),
        "source_code": _safe_label(code),
        "denial_reason": _safe_label(reason.replace(" ", "_")),
        "lane": {
            "host": _safe_host(request.target_host),
            "host_key": _safe_hash(request.host_key),
            "operation_class": _safe_label(request.operation_class),
            "profile": _safe_label(request.profile),
        },
    }
    return diagnostics


def _circuit_failure_class(
    failures: list[dict[str, Any]],
) -> tuple[str, str]:
    observed = {str(item.get("status_class", "unknown")) for item in failures}
    if observed == {"rate_limited"}:
        return "upstream_capacity", "circuit_opened_by_http_429"
    if observed == {"server_error"}:
        return "http_server_error", "circuit_opened_by_http_5xx"
    if observed == {"transport_error"}:
        return "transport_failure", "circuit_opened_by_transport_failures"
    return "unclassified", (
        "circuit_opened_by_mixed_or_unknown_signals:"
        + ",".join(sorted(observed))
    )


def record_lane_outcome(
    mode: str,
    lane: Any,
    status_class: str,
    latency: float,
    clock: Callable[[], float],
    failure: dict[str, Any] | None = None,
) -> None:
    _record_latency(lane, latency)
    _record_status_counter(lane, status_class)
    if mode != ADAPTIVE:
        return
    if status_class in CAPACITY_FAILURES:
        lane.failure_history.append(
            dict(failure or {"status_class": status_class})
        )
        lane.consecutive_failures += 1
        _decrease(lane, halve=True)
        if lane.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            _open_circuit(lane, clock)
        return
    if status_class in {"success", "client_error", "redirect"}:
        lane.consecutive_failures = 0
        lane.failure_history.clear()
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
        lane.failure_history.clear()


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


def _safe_exception_type(error: BaseException | None) -> str | None:
    if error is None:
        return None
    selected = type(error).__name__
    if 1 <= len(selected) <= 128 and selected[0].isalpha() and all(
        character.isascii() and (character.isalnum() or character == "_")
        for character in selected
    ):
        return selected
    return "Exception"


def _safe_host(value: Any) -> str:
    selected = str(value).casefold()
    if 1 <= len(selected) <= 253 and all(
        character in "abcdefghijklmnopqrstuvwxyz0123456789.:-"
        for character in selected
    ):
        return selected
    return "unknown"


def _safe_hash(value: Any) -> str:
    selected = str(value).casefold()
    return selected if len(selected) == 64 and all(
        character in "0123456789abcdef" for character in selected
    ) else "unknown"


def _safe_label(value: Any) -> str:
    selected = str(value)
    if 1 <= len(selected) <= 128 and all(
        character.isascii() and (character.isalnum() or character in "._:-")
        for character in selected
    ):
        return selected
    return "unknown"


__all__ = [
    "CAPACITY_FAILURES",
    "capacity_failure_observation",
    "circuit_rejection",
    "local_governor_rejection",
    "record_lane_outcome",
    "reset_lane_circuits",
]
