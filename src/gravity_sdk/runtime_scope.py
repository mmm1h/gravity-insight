"""Per-env isolation for shared runtimes, metadata cache, and on-disk catalogs.

The fingerprint is an irreversible digest of the resolved credential file path
and the username stored in that file. It is never a credential, and callers
must not print it.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping

from .credential_storage import read_env_file
from .paths import PROJECT_ROOT


ENV_FILE_VAR = "GRAVITY_ENV_FILE"
_FINGERPRINT_LENGTH = 16


def resolve_env_path(
    env_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, bool]:
    """Return the credential file and whether it was explicitly selected.

    An explicit ``env_path`` or ``GRAVITY_ENV_FILE`` is isolated from ambient
    process credential variables. The checkout default stays process-compatible.
    """

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


def env_isolation_key(env_path: str | Path) -> str:
    """Return a short irreversible digest for cache and catalog scoping."""

    selected = Path(env_path).expanduser().resolve()
    username = read_env_file(selected).get("GRAVITY_USERNAME", "").strip()
    material = f"{selected.as_posix()}\0{username}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:_FINGERPRINT_LENGTH]


def gravity_insight_cache_root() -> Path:
    cache_root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "GravityInsight"
    return Path.home() / ".cache" / "gravity-insight"


def operation_catalog_state_path(isolation_key: str = "") -> Path:
    root = gravity_insight_cache_root()
    if isolation_key:
        return root / isolation_key / "operation-catalog.json"
    return root / "operation-catalog.json"


def metadata_catalog_path(isolation_key: str = "") -> Path:
    root = gravity_insight_cache_root()
    if isolation_key:
        return root / isolation_key / "metadata" / "catalog.sqlite3"
    return root / "metadata" / "catalog.sqlite3"


__all__ = [
    "ENV_FILE_VAR",
    "env_isolation_key",
    "gravity_insight_cache_root",
    "metadata_catalog_path",
    "operation_catalog_state_path",
    "resolve_env_path",
]
