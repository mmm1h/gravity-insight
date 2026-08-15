"""Explicit-confirmation CLI surface for governed Segment mutations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError
from .segment_mutation import (
    create_segment_from_analysis,
    create_segment_from_history,
    create_segment_from_rule,
    create_segment_from_tmp,
    delete_segment,
    refresh_segment,
    update_segment_metadata,
    update_segment_rule,
)
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


MUTATION_ACTIONS = frozenset(
    {
        "create-from-analysis",
        "create-from-rule",
        "create-from-history",
        "create-from-tmp",
        "update",
        "update-rule",
        "refresh",
        "delete",
    }
)


def add_segment_mutation_commands(commands: Any) -> None:
    analysis = commands.add_parser(
        "create-from-analysis",
        help="Preview or explicitly persist one ungrouped funnel step/loss as a segment.",
    )
    analysis.add_argument("--spec", required=True, help="Compact funnel spec JSON/file/'-'.")
    analysis.add_argument("--app", required=True, help="Workspace App alias or positive id.")
    analysis.add_argument("--name", required=True, help="Segment name (1..20 characters).")
    analysis.add_argument("--step", required=True, type=int, help="Zero-based funnel step.")
    selection = analysis.add_mutually_exclusive_group(required=True)
    selection.add_argument("--loss", dest="segment_is_loss", action="store_true")
    selection.add_argument("--matched", dest="segment_is_loss", action="store_false")
    analysis.add_argument("--remark", default="")
    analysis.add_argument("--idempotency-key")
    _mode(analysis)

    rule = commands.add_parser(
        "create-from-rule", help="Preview or explicitly create one rule-based segment."
    )
    rule.add_argument("--spec", required=True, help="Compact Segment Rule Spec JSON/file/'-'.")
    rule.add_argument("--app", required=True, help="Workspace App alias or positive id.")
    rule.add_argument("--idempotency-key")
    _mode(rule)

    history = commands.add_parser(
        "create-from-history", help="Preview or copy one exact historical segment version."
    )
    history.add_argument("--app", required=True)
    history.add_argument("--source-segment-id", required=True)
    history.add_argument("--version-id", required=True)
    history.add_argument("--name", required=True)
    history.add_argument("--remark", default="")
    history.add_argument("--idempotency-key")
    _mode(history)

    temporary = commands.add_parser(
        "create-from-tmp", help="Preview or persist one exact temporary segment."
    )
    temporary.add_argument("--app", required=True)
    temporary.add_argument("--tmp-segment-id", required=True)
    temporary.add_argument("--name", required=True)
    temporary.add_argument("--remark", default="")
    temporary.add_argument("--idempotency-key")
    _mode(temporary)

    update = commands.add_parser(
        "update", help="Preview or update a segment's display name and remark."
    )
    update.add_argument("--segment-id", required=True)
    update.add_argument("--name", required=True)
    update.add_argument("--remark", default="")
    _mode(update)

    update_rule = commands.add_parser(
        "update-rule", help="Preview or replace one segment's explicit rule definition."
    )
    update_rule.add_argument("--segment-id", required=True)
    update_rule.add_argument("--spec", required=True)
    update_rule.add_argument("--app", required=True)
    _mode(update_rule)

    refresh = commands.add_parser(
        "refresh", help="Preview or trigger one manual segment recalculation."
    )
    refresh.add_argument("--segment-id", required=True)
    _mode(refresh)

    delete = commands.add_parser(
        "delete", help="Preview or delete only a readback-verified SDK-owned segment."
    )
    delete.add_argument("--segment-id", required=True)
    _mode(delete)


def run_segment_mutation_command(
    args: Any,
    build_client: Callable[..., Any],
    parse_object: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    action = str(getattr(args, "segment_action", ""))
    if action not in MUTATION_ACTIONS:
        raise InputValidationError(
            f"actual value: {actual_value(action)}; allowed values: {actual_value(sorted(MUTATION_ACTIONS))}",
            field="segment_action",
        )
    client = build_client()
    execute = bool(getattr(args, "segment_mutation_execute", False))
    if action == "create-from-analysis":
        return create_segment_from_analysis(
            client,
            parse_object(args.spec),
            app=_app(args.app),
            name=args.name,
            step=args.step,
            is_loss=bool(args.segment_is_loss),
            remark=args.remark,
            idempotency_key=args.idempotency_key,
            execute=execute,
        )
    if action == "create-from-rule":
        return create_segment_from_rule(
            client,
            parse_object(args.spec),
            app=_app(args.app),
            idempotency_key=args.idempotency_key,
            execute=execute,
        )
    if action == "create-from-history":
        return create_segment_from_history(
            client,
            app_id=_app(args.app),
            source_segment_id=args.source_segment_id,
            version_id=args.version_id,
            name=args.name,
            remark=args.remark,
            idempotency_key=args.idempotency_key,
            execute=execute,
        )
    if action == "create-from-tmp":
        return create_segment_from_tmp(
            client,
            app_id=_app(args.app),
            tmp_segment_id=args.tmp_segment_id,
            name=args.name,
            remark=args.remark,
            idempotency_key=args.idempotency_key,
            execute=execute,
        )
    if action == "update":
        return update_segment_metadata(
            client,
            args.segment_id,
            name=args.name,
            remark=args.remark,
            execute=execute,
        )
    if action == "update-rule":
        return update_segment_rule(
            client,
            args.segment_id,
            parse_object(args.spec),
            app=_app(args.app),
            execute=execute,
        )
    if action == "refresh":
        return refresh_segment(client, args.segment_id, execute=execute)
    return delete_segment(client, args.segment_id, execute=execute)


def _mode(parser: Any) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        dest="segment_mutation_dry_run",
        action="store_true",
        help="Compile a zero-network preview; this is the safe default workflow stage.",
    )
    mode.add_argument(
        "--execute",
        dest="segment_mutation_execute",
        action="store_true",
        help="Explicitly send one non-retried production write after reviewing dry-run.",
    )
    parser.set_defaults(network_required=False)


def _app(value: Any) -> int:
    return resolve_workspace_app(load_workspace(), value)


__all__ = [
    "MUTATION_ACTIONS",
    "add_segment_mutation_commands",
    "run_segment_mutation_command",
]
