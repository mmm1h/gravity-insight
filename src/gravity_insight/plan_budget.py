"""Reentrant leases over the single Plan worker budget."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class PlanConcurrencyBudget:
    """Bound outer executions and borrowed adapter workers with one capacity."""

    def __init__(self, capacity: int) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("Plan concurrency capacity must be a positive integer")
        self.capacity = capacity
        self._available = capacity
        self._condition = threading.Condition()

    @contextmanager
    def worker(self) -> Iterator[PlanWorkerLease]:
        with self._condition:
            while self._available == 0:
                self._condition.wait()
            self._available -= 1
        lease = PlanWorkerLease(self)
        try:
            yield lease
        finally:
            lease.close()

    def _try_acquire(self, count: int) -> int:
        with self._condition:
            granted = min(count, self._available)
            self._available -= granted
            return granted

    def _release(self, count: int) -> None:
        if count == 0:
            return
        with self._condition:
            self._available += count
            if self._available > self.capacity:
                raise RuntimeError("Plan concurrency budget was over-released")
            self._condition.notify_all()


class PlanWorkerLease:
    """One Plan worker plus any extra capacity borrowed by its adapter."""

    def __init__(self, budget: PlanConcurrencyBudget) -> None:
        self._budget = budget
        self._owner = threading.get_ident()
        self._owned = 1
        self._closed = False

    @contextmanager
    def borrow(self, limit: int) -> Iterator[int]:
        _validate_limit(limit)
        self._check_owner()
        if self._closed:
            raise RuntimeError("Plan worker lease is closed")
        added = self._budget._try_acquire(max(0, limit - self._owned))
        self._owned += added
        try:
            yield min(limit, self._owned)
        finally:
            self._owned -= added
            self._budget._release(added)

    def close(self) -> None:
        self._check_owner()
        if self._closed:
            return
        owned, self._owned, self._closed = self._owned, 0, True
        self._budget._release(owned)

    def _check_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Plan worker lease cannot cross execution threads")


class SerialWorkerLease:
    """Fallback for adapter contexts constructed outside a running Plan."""

    @contextmanager
    def borrow(self, limit: int) -> Iterator[int]:
        _validate_limit(limit)
        yield 1


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("borrowed Plan worker limit must be a positive integer")


__all__ = ["PlanConcurrencyBudget", "PlanWorkerLease", "SerialWorkerLease"]
