"""Default-on root CLI policy for offline bundled Skill maintenance."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .skill_hub_contract import SkillHubContractError


AUTO_SKILLS_ENV = "GRAVITY_INSIGHT_AUTO_SKILLS"
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_EXPLICIT_MAINTENANCE = frozenset(
    {
        "audit",
        "bootstrap",
        "fetch",
        "host-install-plan",
        "install",
        "lock",
        "repair",
        "resolve",
        "status",
        "sync",
        "update",
        "verify",
    }
)
_INVALID_OPTION = object()


@dataclass(frozen=True)
class StartupSkillMaintenance:
    status: str
    reason_code: str | None = None
    network_called: bool = False


def startup_skill_bootstrap_enabled(
    argv: Sequence[str], *, environ: Mapping[str, str] | None = None
) -> bool:
    env = os.environ if environ is None else environ
    if str(env.get(AUTO_SKILLS_ENV, "")).strip().casefold() in _FALSE_VALUES:
        return False
    args = list(argv)
    if not args or any(item in {"-h", "--help", "--dry-run"} for item in args):
        return False
    if args[:1] == ["doctor"] or args[:2] == ["insight", "doctor"]:
        return False
    command_args = args[1:] if args[:1] == ["insight"] else args
    return not (
        command_args[:1] == ["skills"]
        and (len(command_args) < 2 or command_args[1] in _EXPLICIT_MAINTENANCE)
    )


def maybe_bootstrap_bundled_skills(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    stderr: Any = None,
) -> StartupSkillMaintenance:
    env = os.environ if environ is None else environ
    if not startup_skill_bootstrap_enabled(argv, environ=env):
        return StartupSkillMaintenance("disabled")
    output = sys.stderr if stderr is None else stderr
    try:
        _startup_bootstrap(argv, env)
        return StartupSkillMaintenance("completed")
    except Exception as exc:
        reason = (
            exc.reason_code
            if isinstance(exc, SkillHubContractError)
            else "SKILL_BOOTSTRAP_FAILED"
        )
        print(
            "warning: bundled Skill maintenance failed "
            f"({reason}); continuing this command with the last verified state. "
            "Run `gravity skills repair` to retry or set "
            f"{AUTO_SKILLS_ENV}=0 to disable automatic Skill maintenance.",
            file=output,
        )
        return StartupSkillMaintenance("failed", reason_code=reason)


def _startup_bootstrap(argv: Sequence[str], environ: Mapping[str, str]) -> None:
    from .skill_hub_client import SkillHubClient
    from .workspace import load_workspace

    workspace = load_workspace(environ=environ)
    state_option = _option_value(argv, "--state-root")
    cas_option = _option_value(argv, "--cas-root")
    if state_option is _INVALID_OPTION or cas_option is _INVALID_OPTION:
        return
    state_root = Path(state_option) if state_option else workspace.state_root
    client = SkillHubClient(
        state_root,
        cas_root=Path(cas_option) if cas_option else None,
    )
    client.bootstrap_bundled(
        project_root=workspace.root if workspace.configured else None
    )


def _option_value(argv: Sequence[str], name: str) -> str | object | None:
    values: list[str] = []
    args = list(argv)
    for index, item in enumerate(args):
        if item == name:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                return _INVALID_OPTION
            values.append(args[index + 1])
        elif item.startswith(f"{name}="):
            value = item.partition("=")[2]
            if not value:
                return _INVALID_OPTION
            values.append(value)
    return values[0] if len(values) == 1 else _INVALID_OPTION if values else None


__all__ = [
    "AUTO_SKILLS_ENV",
    "StartupSkillMaintenance",
    "maybe_bootstrap_bundled_skills",
    "startup_skill_bootstrap_enabled",
]
