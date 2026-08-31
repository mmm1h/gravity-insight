"""Principal isolation for runtimes and private on-disk state.

Scope material is reduced to one-way digests before it leaves this module.
Runtime scope keys must never be rendered in caller-visible output.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .credential_storage import (
    EXPIRY_KEY,
    PRINCIPAL_ID_KEY,
    SESSION_USERNAME_KEY,
    TOKEN_KEYS,
    UPDATED_KEY,
    read_env_file,
    session_path,
)
from .paths import PROJECT_ROOT


ENV_FILE_VAR = "GRAVITY_ENV_FILE"
_FINGERPRINT_LENGTH = 32
_CREDENTIAL_KEYS = (
    "GRAVITY_USERNAME",
    "GRAVITY_PASSWORD",
    *TOKEN_KEYS,
    EXPIRY_KEY,
    UPDATED_KEY,
    PRINCIPAL_ID_KEY,
    SESSION_USERNAME_KEY,
)


@dataclass(frozen=True, repr=False)
class RuntimeScopeKey:
    """Non-renderable identity and credential-generation cache key."""

    resolved_env_path_hash: str
    account_fingerprint: str
    principal_fingerprint: str
    credential_generation: str
    workspace_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return _digest(
            "runtime",
            self.resolved_env_path_hash,
            self.account_fingerprint,
            self.principal_fingerprint,
            self.credential_generation,
            self.workspace_fingerprint,
        )

    @property
    def location_fingerprint(self) -> str:
        return _digest(
            "location", self.resolved_env_path_hash, self.workspace_fingerprint
        )

    @property
    def storage_fingerprint(self) -> str:
        """Stable private-storage key for one configured account.

        Runtime and receipt isolation includes the authenticated principal and
        credential generation. Persistent metadata must survive the first login
        discovering those values, while still changing when the configured
        account changes.
        """

        return _digest(
            "storage",
            self.resolved_env_path_hash,
            self.account_fingerprint,
            self.workspace_fingerprint,
        )

    def __repr__(self) -> str:
        return "<RuntimeScopeKey redacted>"


def resolve_env_path(
    env_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, bool]:
    """Return the credential file and whether it was explicitly selected."""

    env = os.environ if environ is None else environ
    default = PROJECT_ROOT / ".env.gravity.local"
    if env_path is not None:
        selected = Path(env_path).expanduser()
    else:
        override = str(env.get(ENV_FILE_VAR, "")).strip()
        selected = Path(override).expanduser() if override else default
    try:
        isolated = selected.resolve() != default.resolve()
    except OSError:
        isolated = selected != default
    return selected, isolated


def runtime_scope_key(
    env_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    isolated: bool | None = None,
    workspace_root: str | Path | None = None,
) -> RuntimeScopeKey:
    """Build a stable key without retaining raw account or secret material."""

    selected, resolved_isolated = resolve_env_path(env_path, environ=environ)
    selected = selected.resolve()
    if isolated is not None:
        resolved_isolated = bool(isolated)
    ambient = os.environ if environ is None else environ
    ambient_values = {} if resolved_isolated else _credential_values(ambient)
    file_values = _credential_values(read_env_file(selected))
    account_values = {**file_values, **ambient_values}
    file_username = file_values.get("GRAVITY_USERNAME", "").strip()
    ambient_username = ambient_values.get("GRAVITY_USERNAME", "").strip()
    username = account_values.get("GRAVITY_USERNAME", "").strip()
    session_values = _bound_session_values(selected, username)
    principal = _first_value(
        ambient_values.get(PRINCIPAL_ID_KEY),
        session_values.get(PRINCIPAL_ID_KEY),
        file_values.get(PRINCIPAL_ID_KEY),
    )
    path_hash = _digest("env-path", selected.as_posix().casefold())
    account = _digest(
        "account", path_hash, file_username, ambient_username
    )
    workspace = _digest(
        "workspace",
        Path(workspace_root).expanduser().resolve().as_posix().casefold()
        if workspace_root is not None
        else "metadata-global",
    )
    return RuntimeScopeKey(
        resolved_env_path_hash=path_hash,
        account_fingerprint=account,
        principal_fingerprint=_digest("principal", account, principal),
        credential_generation=_digest(
            "generation",
            *_generation_parts(file_values, ambient_values, session_values),
        ),
        workspace_fingerprint=workspace,
    )


def env_isolation_key(env_path: str | Path) -> str:
    """Return the stable account digest used by persistent disk caches."""

    return runtime_scope_key(env_path).storage_fingerprint


def gravity_insight_cache_root() -> Path:
    cache_root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "GravityInsight"
    return Path.home() / ".cache" / "gravity-insight"


def operation_catalog_state_path(isolation_key: str | None = "") -> Path:
    return gravity_insight_cache_root() / _required_scope(isolation_key) / "operation-catalog.json"


def metadata_catalog_path(isolation_key: str = "") -> Path:
    return gravity_insight_cache_root() / _required_scope(isolation_key) / "metadata" / "catalog.sqlite3"


def field_policy_cache_dir(isolation_key: str = "") -> Path:
    return gravity_insight_cache_root() / _required_scope(isolation_key) / "field-policy"


def principal_state_root(state_root: str | Path, scope: RuntimeScopeKey) -> Path:
    """Return private state storage for one principal and credential generation."""

    return Path(state_root).expanduser().resolve() / "principals" / scope.fingerprint


def principal_receipt_root(
    state_root: str | Path,
    env_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    isolated: bool | None = None,
) -> Path:
    scope = runtime_scope_key(
        env_path,
        environ=environ,
        isolated=isolated,
        workspace_root=state_root,
    )
    return principal_state_root(state_root, scope)


def scope_workspace(
    workspace: Any,
    env_path: str | Path,
    *,
    isolated: bool,
) -> Any:
    """Bind one immutable Workspace state root to its current principal."""

    scope = runtime_scope_key(
        env_path,
        isolated=isolated,
        workspace_root=workspace.state_root,
    )
    return replace(
        workspace,
        state_root=principal_state_root(workspace.state_root, scope),
    )


def redact_scoped_path(path: str | Path) -> str:
    """Render a default cache path without exposing its scope digest."""

    selected = Path(path)
    root = gravity_insight_cache_root()
    try:
        relative = selected.relative_to(root)
    except ValueError:
        return str(selected)
    if len(relative.parts) < 2:
        return str(selected)
    return str(root / "<principal-scope>" / Path(*relative.parts[1:]))


def public_scoped_path(path: str | Path, *, explicit: bool) -> str:
    return str(path) if explicit else redact_scoped_path(path)


def _required_scope(value: str | None) -> str:
    return str(value).strip() if value else runtime_scope_key().storage_fingerprint


def _credential_values(values: Mapping[str, str]) -> dict[str, str]:
    return {key: str(values.get(key, "")) for key in _CREDENTIAL_KEYS}


def _bound_session_values(path: Path, username: str) -> dict[str, str]:
    values = _credential_values(read_env_file(session_path(path)))
    bound = values.get(SESSION_USERNAME_KEY, "").strip()
    return values if not username or not bound or bound == username else {}


def _generation_parts(*sources: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        f"{source_index}:{key}:{source.get(key, '')}"
        for source_index, source in enumerate(sources)
        for key in _CREDENTIAL_KEYS
    )


def _first_value(*values: str | None) -> str:
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def _digest(domain: str, *values: str) -> str:
    digest = hashlib.sha256()
    for value in (domain, *values):
        encoded = str(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()[:_FINGERPRINT_LENGTH]


__all__ = [
    "ENV_FILE_VAR",
    "RuntimeScopeKey",
    "env_isolation_key",
    "field_policy_cache_dir",
    "gravity_insight_cache_root",
    "metadata_catalog_path",
    "operation_catalog_state_path",
    "principal_receipt_root",
    "principal_state_root",
    "public_scoped_path",
    "redact_scoped_path",
    "resolve_env_path",
    "runtime_scope_key",
    "scope_workspace",
]
