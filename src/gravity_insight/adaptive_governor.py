"""Single process-wide adaptive owner for Runtime HTTP capacity."""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .adaptive_governor_contract import (
    ADAPTIVE,
    BUSINESS_CAPACITY,
    CIRCUIT_FAILURE_THRESHOLD,
    MAX_LANES,
    MAX_QUEUE,
    MAX_SCOPES,
    MAX_WAIT_SECONDS,
    POLICY_REVISION,
    SCHEMA_VERSION,
    SQL_CAPACITY,
    STATIC,
    TOTAL_CAPACITY,
    GovernorRequest,
    GovernorRequestError,
    current_journey_key,
    governor_journey,
    mode_from_environment,
    private_scope_key,
    profile_limits,
    response_status_class,
    validate_configuration,
)
from .adaptive_governor_policy import (
    capacity_failure_observation,
    circuit_rejection,
    record_lane_outcome,
    reset_lane_circuits,
)
from .adaptive_governor_snapshot import (
    AdaptiveGovernorContractError,
    render_adaptive_governor_snapshot,
    validate_adaptive_governor_snapshot,
)


@dataclass
class _Lane:
    limit: int
    max_limit: int
    active: int = 0
    queued: int = 0
    state: str = "closed"
    opened_until: float = 0.0
    consecutive_failures: int = 0
    success_window: int = 0
    ewma_latency_ms: int = 0
    failure_history: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=CIRCUIT_FAILURE_THRESHOLD))
    counters: dict[str, int] = field(
        default_factory=lambda: {
            "success": 0,
            "capacity_failure": 0,
            "client_error": 0,
            "aimd_increase": 0,
            "aimd_decrease": 0,
            "circuit_open": 0,
            "half_open": 0,
            "coalesced": 0,
        }
    )


@dataclass
class _ScopeStats:
    active: int = 0
    queued: int = 0
    peak_active: int = 0
    rejected: int = 0
    cancelled: int = 0
    coalesced: int = 0


@dataclass
class _Waiter:
    request: GovernorRequest
    lane: _Lane


@dataclass
class _Flight:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    share: bool = False


@dataclass
class _Lease:
    request: GovernorRequest
    lane: _Lane
    started: float
    released: bool = False


class AdaptiveRequestGovernor:
    """Global hard caps plus private adaptive lanes and fair bounded waiting."""

    def __init__(
        self,
        *,
        mode: str = ADAPTIVE,
        total_capacity: int = TOTAL_CAPACITY,
        business_capacity: int = BUSINESS_CAPACITY,
        sql_capacity: int = SQL_CAPACITY,
        max_queue: int = MAX_QUEUE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        validate_configuration(
            mode, total_capacity, business_capacity, sql_capacity, max_queue
        )
        self._mode = mode
        self.total_capacity = total_capacity
        self.business_capacity = business_capacity
        self.sql_capacity = sql_capacity
        self.max_queue = max_queue
        self._clock = clock
        self._condition = threading.Condition()
        self._active = 0
        self._business_active = 0
        self._sql_active = 0
        self._last_journey: str | None = None
        self._waiters: deque[_Waiter] = deque()
        self._flight_waiters = 0
        self._lanes: OrderedDict[tuple[str, str, str, str], _Lane] = OrderedDict()
        self._scopes: OrderedDict[str, _ScopeStats] = OrderedDict()
        self._flights: dict[tuple[str, str], _Flight] = {}

    @property
    def mode(self) -> str:
        with self._condition:
            return self._mode

    def set_mode(self, mode: str) -> str:
        if mode not in {ADAPTIVE, STATIC}:
            raise ValueError("Governor mode must be adaptive or static")
        with self._condition:
            previous = self._mode
            self._mode = mode
            if mode != previous:
                self._reset_circuits_locked()
            self._condition.notify_all()
            return previous

    def execute(self, request: GovernorRequest, function: Callable[[], Any]) -> Any:
        while True:
            leader, flight, lane = self._join_flight(request)
            if leader:
                return self._execute_leader(request, function, flight)
            assert flight is not None and lane is not None
            if self._wait_for_flight(request, lane, flight):
                return flight.result

    def snapshot(self, scope_material: Any) -> dict[str, Any]:
        scope_key = private_scope_key(scope_material)
        with self._condition:
            scope = copy.deepcopy(self._scopes.get(scope_key, _ScopeStats()))
            lanes = [
                (key, copy.deepcopy(lane))
                for key, lane in self._lanes.items()
                if key[0] == scope_key
            ]
            snapshot = render_adaptive_governor_snapshot(
                mode=self._mode,
                capacity={
                    "total": self.total_capacity,
                    "business": self.business_capacity,
                    "sql": self.sql_capacity,
                    "max_queue": self.max_queue,
                },
                scope=scope,
                lanes=lanes,
                now=self._clock(),
            )
        return validate_adaptive_governor_snapshot(snapshot)

    def _execute_leader(
        self,
        request: GovernorRequest,
        function: Callable[[], Any],
        flight: _Flight | None,
    ) -> Any:
        lease: _Lease | None = None
        result: Any = None
        error: BaseException | None = None
        status_class = "transport_error"
        try:
            lease = self._acquire(request)
            result = function()
            status_class = response_status_class(result)
            return result
        except BaseException as caught:
            error = caught
            raise
        finally:
            if lease is not None:
                self._complete(lease, status_class, error, result)
            if flight is not None:
                self._finish_flight(request, flight, result, error, status_class)

    def _acquire(self, request: GovernorRequest) -> _Lease:
        deadline = self._clock() + min(request.timeout_seconds, MAX_WAIT_SECONDS)
        with self._condition:
            lane = self._lane_locked(request)
            self._circuit_gate_locked(request, lane)
            if not self._waiters and self._can_grant_locked(request, lane):
                return self._grant_locked(request, lane)
            self._check_queue_capacity_locked(request)
            waiter = _Waiter(request, lane)
            self._waiters.append(waiter)
            self._mark_queued_locked(request, lane, 1)
            return self._wait_for_lease_locked(waiter, deadline)

    def _wait_for_lease_locked(self, waiter: _Waiter, deadline: float) -> _Lease:
        request, lane = waiter.request, waiter.lane
        while True:
            if request.cancellation is not None and request.cancellation.is_set():
                self._remove_waiter_locked(waiter)
                self._scope_locked(request.scope_key).cancelled += 1
                self._reject_locked(request, "GOVERNOR_CANCELLED", "request was cancelled")
            self._circuit_gate_locked(request, lane, waiter=waiter)
            selected = self._selected_waiter_locked()
            if selected is waiter and self._can_grant_locked(request, lane):
                self._remove_waiter_locked(waiter)
                return self._grant_locked(request, lane)
            remaining = deadline - self._clock()
            if remaining <= 0:
                self._remove_waiter_locked(waiter)
                self._reject_locked(request, "GOVERNOR_BACKPRESSURE", "wait timed out")
            self._condition.wait(timeout=min(remaining, 0.05))

    def _grant_locked(self, request: GovernorRequest, lane: _Lane) -> _Lease:
        self._active += 1
        lane.active += 1
        if request.profile != "login":
            self._business_active += 1
        if request.profile == "sql":
            self._sql_active += 1
        scope = self._scope_locked(request.scope_key)
        scope.active += 1
        scope.peak_active = max(scope.peak_active, scope.active)
        self._last_journey = request.journey_key
        return _Lease(request, lane, self._clock())

    def _complete(self, lease: _Lease, status_class: str,
                  error: BaseException | None, result: Any) -> None:
        with self._condition:
            if lease.released:
                return
            lease.released = True
            request, lane = lease.request, lease.lane
            latency = max(0.0, self._clock() - lease.started)
            self._active -= 1
            lane.active -= 1
            if request.profile != "login":
                self._business_active -= 1
            if request.profile == "sql":
                self._sql_active -= 1
            self._scope_locked(request.scope_key).active -= 1
            observed = "transport_error" if error is not None else status_class
            failure = capacity_failure_observation(
                observed, result, error, request.attempt
            ) if observed in {
                "rate_limited", "server_error", "transport_error"
            } else None
            record_lane_outcome(
                self._mode,
                lane,
                observed,
                latency,
                self._clock,
                failure,
            )
            self._condition.notify_all()

    def _circuit_gate_locked(
        self, request: GovernorRequest, lane: _Lane, *, waiter: _Waiter | None = None
    ) -> None:
        if self._mode == STATIC:
            return
        now = self._clock()
        if lane.state == "open" and now >= lane.opened_until:
            lane.state = "half_open"
            lane.counters["half_open"] += 1
        blocked = lane.state == "open" or (
            lane.state == "half_open" and lane.active > 0
        )
        if blocked:
            if waiter is not None:
                self._remove_waiter_locked(waiter)
            reason, diagnostics, next_action = circuit_rejection(lane, request, now)
            self._reject_locked(
                request,
                "GOVERNOR_CIRCUIT_OPEN",
                reason,
                diagnostics=diagnostics,
                next_action=next_action,
            )

    def _can_grant_locked(self, request: GovernorRequest, lane: _Lane) -> bool:
        lane_limit = lane.max_limit if self._mode == STATIC else lane.limit
        return bool(
            self._active < self.total_capacity
            and lane.active < lane_limit
            and (
                request.profile == "login"
                or self._business_active < self.business_capacity
            )
            and (request.profile != "sql" or self._sql_active < self.sql_capacity)
        )

    def _selected_waiter_locked(self) -> _Waiter | None:
        eligible = [
            waiter
            for waiter in self._waiters
            if self._waiter_can_run_locked(waiter)
        ]
        if not eligible:
            return None
        different = [
            waiter
            for waiter in eligible
            if waiter.request.journey_key != self._last_journey
        ]
        return (different or eligible)[0]

    def _waiter_can_run_locked(self, waiter: _Waiter) -> bool:
        lane = waiter.lane
        circuit_available = self._mode == STATIC or lane.state == "closed"
        circuit_available = circuit_available or (
            lane.state == "open"
            and self._clock() >= lane.opened_until
            and lane.active == 0
        )
        circuit_available = circuit_available or (
            lane.state == "half_open" and lane.active == 0
        )
        return circuit_available and self._can_grant_locked(waiter.request, lane)

    def _remove_waiter_locked(self, waiter: _Waiter) -> None:
        try:
            self._waiters.remove(waiter)
        except ValueError:
            return
        self._mark_queued_locked(waiter.request, waiter.lane, -1)

    def _lane_locked(self, request: GovernorRequest) -> _Lane:
        self._ensure_scope_locked(request)
        key = request.lane_key
        lane = self._lanes.pop(key, None)
        if lane is None:
            self._make_lane_room_locked(request)
            initial, maximum = profile_limits(
                request.profile, self.business_capacity, self.sql_capacity
            )
            lane = _Lane(initial, maximum)
        self._lanes[key] = lane
        return lane

    def _make_lane_room_locked(self, request: GovernorRequest) -> None:
        if len(self._lanes) < MAX_LANES:
            return
        removable = next(
            (
                key
                for key, lane in self._lanes.items()
                if lane.active == 0 and lane.queued == 0
            ),
            None,
        )
        if removable is None:
            self._reject_locked(request, "GOVERNOR_BACKPRESSURE", "lane registry is full")
        self._lanes.pop(removable)

    def _ensure_scope_locked(self, request: GovernorRequest) -> None:
        scope_key = request.scope_key
        stats = self._scopes.pop(scope_key, None)
        if stats is None:
            if len(self._scopes) >= MAX_SCOPES:
                self._evict_scope_locked(request)
            stats = _ScopeStats()
        self._scopes[scope_key] = stats

    def _evict_scope_locked(self, request: GovernorRequest) -> None:
        removable = next(
            (
                key
                for key, stats in self._scopes.items()
                if stats.active == 0 and stats.queued == 0
            ),
            None,
        )
        if removable is None:
            self._raise_request_error(
                "GOVERNOR_BACKPRESSURE", "scope registry is full"
            )
        self._scopes.pop(removable)
        for lane_key in [key for key in self._lanes if key[0] == removable]:
            lane = self._lanes[lane_key]
            if lane.active == 0 and lane.queued == 0:
                self._lanes.pop(lane_key)

    def _scope_locked(self, scope_key: str) -> _ScopeStats:
        stats = self._scopes.pop(scope_key)
        self._scopes[scope_key] = stats
        return stats

    def _join_flight(
        self, request: GovernorRequest
    ) -> tuple[bool, _Flight | None, _Lane | None]:
        if not request.coalesce_safe or not request.request_key:
            return True, None, None
        key = (request.scope_key, request.request_key)
        with self._condition:
            if self._mode != ADAPTIVE:
                return True, None, None
            existing = self._flights.get(key)
            if existing is None:
                if len(self._flights) >= self.total_capacity + self.max_queue:
                    self._lane_locked(request)
                    self._reject_locked(
                        request, "GOVERNOR_BACKPRESSURE", "flight registry is full"
                    )
                flight = _Flight()
                self._flights[key] = flight
                return True, flight, None
            lane = self._lane_locked(request)
            self._check_queue_capacity_locked(request)
            self._flight_waiters += 1
            self._mark_queued_locked(request, lane, 1)
            scope = self._scope_locked(request.scope_key)
            scope.coalesced += 1
            lane.counters["coalesced"] += 1
            return False, existing, lane

    def _wait_for_flight(
        self, request: GovernorRequest, lane: _Lane, flight: _Flight
    ) -> bool:
        deadline = self._clock() + min(request.timeout_seconds, MAX_WAIT_SECONDS)
        code: str | None = None
        reason = ""
        while not flight.event.wait(0.05):
            if request.cancellation is not None and request.cancellation.is_set():
                code, reason = "GOVERNOR_CANCELLED", "single-flight wait was cancelled"
                break
            if self._clock() >= deadline:
                code, reason = "GOVERNOR_BACKPRESSURE", "single-flight wait timed out"
                break
        with self._condition:
            self._flight_waiters -= 1
            self._mark_queued_locked(request, lane, -1)
            if code == "GOVERNOR_CANCELLED":
                self._scope_locked(request.scope_key).cancelled += 1
            if code is not None:
                self._reject_locked(request, code, reason)
        return flight.share

    def _finish_flight(
        self,
        request: GovernorRequest,
        flight: _Flight,
        result: Any,
        error: BaseException | None,
        status_class: str,
    ) -> None:
        key = (request.scope_key, str(request.request_key))
        with self._condition:
            if error is None and status_class == "success":
                flight.result = result
                flight.share = True
            self._flights.pop(key, None)
            flight.event.set()

    def _mark_queued_locked(
        self, request: GovernorRequest, lane: _Lane, change: int
    ) -> None:
        lane.queued += change
        self._scope_locked(request.scope_key).queued += change

    def _check_queue_capacity_locked(self, request: GovernorRequest) -> None:
        if len(self._waiters) + self._flight_waiters >= self.max_queue:
            self._reject_locked(request, "GOVERNOR_BACKPRESSURE", "queue is full")

    def _reject_locked(self, request: GovernorRequest, code: str, reason: str, *,
                       diagnostics: dict[str, Any] | None = None,
                       next_action: str | None = None) -> None:
        stats = self._scopes.get(request.scope_key)
        if stats is not None:
            stats.rejected += 1
        self._raise_request_error(
            code, reason, diagnostics=diagnostics, next_action=next_action
        )

    @staticmethod
    def _raise_request_error(code: str, reason: str, *,
                             diagnostics: dict[str, Any] | None = None,
                             next_action: str | None = None) -> None:
        raise GovernorRequestError(
            f"Adaptive Governor stopped HTTP before network ({code}: {reason}).",
            code=code,
            next_action=next_action
            or "Wait for governed capacity or circuit cooldown, then retry the same request once.",
            diagnostics=diagnostics,
        )

    def _reset_circuits_locked(self) -> None:
        reset_lane_circuits(self._lanes.values())


def get_process_governor() -> AdaptiveRequestGovernor:
    return _PROCESS_GOVERNOR


_PROCESS_GOVERNOR = AdaptiveRequestGovernor(mode=mode_from_environment())


__all__ = [
    "ADAPTIVE",
    "AdaptiveGovernorContractError",
    "AdaptiveRequestGovernor",
    "BUSINESS_CAPACITY",
    "GovernorRequest",
    "GovernorRequestError",
    "POLICY_REVISION",
    "SCHEMA_VERSION",
    "SQL_CAPACITY",
    "STATIC",
    "TOTAL_CAPACITY",
    "current_journey_key",
    "get_process_governor",
    "governor_journey",
    "private_scope_key",
    "validate_adaptive_governor_snapshot",
]
