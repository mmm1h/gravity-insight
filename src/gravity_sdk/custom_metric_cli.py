"""CLI registration for current confmetric custom-metric CRUD."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import runtime
from .custom_metric_mutation import (
    create_custom_metric,
    custom_metric_mutation_schema,
    delete_custom_metric,
    list_custom_metrics,
    update_custom_metric,
)


def add_custom_metric_commands(commands: Any, positive_int: Callable[[str], int]) -> None:
    custom = commands.add_parser(
        "custom-metrics", help="List or mutate governed custom-metric definitions."
    )
    actions = custom.add_subparsers(dest="custom_metric_command", required=True)
    schema = actions.add_parser("schema", help="Print the offline mutation action contract.")
    schema.set_defaults(network_required=False, _gravity_handler=_schema)
    listing = actions.add_parser("list", help="Read all current turbo confmetric definitions.")
    listing.add_argument("--max-pages", type=positive_int, default=1_000)
    listing.add_argument("--max-items", type=positive_int, default=100_000)
    listing.set_defaults(_gravity_handler=_list)
    create = actions.add_parser("create", help="Preview or create one marked custom metric.")
    _definition(create)
    create.add_argument("--idempotency-key")
    _mode(create)
    create.set_defaults(_gravity_handler=_create)
    update = actions.add_parser("update", help="Preview or update one marker-or-owner metric.")
    update.add_argument("--metric-id", required=True)
    _definition(update)
    _mode(update)
    update.set_defaults(_gravity_handler=_update)
    delete = actions.add_parser("delete", help="Preview or safely delete one custom metric.")
    delete.add_argument("--metric-id", required=True)
    _mode(delete)
    delete.set_defaults(_gravity_handler=_delete)


def _definition(parser: Any) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--display-format", type=int, choices=range(1, 7), default=1)


def _mode(parser: Any) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="custom_metric_dry_run", action="store_true")
    mode.add_argument("--execute", dest="custom_metric_execute", action="store_true")
    parser.set_defaults(network_required=False)


def _schema(_args: Any, _object_input: Any) -> dict[str, Any]:
    return custom_metric_mutation_schema()


def _list(args: Any, _object_input: Any) -> dict[str, Any]:
    return list_custom_metrics(
        runtime.build_client(), max_pages=args.max_pages, max_items=args.max_items
    )


def _create(args: Any, _object_input: Any) -> dict[str, Any]:
    return create_custom_metric(
        runtime.build_client(), name=args.name, formula=args.formula,
        description=args.description, display_format=args.display_format,
        idempotency_key=args.idempotency_key, execute=bool(args.custom_metric_execute),
    )


def _update(args: Any, _object_input: Any) -> dict[str, Any]:
    return update_custom_metric(
        runtime.build_client(), metric_id=args.metric_id, name=args.name,
        formula=args.formula, description=args.description,
        display_format=args.display_format, execute=bool(args.custom_metric_execute),
    )


def _delete(args: Any, _object_input: Any) -> dict[str, Any]:
    return delete_custom_metric(
        runtime.build_client(), metric_id=args.metric_id,
        execute=bool(args.custom_metric_execute),
    )


__all__ = ["add_custom_metric_commands"]
