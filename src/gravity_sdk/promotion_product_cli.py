"""Narrow CLI router for governed promotion account products."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


PRODUCT_COMMANDS = frozenset({
    "advertiser-profile",
    "bilibili-account-performance",
    "custom-audiences",
})


def add_product_commands(
    subcommands: Any,
    *,
    concurrency_parser: Callable[[str], int],
    positive_int: Callable[[str], int],
    output_file: Callable[[str], Any],
) -> None:
    audiences = subcommands.add_parser(
        "custom-audiences",
        help="Read custom-audience coverage, uploads, sources, and status.",
    )
    audiences.add_argument("--max-pages", type=positive_int, default=1_000)
    audiences.add_argument("--max-items", type=positive_int, default=100_000)

    bilibili_account = subcommands.add_parser(
        "bilibili-account-performance",
        help="Read Bilibili account and product delivery metrics.",
    )
    bilibili_account.add_argument("--start", required=True)
    bilibili_account.add_argument("--end", required=True)
    bilibili_account.add_argument(
        "--concurrency", type=concurrency_parser, default=6,
        help="Bounded page workers; Plan execution fixes this to one.",
    )
    bilibili_account.add_argument("--max-pages", type=positive_int, default=1_000)
    bilibili_account.add_argument("--max-items", type=positive_int, default=100_000)
    bilibili_account.add_argument(
        "--output", type=output_file,
        help="Write the complete JSON result to a local file.",
    )
    bilibili_account.set_defaults(result_output_fail_closed=True)

    advertiser = subcommands.add_parser(
        "advertiser-profile",
        help="Read governed Bytedance advertiser account profiles.",
    )
    advertiser.add_argument("--start", required=True)
    advertiser.add_argument("--end", required=True)
    advertiser.add_argument("--max-pages", type=positive_int, default=1_000)
    advertiser.add_argument("--max-items", type=positive_int, default=100_000)
    advertiser.add_argument(
        "--output", type=output_file,
        help="Write the complete JSON result to a local file.",
    )


def dispatch_product_command(
    args: Any, build_client: Callable[[], Any]
) -> dict[str, Any]:
    if args.promotion_command == "custom-audiences":
        from .custom_audience import custom_audiences

        return custom_audiences(
            build_client(),
            max_pages=args.max_pages,
            max_items=args.max_items,
        )
    if args.promotion_command == "bilibili-account-performance":
        from .bilibili_account_performance import (
            bilibili_account_performance,
            validate_bilibili_account_request,
        )

        validate_bilibili_account_request(
            args.start,
            args.end,
            max_workers=args.concurrency,
            max_pages=args.max_pages,
            max_items=args.max_items,
        )
        return bilibili_account_performance(
            build_client(),
            args.start,
            args.end,
            max_workers=args.concurrency,
            max_pages=args.max_pages,
            max_items=args.max_items,
        )

    from .advertiser_profile import advertiser_profile
    from .composite_batch import validate_composite_bounds
    from .promotion_performance_request import normalize_promotion_window

    normalize_promotion_window(args.start, args.end)
    validate_composite_bounds(args.max_pages, args.max_items, minimum_items=1)
    return advertiser_profile(
        build_client(),
        args.start,
        args.end,
        max_pages=args.max_pages,
        max_items=args.max_items,
    )


__all__ = [
    "PRODUCT_COMMANDS",
    "add_product_commands",
    "dispatch_product_command",
]
