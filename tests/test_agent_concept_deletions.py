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


def _find_function_owner(
    modules: list[_ModuleSource], function_name: str
) -> tuple[_ModuleSource, ast.FunctionDef | ast.AsyncFunctionDef]:
    definitions = [
        (module, node)
        for module in modules
        for node in module.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(definitions) != 1:
        locations = [f"{module.relative}:{node.lineno}" for module, node in definitions]
        raise AssertionError(
            f"expected one {function_name} definition, found {locations}"
        )
    return definitions[0]


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


def _target_usage(
    modules: list[_ModuleSource], target_module: str, symbol: str
) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    calls: list[str] = []
    for module in modules:
        direct_names: set[str] = set()
        module_expressions: set[str] = set()
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_from_import(module, node)
                for alias in node.names:
                    imported_module = f"{resolved}.{alias.name}" if resolved else alias.name
                    if resolved == target_module and alias.name == symbol:
                        direct_names.add(alias.asname or alias.name)
                        imports.append(f"{module.relative}:{node.lineno}")
                    elif imported_module == target_module:
                        module_expressions.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == target_module:
                        module_expressions.add(alias.asname or alias.name)
        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and (
                node.func.id in direct_names
                or (module.module == target_module and node.func.id == symbol)
            ):
                calls.append(f"{module.relative}:{node.lineno}")
            elif isinstance(node.func, ast.Attribute) and node.func.attr == symbol:
                if _dotted_name(node.func.value) in module_expressions:
                    calls.append(f"{module.relative}:{node.lineno}")
    return sorted(set(imports)), sorted(set(calls))


def _assert_metadata_inventory_has_no_callers(
    sources: Mapping[str, str],
    target_module: str = "gravity_sdk.agent_batch_sources",
) -> None:
    _, calls = _target_usage(
        _synthetic_modules(sources), target_module, "metadata_inventory"
    )
    if calls:
        raise AssertionError(f"metadata_inventory() has callers: {calls}")


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
        modules = _repository_modules()
        owner, _ = _find_function_owner(modules, "compact_pagination")
        imports, calls = _target_usage(modules, owner.module, "compact_pagination")
        consumers = {
            location.rsplit(":", 1)[0]
            for location in [*imports, *calls]
            if location.rsplit(":", 1)[0] != owner.relative
        }
        self.assertEqual(
            1,
            len(consumers),
            f"compact_pagination consumers changed: {sorted(consumers)}",
        )
        self.assertTrue(calls, "the sole compact_pagination consumer no longer calls it")

    def test_metadata_inventory_wrapper_has_no_callers(self) -> None:
        modules = _repository_modules()
        owner, _ = _find_function_owner(modules, "metadata_inventory")
        _, calls = _target_usage(modules, owner.module, "metadata_inventory")
        self.assertEqual([], calls, f"metadata_inventory() callers changed: {calls}")

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
        _assert_metadata_inventory_has_no_callers(field_and_attribute_only, owner.module)
        real_call = {
            "gravity_sdk.consumer": (
                f"from {owner.module} import metadata_inventory\n"
                "metadata_inventory([])\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*callers"):
            _assert_metadata_inventory_has_no_callers(real_call, owner.module)

    def test_compact_pagination_output_contract_is_locked(self) -> None:
        modules = _repository_modules()
        _, definition = _find_function_owner(modules, "compact_pagination")
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
