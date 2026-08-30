"""Local CLI family for versioned HTTP receipt queries."""

from __future__ import annotations

from argparse import Namespace
from typing import Any, Callable, Mapping

from .receipt_query import (
    DEFAULT_PAGE_SIZE,
    MAX_EXPORT_ITEMS,
    export_http_receipts,
    get_http_receipt,
    list_http_receipts,
)
from .result_audit import STORED, WRITE_FAILED


def add_receipt_commands(commands: Any) -> None:
    receipts = commands.add_parser(
        "receipts", help="Query value-free HTTP receipts without exposing storage layout."
    )
    actions = receipts.add_subparsers(dest="receipt_command", required=True)
    listing = actions.add_parser("list", help="List one stable newest-first page.")
    listing.add_argument("--limit", type=int, default=DEFAULT_PAGE_SIZE)
    listing.add_argument("--cursor")
    listing.add_argument("--operation-id")
    listing.add_argument("--output")
    listing.set_defaults(network_required=False, _gravity_handler=dispatch)

    get = actions.add_parser("get", help="Resolve one opaque receipt reference.")
    get.add_argument("receipt_id")
    get.add_argument("--storage-status", choices=(STORED, WRITE_FAILED))
    get.add_argument("--output")
    get.set_defaults(network_required=False, _gravity_handler=dispatch)

    export = actions.add_parser("export", help="Export one bounded receipt snapshot.")
    export.add_argument("--output", dest="receipt_destination", required=True)
    export.add_argument("--max-items", type=int, default=MAX_EXPORT_ITEMS)
    export.add_argument("--operation-id")
    export.set_defaults(network_required=False, _gravity_handler=dispatch)


def dispatch(
    args: Namespace,
    _object_input: Callable[[str | None], Mapping[str, Any]],
) -> dict[str, Any]:
    from .paths import STATE_ROOT
    from .runtime_scope import principal_state_root, runtime_scope_key

    state_root = principal_state_root(
        STATE_ROOT,
        runtime_scope_key(workspace_root=STATE_ROOT),
    )

    if args.receipt_command == "list":
        return list_http_receipts(
            state_root,
            limit=args.limit,
            cursor=args.cursor,
            operation_id=args.operation_id,
        )
    if args.receipt_command == "get":
        reference: str | dict[str, str] = args.receipt_id
        if args.storage_status is not None:
            reference = {
                "receipt_id": args.receipt_id,
                "storage_status": args.storage_status,
            }
        return get_http_receipt(state_root, reference)
    return export_http_receipts(
        state_root,
        args.receipt_destination,
        max_items=args.max_items,
        operation_id=args.operation_id,
    )


__all__ = ["add_receipt_commands", "dispatch"]
