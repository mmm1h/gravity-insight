"""CLI registration for the guided first-event-analysis bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import json_output
from .metadata_onboarding import app_sync_pages
from .result_output import output_file, write_rendered_result


def add_analysis_bootstrap_command(
    analysis_commands: Any, concurrency_type: Any
) -> Any:
    parser = analysis_commands.add_parser(
        "bootstrap",
        help="Synchronize one explicit App and emit a reviewable first-event Plan.",
    )
    parser.add_argument("--app", help="positive App id explicitly selected by the caller")
    parser.add_argument("--start", help="inclusive ISO start date")
    parser.add_argument("--end", help="inclusive ISO end date")
    parser.add_argument("--target", help="exact physical event name")
    parser.add_argument(
        "--database", type=Path, default=None,
        help="override the private metadata catalog path",
    )
    parser.add_argument(
        "--max-pages", type=app_sync_pages, default=1,
        help="fixed cold-start metadata page cap (must remain 1)",
    )
    parser.add_argument("--concurrency", type=concurrency_type, default=8)
    parser.add_argument(
        "--plan-output", type=output_file,
        help="atomically write only the reviewable gravity.plan.v1 document",
    )
    parser.set_defaults(_gravity_handler=dispatch_analysis_bootstrap)
    return parser


def dispatch_analysis_bootstrap(args: Any, _object_input: Any) -> dict[str, Any]:
    from .sdk import GravitySDK
    from .workspace import load_workspace

    workspace = load_workspace()
    result = GravitySDK.from_env(
        workspace=workspace, attempts=1
    ).bootstrap_event_analysis(
        app=args.app,
        start=args.start,
        end=args.end,
        target=args.target,
        database=args.database,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
    )
    if args.plan_output:
        rendered = json_output.dumps(
            result["plan"], ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        receipt = write_rendered_result(args.plan_output, rendered)
        result["plan_output"] = receipt
        result["next"]["argv"] = [
            "gravity", "plan", "run", "--input", receipt["output"]
        ]
    return result


__all__ = ["add_analysis_bootstrap_command", "dispatch_analysis_bootstrap"]
