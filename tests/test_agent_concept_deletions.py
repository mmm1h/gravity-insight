"""AST gates for the two concepts R17 plans to delete or consolidate."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import copy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src/gravity_sdk"
OLD_PAGINATION_OWNER = "gravity_sdk.agent_pagination"
NEW_PAGINATION_OWNER = "gravity_sdk.pagination_completeness"
OLD_PAGINATION_CONSUMER = "gravity_sdk.agent_sources"
NEW_PAGINATION_CONSUMER = "gravity_sdk.agents.sources"
OLD_METADATA_OWNER = "gravity_sdk.agent_batch_sources"
NEW_METADATA_OWNER = "gravity_sdk.agents.batch_sources"


@dataclass(frozen=True)
class _ModuleSource:
    module: str
    relative: str
    source: str
    tree: ast.Module
    is_package: bool = False


def _module_name(path: Path, package_root: Path) -> tuple[str, bool]:
    relative = path.relative_to(package_root).with_suffix("")
    parts = [package_root.name, *relative.parts]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _repository_modules(package_root: Path = PACKAGE_ROOT) -> list[_ModuleSource]:
    result: list[_ModuleSource] = []
    for path in sorted(package_root.rglob("*.py")):
        module, is_package = _module_name(path, package_root)
        source = path.read_text(encoding="utf-8")
        result.append(
            _ModuleSource(
                module=module,
                relative=path.relative_to(ROOT).as_posix(),
                source=source,
                tree=ast.parse(source, filename=str(path)),
                is_package=is_package,
            )
        )
    return result


def _synthetic_modules(sources: Mapping[str, str]) -> list[_ModuleSource]:
    return [
        _ModuleSource(
            module=module,
            relative=f"<{module}>",
            source=source,
            tree=ast.parse(source, filename=f"<{module}>"),
        )
        for module, source in sorted(sources.items())
    ]


def _resolve_from_import(module: _ModuleSource, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.module if module.is_package else module.module.rsplit(".", 1)[0]
    parts = package.split(".") if package else []
    remove = node.level - 1
    if remove:
        parts = parts[:-remove]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


@dataclass(frozen=True)
class _TargetUsage:
    imports: tuple[str, ...]
    references: tuple[str, ...]
    calls: tuple[str, ...]


def _bound_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for item in node.elts for name in _bound_names(item)}
    return set()


def _is_module_expression(node: ast.AST, module_expressions: set[str]) -> bool:
    dotted = _dotted_name(node)
    return dotted in module_expressions if dotted is not None else False


def _is_symbol_expression(
    node: ast.AST,
    *,
    symbol: str,
    symbol_names: set[str],
    module_expressions: set[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in symbol_names
    if isinstance(node, ast.Attribute):
        return node.attr == symbol and _is_module_expression(
            node.value, module_expressions
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and _is_module_expression(node.args[0], module_expressions)
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == symbol
    ):
        return True
    return False


def _location(module: _ModuleSource, node: ast.AST, kind: str) -> str:
    return f"{module.relative}:{node.lineno}:{kind}"


def _target_usage(
    modules: list[_ModuleSource], target_module: str, symbol: str
) -> _TargetUsage:
    imports: set[str] = set()
    references: set[str] = set()
    calls: set[str] = set()
    for module in modules:
        symbol_names = {symbol} if module.module == target_module else set()
        module_expressions: set[str] = set()
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_from_import(module, node)
                for alias in node.names:
                    imported_module = f"{resolved}.{alias.name}" if resolved else alias.name
                    if resolved == target_module and alias.name == symbol:
                        symbol_names.add(alias.asname or alias.name)
                        imports.add(_location(module, node, "import"))
                    elif resolved == target_module and alias.name == "*":
                        imports.add(_location(module, node, "star-import"))
                    elif imported_module == target_module:
                        module_expressions.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == target_module:
                        module_expressions.add(alias.asname or alias.name)

        changed = True
        while changed:
            changed = False
            for node in ast.walk(module.tree):
                targets: set[str] = set()
                value: ast.AST | None = None
                if isinstance(node, (ast.Assign, ast.NamedExpr)):
                    target_nodes = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    targets = {
                        name
                        for target in target_nodes
                        for name in _bound_names(target)
                    }
                    value = node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets = _bound_names(node.target)
                    value = node.value
                if value is None or not targets:
                    continue
                if _is_module_expression(value, module_expressions):
                    before = len(module_expressions)
                    module_expressions.update(targets)
                    changed = changed or len(module_expressions) != before
                if _is_symbol_expression(
                    value,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                ):
                    before = len(symbol_names)
                    symbol_names.update(targets)
                    changed = changed or len(symbol_names) != before

        for node in ast.walk(module.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in symbol_names:
                    references.add(_location(module, node, "reference"))
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                if _is_symbol_expression(
                    node,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                ):
                    references.add(_location(module, node, "attribute-reference"))
            elif isinstance(node, ast.Call):
                if _is_symbol_expression(
                    node,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                ):
                    references.add(_location(module, node, "reflective-reference"))
                if _is_symbol_expression(
                    node.func,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                ):
                    calls.add(_location(module, node, "call"))
    return _TargetUsage(
        imports=tuple(sorted(imports)),
        references=tuple(sorted(references)),
        calls=tuple(sorted(calls)),
    )


def _usage_files(locations: tuple[str, ...]) -> set[str]:
    return {location.rsplit(":", 2)[0] for location in locations}


def _function_definitions(
    modules: list[_ModuleSource], function_name: str
) -> list[tuple[_ModuleSource, ast.FunctionDef | ast.AsyncFunctionDef]]:
    return [
        (module, node)
        for module in modules
        for node in module.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]


def _compact_pagination_contract(
    modules: list[_ModuleSource],
) -> tuple[_ModuleSource, ast.FunctionDef | ast.AsyncFunctionDef]:
    by_name = {module.module: module for module in modules}
    if OLD_PAGINATION_OWNER in by_name:
        expected_owner = OLD_PAGINATION_OWNER
        expected_consumer = OLD_PAGINATION_CONSUMER
    else:
        expected_owner = NEW_PAGINATION_OWNER
        expected_consumer = (
            OLD_PAGINATION_CONSUMER
            if OLD_PAGINATION_CONSUMER in by_name
            else NEW_PAGINATION_CONSUMER
        )
    if expected_owner not in by_name or expected_consumer not in by_name:
        raise AssertionError(
            "compact_pagination phase has no exact owner/consumer pair: "
            f"owner={expected_owner}, consumer={expected_consumer}"
        )
    definitions = _function_definitions(modules, "compact_pagination")
    if len(definitions) != 1 or definitions[0][0].module != expected_owner:
        locations = [
            f"{module.relative}:{node.lineno}" for module, node in definitions
        ]
        raise AssertionError(
            f"compact_pagination must be defined only by {expected_owner}: {locations}"
        )
    owner, definition = definitions[0]
    usage = _target_usage(modules, expected_owner, "compact_pagination")
    external = tuple(
        location
        for location in (*usage.imports, *usage.references, *usage.calls)
        if location.rsplit(":", 2)[0] != owner.relative
    )
    consumer_file = by_name[expected_consumer].relative
    if _usage_files(external) != {consumer_file}:
        raise AssertionError(
            "compact_pagination must have only the exact source consumer "
            f"{expected_consumer}: {external}"
        )
    if _usage_files(usage.imports) != {consumer_file}:
        raise AssertionError(
            f"{expected_consumer} must import compact_pagination: {usage.imports}"
        )
    if _usage_files(usage.calls) != {consumer_file}:
        raise AssertionError(
            f"{expected_consumer} must call compact_pagination: {usage.calls}"
        )
    return owner, definition


def _assert_metadata_inventory_has_no_callers(
    sources: Mapping[str, str],
    target_module: str = OLD_METADATA_OWNER,
) -> None:
    usage = _target_usage(
        _synthetic_modules(sources), target_module, "metadata_inventory"
    )
    found = (*usage.imports, *usage.references, *usage.calls)
    if found:
        raise AssertionError(f"metadata_inventory references remain: {found}")


def _metadata_inventory_contract(modules: list[_ModuleSource]) -> None:
    by_name = {module.module: module for module in modules}
    old_owner_exists = OLD_METADATA_OWNER in by_name
    expected_state_owner = (
        OLD_METADATA_OWNER if old_owner_exists else NEW_METADATA_OWNER
    )
    if expected_state_owner not in by_name:
        raise AssertionError(
            f"metadata_inventory_state owner is missing: {expected_state_owner}"
        )
    state_definitions = _function_definitions(modules, "metadata_inventory_state")
    if (
        len(state_definitions) != 1
        or state_definitions[0][0].module != expected_state_owner
    ):
        raise AssertionError(
            f"metadata_inventory_state must remain in {expected_state_owner}"
        )

    wrapper_definitions = _function_definitions(modules, "metadata_inventory")
    if old_owner_exists:
        if (
            len(wrapper_definitions) != 1
            or wrapper_definitions[0][0].module != OLD_METADATA_OWNER
        ):
            raise AssertionError(
                f"baseline wrapper must exist only in {OLD_METADATA_OWNER}"
            )
    elif wrapper_definitions:
        locations = [
            f"{module.relative}:{node.lineno}"
            for module, node in wrapper_definitions
        ]
        raise AssertionError(
            f"terminal metadata_inventory wrapper must be absent: {locations}"
        )

    found: list[str] = []
    for owner in (OLD_METADATA_OWNER, NEW_METADATA_OWNER):
        usage = _target_usage(modules, owner, "metadata_inventory")
        found.extend((*usage.imports, *usage.references, *usage.calls))
    if found:
        raise AssertionError(
            f"metadata_inventory references remain: {sorted(set(found))}"
        )


def _load_isolated_function(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Any:
    selected = copy.deepcopy(definition)
    module = ast.fix_missing_locations(ast.Module(body=[selected], type_ignores=[]))
    namespace: dict[str, Any] = {"Any": Any, "Mapping": Mapping}
    exec(compile(module, "<compact_pagination_contract>", "exec"), namespace)
    return namespace[definition.name]


class AgentConceptDeletionTests(unittest.TestCase):
    def test_compact_pagination_has_single_source_consumer(self) -> None:
        _compact_pagination_contract(_repository_modules())

    def test_compact_pagination_guard_rejects_wrong_owner_and_consumer(self) -> None:
        cases = {
            "wrong owner": {
                NEW_PAGINATION_OWNER: "",
                NEW_PAGINATION_CONSUMER: "",
                "gravity_sdk.wrong": "def compact_pagination(value):\n    return value\n",
            },
            "wrong consumer": {
                NEW_PAGINATION_OWNER: (
                    "def compact_pagination(value):\n    return value\n"
                ),
                NEW_PAGINATION_CONSUMER: "",
                "gravity_sdk.wrong": (
                    "from gravity_sdk.pagination_completeness import "
                    "compact_pagination\n"
                    "result = compact_pagination(None)\n"
                ),
            },
        }
        for label, sources in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                AssertionError,
                "compact_pagination",
            ):
                _compact_pagination_contract(_synthetic_modules(sources))

    def test_metadata_inventory_wrapper_has_no_callers(self) -> None:
        modules = _repository_modules()
        _metadata_inventory_contract(modules)

        field_and_attribute_only = {
            "gravity_sdk.snapshot": (
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Snapshot:\n"
                "    metadata_inventory: tuple\n"
                "rows = sources.metadata_inventory\n"
                "other = getattr(sources, 'metadata_inventory', ())\n"
            )
        }
        _assert_metadata_inventory_has_no_callers(field_and_attribute_only)
        real_call = {
            "gravity_sdk.consumer": (
                f"from {OLD_METADATA_OWNER} import metadata_inventory\n"
                "metadata_inventory([])\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(real_call)

    def test_metadata_inventory_terminal_state_requires_wrapper_absence(self) -> None:
        terminal_without_wrapper = {
            NEW_METADATA_OWNER: (
                "def metadata_inventory_state(warnings):\n"
                "    return (), True\n"
            )
        }
        _metadata_inventory_contract(
            _synthetic_modules(terminal_without_wrapper)
        )

        terminal_with_wrapper = {
            NEW_METADATA_OWNER: (
                "def metadata_inventory_state(warnings):\n"
                "    return (), True\n"
                "def metadata_inventory(warnings):\n"
                "    return metadata_inventory_state(warnings)[0]\n"
            )
        }
        with self.assertRaisesRegex(
            AssertionError,
            "terminal metadata_inventory wrapper must be absent",
        ):
            _metadata_inventory_contract(
                _synthetic_modules(terminal_with_wrapper)
            )

    def test_metadata_inventory_guard_rejects_reexport(self) -> None:
        sources = {
            "gravity_sdk.consumer": (
                "from gravity_sdk.agent_batch_sources import metadata_inventory\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(sources)

    def test_metadata_inventory_guard_rejects_alias_flow(self) -> None:
        sources = {
            OLD_METADATA_OWNER: (
                "def metadata_inventory(warnings):\n"
                "    return ()\n"
                "forward = metadata_inventory\n"
                "forward([])\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(sources)

    def test_metadata_inventory_guard_rejects_callback(self) -> None:
        sources = {
            OLD_METADATA_OWNER: (
                "def metadata_inventory(warnings):\n"
                "    return ()\n"
                "register(metadata_inventory)\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(sources)

    def test_metadata_inventory_guard_rejects_getattr_call(self) -> None:
        sources = {
            "gravity_sdk.consumer": (
                "import gravity_sdk.agent_batch_sources as sources\n"
                "getattr(sources, 'metadata_inventory')([])\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(sources)

    def test_compact_pagination_output_contract_is_locked(self) -> None:
        modules = _repository_modules()
        _, definition = _compact_pagination_contract(modules)
        compact_pagination = _load_isolated_function(definition)
        cases = (
            (
                None,
                b'{"supported":false,"kind":"none","completeness":"unknown",'
                b'"pagination_evidence":"none"}',
            ),
            (
                {
                    "kind": "cursor",
                    "completeness": "complete",
                    "pagination_evidence": "wire",
                    "page_field": "cursor",
                    "page_size_field": "limit",
                    "max_page_size": 200,
                    "ignored": "not part of the output contract",
                },
                b'{"supported":true,"kind":"cursor","completeness":"complete",'
                b'"pagination_evidence":"wire","page_field":"cursor",'
                b'"page_size_field":"limit","max_page_size":200}',
            ),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                actual = json.dumps(
                    compact_pagination(value),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
