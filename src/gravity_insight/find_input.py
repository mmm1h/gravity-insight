"""Shared agent-friendly CLI input parsing and precedence handling."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .errors import InputValidationError, LocalIOError
from .actionable_error_values import actual_value


_JSON_INPUT_NEXT_ACTION = (
    "Run `gravity --help`, then retry the same command with inline JSON, "
    "an existing JSON file, or '-' for stdin."
)


def load_json_input(source: Any, *, required: bool = False) -> Any:
    if source is None:
        if required:
            raise InputValidationError(
                "--input is required (use inline JSON, a JSON file, or '-' for stdin)",
                field="input",
                next_action=_JSON_INPUT_NEXT_ACTION,
            )
        return {}
    if not isinstance(source, str):
        return source
    if source == "-":
        raw = _read_stdin()
    elif source.lstrip().startswith(("{", "[")):
        raw = source
    elif _looks_like_path(source):
        raw = _read_json_file(source)
    else:
        try:
            return json.loads(source)
        except json.JSONDecodeError as exc:
            raise InputValidationError(
                f"actual value: {actual_value(source)}; allowed values: inline JSON, "
                "an existing JSON file path, or '-' for stdin",
                field="input",
                next_action=_JSON_INPUT_NEXT_ACTION,
            ) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputValidationError(
            "input JSON is malformed; allowed value: valid JSON content",
            field="input",
            next_action=_JSON_INPUT_NEXT_ACTION,
        ) from exc


def _looks_like_path(source: str) -> bool:
    candidate = Path(source)
    if candidate.exists():
        return True
    return bool(candidate.drive) or candidate.suffix.casefold() == ".json" or (
        source.startswith((".", "~", "/", "\\"))
        or "/" in source
        or "\\" in source
    )


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except UnicodeError as exc:
        raise LocalIOError(
            "structured input source is not readable UTF-8 text", field="input"
        ) from exc


def _read_json_file(source: str) -> str:
    try:
        return Path(source).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InputValidationError(
            f"actual value: {actual_value(source)}; allowed value: an existing JSON file",
            field="input",
            next_action=_JSON_INPUT_NEXT_ACTION,
        ) from exc
    except UnicodeError as exc:
        raise LocalIOError(
            "structured input file is not readable UTF-8 text", field="input"
        ) from exc


def object_input(source: Any) -> dict[str, Any]:
    value = load_json_input(source)
    if not isinstance(value, Mapping):
        raise ValueError("operation input must be a JSON object")
    return dict(value)


def add_input(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument(
        "--input",
        "-i",
        required=required,
        help="Inline JSON, a JSON file, or '-' to read JSON from stdin.",
    )
    parser.add_argument(
        "--set",
        dest="input_sets",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="Override an input value by dotted path; JSON values are typed.",
    )


def normalize_input_arguments(args: argparse.Namespace) -> None:
    from .relative_dates import apply_relative_dates

    apply_relative_dates(args)
    assignments = getattr(args, "input_sets", None)
    if not hasattr(args, "input") or not assignments:
        return
    value = object_input(args.input)
    for assignment in assignments:
        set_input_path(value, assignment)
    args.input = value


def set_input_path(target: dict[str, Any], assignment: str) -> None:
    if "=" not in assignment:
        raise InputValidationError(f"actual value: {actual_value(assignment)}; " + ("--set must use PATH=VALUE"), field="set")
    path, raw_value = assignment.split("=", 1)
    parts = path.split(".")
    if not path or any(not part for part in parts):
        raise InputValidationError(
            f"actual value: {actual_value(path)}; " + ("--set path must contain non-empty dot-separated names"), field="set"
        )
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    cursor = target
    for part in parts[:-1]:
        child = cursor.get(part)
        if child is None:
            child = {}
            cursor[part] = child
        if not isinstance(child, dict):
            raise InputValidationError(
                f"--set path crosses non-object field: {part}", field="set", next_action="Replace the --set path so every prefix is an object."
            )
        cursor = child
    cursor[parts[-1]] = value


def without_filter(values: Any, field: str, enabled: bool = True) -> list[Any]:
    items = list(values)
    return [item for item in items if item.get("field") != field] if enabled else items


def date_range_input(operation_id: str, start: str | None, end: str | None) -> list[Any] | None:
    if not start or not end:
        return None
    if operation_id.startswith("analysis."):
        return [{"start_date": start, "end_date": end}]
    return [start, end]


__all__ = ["add_input", "date_range_input", "load_json_input", "normalize_input_arguments", "object_input", "without_filter"]
