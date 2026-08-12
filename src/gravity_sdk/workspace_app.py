"""Safe workspace App binding shared by CLI and SDK product surfaces."""

from __future__ import annotations

from typing import Any

from .errors import InputValidationError


def resolve_workspace_app(workspace: Any, value: str | int | None) -> int:
    try:
        return workspace.resolve_app(value)
    except ValueError:
        raise InputValidationError(
            "app must reference a configured workspace App or positive id",
            field="app",
            next_action="Inspect [apps] in gravity.toml and retry with `--app <name|id>`.",
        ) from None


__all__ = ["resolve_workspace_app"]
