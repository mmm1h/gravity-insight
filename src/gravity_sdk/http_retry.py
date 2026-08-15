"""Retry timing and response decoding for the controlled HTTP runtime."""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone
from typing import Any, Callable


def response_payload(response: Any) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError):
        return None


def is_retryable_exception(exc: BaseException) -> bool:
    try:
        import requests
    except ImportError:  # pragma: no cover
        return isinstance(exc, (TimeoutError, OSError))
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def retry_delay(
    response: Any,
    attempt: int,
    *,
    wall_clock: Callable[[], datetime],
    random_source: Callable[[], float],
) -> float:
    value = getattr(response, "headers", {}).get("Retry-After")
    if value:
        minimum = _retry_after_seconds(value, wall_clock)
        if minimum >= 0:
            jitter = min(1.0, max(0.05, minimum * 0.1))
            return minimum + jitter * unit_random(random_source)
    base = float(min(2 ** (attempt + 1), 8))
    return base * (1.0 + 0.2 * unit_random(random_source))


def _retry_after_seconds(value: Any, wall_clock: Callable[[], datetime]) -> float:
    try:
        return max(0.0, min(float(value), 30.0))
    except (TypeError, ValueError):
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, min((retry_at - wall_clock()).total_seconds(), 30.0))
        except (TypeError, ValueError, OverflowError):
            return -1.0


def unit_random(source: Callable[[], float]) -> float:
    try:
        value = float(source())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("random source must return a number") from exc
    return max(0.0, min(value, 1.0))


__all__ = ["is_retryable_exception", "response_payload", "retry_delay", "unit_random"]
