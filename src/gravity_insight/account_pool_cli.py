"""Explicit advanced CLI entry to the same complete-read SDK pool boundary."""

from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from .account_pool import AccountPoolConfig, _account_config_error
from .errors import exit_code_for_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gravity account-pool")
    parser.add_argument("--enable", action="store_true", default=None)
    parser.add_argument("--account-env", action="append", default=None)
    parser.add_argument("--max-accounts", type=int, default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    for name in ("read", "read-all", "run"):
        child = commands.add_parser(name)
        child.add_argument("selector")
        child.add_argument("--input", default="{}")
    for name in ("plan", "sql-products"):
        child = commands.add_parser(name)
        child.add_argument("--input", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = AccountPoolConfig.from_environment()
    if args.enable is not None or args.account_env is not None or args.max_accounts is not None:
        config = AccountPoolConfig(
            enabled=config.enabled if args.enable is None else args.enable,
            env_paths=config.env_paths if args.account_env is None else tuple(args.account_env),
            max_accounts=config.max_accounts if args.max_accounts is None else args.max_accounts,
        )
    from .sdk import connect

    if args.command == "status":
        if not config.enabled:
            result: Any = {"mode": "single", "reason_code": "ACCOUNT_POOL_DISABLED"}
        else:
            result = connect(account_pool=config).account_pool_status
    else:
        if not config.enabled:
            raise _account_config_error("ACCOUNT_POOL_EXPLICIT_ENABLE_REQUIRED", field="account_pool.enabled", next_action="Pass --enable explicitly.")
        try:
            value = json.loads(args.input)
        except ValueError:
            raise _account_config_error("ACCOUNT_POOL_INPUT_INVALID", field="input", next_action="Pass the read input as valid JSON.") from None
        sdk = connect(account_pool=config)
        if args.command in {"read", "read-all", "run"}:
            method = {"read": "read", "read-all": "read_all", "run": "run"}[args.command]
            result = getattr(sdk, method)(args.selector, value)
        elif args.command == "plan":
            result = sdk.execute_plan(value)
        else:
            result = sdk.query_sql_products(value)
    from .cli import _safe_stdout_result

    print(json.dumps(_safe_stdout_result(result), ensure_ascii=False, sort_keys=True))
    return exit_code_for_status(result.get("status", "success"), ok=result.get("ok"))
