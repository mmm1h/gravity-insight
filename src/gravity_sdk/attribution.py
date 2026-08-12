"""Stable attribution configuration snapshots for Agent callers."""

from __future__ import annotations

from typing import Any, Callable

from . import runtime
from .domains import (
    ATTRIBUTION_PAGINATED_OPERATIONS,
    ATTRIBUTION_SNAPSHOT_OPERATIONS,
)
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    ordered_results,
    validate_composite_bounds,
)
from .errors import InputValidationError
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


SCHEMA_VERSION = "gravity-insight.attribution-snapshot.v1"


def add_snapshot_command(
    subcommands: Any, concurrency_type: Callable[[str], int]
) -> None:
    snapshot = subcommands.add_parser(
        "snapshot",
        help="Read every stable attribution configuration for one app concurrently.",
    )
    app = snapshot.add_mutually_exclusive_group(required=True)
    app.add_argument("--app", help="Workspace app alias or literal app id.")
    app.add_argument("--app-id", help="Compatibility alias for --app.")
    snapshot.add_argument("--concurrency", type=concurrency_type, default=6)
    snapshot.set_defaults(_gravity_handler=_dispatch_snapshot)


def _dispatch_snapshot(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    selected = args.app if args.app is not None else args.app_id
    return attribution_snapshot(
        runtime.build_client(),
        resolve_workspace_app(workspace, selected),
        concurrency=args.concurrency,
    )


def attribution_snapshot(
    client: Any,
    app_id: str | int,
    *,
    concurrency: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    normalized_app_id = _positive_app_id(app_id)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=len(ATTRIBUTION_SNAPSHOT_OPERATIONS)
    )
    requests = [
        {
            "operation_id": operation_id,
            "request_id": operation_id,
            "inputs": {"app_id": normalized_app_id},
            "read_all": operation_id in ATTRIBUTION_PAGINATED_OPERATIONS,
        }
        for operation_id in ATTRIBUTION_SNAPSHOT_OPERATIONS
    ]
    ordered = ordered_results(
        runtime.call_batch(
            client,
            requests,
            concurrency=concurrency,
            max_pages=pages,
            max_total_items=items,
        ),
        requests,
        component="attribution snapshot",
    )
    enforce_composite_item_budget(ordered, items)
    results = [
        annotate_result(result, source=operation_id, scope="app")
        for operation_id, result in zip(
            ATTRIBUTION_SNAPSHOT_OPERATIONS, ordered, strict=True
        )
    ]
    envelope = composite_envelope(results, schema_version=SCHEMA_VERSION)
    if envelope["total_count"] != len(requests):
        raise RuntimeError("attribution snapshot result count invariant failed")
    return {
        **envelope,
        "app_id": normalized_app_id,
        "operation_count": len(requests),
        "paginated_operation_count": len(ATTRIBUTION_PAGINATED_OPERATIONS),
    }


def _positive_app_id(value: str | int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _app_id_error()
    rendered = str(value).strip()
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise _app_id_error()
    return str(int(rendered))


def _app_id_error() -> InputValidationError:
    return InputValidationError(
        "attribution snapshot app_id must be a positive integer",
        field="app_id",
        next_action="Retry with `--app-id <positive-integer>`.",
    )


__all__ = ["SCHEMA_VERSION", "add_snapshot_command", "attribution_snapshot"]
