"""CLI registration and dispatch for non-empty discovery."""

from __future__ import annotations

import argparse
from typing import Any, Callable, Mapping


def _positive_bounded(value: str, *, maximum: int, label: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise argparse.ArgumentTypeError(f"{label} must be between 1 and {maximum}")
    return parsed


def _request_budget(value: str) -> int:
    return _positive_bounded(value, maximum=200, label="request budget")


def _candidate_limit(value: str) -> int:
    return _positive_bounded(value, maximum=20, label="candidate limit")


def _interval(value: str) -> int:
    parsed = int(value)
    if parsed < 300:
        raise argparse.ArgumentTypeError("request interval must be at least 300ms")
    return parsed


def register(
    commands: Any,
    add_input: Callable[[argparse.ArgumentParser], None],
) -> None:
    discover = commands.add_parser(
        "discover-nonempty",
        help="Find a non-empty contracted input combination within a strict HTTP budget.",
    )
    discover.add_argument("operation_id")
    add_input(discover)
    discover.add_argument("--request-budget", type=_request_budget, default=12)
    discover.add_argument("--candidate-limit", type=_candidate_limit, default=5)
    discover.add_argument("--interval-ms", type=_interval, default=310)
    discover.add_argument("--refresh-cache", action="store_true")
    discover.add_argument(
        "--apply-draft",
        action="store_true",
        help="Persist value-free schema evidence when a draft yields non-empty data.",
    )
    discover.set_defaults(_gravity_handler=dispatch)


def dispatch(
    args: argparse.Namespace,
    object_input: Callable[[str | None], Mapping[str, Any]],
) -> Any:
    from gravity_insight.nonempty import discover_nonempty

    return discover_nonempty(
        args.operation_id,
        input_overrides=object_input(args.input),
        request_budget=args.request_budget,
        candidate_limit=args.candidate_limit,
        interval_seconds=args.interval_ms / 1000.0,
        refresh_cache=args.refresh_cache,
        apply_draft=args.apply_draft,
    )


def dispatch_or(
    args: argparse.Namespace,
    object_input: Callable[[str | None], Mapping[str, Any]],
    fallback: Callable[[argparse.Namespace], Any],
) -> Any:
    handler = getattr(args, "_gravity_handler", None)
    return handler(args, object_input) if handler is not None else fallback(args)


def runner(
    object_input: Callable[[str | None], Mapping[str, Any]],
    fallback: Callable[[argparse.Namespace], Any],
) -> Callable[[argparse.Namespace], Any]:
    return lambda args: dispatch_or(args, object_input, fallback)


__all__ = ["dispatch", "dispatch_or", "register", "runner"]
