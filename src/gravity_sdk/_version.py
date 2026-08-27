"""Resolve the Runtime version from the distribution or its source project."""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path


def _resolve_version() -> str:
    try:
        return metadata.version("gravity-sdk")
    except metadata.PackageNotFoundError:
        project_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        version = project.get("version")
        if not isinstance(version, str) or not version.strip():
            raise RuntimeError(f"missing project.version in {project_path}")
        return version.strip()


__version__ = _resolve_version()


__all__ = ["__version__"]
