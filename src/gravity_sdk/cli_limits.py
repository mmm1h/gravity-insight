"""Small argparse value parsers shared by the Gravity Insight CLI."""

from __future__ import annotations

import argparse


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def concurrency(value: str) -> int:
    parsed = positive_int(value)
    if parsed > 24:
        raise argparse.ArgumentTypeError("concurrency must be between 1 and 24")
    return parsed


def operation_limit(value: str) -> int:
    parsed = positive_int(value)
    if parsed > 20:
        raise argparse.ArgumentTypeError("operation limit must be between 1 and 20")
    return parsed


def agent_limit(value: str) -> int:
    parsed = positive_int(value)
    if parsed > 5:
        raise argparse.ArgumentTypeError("agent limit must be between 1 and 5")
    return parsed


def metadata_limit(value: str) -> int:
    parsed = positive_int(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError("metadata limit must be between 1 and 100")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def validate_date_pair(start: str | None, end: str | None) -> None:
    if bool(start) != bool(end):
        raise ValueError("--start and --end must be supplied together")
