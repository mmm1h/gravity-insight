"""Test-side contracts for the agent module move."""

from __future__ import annotations

import ast
import importlib.util
import json
from graphlib import CycleError, TopologicalSorter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "gravity_sdk"
PUBLIC_API_BASELINE = ROOT / "tests" / "fixtures" / "public_api_exports.json"
OWNER_MIGRATIONS = ROOT / "tests/fixtures/public_api_owner_migrations.json"

INTERNAL_AGENT_PREFIXES = ("gravity_sdk.agent_", "gravity_sdk.agents")


def expected_public_exports(
    baseline: Path = PUBLIC_API_BASELINE, ledger: Path = OWNER_MIGRATIONS,
) -> dict[str, list[str]]:
    exports = json.loads(baseline.read_text(encoding="utf-8"))
    migrations = json.loads(ledger.read_text(encoding="utf-8"))
    if not isinstance(migrations, list):
        raise AssertionError("owner migration ledger must be a JSON list")
    for index, migration in enumerate(migrations):
        if set(migration) != {"symbol", "from", "to"}:
            raise AssertionError(f"owner migration {index} has invalid fields")
        symbol = migration["symbol"]
        if symbol not in exports:
            raise AssertionError(f"owner migration {index} has unknown symbol {symbol!r}")
        current_owner = exports[symbol][0]
        if current_owner != migration["from"]:
            raise AssertionError(
                f"owner migration {index} for {symbol!r} expected "
                f"{current_owner!r}, not {migration['from']!r}"
            )
        owners = (migration["from"], migration["to"])
        if not all(isinstance(value, str) and value.startswith(".") for value in owners):
            raise AssertionError(f"owner migration {index} must use relative owners")
        exports[symbol][0] = migration["to"]
    return dict(sorted(exports.items()))


def agent_path_references(roots: tuple[Path, ...]) -> list[tuple[Path, int, str]]:
    references: list[tuple[Path, int, str]] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                values: list[str | None] = []
                if isinstance(node, ast.Import):
                    values = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    values = [node.module]
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    values = [node.value]
                references.extend(
                    (path, node.lineno, value)
                    for value in values
                    if value and value.startswith("gravity_sdk.agent")
                )
    return references


def agent_path_classification(reference: str) -> str | None:
    if reference == "gravity_sdk.agent" or reference.startswith("gravity_sdk.agent."):
        return "public"
    if reference.startswith(INTERNAL_AGENT_PREFIXES):
        return "internal"
    return None


def _module_inventory(package_root: Path) -> dict[Path, tuple[str, bool]]:
    inventory: dict[Path, tuple[str, bool]] = {}
    paths = list(package_root.glob("*.py"))
    agents = package_root / "agents"
    if agents.is_dir():
        paths.extend(agents.rglob("*.py"))
    for path in paths:
        relative = path.relative_to(package_root)
        parts = list(relative.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        name = ".".join((package_root.name, *parts))
        inventory[path] = (name, is_package)
    return inventory


def _type_checking_value(node: ast.expr) -> bool | None:
    if isinstance(node, ast.Name) and node.id == "TYPE_CHECKING":
        return False
    if isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING":
        return False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _type_checking_value(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [_type_checking_value(value) for value in node.values]
        if any(value is None for value in values):
            return None
        return all(values) if isinstance(node.op, ast.And) else any(values)
    return None


class _EagerImportVisitor(ast.NodeVisitor):
    def __init__(
        self,
        current: str,
        current_package: str,
        modules: set[str],
    ) -> None:
        self.current = current
        self.current_package = current_package
        self.modules = modules
        self.targets: set[str] = set()

    def _record(self, target: str | None) -> None:
        if not target or not target.startswith("gravity_sdk"):
            return
        candidates = {target}
        if target.startswith("gravity_sdk.agents."):
            candidates.add("gravity_sdk.agents")
        self.targets.update(candidate for candidate in candidates if (
            candidate in self.modules and candidate != self.current
        ))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        value = _type_checking_value(node.test)
        if value is True:
            branches = node.body
        elif value is False:
            branches = node.orelse
        else:
            branches = (*node.body, *node.orelse)
        for child in branches:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            relative = "." * node.level + (node.module or "")
            base = importlib.util.resolve_name(relative, self.current_package)
        else:
            base = node.module
        self._record(base)
        for alias in node.names:
            if alias.name != "*" and base:
                self._record(f"{base}.{alias.name}")


def eager_import_cycles(package_root: Path = PACKAGE_ROOT) -> list[list[str]]:
    inventory = _module_inventory(package_root)
    modules = {name for name, _ in inventory.values()}
    graph = {name: set() for name in modules}
    for path, (name, is_package) in inventory.items():
        current_package = name if is_package else name.rpartition(".")[0]
        visitor = _EagerImportVisitor(name, current_package, modules)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        graph[name].update(visitor.targets)
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as error:
        cycle = list(dict.fromkeys(error.args[1]))
        return [sorted(cycle)]
    return []
