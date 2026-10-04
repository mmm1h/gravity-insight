"""Value-free identification of the credential source used by SQL Evidence."""

from __future__ import annotations

import os
from pathlib import Path

from gravity_insight.runtime_scope import ENV_FILE_VAR


def credential_source(root: Path) -> str:
    default = root / ".env.gravity.local"
    override = os.environ.get(ENV_FILE_VAR, "").strip()
    selected = Path(override).expanduser() if override else default
    # An explicit file isolates the runtime from ambient credentials (#230).
    if not override or _same_path(selected, default):
        if os.environ.get("GRAVITY_AUTH_TOKEN") or os.environ.get("GRAVITY_AUTHORIZATION"):
            return "environment"
        if os.environ.get("GRAVITY_USERNAME") and os.environ.get("GRAVITY_PASSWORD"):
            return "environment"
    try:
        keys = {
            line.split("=", 1)[0].strip()
            for line in selected.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
    except (OSError, UnicodeError):
        return "missing"
    return (
        "local_account_file"
        if {"GRAVITY_USERNAME", "GRAVITY_PASSWORD"}.issubset(keys)
        else "missing"
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


__all__ = ["credential_source"]
