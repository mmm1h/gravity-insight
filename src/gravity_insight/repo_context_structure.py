"""Deterministic bounded structure extraction for Repo Context discovery."""

from __future__ import annotations

import ast
import json
import re
import tomllib
from typing import Any, Mapping


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_FENCE = re.compile(r"^```([A-Za-z0-9_.+-]*)")


def extract_structure(suffix: str, content: str) -> dict[str, Any]:
    if suffix == ".md":
        return _markdown_structure(content)
    if suffix == ".py":
        return _python_structure(content)
    value = json.loads(content) if suffix == ".json" else tomllib.loads(content)
    return {"top_level_keys": sorted(value)[:512] if isinstance(value, Mapping) else []}


def _markdown_structure(content: str) -> dict[str, Any]:
    headings: list[dict[str, Any]] = []
    links: list[str] = []
    fences: list[dict[str, Any]] = []
    for number, line in enumerate(content.splitlines(), 1):
        heading = _HEADING.match(line)
        if heading:
            headings.append(
                {"line": number, "level": len(heading.group(1)), "text": heading.group(2)}
            )
        links.extend(_LINK.findall(line))
        fence = _FENCE.match(line)
        if fence:
            fences.append({"line": number, "language": fence.group(1) or None})
    return {
        "headings": headings[:256],
        "links": sorted(set(links))[:256],
        "code_fences": fences[:256],
    }


def _python_structure(content: str) -> dict[str, Any]:
    tree = ast.parse(content)
    symbols = [
        {"line": node.lineno, "kind": type(node).__name__, "name": node.name}
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.name.startswith("_")
    ]
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return {"symbols": symbols[:512], "imports": sorted(imports)[:256]}


__all__ = ["extract_structure"]
