"""Thin CLI surface for local Built-in Skill packages."""

from __future__ import annotations

from typing import Any


def add_skill_commands(commands: Any) -> Any:
    from .skill_hub_cli import add_hub_show_options, add_skill_hub_actions

    skills = commands.add_parser(
        "skills", help="List, read, or export exact local Built-in Skills."
    )
    actions = skills.add_subparsers(dest="skills_command", required=True)
    listed = actions.add_parser("list")
    listed.set_defaults(network_required=False, _gravity_handler=dispatch)
    show = actions.add_parser("show")
    show.add_argument("skill")
    add_hub_show_options(show)
    show.set_defaults(network_required=False, _gravity_handler=dispatch)
    export = actions.add_parser("export-agent")
    export.add_argument("skill")
    export.add_argument("--output", required=True)
    export.set_defaults(
        network_required=False,
        product_file_output=True,
        _gravity_handler=dispatch,
    )
    add_skill_hub_actions(actions)
    return skills


def dispatch(args: Any, _object_input: Any) -> dict[str, Any]:
    from .skill_package import LocalSkillResolver

    if args.skills_command == "list":
        return LocalSkillResolver().list()
    if args.skills_command == "show":
        if getattr(args, "state_root", None) is not None:
            from .skill_hub_cli import hub_show

            return hub_show(args)
        from .sdk import GravitySDK
        from .workspace import load_workspace

        sdk = GravitySDK.from_env(
            workspace=load_workspace(getattr(args, "workspace", None)), attempts=1
        )
        return LocalSkillResolver(capability_trust=sdk.capability_trust).get(
            args.skill
        )
    return LocalSkillResolver().materialize_agent(args.skill, args.output)


__all__ = ["add_skill_commands", "dispatch"]
