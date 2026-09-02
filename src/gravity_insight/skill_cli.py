"""CLI registration for the unified Skill Hub surface."""

from __future__ import annotations

from typing import Any


def add_skill_commands(commands: Any) -> Any:
    from .skill_hub_cli import add_skill_hub_actions

    skills = commands.add_parser(
        "skills", help="Discover, lock, fetch, install, and verify Hub Skills."
    )
    actions = skills.add_subparsers(dest="skills_command", required=True)
    add_skill_hub_actions(actions)
    return skills


__all__ = ["add_skill_commands"]
