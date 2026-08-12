"""JSON/file/stdin input normalization for the SQL query command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path


def query_requests(args: argparse.Namespace) -> list[Mapping[str, object]]:
    overrides = _overrides(args)
    if args.input is None:
        if not overrides:
            raise ValueError(
                "query requires <product> with --start/--end, or --input JSON"
            )
        return [overrides]
    values, is_batch = _payload_requests(_read_json_input(args.input))
    _validate_values(values)
    return _merge_overrides(values, is_batch, overrides)


def _overrides(args: argparse.Namespace) -> dict[str, object]:
    values = {
        "product": args.product,
        "start": args.start,
        "end": args.end,
        "app_ids": args.app_id,
    }
    return {key: value for key, value in values.items() if value is not None}


def _read_json_input(source: str) -> object:
    if source == "-":
        text = sys.stdin.read()
    elif source.lstrip().startswith(("{", "[")):
        text = source
    else:
        text = Path(source).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid SQL query JSON at line {exc.lineno}, column {exc.colno}"
        ) from None


def _payload_requests(payload: object) -> tuple[list[object], bool]:
    if isinstance(payload, Mapping) and "requests" in payload:
        unknown = sorted(set(payload) - {"requests"})
        if unknown:
            raise ValueError("unknown SQL query wrapper fields: " + ", ".join(unknown))
        values = payload["requests"]
        if not isinstance(values, list):
            raise ValueError("SQL query requests wrapper requires an array")
        return values, True
    if isinstance(payload, list):
        return payload, True
    return [payload], False


def _validate_values(values: list[object]) -> None:
    if not values:
        raise ValueError("SQL query input must contain at least one request")
    if not all(isinstance(value, Mapping) for value in values):
        raise ValueError("each SQL query request must be an object")


def _merge_overrides(
    values: list[object],
    is_batch: bool,
    overrides: dict[str, object],
) -> list[Mapping[str, object]]:
    if is_batch and overrides:
        raise ValueError(
            "positional product, --start, --end, and --app-id cannot override batch input"
        )
    requests = [dict(value) for value in values if isinstance(value, Mapping)]
    if not is_batch and overrides:
        requests[0].update(overrides)
    return requests
