"""Thread-safe counters and circuit state for one Provider RPC session."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping


HEALTH_FAILURES = frozenset(
    {
        "PROVIDER_RPC_TIMEOUT",
        "PROVIDER_RPC_UNAVAILABLE",
        "PROVIDER_RPC_ERROR",
        "PROVIDER_RPC_OUTPUT_LIMIT",
        "PROVIDER_RPC_TOKEN_LIMIT",
        "PROVIDER_RPC_MALFORMED",
        "PROVIDER_RPC_RESPONSE_INVALID",
        "PROVIDER_RESOURCE_HASH_MISMATCH",
    }
)


class ProviderRpcState:
    """Own mutable metrics and closed/open/half-open transitions."""

    def __init__(
        self,
        rpc: Mapping[str, int],
        *,
        process_capacity: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rpc = dict(rpc)
        self._process_capacity = process_capacity
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts_reserved = 0
        self._circuit_state = "closed"
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._half_open_inflight = False
        self._opens = 0
        self._stats = {
            "logical_calls": 0,
            "transport_attempts": 0,
            "successes": 0,
            "gaps": 0,
            "retries": 0,
            "timeouts": 0,
            "cancellations": 0,
            "unavailable": 0,
            "malformed": 0,
            "oversize": 0,
            "busy": 0,
            "permission_filtered": 0,
            "output_bytes": 0,
            "output_tokens": 0,
            "active": 0,
            "peak_active": 0,
        }

    def start_attempt(self) -> bool:
        with self._lock:
            if self._attempts_reserved >= self._rpc["max_calls_per_session"]:
                return False
            self._attempts_reserved += 1
            self._stats["transport_attempts"] += 1
            self._stats["active"] += 1
            self._stats["peak_active"] = max(
                self._stats["peak_active"], self._stats["active"]
            )
            return True

    def finish_attempt(self) -> None:
        with self._lock:
            self._stats["active"] -= 1

    def increment(self, field: str, count: int = 1) -> None:
        with self._lock:
            self._stats[field] += count

    def record_failure(self, reason: str) -> None:
        if reason == "PROVIDER_RPC_TIMEOUT":
            self.increment("timeouts")
        elif reason == "PROVIDER_RPC_CANCELLED":
            self.increment("cancellations")
        elif reason == "PROVIDER_RPC_UNAVAILABLE":
            self.increment("unavailable")
        elif reason in {"PROVIDER_RPC_OUTPUT_LIMIT", "PROVIDER_RPC_TOKEN_LIMIT"}:
            self.increment("oversize")
        elif reason in HEALTH_FAILURES:
            self.increment("malformed")

    def admit_circuit(self) -> bool | None:
        now = self._clock()
        with self._lock:
            if self._circuit_state == "open":
                if now < self._open_until or self._half_open_inflight:
                    return None
                self._circuit_state = "half_open"
                self._half_open_inflight = True
                return True
            if self._circuit_state == "half_open":
                return None
            return False

    def finish_circuit(self, *, success: bool, probe: bool) -> None:
        with self._lock:
            if success:
                self._circuit_state = "closed"
                self._consecutive_failures = 0
                self._open_until = 0.0
                self._half_open_inflight = False
                return
            self._consecutive_failures += 1
            if probe or self._consecutive_failures >= self._rpc[
                "circuit_failure_threshold"
            ]:
                self._circuit_state = "open"
                self._open_until = self._clock() + self._rpc[
                    "circuit_cooldown_ms"
                ] / 1000
                self._half_open_inflight = False
                self._opens += 1

    def abandon_probe(self, probe: bool) -> None:
        if not probe:
            return
        with self._lock:
            self._circuit_state = "open"
            self._open_until = self._clock() + self._rpc[
                "circuit_cooldown_ms"
            ] / 1000
            self._half_open_inflight = False

    def circuit_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            remaining = max(0, int((self._open_until - now) * 1000))
            return {
                "state": self._circuit_state,
                "consecutive_failures": self._consecutive_failures,
                "open_count": self._opens,
                "cooldown_remaining_ms": remaining,
            }

    def stats_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "max_concurrency": self._rpc["max_concurrency"],
                "process_capacity": self._process_capacity,
                "max_calls_per_session": self._rpc["max_calls_per_session"],
            }


def is_health_failure(reason: str) -> bool:
    return reason in HEALTH_FAILURES


__all__ = ["ProviderRpcState", "is_health_failure"]
