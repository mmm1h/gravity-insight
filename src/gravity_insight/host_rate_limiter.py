"""Process-safe fixed Host Rate Limiter used before adaptive activation."""

from __future__ import annotations

import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .http_retry import unit_random


DEFAULT_REQUESTS_PER_SECOND = 10.0
MAX_REQUESTS_PER_SECOND = 100.0


@dataclass
class _HostBucket:
    requests_per_second: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    next_at: float = 0.0
    cooldown_until: float = 0.0
    cooldown_generation: int = 0


class HostRateLimiter:
    """Thread-safe proactive limiter with an independent bucket for each host."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        random_source: Callable[[], float] = random.random,
        interval_jitter_ratio: float = 0.1,
    ) -> None:
        if not 0 <= interval_jitter_ratio <= 1:
            raise ValueError("rate-limit jitter ratio must be between 0 and 1")
        self._clock = clock
        self._random = random_source
        self._jitter_ratio = interval_jitter_ratio
        self._buckets_lock = threading.Lock()
        self._buckets: dict[str, _HostBucket] = {}

    def configure(self, host: str, requests_per_second: float) -> None:
        key = _canonical_host(host)
        rate = _validated_rate(requests_per_second)
        with self._buckets_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _HostBucket(rate)
            elif bucket.requests_per_second != rate:
                raise ValueError("a Gravity host cannot use conflicting rate-limit quotas")

    def acquire(self, host: str, sleeper: Callable[[float], None] = time.sleep) -> float:
        """Reserve under lock, wait outside it, and honor late server cooldowns."""

        bucket = self._bucket(host)
        with bucket.lock:
            now = self._clock()
            slot = max(now, bucket.next_at, bucket.cooldown_until)
            interval = 1.0 / bucket.requests_per_second
            jitter = interval * self._jitter_ratio * unit_random(self._random)
            bucket.next_at = slot + interval + jitter
            delay = max(0.0, slot - now)
            cooldown_generation = bucket.cooldown_generation
        total_delay = delay
        if delay:
            sleeper(delay)

        # A concurrent 429 may publish a cooldown after this caller reserved its
        # original slot. Re-reserve only when the generation changes, keeping
        # every sleep outside the bucket lock and preserving post-cooldown spacing.
        while True:
            with bucket.lock:
                if cooldown_generation == bucket.cooldown_generation:
                    return total_delay
                cooldown_generation = bucket.cooldown_generation
                now = self._clock()
                slot = max(now, bucket.next_at, bucket.cooldown_until)
                interval = 1.0 / bucket.requests_per_second
                jitter = interval * self._jitter_ratio * unit_random(self._random)
                bucket.next_at = slot + interval + jitter
                delay = max(0.0, slot - now)
            total_delay += delay
            if delay:
                sleeper(delay)

    def defer(self, host: str, delay: float) -> None:
        """Publish a server-directed cooldown to all callers of this host."""

        if delay <= 0:
            return
        bucket = self._bucket(host)
        with bucket.lock:
            proposed = self._clock() + float(delay)
            if proposed > bucket.cooldown_until:
                bucket.cooldown_until = proposed
                bucket.next_at = max(bucket.next_at, proposed)
                bucket.cooldown_generation += 1

    def _bucket(self, host: str) -> _HostBucket:
        key = _canonical_host(host)
        with self._buckets_lock:
            bucket = self._buckets.get(key)
        if bucket is None:
            raise ValueError("Gravity host rate limit was not configured")
        return bucket


def _canonical_host(host: str) -> str:
    parsed = urlsplit(host)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Gravity rate-limit host must be an HTTPS origin")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname.lower()}{port}"


def _validated_rate(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("requests_per_second must be numeric")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("requests_per_second must be numeric") from exc
    if not 0 < rate <= MAX_REQUESTS_PER_SECOND:
        raise ValueError(
            f"requests_per_second must be greater than 0 and at most {MAX_REQUESTS_PER_SECOND:g}"
        )
    return rate


def _rate_from_environment() -> float:
    value = os.environ.get("GRAVITY_REQUESTS_PER_SECOND", "").strip()
    return DEFAULT_REQUESTS_PER_SECOND if not value else _validated_rate(value)


__all__ = [
    "DEFAULT_REQUESTS_PER_SECOND",
    "HostRateLimiter",
    "MAX_REQUESTS_PER_SECOND",
]
