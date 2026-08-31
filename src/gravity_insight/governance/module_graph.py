"""Governed possible-runtime module graph used by boundary quality gates."""

from __future__ import annotations

import ast
import importlib.util
import json
from collections.abc import Iterable
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT = PACKAGE_ROOT.parents[1]


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


# Unified v1 graph for technical debt #14, shared by quality and audit.
import hashlib as _module_graph_hashlib
from typing import Any as _ModuleGraphAny
from typing import Mapping as _ModuleGraphMapping


MODULE_GRAPH_DEFINITION_START = "<!-- MODULE_GRAPH_DEFINITION_V1_START -->"
MODULE_GRAPH_DEFINITION_END = "<!-- MODULE_GRAPH_DEFINITION_V1_END -->"
MODULE_GRAPH_BASELINE_START = "<!-- MODULE_GRAPH_BASELINE_V1_START -->"
MODULE_GRAPH_BASELINE_END = "<!-- MODULE_GRAPH_BASELINE_V1_END -->"
MODULE_GRAPH_DEBT_PATH = ROOT / "docs/maintainers/technical-debt.md"
MODULE_GRAPH_CURRENT_DEFINITION_ID = (
    "gravity-insight-runtime-possible-module-dependency-graph.v1"
)
MODULE_GRAPH_CURRENT_PACKAGE_ROOT = "src/gravity_insight"
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


def module_graph_current_definition(
    path: Path = MODULE_GRAPH_DEBT_PATH,
) -> dict[str, _ModuleGraphAny]:
    """Project the embedded graph contract onto the current package identity."""

    definition = module_graph_definition(path)
    definition["definition_id"] = MODULE_GRAPH_CURRENT_DEFINITION_ID
    scope = definition["scope"]
    scope["package_root"] = MODULE_GRAPH_CURRENT_PACKAGE_ROOT
    for field in ("excluded", "package_init"):
        scope[field] = scope[field].replace("gravity_sdk", "gravity_insight")
    return definition


def _module_graph_boolean_value(node: ast.BoolOp) -> bool | None:
    values = [_module_graph_type_checking_value(value) for value in node.values]
    if isinstance(node.op, ast.And):
        if False in values:
            return False
        return True if all(value is True for value in values) else None
    if True in values:
        return True
    return False if all(value is False for value in values) else None


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
        return _module_graph_boolean_value(node)
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


def _module_graph_assignment_values(statement: ast.stmt) -> tuple[ast.expr, ...]:
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign) and any(
        _module_graph_exports_target(target) for target in statement.targets
    ):
        value = statement.value
    elif (
        isinstance(statement, ast.AnnAssign)
        and _module_graph_exports_target(statement.target)
    ):
        value = statement.value
    if value is None:
        return ()
    return tuple(value.values) if isinstance(value, ast.Dict) else (value,)


def _module_graph_resolved_export_owner(
    value: ast.expr,
    *,
    package: str,
    modules: set[str],
) -> str | None:
    owner = _module_graph_export_owner(value)
    if not owner:
        return None
    try:
        target = (
            importlib.util.resolve_name(owner, package)
            if owner.startswith(".")
            else owner
        )
    except ImportError:
        return None
    return target if target in modules and target != package else None


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
            for value in _module_graph_assignment_values(statement):
                target = _module_graph_resolved_export_owner(
                    value,
                    package=name,
                    modules=modules,
                )
                if target is not None:
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
