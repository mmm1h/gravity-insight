"""Default-on root CLI policy for offline bundled Skill maintenance."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .skill_hub_contract import SkillHubContractError


AUTO_SKILLS_ENV = "GRAVITY_INSIGHT_AUTO_SKILLS"
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
# Only consumers of installed method discovery/execution declare this capability.
# Explicit Skill maintenance owns its own assembly; raw reads and diagnostics do not.
_METHOD_LIBRARY_COMMANDS = frozenset({
    ("agent",), ("agent-catalog",), ("plan", "run"),
    ("journey", "run"), ("journey", "can-run"), ("journey", "verify"),
    ("skills", "list"), ("skills", "show"), ("skills", "search"),
})
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
    command_args = args[1:] if args[:1] == ["insight"] else args
    return any(
        tuple(command_args[:len(path)]) == path
        for path in _METHOD_LIBRARY_COMMANDS
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
        if (reason == "HUB_SEED_UNAVAILABLE"
                and isinstance(exc.__cause__, FileNotFoundError)
                and _is_editable_checkout()):
            reason = "HUB_SEED_ABSENT_EDITABLE"
            print(
                f"info: {reason}: this editable checkout has no sealed Skill seed; "
                "method availability depends on the last verified local state. "
                "Install a released wheel for bundled methods or explicitly sync "
                "an approved Skill source.", file=output,
            )
            return StartupSkillMaintenance("unavailable", reason_code=reason)
        print(
            "warning: bundled Skill maintenance failed "
            f"({reason}); continuing this command with the last verified state. "
            "Run `gravity skills repair` to retry or set "
            f"{AUTO_SKILLS_ENV}=0 to disable automatic Skill maintenance.",
            file=output,
        )
        return StartupSkillMaintenance("failed", reason_code=reason)


def _is_editable_checkout() -> bool:
    try:
        direct = json.loads(metadata.distribution("gravity-insight").read_text(
            "direct_url.json") or "{}")
        source = urlsplit(direct.get("url", ""))
        return (
            direct.get("dir_info", {}).get("editable") is True
            and source.scheme == "file" and not source.netloc
            and Path(url2pathname(source.path)).resolve() == Path(__file__).resolve().parents[2]
        )
    except (metadata.PackageNotFoundError, OSError, ValueError, TypeError, AttributeError):
        return False


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
