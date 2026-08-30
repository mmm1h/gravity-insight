"""Value-free identification of the credential source used by SQL Evidence."""

from __future__ import annotations

import os
from pathlib import Path


def credential_source(root: Path) -> str:
    if os.environ.get("GRAVITY_AUTH_TOKEN") or os.environ.get("GRAVITY_AUTHORIZATION"):
        return "environment"
    if os.environ.get("GRAVITY_USERNAME") and os.environ.get("GRAVITY_PASSWORD"):
        return "environment"
    try:
        keys = {
            line.split("=", 1)[0].strip()
            for line in (root / ".env.gravity.local").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
    except (OSError, UnicodeError):
        return "missing"
    return (
        "local_account_file"
        if {"GRAVITY_USERNAME", "GRAVITY_PASSWORD"}.issubset(keys)
        else "missing"
    )


__all__ = ["credential_source"]
