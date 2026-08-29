"""Test-side contracts for the agent module move."""

from __future__ import annotations

import ast
from collections.abc import Iterable
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "gravity_sdk"
PUBLIC_API_BASELINE = ROOT / "tests" / "fixtures" / "public_api_exports.json"
OWNER_MIGRATIONS = ROOT / "tests/fixtures/public_api_owner_migrations.json"
REFERENCE_DISPOSITIONS = (
    ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
)

INTERNAL_AGENT_PREFIXES = ("gravity_sdk.agent_", "gravity_sdk.agents")
LEGACY_AGENT_LEDGER_PREFIX = "gravity_sdk.agent_"
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
                    if value and value.startswith("gravity_sdk.agent")
                )
    return references


def agent_path_classification(reference: str) -> str | None:
    if reference == "gravity_sdk.agent" or reference.startswith("gravity_sdk.agent."):
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
        if not target or not target.startswith("gravity_sdk"):
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
    """Return the exact old/new owners touched by the reviewed R17 ledger."""

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
        old_name = (
            old_module.removeprefix("gravity_sdk.")
            if isinstance(old_module, str)
            else ""
        )
        if old_name.startswith("agent_"):
            responsibility = old_name.removeprefix("agent_")
        elif old_name.endswith("_agent"):
            responsibility = old_name.removesuffix("_agent")
        else:
            responsibility = ""
        if not (
            isinstance(new_module, str)
            and bool(responsibility)
            and new_module == f"gravity_sdk.agents.{responsibility}"
        ):
            raise AssertionError(
                f"R17 move {index} has an invalid owner pair: "
                f"{old_module!r} -> {new_module!r}"
            )
        modules.update((old_module, new_module))
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
        and consolidation.get("symbol") == "compact_pagination"
    ):
        raise AssertionError("R17 pagination consolidation is invalid")
    modules.update((old_module, new_module))
    return frozenset(modules)


def eager_import_cycles(package_root: Path = PACKAGE_ROOT) -> list[list[str]]:
    """Return complete-graph cycles that cross the agent migration boundary."""

    migration_modules = migration_module_names()
    return [
        component
        for component in eager_import_sccs(package_root)
        if any(module in migration_modules for module in component)
    ]


# Unified v1 graph for technical debt #14. This lives in the existing
# test-side characterization owner so the frozen R17 scan denominator stays fixed.
import argparse as _module_graph_argparse
from collections import Counter as _ModuleGraphCounter
import hashlib as _module_graph_hashlib
from typing import Any as _ModuleGraphAny
from typing import Mapping as _ModuleGraphMapping
from typing import Sequence as _ModuleGraphSequence


MODULE_GRAPH_DEFINITION_START = "<!-- MODULE_GRAPH_DEFINITION_V1_START -->"
MODULE_GRAPH_DEFINITION_END = "<!-- MODULE_GRAPH_DEFINITION_V1_END -->"
MODULE_GRAPH_BASELINE_START = "<!-- MODULE_GRAPH_BASELINE_V1_START -->"
MODULE_GRAPH_BASELINE_END = "<!-- MODULE_GRAPH_BASELINE_V1_END -->"
MODULE_GRAPH_DEBT_PATH = ROOT / "docs/maintainers/technical-debt.md"
MODULE_GRAPH_EDGE_KINDS = (
    "ast_eager_import",
    "ast_delayed_import",
    "lazy_export_owner",
    "package_parent",
)
MODULE_GRAPH_PROFILE_ORDER = (
    "eager-ast-only",
    "ast-only",
    "ast+lazy-exports",
    "canonical",
)


def module_graph_canonical_sha256(value: _ModuleGraphAny) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _module_graph_hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _module_graph_embedded_json(
    start_marker: str,
    end_marker: str,
    path: Path = MODULE_GRAPH_DEBT_PATH,
) -> dict[str, _ModuleGraphAny]:
    text = path.read_text(encoding="utf-8")
    try:
        block = text.split(start_marker, 1)[1].split(end_marker, 1)[0]
        payload = block[block.index("{"):block.rindex("}") + 1]
    except (IndexError, ValueError) as exc:
        raise ValueError(f"missing embedded module graph JSON in {path}") from exc
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError("embedded module graph JSON must be an object")
    return document


def module_graph_definition(
    path: Path = MODULE_GRAPH_DEBT_PATH,
) -> dict[str, _ModuleGraphAny]:
    definition = _module_graph_embedded_json(
        MODULE_GRAPH_DEFINITION_START,
        MODULE_GRAPH_DEFINITION_END,
        path,
    )
    profiles = definition.get("profiles")
    if (
        not isinstance(profiles, dict)
        or definition.get("canonical_profile") not in profiles
    ):
        raise ValueError("module graph definition has no valid canonical profile")
    for profile, kinds in profiles.items():
        if not isinstance(profile, str) or not isinstance(kinds, list):
            raise ValueError("module graph profiles must map names to edge-kind lists")
        unknown = sorted(set(kinds) - set(MODULE_GRAPH_EDGE_KINDS))
        if unknown:
            raise ValueError(
                f"module graph profile {profile!r} has unknown edges: {unknown}"
            )
    return definition


def module_graph_baseline(
    path: Path = MODULE_GRAPH_DEBT_PATH,
) -> dict[str, _ModuleGraphAny]:
    return _module_graph_embedded_json(
        MODULE_GRAPH_BASELINE_START,
        MODULE_GRAPH_BASELINE_END,
        path,
    )


def _module_graph_type_checking_value(node: ast.expr) -> bool | None:
    if isinstance(node, ast.Name) and node.id == "TYPE_CHECKING":
        return False
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
        and node.attr == "TYPE_CHECKING"
    ):
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _module_graph_type_checking_value(node.operand)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [_module_graph_type_checking_value(value) for value in node.values]
        if isinstance(node.op, ast.And):
            if False in values:
                return False
            return True if all(value is True for value in values) else None
        if True in values:
            return True
        return False if all(value is False for value in values) else None
    return None


class _PossibleRuntimeImportVisitor(ast.NodeVisitor):
    def __init__(
        self,
        current: str,
        current_package: str,
        modules: set[str],
    ) -> None:
        self.current = current
        self.current_package = current_package
        self.modules = modules
        self.function_depth = 0
        self.edges: dict[str, set[tuple[str, str]]] = {
            "ast_eager_import": set(),
            "ast_delayed_import": set(),
        }

    @property
    def edge_kind(self) -> str:
        return "ast_delayed_import" if self.function_depth else "ast_eager_import"

    def _record(self, target: str | None, *, allow_self: bool = False) -> None:
        if target not in self.modules:
            return
        if target == self.current and not allow_self:
            return
        self.edges[self.edge_kind].add((self.current, target))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        value = _module_graph_type_checking_value(node.test)
        branches: Iterable[ast.stmt]
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
            self._record(alias.name, allow_self=True)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            relative = "." * node.level + (node.module or "")
            try:
                base = importlib.util.resolve_name(relative, self.current_package)
            except ImportError:
                return
        else:
            base = node.module
        self._record(base)
        if node.module is not None or not base:
            return
        for alias in node.names:
            if alias.name != "*":
                self._record(f"{base}.{alias.name}", allow_self=True)


def _module_graph_ast_edges(
    inventory: _ModuleGraphMapping[Path, tuple[str, bool]],
) -> dict[str, set[tuple[str, str]]]:
    modules = {name for name, _is_package in inventory.values()}
    edges = {"ast_eager_import": set(), "ast_delayed_import": set()}
    for path, (name, is_package) in inventory.items():
        current_package = name if is_package else name.rpartition(".")[0]
        visitor = _PossibleRuntimeImportVisitor(name, current_package, modules)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for kind in edges:
            edges[kind].update(visitor.edges[kind])
    return edges


def _module_graph_level_statements(
    statements: Iterable[ast.stmt],
) -> Iterable[ast.stmt]:
    for statement in statements:
        yield statement
        nested: list[ast.stmt] = []
        if isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.If)):
            nested.extend(statement.body)
            nested.extend(statement.orelse)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            nested.extend(statement.body)
        elif isinstance(statement, (ast.Try, ast.TryStar)):
            nested.extend(statement.body)
            nested.extend(statement.orelse)
            nested.extend(statement.finalbody)
            for handler in statement.handlers:
                nested.extend(handler.body)
        elif isinstance(statement, ast.Match):
            for case in statement.cases:
                nested.extend(case.body)
        if nested:
            yield from _module_graph_level_statements(nested)


def _module_graph_export_owner(value: ast.expr) -> str | None:
    if not isinstance(value, (ast.Tuple, ast.List)) or not value.elts:
        return None
    owner = value.elts[0]
    if isinstance(owner, ast.Constant) and isinstance(owner.value, str):
        return owner.value
    return None


def _module_graph_exports_target(target: ast.expr) -> bool:
    return (
        isinstance(target, ast.Name) and target.id == "_EXPORTS"
    ) or (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id == "_EXPORTS"
    )


def _module_graph_lazy_export_edges(
    inventory: _ModuleGraphMapping[Path, tuple[str, bool]],
) -> set[tuple[str, str]]:
    modules = {name for name, _is_package in inventory.values()}
    edges: set[tuple[str, str]] = set()
    for path, (name, is_package) in inventory.items():
        if not is_package:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in _module_graph_level_statements(tree.body):
            values: list[ast.expr] = []
            if isinstance(statement, ast.Assign):
                if any(_module_graph_exports_target(target) for target in statement.targets):
                    if isinstance(statement.value, ast.Dict):
                        values.extend(statement.value.values)
                    else:
                        values.append(statement.value)
            elif (
                isinstance(statement, ast.AnnAssign)
                and _module_graph_exports_target(statement.target)
                and statement.value is not None
            ):
                if isinstance(statement.value, ast.Dict):
                    values.extend(statement.value.values)
                else:
                    values.append(statement.value)
            for value in values:
                owner = _module_graph_export_owner(value)
                if not owner:
                    continue
                try:
                    target = (
                        importlib.util.resolve_name(owner, name)
                        if owner.startswith(".")
                        else owner
                    )
                except ImportError:
                    continue
                if target in modules and target != name:
                    edges.add((name, target))
    return edges


def module_graph_edge_kinds(
    package_root: Path = PACKAGE_ROOT,
) -> tuple[dict[Path, tuple[str, bool]], dict[str, set[tuple[str, str]]]]:
    inventory = module_inventory(package_root)
    ast_edges = _module_graph_ast_edges(inventory)
    modules = {name for name, _is_package in inventory.values()}
    parent_edges = {
        (name, parent)
        for name in modules
        if (parent := name.rpartition(".")[0]) in modules
    }
    return inventory, {
        **ast_edges,
        "lazy_export_owner": _module_graph_lazy_export_edges(inventory),
        "package_parent": parent_edges,
    }


def module_graph_for_profile(
    nodes: Iterable[str],
    edge_kinds: _ModuleGraphMapping[str, set[tuple[str, str]]],
    selected_kinds: Iterable[str],
) -> dict[str, set[str]]:
    graph = {node: set() for node in nodes}
    for kind in selected_kinds:
        for source, target in edge_kinds[kind]:
            graph[source].add(target)
    return graph


def module_graph_sccs(
    graph: _ModuleGraphMapping[str, set[str]],
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
        components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            connect(node)
    return sorted(components, key=lambda component: (-len(component), component))


def module_graph_cyclic_sccs(
    graph: _ModuleGraphMapping[str, set[str]],
) -> list[list[str]]:
    return [
        component
        for component in module_graph_sccs(graph)
        if len(component) > 1 or component[0] in graph[component[0]]
    ]


def _module_graph_graph_sha256(
    graph: _ModuleGraphMapping[str, set[str]],
) -> str:
    rows = [
        {"module": node, "dependencies": sorted(graph[node])}
        for node in sorted(graph)
    ]
    return module_graph_canonical_sha256(rows)


def _module_graph_profile_summary(
    graph: _ModuleGraphMapping[str, set[str]],
    *,
    include_members: bool,
) -> dict[str, _ModuleGraphAny]:
    components = module_graph_cyclic_sccs(graph)
    summary: dict[str, _ModuleGraphAny] = {
        "cyclic_scc_count": len(components),
        "cyclic_scc_sha256": module_graph_canonical_sha256(components),
        "cyclic_scc_sizes": [len(component) for component in components],
        "edge_count": sum(len(targets) for targets in graph.values()),
        "graph_sha256": _module_graph_graph_sha256(graph),
        "largest_cyclic_scc_size": len(components[0]) if components else 0,
        "self_loop_scc_count": sum(len(component) == 1 for component in components),
    }
    if include_members:
        summary["cyclic_sccs"] = components
    return summary


def module_graph_measurement(
    package_root: Path = PACKAGE_ROOT,
    definition: _ModuleGraphMapping[str, _ModuleGraphAny] | None = None,
    *,
    include_members: bool = False,
) -> dict[str, _ModuleGraphAny]:
    selected_definition = definition or module_graph_definition()
    inventory, edge_kinds = module_graph_edge_kinds(package_root)
    nodes = [name for name, _is_package in inventory.values()]
    profiles = {
        profile: _module_graph_profile_summary(
            module_graph_for_profile(nodes, edge_kinds, selected_kinds),
            include_members=include_members,
        )
        for profile, selected_kinds in selected_definition["profiles"].items()
    }
    return {
        "definition_id": selected_definition["definition_id"],
        "definition_sha256": module_graph_canonical_sha256(selected_definition),
        "edge_kind_counts": {
            kind: len(edge_kinds[kind]) for kind in MODULE_GRAPH_EDGE_KINDS
        },
        "node_count": len(nodes),
        "profiles": profiles,
    }


def module_graph_adjacency(
    package_root: Path,
    definition: _ModuleGraphMapping[str, _ModuleGraphAny],
    profile: str,
) -> dict[str, _ModuleGraphAny]:
    try:
        selected_kinds = definition["profiles"][profile]
    except KeyError as exc:
        raise ValueError(f"unknown module graph profile {profile!r}") from exc
    inventory, edge_kinds = module_graph_edge_kinds(package_root)
    graph = module_graph_for_profile(
        (name for name, _is_package in inventory.values()),
        edge_kinds,
        selected_kinds,
    )
    return {
        "definition_id": definition["definition_id"],
        "edges": {
            module: sorted(dependencies)
            for module, dependencies in sorted(graph.items())
        },
        "profile": profile,
    }


def _module_graph_family(module: str, package_name: str) -> str:
    relative = module.removeprefix(package_name).lstrip(".")
    if not relative:
        return "<root-package>"
    head, separator, _tail = relative.partition(".")
    if separator:
        return head
    public_head = head.lstrip("_")
    prefix = public_head.split("_", 1)[0]
    return f"_{prefix}" if head.startswith("_") else prefix


def module_graph_render_text(
    report: _ModuleGraphMapping[str, _ModuleGraphAny],
    definition: _ModuleGraphMapping[str, _ModuleGraphAny],
    *,
    include_members: bool = False,
) -> str:
    package_name = Path(definition["scope"]["package_root"]).name
    lines = [
        f"definition: {report['definition_id']}",
        f"definition_sha256: {report['definition_sha256']}",
        f"package_root: {definition['scope']['package_root']}",
        f"nodes: {report['node_count']}",
        "edge_kinds: " + ", ".join(
            f"{kind}={count}" for kind, count in report["edge_kind_counts"].items()
        ),
    ]
    for profile in MODULE_GRAPH_PROFILE_ORDER:
        summary = report["profiles"][profile]
        lines.extend(
            (
                "",
                f"profile: {profile}",
                f"edges: {summary['edge_count']}",
                f"cyclic_sccs: {summary['cyclic_scc_count']}",
                f"self_loop_sccs: {summary['self_loop_scc_count']}",
                f"largest_cyclic_scc: {summary['largest_cyclic_scc_size']}",
                f"graph_sha256: {summary['graph_sha256']}",
            )
        )
        for index, component in enumerate(summary["cyclic_sccs"], start=1):
            families = _ModuleGraphCounter(
                _module_graph_family(module, package_name) for module in component
            )
            family_text = ", ".join(
                f"{family}={count}"
                for family, count in sorted(
                    families.items(), key=lambda item: (-item[1], item[0])
                )
            )
            lines.append(f"scc[{index}]: size={len(component)}; families={family_text}")
            if include_members:
                lines.append("  members: " + ", ".join(component))
    return "\n".join(lines) + "\n"


def module_graph_main(argv: _ModuleGraphSequence[str] | None = None) -> int:
    parser = _module_graph_argparse.ArgumentParser(
        description="Build the governed Gravity SDK module graph and SCC report."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report", help="print the SCC report")
    report_parser.add_argument("--json", action="store_true")
    report_parser.add_argument("--members", action="store_true")
    graph_parser = subparsers.add_parser("graph", help="print JSON adjacency")
    graph_parser.add_argument("--profile")
    subparsers.add_parser("check", help="compare with the embedded baseline")
    args = parser.parse_args(argv)
    definition = module_graph_definition()
    package_root = ROOT / definition["scope"]["package_root"]
    if args.command == "graph":
        profile = args.profile or definition["canonical_profile"]
        try:
            graph = module_graph_adjacency(package_root, definition, profile)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "report":
        report = module_graph_measurement(
            package_root,
            definition,
            include_members=True,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(
                module_graph_render_text(
                    report,
                    definition,
                    include_members=args.members,
                ),
                end="",
            )
        return 0
    observed = module_graph_measurement(package_root, definition)
    expected = module_graph_baseline()
    if observed != expected:
        print("FAIL module dependency graph baseline drift")
        return 1
    canonical = observed["profiles"][definition["canonical_profile"]]
    print(
        "PASS module dependency graph: "
        f"nodes={observed['node_count']} "
        f"cyclic_sccs={canonical['cyclic_scc_count']} "
        f"largest={canonical['largest_cyclic_scc_size']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(module_graph_main())
