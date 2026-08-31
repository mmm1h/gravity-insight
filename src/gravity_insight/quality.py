"""Measure and ratchet Gravity Insight runtime code quality."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tokenize
from typing import Any, Iterable, Mapping, Sequence

from .documentation_gate import documentation_errors, load_json_object
from .paths import CONTRACT_ROOT as PACKAGE_CONTRACT_ROOT
from .paths import MANIFEST_ROOT as PACKAGE_MANIFEST_ROOT
from .paths import PROJECT_ROOT


ROOT = PROJECT_ROOT
RUNTIME_ROOT = Path("src/gravity_insight")
METRIC_SCOPE = (
    "src/gravity_insight/**/*.py (including compiler.py and quality.py)",
)
CONTRACT_ROOT = PACKAGE_CONTRACT_ROOT.relative_to(ROOT)
MANIFEST_ROOT = PACKAGE_MANIFEST_ROOT.relative_to(ROOT)
BASELINE_PATH = Path("src/gravity_insight/governance/quality-baseline.json")
FILE_SLOC_LIMIT = 500
FUNCTION_SLOC_LIMIT = 80
COMPLEXITY_LIMIT = 15
BASELINE_VERSION = 3
PREVIOUS_BASELINE_VERSION = 2
BASE_REF_ENV = "GRAVITY_QUALITY_BASE_REF"
_IGNORED_TOKENS = {
    tokenize.ENCODING,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.COMMENT,
    tokenize.ENDMARKER,
}
_V3_SCOPE_ADDITIONS = frozenset(
    {
        "src/gravity_insight/compiler.py",
        "src/gravity_insight/quality.py",
    }
)
_EXIT_CODE_EXEMPTION = "exit-code-guard: allow - "
_ERROR_CATEGORY_VALUES = frozenset({"caller", "upstream", "local"})


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    qualname: str
    line: int
    sloc: int
    complexity: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}"


@dataclass(frozen=True)
class LiteralOccurrence:
    path: str
    line: int
    value: str


@dataclass(frozen=True)
class QualityProfile:
    file_sloc: Mapping[str, int]
    file_ast_nodes: Mapping[str, int]
    file_lines: Mapping[str, int]
    functions: tuple[FunctionMetric, ...]
    operation_literals: tuple[LiteralOccurrence, ...]
    operation_ids: tuple[str, ...]
    src_python_sloc: int
    provenance_covered: int
    compiler_check: str
    scan_errors: tuple[str, ...] = ()

    @property
    def operation_count(self) -> int:
        return len(self.operation_ids)

    def document(self) -> dict[str, Any]:
        return {
            "thresholds": {
                "file_sloc": FILE_SLOC_LIMIT,
                "function_sloc": FUNCTION_SLOC_LIMIT,
                "cyclomatic_complexity": COMPLEXITY_LIMIT,
                "operation_literals": 0,
                "provenance_coverage_percent": 100,
            },
            "summary": {
                "runtime_cli_files": len(self.file_sloc),
                "runtime_cli_sloc": sum(self.file_sloc.values()),
                "src_python_sloc": self.src_python_sloc,
                "operation_count": self.operation_count,
                "provenance_covered": self.provenance_covered,
                "operation_literal_count": len(self.operation_literals),
                "compiler_check": self.compiler_check,
            },
            "file_sloc": dict(self.file_sloc),
            "file_ast_nodes": dict(self.file_ast_nodes),
            "file_lines": dict(self.file_lines),
            "functions": [asdict(metric) for metric in self.functions],
            "operation_literals": [asdict(item) for item in self.operation_literals],
            "scan_errors": list(self.scan_errors),
        }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _source_lines(source: str) -> set[int]:
    physical = source.splitlines()
    lines: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type in _IGNORED_TOKENS:
                continue
            start = max(1, token.start[0])
            end = min(len(physical), max(start, token.end[0]))
            for line_number in range(start, end + 1):
                if physical[line_number - 1].strip():
                    lines.add(line_number)
    except (IndentationError, tokenize.TokenError) as exc:
        raise SyntaxError(str(exc)) from exc
    return lines


def count_sloc(source: str) -> int:
    """Count non-blank, non-comment physical Python source lines."""

    return len(_source_lines(source))


def _ast_node_count(tree: ast.AST) -> int:
    return sum(1 for _node in ast.walk(tree))


def count_ast_nodes(source: str) -> int:
    """Count formatting-invariant Python AST nodes."""

    return _ast_node_count(_parse(source, "<quality-source>"))


class _ComplexityVisitor(ast.NodeVisitor):
    """McCabe-compatible decision counter for one function body."""

    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.value = 1

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and node is not self.root:
            return
        if isinstance(node, (ast.If, ast.IfExp, ast.Assert)):
            self.value += 1
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self.value += 1 + bool(node.orelse)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            self.value += len(node.handlers) + bool(node.orelse)
        elif isinstance(node, ast.BoolOp):
            self.value += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            self.value += 1 + len(node.ifs)
        elif isinstance(node, ast.Match):
            defaults = sum(
                isinstance(case.pattern, ast.MatchAs)
                and case.pattern.pattern is None
                and case.pattern.name is None
                for case in node.cases
            )
            self.value += len(node.cases) - defaults
        super().generic_visit(node)


def cyclomatic_complexity(node: ast.AST) -> int:
    visitor = _ComplexityVisitor(node)
    visitor.visit(node)
    return visitor.value


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self, path: str, sloc_lines: set[int]) -> None:
        self.path = path
        self.sloc_lines = sloc_lines
        self.scope: list[str] = []
        self.metrics: list[FunctionMetric] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        start = min(
            [node.lineno, *(item.lineno for item in node.decorator_list)],
        )
        end = node.end_lineno or node.lineno
        qualname = ".".join((*self.scope, node.name))
        sloc = sum(start <= line <= end for line in self.sloc_lines)
        self.metrics.append(
            FunctionMetric(self.path, qualname, node.lineno, sloc, cyclomatic_complexity(node))
        )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


def _parse(source: str, path: str) -> ast.Module:
    return ast.parse(source, filename=path, feature_version=(3, 11))


def _nonzero_integer_literal(node: ast.AST) -> bool:
    return any(
        isinstance(item, ast.Constant)
        and type(item.value) is int
        and item.value in {2, 3, 4}
        for item in ast.walk(node)
    )


def _exit_code_target(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Name) and node.id == "exit_code"
        or isinstance(node, ast.Attribute) and node.attr == "exit_code"
    )


def _category_literal(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in _ERROR_CATEGORY_VALUES
    return bool(
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr in {"CALLER", "UPSTREAM", "LOCAL"}
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "ErrorCategory"
    )


class _HardcodedExitCodeVisitor(ast.NodeVisitor):
    """Find only syntax whose names make an exit-code meaning unambiguous."""

    def __init__(self) -> None:
        self.candidates: list[ast.AST] = []

    def _add(self, node: ast.AST) -> None:
        if _nonzero_integer_literal(node):
            self.candidates.append(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "exit_code":
                self._add(value)
        keys_are_categories = any(_category_literal(key) for key in node.keys)
        values_are_categories = any(_category_literal(value) for value in node.values)
        if keys_are_categories or values_are_categories:
            self._add(node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg == "exit_code":
                self._add(keyword.value)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) > 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "exit_code"
        ):
            self._add(node.args[1])
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(_exit_code_target(target) for target in node.targets):
            self._add(node.value)
        if any(
            isinstance(target, ast.Name) and "EXIT" in target.id
            for target in node.targets
        ):
            self._add(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and _exit_code_target(node.target):
            self._add(node.value)
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        before = len(self.candidates)
        self.generic_visit(node)
        if "exit_code" in node.name and len(self.candidates) == before:
            self._add(node)

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function


# exit-code-guard: allow - this checker necessarily inspects protocol exit literals
def hardcoded_exit_code_errors(path: str, source: str, tree: ast.Module) -> list[str]:
    """Reject numeric error exits unless a protocol exception gives a reason."""

    if path == "src/gravity_insight/errors.py":
        return []
    visitor = _HardcodedExitCodeVisitor()
    visitor.visit(tree)
    lines = source.splitlines()
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    for node in visitor.candidates:
        location = (node.lineno, node.col_offset)
        if location in seen:
            continue
        seen.add(location)
        adjacent = lines[max(0, node.lineno - 2) : node.lineno]
        marker_lines = [line for line in adjacent if _EXIT_CODE_EXEMPTION in line]
        if marker_lines:
            reason = marker_lines[-1].partition(_EXIT_CODE_EXEMPTION)[2].strip()
            if reason:
                continue
            errors.append(
                f"{path}:{node.lineno}: exit-code guard exemption requires a reason"
            )
            continue
        errors.append(
            f"{path}:{node.lineno}: hard-coded non-zero exit code must use the "
            "shared error classification; for a non-ErrorDetail protocol value add "
            f"`# {_EXIT_CODE_EXEMPTION}<reason>`"
        )
    return errors


def _python_sources(
    root: Path, relative_root: Path, *, recursive: bool = True
) -> Iterable[tuple[str, str]]:
    directory = root / relative_root
    if not directory.is_dir():
        return
    paths = directory.rglob("*.py") if recursive else directory.glob("*.py")
    for path in sorted(paths):
        yield _relative(root, path), path.read_text(encoding="utf-8")


def _compile_contracts(root: Path) -> tuple[tuple[str, ...], int, str, list[str]]:
    try:
        from gravity_insight.compiler import ContractCompiler

        result = ContractCompiler(root / CONTRACT_ROOT, root / MANIFEST_ROOT).check()
        document = json.loads(result.provenance)
        operations = document.get("operations", {})
        errors: list[str] = []
        if not isinstance(operations, dict):
            return (), 0, "FAIL", ["compiler provenance operations must be an object"]
        covered = 0
        required = {"source_files", "family", "platform", "applied_overrides"}
        for operation_id, provenance in sorted(operations.items()):
            if not isinstance(provenance, dict):
                errors.append(f"provenance {operation_id}: entry must be an object")
                continue
            missing = required - set(provenance)
            sources = provenance.get("source_files")
            if missing or not isinstance(sources, list) or not sources:
                errors.append(
                    f"provenance {operation_id}: missing source/family/platform/override coverage"
                )
                continue
            covered += 1
        return tuple(sorted(operations)), covered, "PASS", errors
    except Exception as exc:
        return (), 0, "FAIL", [f"compile --check failed: {type(exc).__name__}: {exc}"]


def inspect_repository(root: Path) -> QualityProfile:
    root = root.resolve()
    operation_ids, provenance_covered, compiler_check, errors = _compile_contracts(root)
    file_sloc: dict[str, int] = {}
    file_ast_nodes: dict[str, int] = {}
    file_lines: dict[str, int] = {}
    functions: list[FunctionMetric] = []
    parsed: dict[str, ast.Module] = {}
    for path, source in _python_sources(root, RUNTIME_ROOT):
        try:
            lines = _source_lines(source)
            tree = _parse(source, path)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{path}: Python 3.11 parse failed: {exc}")
            continue
        file_sloc[path] = len(lines)
        file_ast_nodes[path] = _ast_node_count(tree)
        file_lines[path] = len(source.splitlines())
        collector = _FunctionCollector(path, lines)
        collector.visit(tree)
        functions.extend(collector.metrics)
        parsed[path] = tree
        errors.extend(hardcoded_exit_code_errors(path, source, tree))
    known = set(operation_ids)
    literals: list[LiteralOccurrence] = []
    for path, tree in parsed.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in known:
                literals.append(LiteralOccurrence(path, node.lineno, node.value))
    src_python_sloc = 0
    for _path, source in _python_sources(root, Path("src")):
        try:
            src_python_sloc += count_sloc(source)
        except SyntaxError as exc:
            errors.append(f"{_path}: SLOC tokenize failed: {exc}")
    return QualityProfile(
        file_sloc=dict(sorted(file_sloc.items())),
        file_ast_nodes=dict(sorted(file_ast_nodes.items())),
        file_lines=dict(sorted(file_lines.items())),
        functions=tuple(sorted(functions, key=lambda item: (item.path, item.line, item.qualname))),
        operation_literals=tuple(sorted(literals, key=lambda item: (item.path, item.line, item.value))),
        operation_ids=operation_ids,
        src_python_sloc=src_python_sloc,
        provenance_covered=provenance_covered,
        compiler_check=compiler_check,
        scan_errors=tuple(errors),
    )


def _thresholds() -> dict[str, int]:
    return {
        "file_sloc": FILE_SLOC_LIMIT,
        "function_sloc": FUNCTION_SLOC_LIMIT,
        "cyclomatic_complexity": COMPLEXITY_LIMIT,
        "operation_literals": 0,
    }


def _legacy_files(document: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    values = document.get("legacy_files", {})
    if not isinstance(values, Mapping):
        raise ValueError("legacy_files must be an object")
    result: dict[str, dict[str, int]] = {}
    required = {"ast_nodes", "ast_hard_limit", "sloc_hard_limit", "migration_sloc"}
    for path, raw in values.items():
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError(f"legacy_files.{path} must contain exactly {sorted(required)}")
        entry = {name: raw[name] for name in required}
        if any(type(value) is not int or value < 0 for value in entry.values()):
            raise ValueError(f"legacy_files.{path} values must be non-negative integers")
        if entry["ast_hard_limit"] < entry["ast_nodes"]:
            raise ValueError(f"legacy_files.{path}.ast_hard_limit is below ast_nodes")
        version = document.get("baseline_version")
        if version == BASELINE_VERSION and entry["ast_hard_limit"] != entry["ast_nodes"]:
            raise ValueError(
                f"legacy_files.{path}.ast_hard_limit must equal the v3 AST ratchet"
            )
        if (
            version == PREVIOUS_BASELINE_VERSION
            and entry["sloc_hard_limit"] < entry["migration_sloc"]
        ):
            raise ValueError(f"legacy_files.{path}.sloc_hard_limit is below migration_sloc")
        result[str(path)] = entry
    return result


def _growth_ledger(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = document.get("growth_ledger", [])
    if not isinstance(values, list):
        raise ValueError("growth_ledger must be an array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, Mapping) or set(raw) != {"path", "from", "to", "reason"}:
            raise ValueError(f"growth_ledger[{index}] has an invalid shape")
        path, before, after, reason = raw["path"], raw["from"], raw["to"], raw["reason"]
        if (
            not isinstance(path, str)
            or not path
            or type(before) is not int
            or type(after) is not int
            or after <= before
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError(f"growth_ledger[{index}] must record path/from/to/non-empty reason")
        result.append({"path": path, "from": before, "to": after, "reason": reason.strip()})
    return result


def _legacy_file_snapshot(
    profile: QualityProfile,
    prior_version: Any,
    prior_legacy: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, int]]:
    legacy_files: dict[str, dict[str, int]] = {}
    for path, sloc in profile.file_sloc.items():
        if sloc <= FILE_SLOC_LIMIT:
            continue
        nodes = profile.file_ast_nodes[path]
        old = prior_legacy.get(path)
        if old is None:
            if prior_version == BASELINE_VERSION:
                raise ValueError(f"{path}: new file SLOC debt cannot be baselined")
            if prior_version == PREVIOUS_BASELINE_VERSION and path not in _V3_SCOPE_ADDITIONS:
                raise ValueError(f"{path}: new file SLOC debt cannot be added during v3 migration")
            migration_sloc = sloc
        else:
            ast_limit = old["ast_nodes"] if prior_version == PREVIOUS_BASELINE_VERSION else old["ast_hard_limit"]
            if sloc > old["sloc_hard_limit"] and prior_version == BASELINE_VERSION:
                raise ValueError(f"{path}: SLOC exceeds its immutable legacy hard limit")
            if nodes > ast_limit:
                raise ValueError(f"{path}: AST nodes exceed its immutable legacy hard limit")
            migration_sloc = old["migration_sloc"]
        legacy_files[path] = {
            "ast_nodes": nodes,
            "ast_hard_limit": nodes,
            "sloc_hard_limit": sloc,
            "migration_sloc": migration_sloc,
        }
    return legacy_files


def debt_snapshot(
    profile: QualityProfile,
    prior_baseline: Mapping[str, Any] | None = None,
    growth_reasons: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    reasons = dict(growth_reasons or {})
    if reasons:
        raise ValueError(
            "AST growth reasons are no longer supported; legacy ratchets may only decrease"
        )
    prior_version = prior_baseline.get("baseline_version") if prior_baseline else None
    if prior_baseline and prior_version not in {PREVIOUS_BASELINE_VERSION, BASELINE_VERSION}:
        raise ValueError(
            f"cannot migrate quality baseline version {prior_version!r}; expected "
            f"{PREVIOUS_BASELINE_VERSION} or {BASELINE_VERSION}"
        )
    prior_legacy = _legacy_files(prior_baseline) if prior_baseline else {}
    ledger = _growth_ledger(prior_baseline) if prior_baseline else []
    legacy_files = _legacy_file_snapshot(profile, prior_version, prior_legacy)
    function_debt: dict[str, int] = {}
    complexity_debt: dict[str, int] = {}
    for metric in profile.functions:
        if metric.sloc > FUNCTION_SLOC_LIMIT:
            function_debt[metric.key] = metric.sloc
        if metric.complexity > COMPLEXITY_LIMIT:
            complexity_debt[metric.key] = metric.complexity
    literal_debt: dict[str, dict[str, int]] = {}
    for item in profile.operation_literals:
        values = literal_debt.setdefault(item.path, {})
        values[item.value] = values.get(item.value, 0) + 1
    return {
        "baseline_version": BASELINE_VERSION,
        "scope": list(METRIC_SCOPE),
        "thresholds": _thresholds(),
        "legacy_files": dict(sorted(legacy_files.items())),
        "growth_ledger": ledger,
        "debt": {
            "function_sloc": function_debt,
            "cyclomatic_complexity": complexity_debt,
            "operation_literals": literal_debt,
        },
    }


def _flatten_debt(document: Mapping[str, Any], category: str) -> dict[str, int]:
    debt = document.get("debt", {})
    values = debt.get(category, {}) if isinstance(debt, Mapping) else {}
    if category != "operation_literals":
        if not isinstance(values, Mapping):
            return {}
        return {str(key): int(value) for key, value in values.items()}
    flattened: dict[str, int] = {}
    if isinstance(values, Mapping):
        for path, literals in values.items():
            if isinstance(literals, Mapping):
                for literal, count in literals.items():
                    flattened[f"{path}::{literal}"] = int(count)
    return flattened


def _current_values(profile: QualityProfile, category: str) -> dict[str, int]:
    return _flatten_debt(debt_snapshot(profile), category)


def _metric_label(category: str) -> tuple[str, int]:
    return {
        "file_sloc": ("file SLOC", FILE_SLOC_LIMIT),
        "function_sloc": ("function SLOC", FUNCTION_SLOC_LIMIT),
        "cyclomatic_complexity": ("cyclomatic complexity", COMPLEXITY_LIMIT),
        "operation_literals": ("operation ID literal count", 0),
    }[category]


def _legacy_ratchet_errors(
    profile: QualityProfile,
    legacy: Mapping[str, Mapping[str, int]],
    errors: list[str],
) -> None:
    for path in sorted(set(profile.file_sloc) | set(legacy)):
        sloc = profile.file_sloc.get(path, 0)
        nodes = profile.file_ast_nodes.get(path, 0)
        entry = legacy.get(path)
        if entry is None:
            if sloc > FILE_SLOC_LIMIT:
                errors.append(
                    f"{path}: file SLOC current={sloc}, threshold={FILE_SLOC_LIMIT}; "
                    "split or data-drive the code instead of adding new debt"
                )
            continue
        if sloc <= FILE_SLOC_LIMIT:
            errors.append(
                f"{path}: legacy file improved current={sloc}, threshold={FILE_SLOC_LIMIT}; "
                f"remove it from the baseline with `{_baseline_command()}`"
            )
            continue
        if sloc > entry["sloc_hard_limit"]:
            errors.append(
                f"{path}: file SLOC current={sloc}, immutable hard limit="
                f"{entry['sloc_hard_limit']}; split the file"
            )
        elif sloc < entry["sloc_hard_limit"]:
            errors.append(
                f"{path}: file SLOC improved current={sloc}, old ratchet="
                f"{entry['sloc_hard_limit']}; tighten and commit the baseline with "
                f"`{_baseline_command()}`"
            )
        if nodes > entry["ast_hard_limit"]:
            errors.append(
                f"{path}: AST nodes current={nodes}, immutable hard limit="
                f"{entry['ast_hard_limit']}; split the file"
            )
        elif nodes < entry["ast_hard_limit"]:
            errors.append(
                f"{path}: AST nodes improved current={nodes}, old ratchet="
                f"{entry['ast_hard_limit']}; "
                f"tighten and commit the baseline with `{_baseline_command()}`"
            )


def _debt_ratchet_errors(
    profile: QualityProfile, baseline: Mapping[str, Any], errors: list[str]
) -> None:
    for category in ("function_sloc", "cyclomatic_complexity", "operation_literals"):
        label, limit = _metric_label(category)
        current = _current_values(profile, category)
        allowed = _flatten_debt(baseline, category)
        for key in sorted(set(current) | set(allowed)):
            value = current.get(key, 0)
            ceiling = allowed.get(key)
            if value <= limit and ceiling is None:
                continue
            if ceiling is None:
                errors.append(
                    f"{key}: {label} current={value}, threshold={limit}; "
                    "split or data-drive the code instead of adding new debt"
                )
            elif value > ceiling:
                errors.append(
                    f"{key}: {label} current={value}, ratchet={ceiling}, threshold={limit}; "
                    "reduce it to the baseline or lower"
                )
            elif value < ceiling:
                errors.append(
                    f"{key}: {label} improved current={value}, old ratchet={ceiling}, threshold={limit}; "
                    f"tighten and commit the baseline with `{_baseline_command()}`"
                )


def evaluate_ratchet(profile: QualityProfile, baseline: Mapping[str, Any]) -> list[str]:
    errors = list(profile.scan_errors)
    if (
        baseline.get("baseline_version") != BASELINE_VERSION
        or baseline.get("scope") != list(METRIC_SCOPE)
        or baseline.get("thresholds") != _thresholds()
    ):
        errors.append(
            f"quality baseline header is invalid; run `{_baseline_command()}` and commit the result"
        )
        return errors
    try:
        legacy = _legacy_files(baseline)
        _growth_ledger(baseline)
    except (TypeError, ValueError) as exc:
        errors.append(f"quality baseline legacy ratchet is invalid: {exc}")
        return errors
    _legacy_ratchet_errors(profile, legacy, errors)
    _debt_ratchet_errors(profile, baseline, errors)
    if profile.operation_count == 0:
        errors.append("provenance coverage cannot be measured because compilation produced no operations")
    elif profile.provenance_covered != profile.operation_count:
        errors.append(
            "provenance coverage "
            f"current={profile.provenance_covered}/{profile.operation_count}, threshold=100%; "
            "add source_files, family, platform, and applied_overrides provenance"
        )
    return errors


def _baseline_debt_relaxation_errors(
    current: Mapping[str, Any],
    base: Mapping[str, Any],
    migrating: bool,
    errors: list[str],
) -> None:
    for category in (
        "function_sloc",
        "cyclomatic_complexity",
        "operation_literals",
    ):
        label, limit = _metric_label(category)
        current_values = _flatten_debt(current, category)
        base_values = _flatten_debt(base, category)
        for key, value in sorted(current_values.items()):
            old = base_values.get(key)
            path = key.partition("::")[0]
            if old is None and migrating and path in _V3_SCOPE_ADDITIONS:
                continue
            if old is None or value > old:
                errors.append(
                    f"{key}: baseline relaxation rejected for {label}: "
                    f"base={old if old is not None else 'absent'}, proposed={value}, threshold={limit}; "
                    "a baseline may only decrease or remove debt"
                )


def _legacy_baseline_relaxation_errors(
    current_legacy: Mapping[str, Mapping[str, int]],
    base_legacy: Mapping[str, Mapping[str, int]],
    migrating: bool,
    errors: list[str],
) -> None:
    for path, entry in current_legacy.items():
        old = base_legacy.get(path)
        if old is None:
            if not migrating or path not in _V3_SCOPE_ADDITIONS:
                errors.append(f"{path}: adding a new legacy file is rejected")
            elif entry["migration_sloc"] != entry["sloc_hard_limit"]:
                errors.append(
                    f"{path}: newly scanned migration_sloc must equal its SLOC ratchet"
                )
            continue
        if migrating:
            if entry["migration_sloc"] != old["migration_sloc"]:
                errors.append(f"{path}: migration_sloc must preserve the v2 value")
            if entry["ast_hard_limit"] > old["ast_nodes"]:
                errors.append(
                    f"{path}: v3 AST ratchet relaxation rejected: "
                    f"v2 ratchet={old['ast_nodes']}, proposed={entry['ast_hard_limit']}"
                )
            continue
        for field in ("ast_hard_limit", "sloc_hard_limit"):
            if entry[field] > old[field]:
                errors.append(
                    f"{path}: immutable {field} relaxation rejected: "
                    f"base={old[field]}, proposed={entry[field]}"
                )
        if entry["migration_sloc"] != old["migration_sloc"]:
            errors.append(f"{path}: migration_sloc is immutable")


def compare_baselines(current: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    current_version = current.get("baseline_version")
    base_version = base.get("baseline_version")
    if current_version != BASELINE_VERSION:
        return [f"proposed baseline version must be {BASELINE_VERSION}, got {current_version!r}"]
    if base_version not in {PREVIOUS_BASELINE_VERSION, BASELINE_VERSION}:
        return [
            f"base baseline version must be {PREVIOUS_BASELINE_VERSION} or "
            f"{BASELINE_VERSION}, got {base_version!r}"
        ]
    migrating = base_version == PREVIOUS_BASELINE_VERSION
    _baseline_debt_relaxation_errors(current, base, migrating, errors)
    try:
        current_legacy = _legacy_files(current)
        current_ledger = _growth_ledger(current)
    except (TypeError, ValueError) as exc:
        return [*errors, f"proposed legacy ratchet is invalid: {exc}"]
    try:
        base_legacy = _legacy_files(base)
        base_ledger = _growth_ledger(base)
    except (TypeError, ValueError) as exc:
        return [*errors, f"base legacy ratchet is invalid: {exc}"]
    if current_ledger != base_ledger:
        errors.append("historical growth ledger is immutable in baseline v3")
    _legacy_baseline_relaxation_errors(current_legacy, base_legacy, migrating, errors)
    return errors


def migration_source_errors(
    baseline: Mapping[str, Any], base_sources: Mapping[str, str]
) -> list[str]:
    """Verify that v3 ratchets do not exceed metrics in the v2 base source."""

    errors: list[str] = []
    legacy = _legacy_files(baseline)
    for path, source in base_sources.items():
        if path not in legacy:
            continue
        entry = legacy[path]
        expected_sloc_hard_limit = count_sloc(source)
        expected_ast_hard_limit = count_ast_nodes(source)
        if entry["sloc_hard_limit"] > expected_sloc_hard_limit:
            errors.append(
                f"{path}: v3 SLOC ratchet {entry['sloc_hard_limit']} exceeds "
                f"base SLOC {expected_sloc_hard_limit}"
            )
        if entry["ast_hard_limit"] > expected_ast_hard_limit:
            errors.append(
                f"{path}: v3 AST ratchet {entry['ast_hard_limit']} exceeds "
                f"base AST nodes {expected_ast_hard_limit}"
            )
    return errors


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_text(root: Path, ref: str, path: str) -> str:
    result = _git(root, "show", f"{ref}:{path}")
    return result.stdout.decode("utf-8")


def _base_quality_snapshot(root: Path, ref: str) -> tuple[set[str], int]:
    provenance = json.loads(
        _git_text(root, ref, (CONTRACT_ROOT / "generated/provenance.json").as_posix())
    )
    operations = provenance.get("operations", {})
    if not isinstance(operations, dict):
        raise ValueError("base provenance operations must be an object")
    listing = _git(root, "ls-tree", "-r", "--name-only", ref, "--", "src")
    src_sloc = 0
    for path in listing.stdout.decode("utf-8").splitlines():
        if path.endswith(".py"):
            src_sloc += count_sloc(_git_text(root, ref, path))
    return set(operations), src_sloc


def evaluate_slope(profile: QualityProfile, root: Path, base_ref: str | None) -> list[str]:
    if not base_ref or not base_ref.strip("0"):
        return []
    try:
        base_operations, base_sloc = _base_quality_snapshot(root, base_ref)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        return [
            f"contract expansion slope: cannot read base-ref {base_ref!r}: {type(exc).__name__}: {exc}; "
            "fetch full history and pass a commit containing generated provenance"
        ]
    added = set(profile.operation_ids) - base_operations
    if not added:
        return []
    delta = profile.src_python_sloc - base_sloc
    if delta == 0:
        return []
    sample = ", ".join(sorted(added)[:5])
    suffix = "..." if len(added) > 5 else ""
    return [
        "contract expansion Python slope failed: "
        f"added_operations={len(added)} ({sample}{suffix}), src_python_sloc_delta={delta}, threshold=0; "
        "keep an operation-only PR data-only, and submit engine changes separately"
    ]


def _baseline_at_ref(root: Path, ref: str | None) -> dict[str, Any] | None:
    if not ref or not ref.strip("0"):
        return None
    result = _git(root, "show", f"{ref}:{BASELINE_PATH.as_posix()}", check=False)
    if result.returncode != 0:
        return None
    document = json.loads(result.stdout.decode("utf-8"))
    return document if isinstance(document, dict) else None


def _baseline_command() -> str:
    return "python -m gravity_insight.quality baseline --write"


def validate(root: Path, *, base_ref: str | None = None) -> list[str]:
    root = root.resolve()
    profile = inspect_repository(root)
    path = root / BASELINE_PATH
    if not path.is_file():
        return [f"missing quality baseline {BASELINE_PATH.as_posix()}; run `{_baseline_command()}`"]
    try:
        baseline = load_json_object(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid quality baseline {BASELINE_PATH.as_posix()}: {exc}"]
    resolved_ref = base_ref if base_ref is not None else os.environ.get(BASE_REF_ENV)
    try:
        errors = evaluate_ratchet(profile, baseline)
    except (TypeError, ValueError) as exc:
        return [
            f"invalid quality baseline {BASELINE_PATH.as_posix()}: {exc}; "
            f"run `{_baseline_command()}`"
        ]
    errors.extend(evaluate_slope(profile, root, resolved_ref))
    try:
        base = _baseline_at_ref(root, resolved_ref)
    except (UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot parse quality baseline at {resolved_ref!r}: {exc}")
    else:
        if base is not None:
            try:
                errors.extend(compare_baselines(baseline, base))
                if base.get("baseline_version") == PREVIOUS_BASELINE_VERSION:
                    legacy = _legacy_files(baseline)
                    sources = {
                        path: _git_text(root, resolved_ref, path)
                        for path in legacy
                        if path not in _V3_SCOPE_ADDITIONS
                    }
                    errors.extend(migration_source_errors(baseline, sources))
            except (TypeError, ValueError, UnicodeError, subprocess.CalledProcessError) as exc:
                errors.append(f"invalid quality baseline at {resolved_ref!r}: {exc}")
    errors.extend(documentation_errors(root))
    return errors


def _debt_by_file(profile: QualityProfile) -> dict[str, dict[str, int]]:
    rows: dict[str, dict[str, int]] = {}
    for path, sloc in profile.file_sloc.items():
        if sloc > FILE_SLOC_LIMIT:
            rows.setdefault(path, {})["file"] = sloc - FILE_SLOC_LIMIT
    for metric in profile.functions:
        if metric.sloc > FUNCTION_SLOC_LIMIT:
            row = rows.setdefault(metric.path, {})
            row["functions"] = row.get("functions", 0) + 1
            row["function_excess"] = row.get("function_excess", 0) + metric.sloc - FUNCTION_SLOC_LIMIT
        if metric.complexity > COMPLEXITY_LIMIT:
            row = rows.setdefault(metric.path, {})
            row["complexity"] = row.get("complexity", 0) + 1
            row["complexity_excess"] = row.get("complexity_excess", 0) + metric.complexity - COMPLEXITY_LIMIT
    for item in profile.operation_literals:
        row = rows.setdefault(item.path, {})
        row["literals"] = row.get("literals", 0) + 1
    return rows


def _row_total(rows: Iterable[Mapping[str, int]], key: str) -> int:
    return sum(row.get(key, 0) for row in rows)


def _debt_summary(profile: QualityProfile) -> dict[str, int]:
    rows = _debt_by_file(profile).values()
    return {
        "file_count": sum("file" in row for row in rows),
        "file_excess": _row_total(rows, "file"),
        "function_count": _row_total(rows, "functions"),
        "function_excess": _row_total(rows, "function_excess"),
        "complexity_count": _row_total(rows, "complexity"),
        "complexity_excess": _row_total(rows, "complexity_excess"),
        "operation_literals": len(profile.operation_literals),
    }


def render_markdown(profile: QualityProfile) -> str:
    rows = _debt_by_file(profile)
    summary = _debt_summary(profile)
    lines = [
        "# Gravity Insight 代码质量门禁",
        "",
        "> 本文由 `python -m gravity_insight.quality profile --markdown-out "
        "tmp/quality-profile.md` 从当前工作树生成；它是临时诊断，不属于长期文档。",
        "",
        "## 口径与结论",
        "",
        f"- runtime/CLI 文件 SLOC 上限 `{FILE_SLOC_LIMIT}`；函数 SLOC 上限 `{FUNCTION_SLOC_LIMIT}`；圈复杂度上限 `{COMPLEXITY_LIMIT}`。",
        "- SLOC 使用 tokenize 统计非空、非纯注释物理行；存量大文件的 SLOC 与格式无关 AST 节点数均按当前值建立只降不升的 ratchet。",
        "- 圈复杂度从 1 起计，增加 if/条件表达式、循环及其 else、except/try else、布尔分支、assert、推导式分支和非默认 match case；外层函数不累计嵌套函数。",
        "- operation ID 使用编译器产出的精确 ID 集合做 AST 字符串常量匹配，不使用宽泛正则。",
        "- 文件/函数范围递归覆盖全部 `src/gravity_insight/**/*.py`，包括 build-time compiler 与门禁自身。",
        "- 保留蓝图的 500/80/15：500 足以容纳单个完整引擎，80/15 与常用可评审函数边界一致；本仓存量由 ratchet 承接，无需放松绝对阈值。",
        "- 将蓝图的 dotted-string 正则改为编译 catalog 精确 ID 集合：这样既能抓到两段式 `app.list`，也不会把普通模块名或配置路径误判为 operation。",
        f"- 确定性编译：`{profile.compiler_check}`；provenance：`{profile.provenance_covered}/{profile.operation_count}`。",
        f"- 当前 runtime/CLI SLOC `{sum(profile.file_sloc.values())}`、AST 节点 `{sum(profile.file_ast_nodes.values())}`；全 `src/**/*.py` SLOC `{profile.src_python_sloc}`。",
        f"- 总债务：文件超额 `{summary['file_excess']}` SLOC，函数超额 `{summary['function_excess']}` SLOC，复杂度超额 `{summary['complexity_excess']}`，operation 字面量 `{len(profile.operation_literals)}` 个。",
        "- operation 字面量没有永久语义白名单；下表全部是上线时存量 ratchet，目标阈值仍为 0。",
        "",
        "## 逐文件债务",
        "",
        "| 文件 | 当前 SLOC | 文件超额 | 超长函数数/超额 | 高复杂函数数/超额 | operation 字面量 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for path, debt in sorted(rows.items()):
        lines.append(
            f"| `{path}` | {profile.file_sloc.get(path, '-')} | {debt.get('file', 0)} | "
            f"{debt.get('functions', 0)}/{debt.get('function_excess', 0)} | "
            f"{debt.get('complexity', 0)}/{debt.get('complexity_excess', 0)} | "
            f"{debt.get('literals', 0)} |"
        )
    lines.extend(
        [
            "",
            "## 超限函数",
            "",
            "| 文件::函数 | 行 | SLOC/超额 | 圈复杂度/超额 |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric in profile.functions:
        if metric.sloc <= FUNCTION_SLOC_LIMIT and metric.complexity <= COMPLEXITY_LIMIT:
            continue
        lines.append(
            f"| `{metric.key}` | {metric.line} | {metric.sloc}/{max(0, metric.sloc - FUNCTION_SLOC_LIMIT)} | "
            f"{metric.complexity}/{max(0, metric.complexity - COMPLEXITY_LIMIT)} |"
        )
    lines.extend(
        [
            "",
            "## operation 字面量分布",
            "",
            "| 文件 | 数量 | 不同 ID 数 |",
            "|---|---:|---:|",
        ]
    )
    grouped: dict[str, list[str]] = {}
    for item in profile.operation_literals:
        grouped.setdefault(item.path, []).append(item.value)
    for path, values in sorted(grouped.items()):
        lines.append(f"| `{path}` | {len(values)} | {len(set(values))} |")
    lines.extend(
        [
            "",
            "## 本轮未设硬门的蓝图指标",
            "",
            "runtime 密度暂不设硬门，因为当前低密度存量尚无稳定拆分归因；family override 比例、契约完整度和 census 由并行契约/探测任务演进，当前接入会形成重复或竞态权威；family 测试增长无法仅凭测试名可靠判断同构实例。它们应在各自数据源稳定后接入本门禁，而不是以易误伤的启发式先占位。",
            "",
            "## Ratchet",
            "",
            f"机器基线位于 `{BASELINE_PATH.as_posix()}`。新文件继续执行 500/80/15/0；存量大文件的 SLOC 与 AST ratchet 只能下降。下降后运行 `{_baseline_command()}` 收紧基线；CI 与 PR base 比较 ratchet，并保持 v2 历史增长台账不可变。",
            "",
        ]
    )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="run the quality gate")
    check.add_argument("--base-ref", default=None)
    baseline = subparsers.add_parser("baseline", help="render the current ratchet baseline")
    baseline.add_argument("--write", action="store_true")
    profile = subparsers.add_parser("profile", help="render the current quality profile")
    profile.add_argument("--json-out", type=Path)
    profile.add_argument("--markdown-out", type=Path)
    return parser


def _run_check(root: Path, base_ref: str | None) -> int:
    errors = validate(root, base_ref=base_ref)
    if errors:
        for error in errors:
            print(f"FAIL P1 gravity-insight-quality: {error}")
        return 1
    profile = inspect_repository(root)
    debt = _debt_summary(profile)
    print(
        "PASS gravity-insight-quality: "
        f"operations={profile.operation_count}, provenance={profile.provenance_covered}, "
        f"debt_files={debt['file_count']} (+{debt['file_excess']} SLOC), "
        f"debt_functions={debt['function_count']} (+{debt['function_excess']} SLOC), "
        f"debt_complexity={debt['complexity_count']} (+{debt['complexity_excess']}), "
        f"debt_operation_literals={debt['operation_literals']}"
    )
    return 0


def _run_baseline(root: Path, profile: QualityProfile, write: bool) -> int:
    path = root / BASELINE_PATH
    try:
        prior = load_json_object(path) if path.is_file() else None
        document = debt_snapshot(profile, prior)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL P1 gravity-insight-quality: cannot update baseline: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if profile.scan_errors:
        for error in profile.scan_errors:
            print(f"FAIL P1 gravity-insight-quality: {error}", file=sys.stderr)
        return 1
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    else:
        print(payload, end="")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "check":
        return _run_check(root, args.base_ref)
    profile = inspect_repository(root)
    if args.command == "baseline":
        return _run_baseline(root, profile, args.write)
    document = profile.document()
    payload = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        path = args.json_out if args.json_out.is_absolute() else root / args.json_out
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8", newline="\n")
    if args.markdown_out:
        path = args.markdown_out if args.markdown_out.is_absolute() else root / args.markdown_out
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(profile), encoding="utf-8", newline="\n")
    if not args.json_out and not args.markdown_out:
        print(payload, end="")
    return 1 if profile.scan_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
