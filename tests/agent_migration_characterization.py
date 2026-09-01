"""Test-side contracts and graph forwarding for technical debt #14."""

from __future__ import annotations

import ast
from collections.abc import Iterable
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "gravity_insight"
PUBLIC_API_MANIFEST = (
    ROOT / "src/gravity_insight/governance/public-api-manifest.json"
)
REFERENCE_DISPOSITIONS = (
    ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
)

INTERNAL_AGENT_PREFIXES = ("gravity_insight.agent_", "gravity_insight.agents")
HISTORICAL_PACKAGE_ROOT = "gravity_sdk"
HISTORICAL_AGENT_LEDGER_PREFIX = "gravity_sdk.agent_"
CURRENT_PACKAGE_ROOT = "gravity_insight"
KNOWN_ROOT_EXPORT_MODULE_COLLISIONS = frozenset(
    {
        "analysis_query_batch_schema",
        "bilibili_account_performance",
        "business_pulse",
        "company_usage",
        "dashboard_snapshot",
        "monetization_detail",
        "order_directory",
        "promotion_performance",
    }
)


def expected_public_exports(
    manifest: Path = PUBLIC_API_MANIFEST,
) -> dict[str, list[str]]:
    from scripts.generate_public_api_exports import export_mapping

    return dict(sorted(export_mapping(manifest).items()))


def root_export_module_collisions(
    package_root: Path = PACKAGE_ROOT,
    exports: Iterable[str] | None = None,
) -> list[str]:
    """Return public names also occupied by an importable root child module."""

    public_names = set(expected_public_exports() if exports is None else exports)
    root_modules = {
        path.stem
        for path in package_root.glob("*.py")
        if path.name != "__init__.py"
    }
    root_modules.update(
        path.name
        for path in package_root.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )
    return sorted(public_names & root_modules)


def unexpected_root_export_module_collisions(
    package_root: Path = PACKAGE_ROOT,
    exports: Iterable[str] | None = None,
) -> list[str]:
    return sorted(
        set(root_export_module_collisions(package_root, exports))
        - KNOWN_ROOT_EXPORT_MODULE_COLLISIONS
    )


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
                    if value and value.startswith("gravity_insight.agent")
                )
    return references


def agent_path_classification(reference: str) -> str | None:
    if reference == "gravity_insight.agent" or reference.startswith("gravity_insight.agent."):
        return "public"
    if reference.startswith(INTERNAL_AGENT_PREFIXES):
        return "internal"
    return None


def module_inventory(package_root: Path) -> dict[Path, tuple[str, bool]]:
    """Return every Python module below a package root."""

    inventory: dict[Path, tuple[str, bool]] = {}
    for path in sorted(package_root.rglob("*.py")):
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

    def _record(self, target: str | None, *, allow_exact_self: bool = False) -> None:
        if not target or not target.startswith("gravity_insight"):
            return
        parts = target.split(".")
        candidates = {
            ".".join(parts[:index]) for index in range(1, len(parts) + 1)
        }
        self.targets.update(
            candidate
            for candidate in candidates
            if candidate in self.modules
            and (
                candidate != self.current
                or (allow_exact_self and candidate == target)
            )
        )

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
            self._record(alias.name, allow_exact_self=True)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            relative = "." * node.level + (node.module or "")
            base = importlib.util.resolve_name(relative, self.current_package)
        else:
            base = node.module
        self._record(
            base,
            allow_exact_self=self.current != self.current_package,
        )
        for alias in node.names:
            if alias.name != "*" and base:
                self._record(f"{base}.{alias.name}", allow_exact_self=True)


def _eager_import_graph(package_root: Path) -> dict[str, set[str]]:
    inventory = module_inventory(package_root)
    modules = {name for name, _ in inventory.values()}
    graph = {name: set() for name in modules}
    for path, (name, is_package) in inventory.items():
        current_package = name if is_package else name.rpartition(".")[0]
        visitor = _EagerImportVisitor(name, current_package, modules)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        graph[name].update(visitor.targets)
    return graph


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[list[str]]:
    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def connect(node: str) -> None:
        nonlocal next_index
        indices[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(graph[node]):
            if target not in indices:
                connect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or node in graph[node]:
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            connect(node)
    return sorted(components)


def eager_import_sccs(package_root: Path = PACKAGE_ROOT) -> list[list[str]]:
    """Return every real eager-import cycle in the complete package graph."""

    return _strongly_connected_components(_eager_import_graph(package_root))


def migration_module_names(
    ledger: Path = REFERENCE_DISPOSITIONS,
) -> frozenset[str]:
    """Project the exact historical R17 owners onto the current package root."""

    document = json.loads(ledger.read_text(encoding="utf-8"))
    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves")
    if not isinstance(moves, list) or len(moves) != 82:
        raise AssertionError("R17 migration ledger must contain exactly 82 moves")
    modules: set[str] = set()
    for index, move in enumerate(moves):
        if not isinstance(move, dict):
            raise AssertionError(f"R17 move {index} is not an object")
        old_module = move.get("old_module")
        new_module = move.get("new_module")
        old_parts = old_module.partition(".") if isinstance(old_module, str) else ()
        new_parts = new_module.partition(".") if isinstance(new_module, str) else ()
        old_name = (
            old_parts[2]
            if old_parts[:2] == (HISTORICAL_PACKAGE_ROOT, ".")
            else ""
        )
        if old_name.startswith("agent_"):
            responsibility = old_name.removeprefix("agent_")
        elif old_name.endswith("_agent"):
            responsibility = old_name.removesuffix("_agent")
        else:
            responsibility = ""
        if not (
            isinstance(old_module, str)
            and old_parts[:2] == (HISTORICAL_PACKAGE_ROOT, ".")
            and isinstance(new_module, str)
            and bool(responsibility)
            and new_parts
            == (HISTORICAL_PACKAGE_ROOT, ".", f"agents.{responsibility}")
        ):
            raise AssertionError(
                f"R17 move {index} has an invalid owner pair: "
                f"{old_module!r} -> {new_module!r}"
            )
        modules.update(
            (
                f"{CURRENT_PACKAGE_ROOT}.{old_parts[2]}",
                f"{CURRENT_PACKAGE_ROOT}.{new_parts[2]}",
            )
        )
    if len(modules) != 164:
        raise AssertionError("R17 move ledger must contain 82 unique old/new pairs")

    consolidation = scope.get("consolidate_delete")
    expected_fields = {"old_module", "new_module", "symbol"}
    if not isinstance(consolidation, dict) or set(consolidation) != expected_fields:
        raise AssertionError("R17 consolidation ledger has invalid fields")
    old_module = consolidation.get("old_module")
    new_module = consolidation.get("new_module")
    if not (
        isinstance(old_module, str)
        and isinstance(new_module, str)
        and old_module.partition(".")
        == (HISTORICAL_PACKAGE_ROOT, ".", "agent_" + "pagination")
        and new_module == "gravity_sdk.pagination_completeness"
        and consolidation.get("symbol") == "compact_pagination"
    ):
        raise AssertionError("R17 pagination consolidation is invalid")
    modules.update(
        (
            f"{CURRENT_PACKAGE_ROOT}.{old_module.partition('.')[2]}",
            f"{CURRENT_PACKAGE_ROOT}.{new_module.partition('.')[2]}",
        )
    )
    return frozenset(modules)


def eager_import_cycles(package_root: Path = PACKAGE_ROOT) -> list[list[str]]:
    """Return complete-graph cycles that cross the agent migration boundary."""

    migration_modules = migration_module_names()
    return [
        component
        for component in eager_import_sccs(package_root)
        if any(module in migration_modules for module in component)
    ]


from scripts.audit_agent_module_references import (
    MODULE_GRAPH_CURRENT_DEFINITION_ID,
    MODULE_GRAPH_CURRENT_PACKAGE_ROOT,
    MODULE_GRAPH_DEBT_PATH,
    MODULE_GRAPH_EDGE_KINDS,
    MODULE_GRAPH_PROFILE_ORDER,
    module_graph_adjacency,
    module_graph_baseline,
    module_graph_canonical_sha256,
    module_graph_current_definition,
    module_graph_cyclic_sccs,
    module_graph_definition,
    module_graph_edge_kinds,
    module_graph_for_profile,
    module_graph_main,
    module_graph_measurement,
    module_graph_render_text,
    refresh_module_graph_baseline,
)


if __name__ == "__main__":
    raise SystemExit(module_graph_main())
