"""Environment-bound lazy factories for the public GravitySDK facade."""

from __future__ import annotations

import threading
from typing import Any, Callable

from .runtime_scope import resolve_env_path, scope_workspace


def environment_components(
    *,
    allow_experimental: bool,
    timeout: float,
    attempts: int,
    workspace: Any,
    env_path: Any | None,
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


__all__ = ["environment_components"]
