"""Inventory explicit caller-recoverable error sites without sampling output."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any


CALLER_ERROR_TYPES = {
    "InputValidationError",
    "ParentRequiredError",
    "PlanRecipeError",
    "PlanValidationError",
    "SemanticRejectedError",
    "SqlValidationError",
    "UnknownOperationError",
}
_ACTUAL_MARKERS = ("actual value", "observed value", "actual_value(")
_REMEDY_MARKERS = (
    "allowed",
    "must ",
    "one of",
    "requires",
    "retry",
    "replace",
    "remove",
    "run `gravity",
    "through",
)


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _annotation_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return _name(node)


def _helper_signatures(trees: dict[Path, ast.Module]) -> dict[str, tuple[str, ...]]:
    helpers: dict[str, tuple[str, ...]] = {}
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _annotation_name(node.returns) not in CALLER_ERROR_TYPES:
                continue
            helpers[node.name] = tuple(argument.arg for argument in node.args.args)
    return helpers


def _call_arguments(call: ast.Call, names: tuple[str, ...]) -> dict[str, ast.AST]:
    result = {name: value for name, value in zip(names, call.args)}
    result.update({item.arg: item.value for item in call.keywords if item.arg})
    return result


def _source(node: ast.AST | None) -> str:
    return ast.unparse(node) if node is not None else ""


def inventory(root: Path) -> list[dict[str, Any]]:
    """Return every explicit caller-error raise site under ``root``."""

    paths = sorted(root.rglob("*.py"))
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in paths}
    helpers = _helper_signatures(trees)
    rows: list[dict[str, Any]] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            call = node.exc
            constructor = _name(call.func)
            if constructor in CALLER_ERROR_TYPES:
                arguments = _call_arguments(
                    call, ("message", "field", "next_action")
                )
            elif constructor in helpers:
                arguments = _call_arguments(call, helpers[constructor])
            else:
                continue
            rendered = _source(call).casefold()
            field_source = _source(arguments.get("field"))
            has_path = bool(field_source)
            has_actual = any(marker in rendered for marker in _ACTUAL_MARKERS)
            has_remedy = "next_action" in arguments or any(
                marker in rendered for marker in _REMEDY_MARKERS
            )
            grade = "A" if has_path and has_actual and has_remedy else (
                "B" if has_path and has_remedy else "C"
            )
            rows.append(
                {
                    "source": path.as_posix(),
                    "line": node.lineno,
                    "constructor": constructor,
                    "path_expression": field_source or None,
                    "has_actual_value": has_actual,
                    "has_alternative_or_discovery": has_remedy,
                    "grade": grade,
                    "expression": _source(call),
                }
            )
    rows.sort(key=lambda item: (item["source"], item["line"], item["constructor"]))
    assert len(rows) == sum(Counter(item["grade"] for item in rows).values())
    assert len({(item["source"], item["line"]) for item in rows}) == len(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("src/gravity_sdk"))
    parser.add_argument("--json", action="store_true", help="Print the complete inventory.")
    args = parser.parse_args()
    rows = inventory(args.root)
    counts = Counter(item["grade"] for item in rows)
    payload = {
        "scope": "explicit caller-recoverable raise sites",
        "total": len(rows),
        "grades": {grade: counts.get(grade, 0) for grade in "ABC"},
    }
    if args.json:
        payload["items"] = rows
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
