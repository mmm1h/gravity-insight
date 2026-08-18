"""Process-local Gravity HTTP runtime keyed by credential file."""

from __future__ import annotations

import threading
from pathlib import Path

from .credentials import GRAVITY_HOST
from .http_runtime import GravityHttpRuntime, HostRateLimiter, _rate_from_environment, _validated_rate
from .runtime_scope import resolve_env_path


_SHARED_LOCK = threading.Lock()
_SHARED_RUNTIMES: dict[Path, GravityHttpRuntime] = {}
_PROCESS_LIMITER = HostRateLimiter()


def get_shared_runtime(
    *,
    env_path: Path | None = None,
    requests_per_second: float | None = None,
    timeout: float = 120.0,
    attempts: int = 3,
    isolated: bool | None = None,
) -> GravityHttpRuntime:
    """Return the runtime for one credential file inside this process.

    Shared per resolved env file: session, credentials, connection pool.
    Shared process-wide: 10 rps host limiter and 24 in-flight slots.
    """

    selected, resolved_isolated = resolve_env_path(env_path)
    if isolated is not None:
        resolved_isolated = bool(isolated)
    resolved_path = Path(selected).resolve()
    rate = (
        _rate_from_environment()
        if requests_per_second is None
        else _validated_rate(requests_per_second)
    )
    with _SHARED_LOCK:
        existing = _SHARED_RUNTIMES.get(resolved_path)
        if existing is None:
            existing = GravityHttpRuntime(
                env_path=resolved_path,
                limiter=_PROCESS_LIMITER,
                requests_per_second=rate,
                timeout=timeout,
                attempts=attempts,
                isolated=resolved_isolated,
            )
            _SHARED_RUNTIMES[resolved_path] = existing
        else:
            _PROCESS_LIMITER.configure(GRAVITY_HOST, rate)
        return existing


def reset_shared_runtimes() -> None:
    with _SHARED_LOCK:
        _SHARED_RUNTIMES.clear()


__all__ = ["get_shared_runtime", "reset_shared_runtimes"]
