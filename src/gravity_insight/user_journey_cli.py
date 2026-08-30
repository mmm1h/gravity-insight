"""Thin CLI registration and dispatch for the governed user journey."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .user_journey import user_journey
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


def add_user_journey_command(
    analysis_commands: Any,
    concurrency_parser: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> None:
    """Register ``analysis user journey`` without owning the root parser."""

    user = analysis_commands.add_parser(
        "user", help="Read bounded single-user Analysis products."
    )
    commands = user.add_subparsers(dest="analysis_user_command", required=True)
    journey = commands.add_parser(
        "journey",
        help="Read profile, event timeline and postback status concurrently.",
    )
    journey.add_argument("--app", required=True)
    journey.add_argument("--client-id", required=True)
    dates = journey.add_mutually_exclusive_group(required=True)
    dates.add_argument("--date")
    dates.add_argument("--start")
    journey.add_argument("--end")
    journey.add_argument("--page", type=positive_int, default=1)
    journey.add_argument("--page-size", type=positive_int, default=20)
    journey.add_argument("--field", action="append")
    journey.add_argument("--event", action="append")
    journey.add_argument("--concurrency", type=concurrency_parser, default=3)
    journey.add_argument("--max-items", type=positive_int, default=200)
    journey.set_defaults(_gravity_handler=dispatch_user_journey)


def dispatch_user_journey(
    args: argparse.Namespace,
    _object_input: Callable[[str | None], Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve the workspace App once, then delegate the complete product."""

    workspace = load_workspace()
    app_id = resolve_workspace_app(workspace, args.app)
    return user_journey(
        runtime.build_client(),
        app_id,
        args.client_id,
        date_value=args.date,
        start=args.start,
        end=args.end,
        page=args.page,
        page_size=args.page_size,
        fields=_split(args.field),
        events=_split(args.event),
        max_workers=args.concurrency,
        max_items=args.max_items,
    )


def _split(values: list[str] | None) -> tuple[str, ...]:
    return tuple(
        part
        for value in values or []
        for item in value.split(",")
        if (part := item.strip())
    )


__all__ = ["add_user_journey_command", "dispatch_user_journey"]
