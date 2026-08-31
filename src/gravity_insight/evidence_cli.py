"""CLI registration for maturity and repository evidence commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import PROJECT_ROOT


def _json_flag(parser: Any) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the stable machine-readable JSON envelope",
    )


def add_evidence_commands(commands: Any) -> None:
    maturity = commands.add_parser(
        "maturity", help="Score requirement 2.1 from current machine evidence."
    )
    maturity_actions = maturity.add_subparsers(dest="maturity_command", required=True)
    score = maturity_actions.add_parser("score")
    _json_flag(score)
    score.set_defaults(network_required=False, local_command_handler=_dispatch)

    runtime = commands.add_parser(
        "runtime", help="Inspect deterministic Runtime health."
    )
    runtime_actions = runtime.add_subparsers(dest="runtime_command", required=True)
    health = runtime_actions.add_parser("health")
    _json_flag(health)
    health.set_defaults(network_required=False, local_command_handler=_dispatch)

    docs = commands.add_parser(
        "docs", help="Inspect documentation governance and navigation."
    )
    docs_actions = docs.add_subparsers(dest="docs_command", required=True)
    check = docs_actions.add_parser("check")
    _json_flag(check)
    check.set_defaults(network_required=False, local_command_handler=_dispatch)


def _dispatch(args: Any) -> dict[str, Any]:
    root = Path(PROJECT_ROOT)
    if getattr(args, "maturity_command", None) == "score":
        from .maturity import maturity_score

        return maturity_score(root)
    if getattr(args, "runtime_command", None) == "health":
        from .runtime_health import runtime_health_report

        return runtime_health_report(root)
    from .documentation_status import documentation_report

    return documentation_report(root)


__all__ = ["add_evidence_commands"]
