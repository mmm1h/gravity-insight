"""CLI registration for the bounded Dashboard Snapshot composite."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from . import runtime
from .dashboard_snapshot import dashboard_snapshot
from .domains import ANALYSIS_DASHBOARD_OPERATIONS, ANALYSIS_PAGINATED_OPERATIONS
from .errors import InputValidationError
from .pagination_cli import page_options
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


class _DashboardNetworkValue(argparse.Action):
    """Make first-run credential checks follow a complete dashboard command.

    The unified launcher asks the parser whether credentials are needed before
    it invokes the command handler.  Dashboard has both a legacy option form
    and a product subcommand, so a static parser default would prompt before an
    incomplete or mixed command can report its local caller error.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        _refresh_network_requirement(namespace)


class _DashboardSubparsersAction(argparse._SubParsersAction):
    """Recompute the credential predicate after child defaults are merged."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        super().__call__(parser, namespace, values, option_string)
        _refresh_network_requirement(namespace)


class _DashboardSetValue(argparse.Action):
    """Keep repeatable ``--set`` compatible with the local credential gate."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        assignments = list(getattr(namespace, self.dest, None) or ())
        assignments.append(values)
        setattr(namespace, self.dest, assignments)
        _refresh_network_requirement(namespace)


def _refresh_network_requirement(args: Any) -> None:
    if getattr(args, "analysis_dashboard_command", None) == "snapshot":
        ready = (
            getattr(args, "app", None) is not None
            and getattr(args, "ref", None) is not None
            and not _has_legacy_dashboard_arguments(args)
        )
    else:
        ready = (
            getattr(args, "kind", None) is not None
            and (
                getattr(args, "input", None) is not None
                or bool(getattr(args, "input_sets", None))
            )
        )
    setattr(args, "network_required", bool(ready))


def _has_legacy_dashboard_arguments(args: Any) -> bool:
    return any(
        (
            getattr(args, "kind", None) is not None,
            getattr(args, "input", None) is not None,
            bool(getattr(args, "input_sets", None)),
            bool(getattr(args, "all_pages", False)),
            getattr(args, "max_pages", None) is not None,
            getattr(args, "max_items", None) is not None,
            getattr(args, "concurrency", None) is not None,
        )
    )


def add_dashboard_snapshot_command(
    dashboard_parser: Any,
    concurrency_type: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> Any:
    """Attach ``analysis dashboard snapshot`` without replacing legacy reads."""

    commands = dashboard_parser.add_subparsers(
        dest="analysis_dashboard_command",
        action=_DashboardSubparsersAction,
    )
    snapshot = commands.add_parser(
        "snapshot",
        help="Resolve one dashboard and read its governed control-plane context.",
    )
    snapshot.add_argument(
        "--app",
        required=True,
        action=_DashboardNetworkValue,
        help="Workspace App alias or positive id.",
    )
    snapshot.add_argument(
        "--ref",
        required=True,
        action=_DashboardNetworkValue,
        help="Exact dashboard id or exact dashboard name.",
    )
    snapshot.add_argument(
        "--concurrency", dest="snapshot_concurrency", type=concurrency_type, default=5
    )
    snapshot.add_argument(
        "--max-pages", dest="snapshot_max_pages", type=positive_int, default=5
    )
    snapshot.add_argument(
        "--max-items", dest="snapshot_max_items", type=positive_int, default=200
    )
    snapshot.add_argument("--output", help="Write JSON or NDJSON to this local path.")
    snapshot.add_argument(
        "--format",
        choices=("json", "ndjson"),
        default="json",
        help="Output encoding; NDJSON may stream to stdout.",
    )
    snapshot.set_defaults(
        _gravity_handler=dispatch_dashboard_snapshot,
        network_required=False,
    )
    return snapshot


def add_dashboard_commands(
    analysis_commands: Any,
    _add_input: Callable[..., None],
    add_all_pages: Callable[[Any], None],
    concurrency_type: Callable[[str], int],
    positive_int: Callable[[str], int],
) -> Any:
    """Register legacy dashboard reads plus the snapshot product child."""

    parser = analysis_commands.add_parser(
        "dashboard", help="Read Analysis dashboards or one governed snapshot."
    )
    parser.set_defaults(network_required=False)
    parser.add_argument(
        "--kind",
        choices=sorted(ANALYSIS_DASHBOARD_OPERATIONS),
        action=_DashboardNetworkValue,
    )
    parser.add_argument(
        "--input",
        "-i",
        action=_DashboardNetworkValue,
        help="Inline JSON, a JSON file, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--set",
        dest="input_sets",
        action=_DashboardSetValue,
        default=[],
        metavar="PATH=VALUE",
        help="Override an input value by dotted path; JSON values are typed.",
    )
    add_all_pages(parser)
    parser.set_defaults(concurrency=None)
    parser.set_defaults(_gravity_handler=dispatch_dashboard_read)
    add_dashboard_snapshot_command(parser, concurrency_type, positive_int)
    return parser


def dispatch_dashboard_read(args: Any, object_input: Any) -> dict[str, Any]:
    """Keep the legacy ``--kind`` surface compatible beside the product child."""

    if args.kind is None:
        raise InputValidationError(
            "analysis dashboard requires --kind or snapshot", field="kind"
        )
    if args.input is None:
        raise InputValidationError(
            "analysis dashboard read requires --input", field="input"
        )
    operation_id = ANALYSIS_DASHBOARD_OPERATIONS[args.kind]
    read_all = bool(getattr(args, "all_pages", False))
    if read_all and operation_id not in ANALYSIS_PAGINATED_OPERATIONS:
        raise InputValidationError(
            f"--all-pages is not supported for non-paginated operation {operation_id}",
            field="all_pages",
        )
    options = page_options(args, all_pages=True, active=read_all)
    if read_all and options["max_workers"] is None:
        options["max_workers"] = 6
    return runtime.call_read(
        runtime.build_client(),
        operation_id,
        object_input(args.input),
        read_all=read_all,
        **options,
    )


def dispatch_dashboard_snapshot(args: Any, _object_input: Any) -> dict[str, Any]:
    """Bind one immutable workspace, then delegate to the shared composite."""

    if _has_legacy_dashboard_arguments(args):
        raise InputValidationError(
            "dashboard snapshot cannot use legacy dashboard read arguments",
            field="snapshot",
            next_action="Remove --kind, --input, and --all-pages before snapshot.",
        )
    workspace = load_workspace(getattr(args, "workspace", None))
    app_id = resolve_workspace_app(workspace, args.app)
    return dashboard_snapshot(
        runtime.build_client(),
        app_id,
        args.ref,
        max_workers=args.snapshot_concurrency,
        max_pages=args.snapshot_max_pages,
        max_items=args.snapshot_max_items,
    )


__all__ = [
    "add_dashboard_commands",
    "add_dashboard_snapshot_command",
    "dispatch_dashboard_read",
    "dispatch_dashboard_snapshot",
]
