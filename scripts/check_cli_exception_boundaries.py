"""Reject CLI handlers that flatten caught exceptions into plain text."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = ROOT / "scripts" / "cli_exception_boundary_allowlist.json"
SCHEMA_VERSION = "gravity.cli-exception-boundary-allowlist.v1"
_ALLOWLIST_FIELDS = {
    "path",
    "line",
    "detector",
    "handler_sha256",
    "reason",
    "review_expires",
}
_CLI_FILENAMES = frozenset({"__main__.py", "cli.py", "cli_stdio.py"})
_PLAIN_STREAM_PATHS = frozenset(
    {
        "sys.stdout.write",
        "sys.stderr.write",
        "sys.stdout.buffer.write",
        "sys.stderr.buffer.write",
    }
)
_STRUCTURED_SERIALIZERS = frozenset({"json.dumps", "json_bytes", "json_output.dumps"})


class CliBoundaryGateError(ValueError):
    """The gate configuration or scanned source is invalid."""


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    detector: str
    handler_sha256: str

    @property
    def allowlist_key(self) -> tuple[str, int, str, str]:
        return self.path, self.line, self.detector, self.handler_sha256


class _HandlerNodes(ast.NodeVisitor):
    """Collect nodes in one handler without crossing a nested definition."""

    def __init__(self) -> None:
        self.nodes: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes.append(node)
        super().generic_visit(node)

    def _skip_definition(self, node: ast.AST) -> None:
        self.nodes.append(node)

    visit_AsyncFunctionDef = _skip_definition
    visit_ClassDef = _skip_definition
    visit_FunctionDef = _skip_definition
    visit_Lambda = _skip_definition


def _name_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name_path(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _names(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return {name for item in node.elts for name in _target_names(item)}
    return set()


def _plain_exception_text(node: ast.AST, tainted: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.JoinedStr):
        return bool(_names(node) & tainted)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return bool(_names(node) & tainted)
    if isinstance(node, ast.Call):
        name = _name_path(node.func)
        if name in {"str", "repr", "ascii"}:
            return any(bool(_names(value) & tainted) for value in node.args)
        if name.endswith(".format"):
            values = [*node.args, *(item.value for item in node.keywords)]
            return any(bool(_names(value) & tainted) for value in values)
        if name in _STRUCTURED_SERIALIZERS:
            values = [*node.args, *(item.value for item in node.keywords)]
            return any(_plain_exception_text(value, tainted) for value in values)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return any(_plain_exception_text(item, tainted) for item in node.elts)
    if isinstance(node, ast.Dict):
        values = [item for item in [*node.keys, *node.values] if item is not None]
        return any(_plain_exception_text(item, tainted) for item in values)
    return False


def _plain_sink(call: ast.Call) -> bool:
    name = _name_path(call.func)
    return name == "print" or name in _PLAIN_STREAM_PATHS


def _structured_serialization(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Call)
        and _name_path(node.func) in _STRUCTURED_SERIALIZERS
    )


def _handler_hash(handler: ast.ExceptHandler) -> str:
    normalized = ast.dump(handler, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _handler_findings(path: str, handler: ast.ExceptHandler) -> list[Finding]:
    collector = _HandlerNodes()
    for statement in handler.body:
        collector.visit(statement)
    tainted = {handler.name} if handler.name else set()
    bindings: list[ast.AST] = []
    changed = True
    while changed:
        changed = False
        for node in collector.nodes:
            targets: set[str] = set()
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets = {name for target in node.targets for name in _target_names(target)}
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = _target_names(node.target)
                value = node.value
            elif isinstance(node, ast.NamedExpr):
                targets = _target_names(node.target)
                value = node.value
            if value is not None and targets and _plain_exception_text(value, tainted):
                bindings.append(node)
                additions = targets - tainted
                tainted.update(additions)
                changed = changed or bool(additions)
    detectors: set[str] = set()
    if bindings:
        detectors.add("flattened-exception-binding")
    plain_output = False
    derived_output = False
    for node in collector.nodes:
        if isinstance(node, ast.Call) and _plain_sink(node):
            values = [
                *node.args,
                *(
                    item.value
                    for item in node.keywords
                    if _name_path(node.func) != "print"
                    or item.arg not in {"file", "flush", "end", "sep"}
                ),
            ]
            plain_output = plain_output or any(
                not _structured_serialization(value) for value in values
            )
            if any(_plain_exception_text(value, tainted) for value in values):
                derived_output = True
                detectors.add("exception-to-plain-output")
        elif isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)):
            if node.value is not None and _plain_exception_text(node.value, tainted):
                detectors.add("flattened-exception-escape")
    if plain_output and not derived_output:
        detectors.add("opaque-exception-to-plain-output")
    digest = _handler_hash(handler)
    return [Finding(path, handler.lineno, detector, digest) for detector in sorted(detectors)]


def _is_cli_boundary(path: Path, tree: ast.Module) -> bool:
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return (
        path.name in _CLI_FILENAMES
        or path.name.startswith("cli_")
        or path.name.endswith("_cli.py")
        or any(
            node.name == "main"
            or node.name.endswith("_cli")
            or node.name.startswith("run_cli")
            for node in functions
        )
    )


def inventory(root: Path) -> list[Finding]:
    """Return every structurally detected exception-to-text CLI boundary."""

    source_root = root / "src" / "gravity_insight"
    findings: list[Finding] = []
    for source_path in sorted(source_root.rglob("*.py")):
        relative = source_path.relative_to(root).as_posix()
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise CliBoundaryGateError(f"cannot parse CLI candidate {relative}: {exc}") from exc
        if not _is_cli_boundary(source_path, tree):
            continue
        for handler in sorted(
            (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)),
            key=lambda node: node.lineno,
        ):
            findings.extend(_handler_findings(relative, handler))
    return sorted(
        set(findings),
        key=lambda item: (item.path, item.line, item.detector, item.handler_sha256),
    )


def load_allowlist(
    path: Path, *, today: date | None = None
) -> dict[tuple[str, int, str, str], dict[str, Any]]:
    """Load exact, reasoned, expiring exemptions keyed to one handler AST."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliBoundaryGateError(f"CLI exception allowlist is invalid: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != SCHEMA_VERSION:
        raise CliBoundaryGateError("CLI exception allowlist schema_version is invalid")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise CliBoundaryGateError("CLI exception allowlist entries must be an array")
    selected_day = today or date.today()
    result: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != _ALLOWLIST_FIELDS:
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} has invalid fields"
            )
        reason = item.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} lacks a specific reason"
            )
        if type(item.get("line")) is not int or item["line"] < 1:
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} has an invalid line"
            )
        if not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("path", "detector", "handler_sha256", "review_expires")
        ):
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} has invalid identity fields"
            )
        if len(item["handler_sha256"]) != 64 or any(
            value not in "0123456789abcdef" for value in item["handler_sha256"]
        ):
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} has an invalid handler hash"
            )
        try:
            expiry = date.fromisoformat(item["review_expires"])
        except ValueError as exc:
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} has an invalid expiry"
            ) from exc
        if expiry < selected_day:
            raise CliBoundaryGateError(
                f"CLI exception allowlist entry {index} expired on {expiry.isoformat()}"
            )
        key = (
            item["path"],
            item["line"],
            item["detector"],
            item["handler_sha256"],
        )
        if key in result:
            raise CliBoundaryGateError(
                f"duplicate CLI exception allowlist entry {index}"
            )
        result[key] = dict(item)
    return result


def evaluate(
    findings: Iterable[Finding],
    allowlist: Mapping[tuple[str, int, str, str], Mapping[str, Any]],
) -> tuple[list[Finding], list[Finding], list[tuple[str, int, str, str]]]:
    allowed: list[Finding] = []
    blocked: list[Finding] = []
    used: set[tuple[str, int, str, str]] = set()
    for finding in findings:
        if finding.allowlist_key in allowlist:
            allowed.append(finding)
            used.add(finding.allowlist_key)
        else:
            blocked.append(finding)
    unused = sorted(set(allowlist) - used)
    return allowed, blocked, unused


def check_repository(
    root: Path, *, allowlist_path: Path = DEFAULT_ALLOWLIST, today: date | None = None
) -> tuple[int, dict[str, Any]]:
    findings = inventory(root)
    allowlist = load_allowlist(allowlist_path, today=today)
    allowed, blocked, unused = evaluate(findings, allowlist)
    passed = not blocked and not unused
    receipt = {
        "schema_version": "gravity.cli-exception-boundary-check.v1",
        "status": "passed" if passed else "failed",
        "scanned_scope": (
            "src/gravity_insight CLI-named modules plus modules with top-level main() or CLI runner functions"
        ),
        "finding_count": len(findings),
        "allowlisted_count": len(allowed),
        "unreviewed_findings": [asdict(item) for item in blocked],
        "unused_allowlist_entries": [
            {
                "path": key[0],
                "line": key[1],
                "detector": key[2],
                "handler_sha256": key[3],
            }
            for key in unused
        ],
    }
    return (0 if passed else 1), receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)
    try:
        code, receipt = check_repository(
            args.root.resolve(), allowlist_path=args.allowlist.resolve()
        )
    except CliBoundaryGateError as exc:
        print(f"CLI exception boundary check failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
