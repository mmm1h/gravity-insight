"""Process-local Gravity HTTP runtime keyed by principal scope."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .credentials import GRAVITY_HOST
from .errors import CredentialError
from .http_runtime import GravityHttpRuntime, HostRateLimiter, _rate_from_environment, _validated_rate
from .paths import STATE_ROOT
from .runtime_scope import (
    RuntimeScopeKey,
    principal_state_root,
    resolve_env_path,
    runtime_scope_key,
)


_SHARED_LOCK = threading.Lock()
_SHARED_RUNTIMES: dict[RuntimeScopeKey, GravityHttpRuntime] = {}
_PROCESS_LIMITER = HostRateLimiter()


class _RetiredCredentialProvider:
    def get(self, **_kwargs: Any) -> Any:
        raise CredentialError(
            "Gravity runtime credential generation actual value: stale",
            field="env_path",
            next_action="Call gravity_sdk.connect() again and retry the operation.",
        )


def _retire(runtime: GravityHttpRuntime) -> None:
    setattr(
        runtime,
        "_GravityHttpRuntime__credentials",
        _RetiredCredentialProvider(),
    )


def get_shared_runtime(
    *,
    env_path: Path | None = None,
    requests_per_second: float | None = None,
    timeout: float = 120.0,
    attempts: int = 3,
    isolated: bool | None = None,
    receipt_root: Path | None = None,
) -> GravityHttpRuntime:
    """Return the runtime for one principal generation inside this process.

    Shared per principal generation: session, credentials, connection pool.
    Shared process-wide: 10 rps host limiter and 24 in-flight slots.
    """

    selected, resolved_isolated = resolve_env_path(env_path)
    if isolated is not None:
        resolved_isolated = bool(isolated)
    resolved_path = Path(selected).resolve()
    base_receipt_root = Path(receipt_root or STATE_ROOT).resolve()
    scope = runtime_scope_key(
        resolved_path,
        isolated=resolved_isolated,
        workspace_root=base_receipt_root,
    )
    rate = (
        _rate_from_environment()
        if requests_per_second is None
        else _validated_rate(requests_per_second)
    )
    with _SHARED_LOCK:
        existing = _SHARED_RUNTIMES.get(scope)
        if existing is None:
            stale = [
                key
                for key in _SHARED_RUNTIMES
                if key.location_fingerprint == scope.location_fingerprint
            ]
            for key in stale:
                _retire(_SHARED_RUNTIMES.pop(key))
            existing = GravityHttpRuntime(
                env_path=resolved_path,
                limiter=_PROCESS_LIMITER,
                requests_per_second=rate,
                timeout=timeout,
                attempts=attempts,
                isolated=resolved_isolated,
                receipt_root=principal_state_root(base_receipt_root, scope),
            )
            _SHARED_RUNTIMES[scope] = existing
        else:
            _PROCESS_LIMITER.configure(GRAVITY_HOST, rate)
        return existing


def reset_shared_runtimes() -> None:
    with _SHARED_LOCK:
        for runtime in _SHARED_RUNTIMES.values():
            _retire(runtime)
        _SHARED_RUNTIMES.clear()


__all__ = ["get_shared_runtime", "reset_shared_runtimes"]
