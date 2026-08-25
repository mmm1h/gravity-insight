"""Thin explicit CLI delegate for isolated SQL Explorer operations."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from . import json_output
from .find_input import load_json_input
from .errors import ErrorCategory, exit_code_for_category
from .result_output import output_file, write_rendered_result
from .sql_explorer_contract import SqlExplorerContractError
from .workspace import WorkspaceError, load_workspace


def add_sql_explorer_commands(commands: Any) -> None:
    explorer = commands.add_parser(
        "explorer",
        help="Run an explicit isolated local SQLite exploratory session.",
    )
    explorer.set_defaults(network_required=False)
    actions = explorer.add_subparsers(dest="explorer_command", required=True)
    for name, help_text in (
        ("inspect", "Validate AST, identity, and budgets without executing rows."),
        ("execute", "Execute one governed exploratory SQLite SELECT."),
    ):
        parser = actions.add_parser(name, help=help_text)
        parser.add_argument(
            "--input",
            "-i",
            required=True,
            help="Inline JSON, a JSON file, or '-' for stdin.",
        )
        parser.set_defaults(network_required=False)
    promote = actions.add_parser(
        "promote",
        help="Atomically install an explicitly reviewed registered SQL product.",
    )
    promote.add_argument(
        "--input",
        "-i",
        required=True,
        help="Inline promotion JSON, a JSON file, or '-' for stdin.",
    )
    promote.add_argument(
        "--output",
        required=True,
        type=output_file,
        help="Atomically write the reviewed promotion artifact.",
    )
    promote.set_defaults(network_required=False, product_file_output=True)


def dispatch_sql_explorer(args: argparse.Namespace) -> int:
    from .sql_explorer import SqlExplorerService

    try:
        payload = load_json_input(args.input, required=True)
        if not isinstance(payload, Mapping):
            raise ValueError("Explorer input must be a JSON object")
        if args.explorer_command == "promote":
            service = SqlExplorerService(load_workspace())
            result = service.promote(payload)
            rendered = json_output.dumps(
                result, ensure_ascii=False, indent=2, sort_keys=True
            ) + "\n"
            receipt = write_rendered_result(args.output, rendered)
            print(json_output.dumps(receipt, ensure_ascii=False, sort_keys=True))
            return 0
        service = SqlExplorerService()
        method = getattr(service, args.explorer_command)
        result = method(payload)
        print(
            json_output.dumps(
                result, ensure_ascii=False, indent=2, sort_keys=True
            )
        )
        return _result_exit_code(result)
    except SqlExplorerContractError as exc:
        return _emit_error(
            exc.code,
            exc.safe_message,
            stage=exc.stage,
            field=exc.field,
        )
    except (OSError, UnicodeError, ValueError, WorkspaceError):
        return _emit_error(
            "SQL_EXPLORER_INPUT_INVALID",
            "Explorer input, workspace, or output path is invalid",
            stage="input",
            field="input",
        )


def _result_exit_code(result: Mapping[str, Any]) -> int:
    if result.get("ok") is True:
        return 0
    error = result.get("error")
    category = error.get("category") if isinstance(error, Mapping) else "policy"
    selected = (
        ErrorCategory.LOCAL
        if category in {"local", "runtime"}
        else ErrorCategory.CALLER
    )
    return exit_code_for_category(selected)


def _emit_error(
    code: str,
    message: str,
    *,
    stage: str,
    field: str | None,
) -> int:
    print(
        json_output.dumps(
            {
                "schema_version": "gravity.sql-explorer-cli-error.v1",
                "ok": False,
                "status": "blocked",
                "error": {
                    "code": code,
                    "stage": stage,
                    "field": field,
                    "message": message,
                    "next_action": "Correct the explicit Explorer input and retry; no fallback is available.",
                },
                "network_called": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return exit_code_for_category(ErrorCategory.CALLER)


__all__ = ["add_sql_explorer_commands", "dispatch_sql_explorer"]
