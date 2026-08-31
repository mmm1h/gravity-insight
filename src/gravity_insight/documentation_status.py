"""Machine-readable documentation governance report."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from .documentation_gate import documentation_errors, load_json_object
from .paths import PROJECT_ROOT


_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_COMMAND = re.compile(
    r"`((?:gravity|python\s+-m\s+gravity_insight)(?:\s+[^`\r\n]+)?)`"
    r"|^\s*((?:gravity|python\s+-m\s+gravity_insight)\s+[^\r\n]+)$",
    re.MULTILINE,
)

_CLI_PATH_SCRIPT = """
import argparse
import json
from gravity_insight import cli
from gravity_insight.census import cli as census_cli
from gravity_insight.sql import __main__ as sql_cli

def parser_paths(parser, prefix=()):
    paths = set()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, child in action.choices.items():
            selected = (*prefix, name)
            paths.add(selected)
            paths.update(parser_paths(child, selected))
    return paths

insight_paths = parser_paths(cli.build_parser())
paths = set(insight_paths)
paths.add(("insight",))
paths.update({("insight", *path) for path in insight_paths})
paths.add(("census",))
paths.update({("census", *path) for path in parser_paths(census_cli.build_parser())})
paths.add(("sql",))
paths.update({("sql", *path) for path in parser_paths(sql_cli.build_parser())})
print(json.dumps(sorted(paths)))
"""


def _active_sources(root: Path) -> list[Path]:
    archive = (root / "docs/archive").resolve()
    result = [
        path
        for path in sorted((root / "docs").rglob("*.md"))
        if archive not in path.resolve().parents
    ]
    result.extend(
        path for path in (root / "README.md", root / "AGENTS.md") if path.is_file()
    )
    return sorted(set(result))


def _local_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw in _LINK.findall(path.read_text(encoding="utf-8")):
        value = raw.split("#", 1)[0].strip().strip("<>")
        if not value or "://" in value or value.startswith("mailto:"):
            continue
        targets.append((path.parent / value).resolve())
    return targets


def _broken_links(root: Path, sources: Iterable[Path]) -> list[str]:
    old_architecture = (root / "specs/agent-runtime/architecture-source.md").resolve()
    errors: list[str] = []
    for source in sources:
        for target in _local_targets(source):
            if source == root / "README.md" and target == old_architecture:
                continue
            if not target.exists():
                errors.append(
                    f"{source.relative_to(root).as_posix()} -> {target.as_posix()}"
                )
    return errors


def _reachable(start: Path, allowed: set[Path]) -> set[Path]:
    reached: set[Path] = set()
    queue: deque[Path] = deque([start.resolve()])
    while queue:
        current = queue.popleft()
        if current in reached or current not in allowed or not current.is_file():
            continue
        reached.add(current)
        queue.extend(target for target in _local_targets(current) if target in allowed)
    return reached


def _orphans(root: Path) -> list[str]:
    archive = (root / "docs/archive").resolve()
    allowed = {
        path.resolve()
        for path in (root / "docs").rglob("*.md")
        if archive not in path.resolve().parents
    }
    reached = _reachable(root / "docs/index.md", allowed)
    return sorted(path.relative_to(root).as_posix() for path in allowed - reached)


def _known_commands() -> set[tuple[str, ...]]:
    completed = subprocess.run(
        (sys.executable, "-c", _CLI_PATH_SCRIPT),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(f"CLI parser inventory exit={completed.returncode}")
    value = json.loads(completed.stdout)
    if not isinstance(value, list):
        raise ValueError("CLI parser inventory must be a list")
    return {tuple(str(part) for part in item) for item in value}


def _reference_tokens(reference: str) -> list[str]:
    try:
        tokens = shlex.split(reference, posix=True)
    except ValueError:
        return []
    if tokens[:3] == ["python", "-m", "gravity_insight"]:
        return tokens[3:]
    if tokens[:1] == ["gravity"]:
        return tokens[1:]
    return []


def _stale_reference(reference: str, paths: set[tuple[str, ...]]) -> bool:
    tokens = _reference_tokens(reference)
    while tokens[:1] == ["--workspace"] and len(tokens) >= 2:
        tokens = tokens[2:]
    if (
        not tokens
        or tokens[0] == "="
        or tokens[0].startswith(("-", "<", "$", "{"))
    ):
        return False
    prefix: tuple[str, ...] = ()
    for token in tokens:
        if (
            token == "..."
            or "|" in token
            or token.startswith(("-", "<", "$", "{", "@"))
        ):
            break
        children = {path[len(prefix)] for path in paths if len(path) > len(prefix) and path[: len(prefix)] == prefix}
        if not children:
            break
        if token not in children:
            return True
        prefix = (*prefix, token)
    return not prefix


def _stale_commands(root: Path, sources: Iterable[Path]) -> list[str]:
    try:
        paths = _known_commands()
    except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as exc:
        return [f"CLI parser inventory unavailable: {exc}"]
    errors: list[str] = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for match in _COMMAND.finditer(text):
            reference = next(value for value in match.groups() if value is not None).strip()
            if _stale_reference(reference, paths):
                line = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{source.relative_to(root).as_posix()}:{line}: {reference}"
                )
    return errors


def _navigation_errors(root: Path) -> list[str]:
    required = (
        root / "docs/index.md",
        root / "docs/maintainers/index.md",
        root / "docs/agent-skills/index.md",
        root / "docs/archive/index.md",
    )
    errors = [
        f"missing navigation owner {path.relative_to(root).as_posix()}"
        for path in required
        if not path.is_file()
    ]
    if errors:
        return errors
    root_targets = set(_local_targets(root / "docs/index.md"))
    for path in required[1:3]:
        if path.resolve() not in root_targets:
            errors.append(
                f"docs/index.md does not directly link {path.relative_to(root).as_posix()}"
            )
    return errors


def _result(check_id: str, source: str, errors: list[str]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if not errors else "fail",
        "source": source,
        "error_count": len(errors),
        "errors": errors,
    }


def _existing_governance_errors(root: Path) -> list[str]:
    duplicated_prefixes = (
        "broken local link:",
        "docs check ",
        "runtime health ",
    )
    return [
        error
        for error in documentation_errors(root)
        if not error.startswith(duplicated_prefixes)
    ]


def supplemental_documentation_errors(root: Path) -> list[str]:
    sources = _active_sources(root)
    checks = (
        ("broken_links", _broken_links(root, sources)),
        ("orphan_documents", _orphans(root)),
        ("stale_commands", _stale_commands(root, sources)),
        ("navigation_consistency", _navigation_errors(root)),
    )
    return [
        f"docs check {check_id}: {error}"
        for check_id, errors in checks
        for error in errors
    ]


def integrated_documentation_errors(root: Path) -> list[str]:
    errors = documentation_errors(root)
    if (root / ".git").exists():
        errors.extend(supplemental_documentation_errors(root))
    return errors


def documentation_report(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    sources = _active_sources(root)
    checks = [
        _result(
            "existing_governance",
            "gravity_insight.documentation_gate.documentation_errors",
            _existing_governance_errors(root),
        ),
        _result("broken_links", "README.md + docs/**/*.md", _broken_links(root, sources)),
        _result("orphan_documents", "docs/index.md navigation graph", _orphans(root)),
        _result("stale_commands", "current CLI parser trees", _stale_commands(root, sources)),
        _result("navigation_consistency", "documentation index owners", _navigation_errors(root)),
    ]
    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "schema_version": "gravity.docs-check.v1",
        "status": "pass" if not failed else "fail",
        "ok": not failed,
        "exit_code": 0 if not failed else 1,
        "summary": {
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "total": len(checks),
            "active_documents": len(sources),
        },
        "checks": checks,
        "network_called": False,
    }


__all__ = [
    "documentation_report",
    "integrated_documentation_errors",
    "load_json_object",
    "supplemental_documentation_errors",
]
