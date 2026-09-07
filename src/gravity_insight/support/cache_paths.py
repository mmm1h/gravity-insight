"""One normalized cache-root policy, with discoverable pre-unification roots."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def user_cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """Return the configured/platform cache root without creating it."""

    env = os.environ if environ is None else environ
    configured = env.get("GRAVITY_CACHE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt" and (local := env.get("LOCALAPPDATA", "").strip()):
        return (Path(local).expanduser() / "gravity-insight").resolve()
    if xdg := env.get("XDG_CACHE_HOME", "").strip():
        return (Path(xdg).expanduser() / "gravity-insight").resolve()
    return (Path.home() / ".cache" / "gravity-insight").resolve()


def cache_roots(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Canonical first; also enumerate standard old locations, never credentials.

    Historical custom overrides cannot be inferred from the filesystem.
    """

    env = os.environ if environ is None else environ
    candidates = [user_cache_root(env)]
    for variable in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
        if base := env.get(variable, "").strip():
            candidates.extend(Path(base).expanduser() / name for name in (
                "GravityInsight", "gravity-insight"
            ))
    candidates.append(Path.home() / ".cache" / "gravity-insight")
    # Keep lexical paths for legacy roots so inventory can refuse links.
    return tuple(dict.fromkeys(path.parent.resolve() / path.name for path in candidates))


def existing_cache_path(primary: Path) -> Path:
    """Keep existing account snapshots usable without copying live databases.

    The selected location remains the read/write location for that artifact.
    This avoids splitting SQLite sidecars or a field-policy snapshot directory.
    """

    for candidate in cache_path_candidates(primary):
        try:
            candidate.stat()
        except FileNotFoundError:
            continue
        return candidate
    return primary


def cache_path_candidates(primary: Path) -> tuple[Path, ...]:
    roots = cache_roots()
    owner = next((root for root in sorted(roots, key=lambda path: len(path.parts), reverse=True)
                  if primary.is_relative_to(root)), None)
    if owner is None:
        return (primary,)
    relative = primary.relative_to(owner)
    return tuple(dict.fromkeys((primary, *(root / relative for root in roots))))
