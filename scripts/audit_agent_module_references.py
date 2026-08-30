"""Reproducible source audit for the R17 agent-module migration ledger."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tokenize
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_PACKAGE_ROOT = "gravity_sdk"
CURRENT_PACKAGE_ROOT = "gravity_insight"
PACKAGE_ROOT_MIGRATION = {
    "historical_package_root": HISTORICAL_PACKAGE_ROOT,
    "current_package_root": CURRENT_PACKAGE_ROOT,
    "projection": "replace_exact_leading_package_component",
}
FROZEN_SCOPE_LEDGER = PurePosixPath(
    "tests/fixtures/agent_module_reference_dispositions.json"
)
EXPECTED_OWNER_STATES = {
    "baseline": (82, 0, True),
    "phase_1": (34, 48, False),
    "phase_2": (0, 82, False),
}
GENERATED_GOVERNANCE_FILES = frozenset(
    {
        "scripts/audit_agent_module_references.py",
        "scripts/generate_agent_module_reference_dispositions.py",
        "tests/fixtures/agent_module_reference_checkpoint.json",
        "tests/fixtures/agent_module_reference_dispositions.json",
        "tests/test_agent_module_reference_dispositions.py",
    }
)
GOVERNANCE_EXCLUSION_RULE = (
    "Exclude only tmp/**, direct specs/agent-runtime/R17-*.md migration "
    "specifications, the checked-in baseline disposition fixture, live checkpoint "
    "receipt and their validator, and "
    "the two scripts that produce this audit. These paths define, generate, or "
    "validate R17 governance metadata rather than consume migrated runtime "
    "modules. Do not exclude AGENTS.md; specs/agent-runtime/architecture-source.md, "
    "index.json, or index.md; docs/maintainers/technical-debt.md; "
    "tests/agent_migration_characterization.py; or any other src, docs, specs, "
    "or tests path."
)
CONFIG_NAMES = {"pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "MANIFEST.in"}
DOC_ROOTS = {"docs", "specs"}
DOC_NAMES = {"README.md", "AGENTS.md"}


@dataclass(frozen=True)
class ModuleMap:
    old_module: str
    new_module: str
    old_file: str
    new_file: str
    target_exists: bool
    casefold_target_collision: bool
    stdlib_basename_collision: bool
    notes: str


@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int
    column: int
    form: str
    old_value: str
    new_value: str
    certainty: str
    details: str


@dataclass(frozen=True)
class AuditResult:
    mappings: tuple[ModuleMap, ...]
    references: tuple[Finding, ...]
    manual_review: tuple[Finding, ...]
    version_controlled_file_count: int
    scanned_file_count: int
    excluded_files: tuple[str, ...]
    owner_state: str

    def summary(self) -> dict[str, Any]:
        reference_counts = Counter(item.category for item in self.references)
        manual_counts = Counter(item.form for item in self.manual_review)
        return {
            "version_controlled_file_count": self.version_controlled_file_count,
            "scanned_file_count": self.scanned_file_count,
            "excluded_files": list(self.excluded_files),
            "module_count": len(self.mappings),
            "reference_count": len(self.references),
            "manual_review_count": len(self.manual_review),
            "owner_state": self.owner_state,
            "package_root_migration": PACKAGE_ROOT_MIGRATION,
            "reference_categories": dict(sorted(reference_counts.items())),
            "manual_review_forms": dict(sorted(manual_counts.items())),
            "governance_exclusion_rule": GOVERNANCE_EXCLUSION_RULE,
        }


def _git_lines(root: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return [line for line in completed.stdout.split("\0") if line]


def is_generated_governance_artifact(relative: str) -> bool:
    """Return whether a path is audit metadata rather than a migration consumer."""

    normalized = PurePosixPath(relative.replace("\\", "/"))
    parts = normalized.parts
    if parts and parts[0] == "tmp":
        return True
    value = normalized.as_posix()
    if value in GENERATED_GOVERNANCE_FILES:
        return True
    return (
        len(parts) == 3
        and parts[:2] == ("specs", "agent-runtime")
        and normalized.name.startswith("R17-")
        and normalized.suffix == ".md"
    )


def version_controlled_files(root: Path = ROOT) -> tuple[list[Path], list[str]]:
    """List tracked and pending non-ignored files using repository-relative rules."""

    relative_files = sorted(
        set(_git_lines(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"))
    )
    files: list[Path] = []
    excluded: list[str] = []
    for relative in relative_files:
        path = root / relative
        if not path.is_file():
            continue
        if is_generated_governance_artifact(relative):
            excluded.append(PurePosixPath(relative).as_posix())
        else:
            files.append(path)
    return files, excluded


def source_key(row: Finding) -> str:
    return f"{row.file}:{row.line}:{row.column}:{row.form}"


def canonical_sha256(rows: Iterable[Finding | ModuleMap]) -> str:
    import hashlib

    payload = [asdict(row) for row in rows]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def project_module_root(module: str) -> str:
    """Project a historical R17 module identity onto the current package root."""

    if module == HISTORICAL_PACKAGE_ROOT:
        return CURRENT_PACKAGE_ROOT
    prefix = HISTORICAL_PACKAGE_ROOT + "."
    if module.startswith(prefix):
        return CURRENT_PACKAGE_ROOT + module.removeprefix(HISTORICAL_PACKAGE_ROOT)
    return module


def historical_module_root(module: str) -> str:
    """Return the immutable-ledger identity for a projected current module."""

    if module == CURRENT_PACKAGE_ROOT:
        return HISTORICAL_PACKAGE_ROOT
    prefix = CURRENT_PACKAGE_ROOT + "."
    if module.startswith(prefix):
        return HISTORICAL_PACKAGE_ROOT + module.removeprefix(CURRENT_PACKAGE_ROOT)
    return module


def projected_module_mapping(mapping: dict[str, str]) -> dict[str, str]:
    return {
        project_module_root(old): project_module_root(new)
        for old, new in mapping.items()
    }


def reference_module_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Scan immutable historical identities and their current-root projection."""

    return {**mapping, **projected_module_mapping(mapping)}


def _read_text(path: Path) -> str | None:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _line_col(text: str, index: int) -> tuple[int, int]:
    return text.count("\n", 0, index) + 1, index - text.rfind("\n", 0, index)


def _source_segment(text: str, node: ast.AST) -> str:
    value = ast.get_source_segment(text, node)
    return value if value is not None else ast.dump(node, include_attributes=False)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _const_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        chunks: list[str] = []
        for item in node.values:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            chunks.append(item.value)
        return "".join(chunks)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _const_string(node.left)
        right = _const_string(node.right)
        return None if left is None or right is None else left + right
    return None


def _category_for_text(relative: str) -> str:
    path = PurePosixPath(relative)
    if "fixtures" in path.parts:
        return "test_fixture"
    if (path.parts and path.parts[0] in DOC_ROOTS) or path.name in DOC_NAMES:
        return "documentation_spec"
    if path.name in CONFIG_NAMES or path.suffix.lower() in {
        ".toml",
        ".ini",
        ".cfg",
        ".json",
        ".yaml",
        ".yml",
    }:
        return "entrypoint_config"
    return "string_reference"


def _category_for_python_literal(relative: str) -> str:
    path = PurePosixPath(relative)
    if "fixtures" in path.parts:
        return "test_fixture"
    if (
        path.name in {"__init__.py", "cli.py", "__main__.py"}
        and relative.startswith(f"src/{CURRENT_PACKAGE_ROOT}/")
    ):
        return "entrypoint_config"
    return "string_reference"


def _module_file(root: Path, module: str) -> Path:
    current_module = project_module_root(module)
    return root / "src" / Path(*current_module.split(".")).with_suffix(".py")


def _moved_agent_target(old_module: str) -> str | None:
    parts = old_module.split(".")
    if len(parts) != 2 or parts[0] != HISTORICAL_PACKAGE_ROOT:
        return None
    name = parts[1]
    if name.startswith("agent_"):
        responsibility = name.removeprefix("agent_")
    elif name.endswith("_agent"):
        responsibility = name.removesuffix("_agent")
    else:
        return None
    return (
        f"{HISTORICAL_PACKAGE_ROOT}.agents.{responsibility}"
        if responsibility
        else None
    )


def _frozen_module_scope(root: Path) -> list[tuple[str, str]]:
    path = root / FROZEN_SCOPE_LEDGER
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load frozen R17 scope ledger: {path}") from exc
    if document.get("schema_version") != "gravity.agent-module-reference-dispositions.v2":
        raise RuntimeError("frozen R17 scope ledger schema is not dispositions.v2")
    scope = document.get("scope")
    if not isinstance(scope, dict):
        raise RuntimeError("frozen R17 scope ledger has no scope object")
    moves = scope.get("one_to_one_moves")
    if not isinstance(moves, list) or len(moves) != 82:
        raise RuntimeError("frozen R17 scope must contain 82 one-to-one moves")
    result: list[tuple[str, str]] = []
    for move in moves:
        if not isinstance(move, dict):
            raise RuntimeError("frozen R17 move must be an object")
        old = move.get("old_module")
        new = move.get("new_module")
        if (
            not isinstance(old, str)
            or new != _moved_agent_target(old)
        ):
            raise RuntimeError(f"invalid frozen R17 move: {old!r} -> {new!r}")
        result.append((old, new))
    if len({old for old, _ in result}) != 82 or len({new for _, new in result}) != 82:
        raise RuntimeError("frozen R17 move owners must be unique")
    consolidation = scope.get("consolidate_delete")
    if consolidation != {
        "old_module": "gravity_sdk.agent_pagination",
        "new_module": "gravity_sdk.pagination_completeness",
        "symbol": "compact_pagination",
    }:
        raise RuntimeError("frozen R17 pagination consolidation changed")
    if scope.get("retained_modules") != ["gravity_sdk.agent_runtime_contracts"]:
        raise RuntimeError("frozen R17 retained owner changed")
    result.extend(
        [
            (
                consolidation["old_module"],
                consolidation["new_module"],
            ),
            (
                "gravity_sdk.agent_runtime_contracts",
                "gravity_sdk.agent_runtime_contracts",
            ),
        ]
    )
    return result


def make_module_map(root: Path = ROOT) -> tuple[list[ModuleMap], dict[str, str]]:
    frozen_scope = _frozen_module_scope(root)
    move_scope = frozen_scope[:82]
    old_move_count = sum(_module_file(root, old).is_file() for old, _ in move_scope)
    new_move_count = sum(_module_file(root, new).is_file() for _, new in move_scope)
    overlaps = [
        old
        for old, new in move_scope
        if _module_file(root, old).is_file() and _module_file(root, new).is_file()
    ]
    missing = [
        old
        for old, new in move_scope
        if not _module_file(root, old).is_file()
        and not _module_file(root, new).is_file()
    ]
    if overlaps or missing:
        raise RuntimeError(
            "R17 frozen owners must exist at exactly one old/new path: "
            f"overlaps={overlaps[:5]}, missing={missing[:5]}"
        )
    pagination_old = _module_file(
        root, "gravity_sdk.agent_pagination"
    ).is_file()
    if not _module_file(root, "gravity_sdk.pagination_completeness").is_file():
        raise RuntimeError("R17 pagination consolidation target is missing")
    if not _module_file(root, "gravity_sdk.agent_runtime_contracts").is_file():
        raise RuntimeError("R17 retained owner is missing")
    owner_state = (old_move_count, new_move_count, pagination_old)
    state_name = next(
        (
            name
            for name, expected in EXPECTED_OWNER_STATES.items()
            if expected == owner_state
        ),
        None,
    )
    if state_name is None:
        raise RuntimeError(
            "unsupported R17 frozen-owner state: "
            f"old_moves={old_move_count}, new_moves={new_move_count}, "
            f"pagination_old={pagination_old}"
        )
    expected_root_owners = {
        project_module_root(old)
        for old, _ in move_scope
        if old.rsplit(".", 1)[-1].startswith("agent_")
        and _module_file(root, old).is_file()
    }
    if pagination_old:
        expected_root_owners.add(project_module_root("gravity_sdk.agent_pagination"))
    expected_root_owners.add(project_module_root("gravity_sdk.agent_runtime_contracts"))
    actual_root_owners = {
        f"{CURRENT_PACKAGE_ROOT}.{path.stem}"
        for path in (root / "src" / CURRENT_PACKAGE_ROOT).glob("agent_*.py")
    }
    if actual_root_owners != expected_root_owners:
        raise RuntimeError(
            f"unexpected root agent owner in R17 {state_name} state: "
            f"extra={sorted(actual_root_owners - expected_root_owners)}, "
            f"missing={sorted(expected_root_owners - actual_root_owners)}"
        )
    target_counts = Counter(new.rsplit(".", 1)[1].casefold() for _, new in frozen_scope)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    mappings: list[ModuleMap] = []
    for old_module, new_module in frozen_scope:
        old_file = _module_file(root, old_module)
        target_file = _module_file(root, new_module)
        target = new_module.rsplit(".", 1)[1]
        notes: list[str] = []
        if target_counts[target.casefold()] > 1:
            notes.append("case-insensitive target collision")
        if target_file.exists():
            notes.append("target file already exists")
        if target in stdlib:
            notes.append("basename matches stdlib module")
        mappings.append(
            ModuleMap(
                old_module=old_module,
                new_module=new_module,
                old_file=_relative(root, old_file),
                new_file=_relative(root, target_file),
                target_exists=target_file.exists(),
                casefold_target_collision=target_counts[target.casefold()] > 1,
                stdlib_basename_collision=target in stdlib,
                notes="; ".join(notes) or "none",
            )
        )
    return mappings, {item.old_module: item.new_module for item in mappings}


class ReferenceScanner:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.short_mapping = {
            old.rsplit(".", 1)[1]: new.rsplit(".", 1)[1]
            for old, new in mapping.items()
        }
        self.path_mapping = {
            "src/" + old.replace(".", "/") + ".py":
                "src/" + new.replace(".", "/") + ".py"
            for old, new in mapping.items()
        }
        self.module_pattern = self._pattern(mapping, prefix="", negative_dot=False)
        self.short_pattern = self._pattern(
            self.short_mapping,
            prefix=r"(?<![A-Za-z0-9_.])",
            negative_dot=True,
        )
        self.path_pattern = self._pattern(
            self.path_mapping,
            prefix="",
            negative_dot=False,
        )

    @staticmethod
    def _pattern(
        values: Iterable[str], *, prefix: str, negative_dot: bool
    ) -> re.Pattern[str]:
        del negative_dot
        alternatives = "|".join(
            re.escape(value) for value in sorted(values, key=len, reverse=True)
        )
        return re.compile(prefix + f"(?:{alternatives})" + r"(?![A-Za-z0-9_])")

    def _module_replacements(self, value: str) -> list[tuple[str, str]]:
        return [
            (match.group(), self.mapping[match.group()])
            for match in self.module_pattern.finditer(value)
        ]

    def _short_replacements(self, value: str) -> list[tuple[str, str]]:
        return [
            (match.group(), self.short_mapping[match.group()])
            for match in self.short_pattern.finditer(value)
        ]

    @staticmethod
    def _importfrom_full_module(relative: str, node: ast.ImportFrom) -> str | None:
        package_source = f"src/{CURRENT_PACKAGE_ROOT}"
        if not relative.startswith(package_source + "/") or not node.level:
            return node.module
        parent = PurePosixPath(relative).parent.relative_to(package_source)
        package_parts = [CURRENT_PACKAGE_ROOT, *parent.parts]
        keep = len(package_parts) - (node.level - 1)
        if keep < 1:
            return None
        base = package_parts[:keep]
        return (
            ".".join([*base, *node.module.split(".")])
            if node.module
            else ".".join(base)
        )

    @staticmethod
    def _patch_target_expressions(node: ast.Call, called: str | None) -> list[ast.AST]:
        if called in {
            "patch",
            "mock.patch",
            "unittest.mock.patch",
            "monkeypatch.setattr",
        }:
            if node.args:
                return [node.args[0]]
            return [
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"target", "name"}
            ]
        if called in {
            "patch.object",
            "mock.patch.object",
            "unittest.mock.patch.object",
        }:
            if node.args:
                return [node.args[0]]
            return [
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"target", "object"}
            ]
        return []

    def scan_python(self, relative: str, text: str) -> tuple[list[Finding], list[Finding]]:
        findings: list[Finding] = []
        manual: list[Finding] = []
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError as error:
            manual.append(
                Finding(
                    "manual_review",
                    relative,
                    error.lineno or 0,
                    error.offset or 0,
                    "syntax_error",
                    "",
                    "",
                    "manual",
                    str(error),
                )
            )
            return findings, manual

        import_calls = {"import_module", "importlib.import_module", "__import__"}
        patch_calls = {
            "patch",
            "mock.patch",
            "unittest.mock.patch",
            "patch.object",
            "mock.patch.object",
            "unittest.mock.patch.object",
            "monkeypatch.setattr",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for old, new in self._module_replacements(alias.name):
                        findings.append(
                            Finding(
                                "static_import",
                                relative,
                                node.lineno,
                                node.col_offset + 1,
                                "import",
                                old,
                                new,
                                "exact",
                                _source_segment(text, node),
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                module = self._importfrom_full_module(relative, node) or ""
                for old, new in self._module_replacements(module):
                    findings.append(
                        Finding(
                            "static_import",
                            relative,
                            node.lineno,
                            node.col_offset + 1,
                            "from import",
                            old,
                            new,
                            "exact",
                            _source_segment(text, node),
                        )
                    )
                if node.module is None:
                    for alias in node.names:
                        old = f"{module}.{alias.name}"
                        if old in self.mapping:
                            findings.append(
                                Finding(
                                    "static_import",
                                    relative,
                                    node.lineno,
                                    node.col_offset + 1,
                                    "relative from-import name",
                                    old,
                                    self.mapping[old],
                                    "exact",
                                    _source_segment(text, node),
                                )
                            )
            elif isinstance(node, ast.Call):
                called = _dotted_name(node.func)
                if called in import_calls and node.args:
                    expression = node.args[0]
                    value = _const_string(expression)
                    rendered = _source_segment(text, expression)
                    if value is None:
                        finding = Finding(
                            "dynamic_import",
                            relative,
                            node.lineno,
                            node.col_offset + 1,
                            called or "",
                            rendered,
                            "",
                            "manual",
                            "dynamic import expression is not compile-time constant",
                        )
                        findings.append(finding)
                        manual.append(
                            Finding(
                                "manual_review",
                                finding.file,
                                finding.line,
                                finding.column,
                                finding.form,
                                finding.old_value,
                                finding.new_value,
                                "manual",
                                finding.details,
                            )
                        )
                    else:
                        for old, new in self._module_replacements(value):
                            findings.append(
                                Finding(
                                    "dynamic_import",
                                    relative,
                                    node.lineno,
                                    node.col_offset + 1,
                                    called or "",
                                    old,
                                    new,
                                    "constant-folded",
                                    rendered,
                                )
                            )
                        for old, new in self._short_replacements(value):
                            finding = Finding(
                                "dynamic_import",
                                relative,
                                node.lineno,
                                node.col_offset + 1,
                                called or "",
                                old,
                                new,
                                "context review",
                                rendered,
                            )
                            findings.append(finding)
                            manual.append(
                                Finding(
                                    "manual_review",
                                    finding.file,
                                    finding.line,
                                    finding.column,
                                    finding.form,
                                    finding.old_value,
                                    finding.new_value,
                                    "manual",
                                    "bare dynamic import name has no statically "
                                    "provable package owner",
                                )
                            )
                if called in patch_calls:
                    for expression in self._patch_target_expressions(node, called):
                        value = _const_string(expression)
                        if value is None:
                            finding = Finding(
                                "manual_patch_expression",
                                relative,
                                node.lineno,
                                node.col_offset + 1,
                                called or "",
                                _source_segment(text, expression),
                                "",
                                "manual",
                                "patch target expression is not compile-time constant",
                            )
                            findings.append(finding)
                            manual.append(
                                Finding(
                                    "manual_review",
                                    finding.file,
                                    finding.line,
                                    finding.column,
                                    finding.form,
                                    finding.old_value,
                                    finding.new_value,
                                    "manual",
                                    finding.details,
                                )
                            )
                        else:
                            for old, new in self._module_replacements(value):
                                findings.append(
                                    Finding(
                                        "patch_target",
                                        relative,
                                        getattr(expression, "lineno", node.lineno),
                                        getattr(expression, "col_offset", node.col_offset) + 1,
                                        called or "",
                                        old,
                                        new,
                                        "exact",
                                        _source_segment(text, expression),
                                    )
                                )
                            for old, new in self._short_replacements(value):
                                finding = Finding(
                                    "patch_target",
                                    relative,
                                    getattr(expression, "lineno", node.lineno),
                                    getattr(expression, "col_offset", node.col_offset) + 1,
                                    called or "",
                                    old,
                                    new,
                                    "context review",
                                    _source_segment(text, expression),
                                )
                                findings.append(finding)
                                manual.append(
                                    Finding(
                                        "manual_review",
                                        relative,
                                        node.lineno,
                                        node.col_offset + 1,
                                        called or "",
                                        old,
                                        new,
                                        "manual",
                                        "bare patch target name has no statically "
                                        "provable package owner",
                                    )
                                )
            elif isinstance(node, ast.Attribute) and node.attr in {
                "__module__",
                "__qualname__",
            }:
                dependency = Finding(
                    "module_qualname_dependency",
                    relative,
                    node.lineno,
                    node.col_offset + 1,
                    node.attr,
                    _source_segment(text, node),
                    "",
                    "requires ownership review",
                    "receiver may resolve to a relocated agent symbol",
                )
                findings.append(dependency)
                manual.append(
                    Finding(
                        "manual_review",
                        dependency.file,
                        dependency.line,
                        dependency.column,
                        dependency.form,
                        dependency.old_value,
                        "",
                        "manual",
                        "__module__/__qualname__ receiver ownership cannot be "
                        "proven statically",
                    )
                )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                category = _category_for_python_literal(relative)
                for old, new in self._module_replacements(value):
                    findings.append(
                        Finding(
                            category,
                            relative,
                            node.lineno,
                            node.col_offset + 1,
                            "python string literal",
                            old,
                            new,
                            "exact",
                            value,
                        )
                    )
                for old, new in self._short_replacements(value):
                    finding = Finding(
                        category,
                        relative,
                        node.lineno,
                        node.col_offset + 1,
                        "bare python module string",
                        old,
                        new,
                        "context review",
                        value,
                    )
                    findings.append(finding)
                    manual.append(
                        Finding(
                            "manual_review",
                            finding.file,
                            finding.line,
                            finding.column,
                            finding.form,
                            finding.old_value,
                            finding.new_value,
                            "manual",
                            "bare agent module name may be a module selector or "
                            "unrelated data; inspect caller contract before replacing",
                        )
                    )
                if any(
                    f"{package_root}.agent_" in value
                    for package_root in (
                        HISTORICAL_PACKAGE_ROOT,
                        CURRENT_PACKAGE_ROOT,
                    )
                ) and not self._module_replacements(value):
                    manual.append(
                        Finding(
                            "manual_review",
                            relative,
                            node.lineno,
                            node.col_offset + 1,
                            "python string literal",
                            value,
                            "",
                            "manual",
                            "template/string mentions agent module prefix but does "
                            "not name a fixed module",
                        )
                    )
        findings.extend(self._scan_python_comments(relative, text))
        return findings, manual

    def _scan_python_comments(self, relative: str, text: str) -> list[Finding]:
        findings: list[Finding] = []
        reader = iter(text.splitlines(keepends=True)).__next__
        try:
            tokens = tokenize.generate_tokens(reader)
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                for old, new in self._module_replacements(token.string):
                    findings.append(
                        Finding(
                            "string_reference",
                            relative,
                            token.start[0],
                            token.start[1] + 1,
                            "python comment module path",
                            old,
                            new,
                            "exact",
                            token.string,
                        )
                    )
                for old, new in self._short_replacements(token.string):
                    findings.append(
                        Finding(
                            "string_reference",
                            relative,
                            token.start[0],
                            token.start[1] + 1,
                            "python comment bare module string",
                            old,
                            new,
                            "context review",
                            token.string,
                        )
                    )
        except (tokenize.TokenError, IndentationError):
            pass
        return findings

    def scan_text(self, relative: str, text: str) -> list[Finding]:
        findings: list[Finding] = []
        category = _category_for_text(relative)
        lines = text.splitlines()
        for match in self.module_pattern.finditer(text):
            line, column = _line_col(text, match.start())
            old = match.group()
            findings.append(
                Finding(
                    category,
                    relative,
                    line,
                    column,
                    "text module path",
                    old,
                    self.mapping[old],
                    "exact",
                    lines[line - 1],
                )
            )
        for match in self.short_pattern.finditer(text):
            line, column = _line_col(text, match.start())
            old = match.group()
            findings.append(
                Finding(
                    category,
                    relative,
                    line,
                    column,
                    "bare text module string",
                    old,
                    self.short_mapping[old],
                    "context review",
                    lines[line - 1],
                )
            )
        for match in self.path_pattern.finditer(text):
            line, column = _line_col(text, match.start())
            old = match.group()
            findings.append(
                Finding(
                    category,
                    relative,
                    line,
                    column,
                    "text source path",
                    old,
                    self.path_mapping[old],
                    "exact",
                    lines[line - 1],
                )
            )
        return findings


def _de_duplicate(rows: Iterable[Finding]) -> list[Finding]:
    unique: dict[tuple[Any, ...], Finding] = {}
    for row in rows:
        key = (
            row.category,
            row.file,
            row.line,
            row.column,
            row.form,
            row.old_value,
            row.new_value,
        )
        unique.setdefault(key, row)
    return sorted(
        unique.values(),
        key=lambda row: (
            row.category,
            row.file,
            row.line,
            row.column,
            row.old_value,
        ),
    )


def scan_repository(root: Path = ROOT) -> AuditResult:
    mappings, mapping = make_module_map(root)
    scanner = ReferenceScanner(reference_module_mapping(mapping))
    files, excluded = version_controlled_files(root)
    ast_findings: list[Finding] = []
    text_findings: list[Finding] = []
    manual: list[Finding] = []
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        relative = _relative(root, path)
        if path.suffix == ".py":
            findings, reviews = scanner.scan_python(relative, text)
            ast_findings.extend(findings)
            manual.extend(reviews)
        else:
            text_findings.extend(scanner.scan_text(relative, text))
    references = _de_duplicate([*ast_findings, *text_findings])
    for finding in references:
        if finding.certainty == "context review":
            manual.append(
                Finding(
                    "manual_review",
                    finding.file,
                    finding.line,
                    finding.column,
                    finding.form,
                    finding.old_value,
                    finding.new_value,
                    "manual",
                    "bare agent module name may be a module selector or unrelated "
                    "data; inspect caller contract before replacing",
                )
            )
    manual = _de_duplicate(manual)
    one_to_one = [
        item for item in mappings if item.new_module.startswith("gravity_sdk.agents.")
    ]
    owner_shape = (
        sum((root / item.old_file).is_file() for item in one_to_one),
        sum((root / item.new_file).is_file() for item in one_to_one),
        _module_file(root, "gravity_sdk.agent_pagination").is_file(),
    )
    owner_state = next(
        name for name, expected in EXPECTED_OWNER_STATES.items() if expected == owner_shape
    )
    versioned_count = len(files) + len(excluded)
    return AuditResult(
        mappings=tuple(mappings),
        references=tuple(references),
        manual_review=tuple(manual),
        version_controlled_file_count=versioned_count,
        scanned_file_count=len(files),
        excluded_files=tuple(excluded),
        owner_state=owner_state,
    )


def main() -> None:
    print(json.dumps(scan_repository().summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
