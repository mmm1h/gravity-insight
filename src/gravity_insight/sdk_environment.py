"""Environment-bound lazy factories for the public GravitySDK facade."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Self

from .runtime_scope import resolve_env_path, scope_workspace


class EnvironmentSdkMixin:
    @classmethod
    def from_env(cls, *, allow_experimental: bool = False, timeout: float = 120.0,
                 attempts: int = 3, workspace: Any | None = None, env_path: Any | None = None,
                 account_pool: Any | None = None, _read_lease: Any | None = None) -> Self:
        """Create a lazy facade from one source or an explicitly enabled account pool."""
        from .account_pool import AccountPool, AccountPoolConfig, _account_config_error

        config = AccountPoolConfig.from_environment() if account_pool is None else account_pool
        if not isinstance(config, AccountPoolConfig):
            raise _account_config_error("ACCOUNT_POOL_CONFIG_INVALID", field="account_pool", next_action="Provide AccountPoolConfig or omit the pool.")
        paths = config.paths()
        if paths:
            if env_path is not None and Path(env_path).expanduser().absolute() != paths[0]:
                raise _account_config_error("ACCOUNT_POOL_PRIMARY_MISMATCH", field="env_path", next_action="Use the first configured account path or omit env_path.")
            result = cls(workspace=workspace)
            result._account_pool = AccountPool(config, {
                "allow_experimental": allow_experimental, "timeout": timeout,
                "attempts": attempts, "workspace": result._workspace,
            })
            return result
        selected = _load_workspace(workspace)
        insight, sql, selected, runtime = environment_components(
            allow_experimental=allow_experimental, timeout=timeout, attempts=attempts,
            workspace=selected, env_path=env_path, read_lease=_read_lease,
        )
        result = cls(insight_factory=insight, sql_factory=sql, workspace=selected,
                     _runtime_scope_bound=True, _runtime_factory=runtime)
        result._account_read_lease = _read_lease
        return result

    @property
    def workspace(self) -> Any:
        """Current selected account workspace; ordinary SDK selections stay immutable."""
        if self._account_pool is not None and self._account_pool.sdk is not None:
            return self._account_pool.sdk.workspace
        return self._workspace

    @property
    def account_pool_status(self) -> dict[str, Any]:
        """Value-free account availability and logical-read transition state."""
        if self._account_pool is None:
            return {"mode": "single", "reason_code": "ACCOUNT_POOL_DISABLED"}
        return self._account_pool.snapshot()


def environment_components(
    *,
    allow_experimental: bool,
    timeout: float,
    attempts: int,
    workspace: Any,
    env_path: Any | None,
    read_lease: Any | None = None,
) -> tuple[Callable[[], Any], Callable[[], Any], Any, Callable[[], Any]]:
    base_workspace = workspace
    selected_env, isolated = resolve_env_path(env_path)
    selected_workspace = scope_workspace(
        base_workspace, selected_env, isolated=isolated
    )
    shared_runtime: Any | None = None
    runtime_lock = threading.Lock()

    def runtime() -> Any:
        nonlocal shared_runtime
        if shared_runtime is None:
            with runtime_lock:
                if shared_runtime is None:
                    from .shared_runtime import get_shared_runtime

                    shared_runtime = get_shared_runtime(
                        env_path=selected_env,
                        timeout=timeout,
                        attempts=attempts,
                        isolated=isolated,
                        receipt_root=base_workspace.state_root,
                    )
                    if read_lease is not None:
                        from .account_pool_lease import LeasedRuntime
                        shared_runtime = LeasedRuntime(shared_runtime, read_lease)
        return shared_runtime

    def build_insight() -> Any:
        from .client import GravityInsightClient

        return GravityInsightClient.from_env(
            allow_experimental=allow_experimental,
            runtime=runtime(),
            env_path=env_path,
        )

    def build_sql() -> Any:
        from .sql.client import GravityClient

        return GravityClient(runtime())

    return build_insight, build_sql, selected_workspace, runtime


def _default_insight_client() -> Any:
    from .client import GravityInsightClient

    return GravityInsightClient.from_env()


def _default_sql_client() -> Any:
    from .sql import build_sql_client

    return build_sql_client()


def _load_workspace(value: Any | None) -> Any:
    from .workspace import load_workspace

    if value is None or isinstance(value, (str, Path)):
        return load_workspace(value)
    return value


__all__ = ["environment_components"]
