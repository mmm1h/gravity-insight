"""Offline-only planning for SQL CLI commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from gravity_sdk import json_output
from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY
from gravity_sdk.sql.cli_input import query_requests
from gravity_sdk.sql.products import (
    EvidenceFormatError,
    describe_products,
    dry_run_checks,
    normalize_app_ids,
    normalize_window,
)
from gravity_sdk.sql.query import sql_error_exit_code
from gravity_sdk.workspace import WorkspaceError


SCHEMA_VERSION = "gravity-sql.query-plan.v1"
_QUERY_INPUT_FIELDS = frozenset(
    {"product", "start", "end", "app_id", "app_ids", "request_id"}
)
_CONTRACT_CARD_FIELDS = (
    "kind",
    "datasource",
    "privacy",
    "measurement",
    "output_fields",
    "output_semantics",
    "max_rows",
    "forbidden_claims",
)


def dry_run_override(
    args: argparse.Namespace, configured_products: tuple[str, ...]
) -> int | None:
    """Handle dry-run modes that must differ from normal command dispatch."""

    if args.command == "query":
        if not configured_products:
            return emit_error(
                "No configured SQL product is available for offline validation",
                category="contract",
                code="SQL_DRY_RUN_WORKSPACE_INVALID",
            )
        return run_query_plan(args, configured_products)
    if args.command == "verify" or (
        args.command == "credentials" and args.credential_command != "status"
    ):
        return reject_networked(args)
    return None


def run_query_plan(
    args: argparse.Namespace, configured_products: tuple[str, ...]
) -> int:
    """Validate a product query without credentials, Evidence, or a SQL client."""

    try:
        requests = query_requests(args)
        _validate_concurrency(args.concurrency)
        product_cards = _product_cards()
        plans = [
            _query_plan_item(value, configured_products, product_cards)
            for value in requests
        ]
        # Exercise every configured template and aggregate projection locally. SQL
        # may be rendered in memory, but is never returned by the safe plan.
        dry_run_checks()
    except OSError:
        return emit_error(
            "SQL query input or local state could not be read",
            category="local_io",
            code="SQL_DRY_RUN_LOCAL_IO",
        )
    except (EvidenceFormatError, WorkspaceError, AssertionError):
        return emit_error(
            "SQL product contract failed offline validation",
            category="contract",
            code="SQL_DRY_RUN_CONTRACT_INVALID",
        )
    except (TypeError, ValueError):
        return emit_error(
            "SQL query input is invalid; run `gravity sql products` for the input contract",
            category="input",
            code="SQL_DRY_RUN_INPUT_INVALID",
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "validated",
        "offline": True,
        "network_called": False,
        "requested_count": len(plans),
        "concurrency": args.concurrency,
        "requests": plans,
        "next_action": (
            "Remove --dry-run from the same validated query only when a Gravity "
            "read is intended."
        ),
    }
    print(
        json_output.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _query_plan_item(
    value: Mapping[str, object],
    configured_products: tuple[str, ...],
    product_cards: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    _validate_fields(value)
    product = _product_name(value, configured_products)
    request_id = _request_id(value)
    start_at, end_at = _window(value)
    app_ids = normalize_app_ids(product, _requested_apps(value))
    card = product_cards.get(product)
    if card is None:
        raise EvidenceFormatError("configured SQL product is missing its safe card")
    return {
        "request_id": request_id,
        "product": product,
        "window": {
            "start_inclusive": start_at.isoformat(),
            "end_exclusive": end_at.isoformat(),
        },
        "app_ids": list(app_ids),
        "product_contract": {
            key: card.get(key) for key in _CONTRACT_CARD_FIELDS
        },
    }


def _validate_fields(value: Mapping[str, object]) -> None:
    unknown = sorted(set(value) - _QUERY_INPUT_FIELDS)
    if unknown:
        raise ValueError("unknown SQL product request fields")
    if "app_id" in value and "app_ids" in value:
        raise ValueError("app_id and app_ids cannot be combined")


def _product_name(
    value: Mapping[str, object], configured_products: tuple[str, ...]
) -> str:
    product = value.get("product")
    if not isinstance(product, str) or product not in configured_products:
        raise ValueError("unknown configured SQL product")
    return product


def _request_id(value: Mapping[str, object]) -> str | None:
    request_id = value.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise ValueError("SQL product request_id must be a string")
    return request_id


def _window(value: Mapping[str, object]) -> tuple[Any, Any]:
    start, end = value.get("start"), value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("SQL product request requires string start and end timestamps")
    return normalize_window(start, end)


def _requested_apps(value: Mapping[str, object]) -> list[Any] | None:
    raw_apps = value.get("app_ids", value.get("app_id"))
    if raw_apps is None:
        return None
    if type(raw_apps) is int:
        return [raw_apps]
    if isinstance(raw_apps, Sequence) and not isinstance(
        raw_apps, (str, bytes, bytearray)
    ):
        return list(raw_apps)
    raise ValueError("SQL product app_ids must be a positive integer or array")


def _product_cards() -> dict[str, Mapping[str, object]]:
    return {
        str(item["name"]): item
        for item in describe_products()
        if isinstance(item, Mapping) and item.get("name")
    }


def _validate_concurrency(value: object) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SQL_CONCURRENCY:
        raise ValueError(
            f"SQL product concurrency must be between 1 and {MAX_SQL_CONCURRENCY}"
        )


def emit_error(
    message: str,
    *,
    category: str,
    code: str,
    next_action: str = (
        "Run `gravity sql products`, correct the local request, and retry with "
        "--dry-run."
    ),
) -> int:
    exit_code = sql_error_exit_code(category)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "offline": True,
        "network_called": False,
        "exit_code": exit_code,
        "error": {
            "category": category,
            "code": code,
            "message": message,
            "next_action": next_action,
        },
    }
    print(
        json_output.dumps(payload, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
    )
    return exit_code


def reject_networked(args: argparse.Namespace) -> int:
    command = args.command or "<none>"
    if command == "credentials":
        command = f"credentials {args.credential_command}"
    return emit_error(
        f"--dry-run cannot be combined with `{command}` because it may access external state",
        category="input",
        code="SQL_DRY_RUN_COMMAND_NOT_OFFLINE",
        next_action=(
            "Remove --dry-run and retry only when this external-state operation "
            "is explicitly intended."
        ),
    )


__all__ = ["dry_run_override", "run_query_plan"]
