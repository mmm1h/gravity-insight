"""CLI registration for report reads and marker-governed writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from . import runtime
from .report_mutation import (
    create_report, create_subscription, delete_report, delete_subscription,
)
from .report_products import report_directory, report_subscriptions


def add_report_commands(
    commands: Any,
    positive_int: Callable[[str], int],
    concurrency: Callable[[str], int],
) -> None:
    directory = commands.add_parser(
        "directory", help="Read owned reports and each report definition."
    )
    _bounds(directory, positive_int, concurrency, workers=True)
    directory.set_defaults(_gravity_handler=_dispatch_directory)

    subscriptions = commands.add_parser(
        "subscriptions", help="Read the complete report subscription list."
    )
    _bounds(subscriptions, positive_int, concurrency, workers=False)
    subscriptions.set_defaults(_gravity_handler=_dispatch_subscriptions)

    create = commands.add_parser(
        "create", help="Preview or create one marker-owned test report."
    )
    create.add_argument("--app-id", required=True, type=positive_int)
    create.add_argument("--name", required=True)
    create.add_argument("--config", required=True, help="Report config JSON/file/'-'.")
    create.add_argument("--subject", default="measurement_report")
    create.add_argument("--remark", default="SDK production-contract test")
    create.add_argument("--idempotency-key")
    _mode(create)
    create.set_defaults(_gravity_handler=_dispatch_create)

    delete = commands.add_parser(
        "delete", help="Preview or delete one readback-verified marked report."
    )
    delete.add_argument("--report-id", required=True, type=positive_int)
    _mode(delete)
    delete.set_defaults(_gravity_handler=_dispatch_delete)

    subscribe = commands.add_parser(
        "subscribe", help="Preview or create one disabled, recipient-free test subscription."
    )
    subscribe.add_argument("--report-id", required=True, type=positive_int)
    subscribe.add_argument("--report-name", required=True)
    subscribe.add_argument("--start", required=True)
    subscribe.add_argument("--end", required=True)
    subscribe.add_argument(
        "--column", action="append", default=[],
        help="Exact selected report column; repeat for each column.",
    )
    subscribe.add_argument("--idempotency-key")
    _mode(subscribe)
    subscribe.set_defaults(_gravity_handler=_dispatch_subscribe)

    unsubscribe = commands.add_parser(
        "unsubscribe", help="Preview or delete one readback-verified marked subscription."
    )
    unsubscribe.add_argument("--subscription-id", required=True, type=positive_int)
    _mode(unsubscribe)
    unsubscribe.set_defaults(_gravity_handler=_dispatch_unsubscribe)


def _dispatch_directory(args: Any, _object_input: Any) -> dict[str, Any]:
    return report_directory(
        runtime.build_client(), max_pages=args.max_pages,
        max_items=args.max_items, max_workers=args.concurrency,
    )


def _dispatch_subscriptions(args: Any, _object_input: Any) -> dict[str, Any]:
    return report_subscriptions(
        runtime.build_client(), max_pages=args.max_pages, max_items=args.max_items,
    )


def _dispatch_create(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    return create_report(
        runtime.build_client(), app_id=args.app_id, name=args.name,
        config=object_input(args.config), subject=args.subject, remark=args.remark,
        idempotency_key=args.idempotency_key, execute=bool(args.report_execute),
    )


def _dispatch_delete(args: Any, _object_input: Any) -> dict[str, Any]:
    return delete_report(
        runtime.build_client(), args.report_id, execute=bool(args.report_execute)
    )


def _dispatch_subscribe(args: Any, _object_input: Any) -> dict[str, Any]:
    return create_subscription(
        runtime.build_client(), report_id=args.report_id, report_name=args.report_name,
        subscribe_time=[args.start, args.end], selected_columns=args.column,
        idempotency_key=args.idempotency_key, execute=bool(args.report_execute),
    )


def _dispatch_unsubscribe(args: Any, _object_input: Any) -> dict[str, Any]:
    return delete_subscription(
        runtime.build_client(), args.subscription_id,
        execute=bool(args.report_execute),
    )


def _bounds(
    parser: Any,
    positive_int: Callable[[str], int],
    concurrency: Callable[[str], int],
    *,
    workers: bool,
) -> None:
    parser.add_argument("--max-pages", type=positive_int, default=1_000)
    parser.add_argument("--max-items", type=positive_int, default=100_000)
    if workers:
        parser.add_argument("--concurrency", type=concurrency, default=6)


def _mode(parser: Any) -> None:
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", dest="report_dry_run", action="store_true")
    mode.add_argument("--execute", dest="report_execute", action="store_true")
    parser.set_defaults(network_required=False)


__all__ = ["add_report_commands"]
