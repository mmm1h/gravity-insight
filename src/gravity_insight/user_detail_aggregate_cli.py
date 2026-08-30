"""CLI registration for governed user-detail aggregation."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from typing import Any

from . import runtime


def add_user_detail_aggregate_command(
    analysis_commands: Any,
    add_input: Callable[..., None],
    concurrency: Callable[[str], int],
) -> None:
    command = analysis_commands.add_parser(
        "user-detail-aggregate",
        help="Reduce bounded paginated user detail to governed aggregate cells.",
    )
    add_input(command)
    command.add_argument("--concurrency", type=concurrency, default=6)
    offline = command.add_mutually_exclusive_group()
    offline.add_argument(
        "--dry-run",
        dest="user_detail_aggregate_dry_run",
        action="store_true",
        help="Validate the closed aggregate request without network access.",
    )
    offline.add_argument(
        "--input-schema",
        dest="user_detail_aggregate_input_schema",
        action="store_true",
        help="Print the closed aggregate input schema without network access.",
    )
    command.set_defaults(_gravity_handler=run_user_detail_aggregate_command)


def run_user_detail_aggregate_command(
    args: Any,
    object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    from .user_detail_aggregate_product import (
        prepare_user_detail_aggregate,
        run_user_detail_aggregate,
        user_detail_aggregate_input_schema,
    )

    if bool(getattr(args, "user_detail_aggregate_input_schema", False)):
        return user_detail_aggregate_input_schema()
    inputs = object_input(args.input)
    preview = prepare_user_detail_aggregate(inputs)
    if bool(getattr(args, "user_detail_aggregate_dry_run", False)):
        return preview
    return run_user_detail_aggregate(
        runtime.build_client(),
        inputs,
        max_workers=getattr(args, "concurrency", 6),
    )


__all__ = [
    "add_user_detail_aggregate_command",
    "run_user_detail_aggregate_command",
]
