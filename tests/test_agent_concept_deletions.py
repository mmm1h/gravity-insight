"""AST gates for the two concepts R17 plans to delete or consolidate."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src/gravity_insight"
HISTORICAL_PACKAGE_ROOT = "gravity_sdk"
CURRENT_PACKAGE_ROOT = "gravity_insight"
OLD_PAGINATION_OWNER = "gravity_insight.agent_pagination"
NEW_PAGINATION_OWNER = "gravity_insight.pagination_completeness"
OLD_PAGINATION_CONSUMER = "gravity_insight.agent_sources"
NEW_PAGINATION_CONSUMER = "gravity_insight.agents.sources"
OLD_METADATA_OWNER = "gravity_insight.agent_batch_sources"
NEW_METADATA_OWNER = "gravity_insight.agents.batch_sources"


@dataclass(frozen=True)
class _ModuleSource:
    module: str
    relative: str
    source: str
    tree: ast.Module
    is_package: bool = False
    is_native_extension: bool = False


def _module_name(path: Path, package_root: Path) -> tuple[str, bool]:
    relative = path.relative_to(package_root).with_suffix("")
    parts = [package_root.name, *relative.parts]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _uncached_repository_modules(package_root: Path = PACKAGE_ROOT) -> list[_ModuleSource]:
    result: list[_ModuleSource] = []
    paths = set(package_root.rglob("*.py"))
    for pattern in ("*.pyd", "*.so", "*.dll", "*.dylib"):
        paths.update(package_root.rglob(pattern))
    for path in sorted(paths):
        module, is_package = _module_name(path, package_root)
        native = path.suffix.lower() != ".py"
        source = "" if native else path.read_text(encoding="utf-8")
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.relative_to(package_root.parent).as_posix()
        result.append(
            _ModuleSource(
                module=module,
                relative=relative,
                source=source,
                tree=ast.parse(source, filename=str(path)),
                is_package=is_package,
                is_native_extension=native,
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
    blockers: tuple[str, ...]


_REVIEWED_OPAQUE_IMPORT_EXPRESSIONS = {
    "gravity_insight": {"module_name"},
    "gravity_insight.runtime": {"name"},
    "gravity_insight.prober.cli": {'sdk.__name__ + ".errors"'},
    "gravity_insight.prober.export_verify": {'f"{base}.{name}"'},
    "gravity_insight.prober.transport": {
        'base + ".models"',
        'base + ".registry"',
        'base + ".executor"',
        'base + ".transport"',
        'base + ".http_runtime"',
        'base + ".credentials"',
    },
}


def _source_expression(module: _ModuleSource, node: ast.AST) -> str:
    value = ast.get_source_segment(module.source, node)
    return value if value is not None else ast.unparse(node)


def _reviewed_opaque_import(module: _ModuleSource, expression: ast.AST) -> bool:
    return _source_expression(module, expression) in _REVIEWED_OPAQUE_IMPORT_EXPRESSIONS.get(
        module.module, set()
    )


def _bound_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for item in node.elts for name in _bound_names(item)}
    return set()


def _string_values(
    node: ast.AST, bindings: Mapping[str, set[str]]
) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(bindings.get(node.id, ()))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return {
            left + right
            for left in _string_values(node.left, bindings)
            for right in _string_values(node.right, bindings)
        }
    if isinstance(node, ast.JoinedStr):
        chunks: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return set()
            chunks.append(value.value)
        return {"".join(chunks)}
    return set()


def _is_named_expression(node: ast.AST, names: set[str]) -> bool:
    dotted = _dotted_name(node)
    return dotted in names if dotted is not None else False


def _is_module_expression(
    node: ast.AST,
    *,
    target_module: str,
    module_expressions: set[str],
    import_loaders: set[str],
    module_registries: set[str],
    string_bindings: Mapping[str, set[str]],
) -> bool:
    if _is_named_expression(node, module_expressions):
        return True
    if isinstance(node, ast.Call) and _is_named_expression(
        node.func, import_loaders
    ):
        return bool(node.args) and target_module in _string_values(
            node.args[0], string_bindings
        )
    if isinstance(node, ast.Subscript) and _is_named_expression(
        node.value, module_registries
    ):
        return target_module in _string_values(node.slice, string_bindings)
    return False


def _is_symbol_expression(
    node: ast.AST,
    *,
    target_module: str,
    symbol: str,
    symbol_names: set[str],
    module_expressions: set[str],
    import_loaders: set[str],
    module_registries: set[str],
    getattr_functions: set[str],
    string_bindings: Mapping[str, set[str]],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in symbol_names
    if isinstance(node, ast.Attribute):
        return node.attr == symbol and _is_module_expression(
            node.value,
            target_module=target_module,
            module_expressions=module_expressions,
            import_loaders=import_loaders,
            module_registries=module_registries,
            string_bindings=string_bindings,
        )
    if (
        isinstance(node, ast.Call)
        and _is_named_expression(node.func, getattr_functions)
        and len(node.args) >= 2
        and _is_module_expression(
            node.args[0],
            target_module=target_module,
            module_expressions=module_expressions,
            import_loaders=import_loaders,
            module_registries=module_registries,
            string_bindings=string_bindings,
        )
        and symbol in _string_values(node.args[1], string_bindings)
    ):
        return True
    return False


def _is_string_patch_reference(
    node: ast.Call,
    *,
    target_module: str,
    symbol: str,
    module_expressions: set[str],
    import_loaders: set[str],
    module_registries: set[str],
    patch_functions: set[str],
    patch_object_functions: set[str],
    string_bindings: Mapping[str, set[str]],
) -> bool:
    called = _dotted_name(node.func)
    if called in patch_functions or (called or "").endswith(".setattr"):
        if not node.args:
            return False
        values = _string_values(node.args[0], string_bindings)
        if f"{target_module}.{symbol}" in values:
            return True
        return (
            len(node.args) >= 2
            and target_module in values
            and symbol in _string_values(node.args[1], string_bindings)
        )
    if called not in patch_object_functions or len(node.args) < 2:
        return False
    return _is_module_expression(
        node.args[0],
        target_module=target_module,
        module_expressions=module_expressions,
        import_loaders=import_loaders,
        module_registries=module_registries,
        string_bindings=string_bindings,
    ) and symbol in _string_values(node.args[1], string_bindings)


def _location(module: _ModuleSource, node: ast.AST, kind: str) -> str:
    return f"{module.relative}:{node.lineno}:{kind}"


def _enumerated_target_usage(
    modules: list[_ModuleSource], target_module: str, symbol: str
) -> _TargetUsage:
    imports: set[str] = set()
    references: set[str] = set()
    calls: set[str] = set()
    blockers: set[str] = set()
    for module in modules:
        if module.is_native_extension:
            blockers.add(f"{module.relative}:0:blocker:native-extension-module")
            continue
        symbol_names = {symbol} if module.module == target_module else set()
        module_expressions: set[str] = set()
        import_loaders = {"__import__", "importlib.import_module"}
        module_registries = {"sys.modules"}
        getattr_functions = {"getattr"}
        patch_functions = {
            "patch",
            "mock.patch",
            "unittest.mock.patch",
            "monkeypatch.setattr",
        }
        patch_object_functions = {
            "patch.object",
            "mock.patch.object",
            "unittest.mock.patch.object",
        }
        string_bindings: dict[str, set[str]] = {}
        for node in ast.walk(module.tree):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_from_import(module, node)
                for alias in node.names:
                    bound = alias.asname or alias.name
                    imported_module = f"{resolved}.{alias.name}" if resolved else alias.name
                    if resolved == target_module and alias.name == symbol:
                        symbol_names.add(bound)
                        imports.add(_location(module, node, "import"))
                    elif resolved == target_module and alias.name == "*":
                        imports.add(_location(module, node, "star-import"))
                    elif imported_module == target_module:
                        module_expressions.add(bound)
                    if resolved == "importlib" and alias.name == "import_module":
                        import_loaders.add(bound)
                    elif resolved == "sys" and alias.name == "modules":
                        module_registries.add(bound)
                    elif resolved in {"unittest.mock", "mock"} and alias.name == "patch":
                        patch_functions.add(bound)
                        patch_object_functions.add(f"{bound}.object")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".", 1)[0]
                    if alias.name == target_module:
                        module_expressions.add(alias.asname or alias.name)
                    if alias.name == "importlib":
                        import_loaders.add(f"{bound}.import_module")
                    elif alias.name == "sys":
                        module_registries.add(f"{bound}.modules")
                    elif alias.name in {"unittest.mock", "mock"}:
                        patch_functions.add(f"{bound}.patch")
                        patch_object_functions.add(f"{bound}.patch.object")

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
                values = _string_values(value, string_bindings)
                for target in targets:
                    previous = len(string_bindings.get(target, ()))
                    string_bindings.setdefault(target, set()).update(values)
                    changed = changed or len(string_bindings[target]) != previous
                if _is_module_expression(
                    value,
                    target_module=target_module,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    string_bindings=string_bindings,
                ):
                    before = len(module_expressions)
                    module_expressions.update(targets)
                    changed = changed or len(module_expressions) != before
                if _is_symbol_expression(
                    value,
                    target_module=target_module,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    getattr_functions=getattr_functions,
                    string_bindings=string_bindings,
                ):
                    before = len(symbol_names)
                    symbol_names.update(targets)
                    changed = changed or len(symbol_names) != before
                dotted = _dotted_name(value)
                for bindings in (
                    import_loaders,
                    module_registries,
                    getattr_functions,
                    patch_functions,
                    patch_object_functions,
                ):
                    if dotted in bindings if dotted is not None else False:
                        before = len(bindings)
                        bindings.update(targets)
                        changed = changed or len(bindings) != before

        loader_wrappers = {
            node.name
            for node in ast.walk(module.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(descendant, ast.Call)
                and _is_named_expression(descendant.func, import_loaders)
                for descendant in ast.walk(node)
            )
        }
        known_callback_targets = {
            *import_loaders,
            *getattr_functions,
            *patch_functions,
            *patch_object_functions,
            *loader_wrappers,
        }

        for node in ast.walk(module.tree):
            dotted = _dotted_name(node)
            if dotted == "meta_path" or (dotted or "").endswith(".meta_path"):
                blockers.add(_location(module, node, "blocker:meta-path-import-hook"))
            if not isinstance(node, ast.Call):
                continue
            called = _dotted_name(node.func)
            if called in {"eval", "exec", "builtins.eval", "builtins.exec"}:
                blockers.add(_location(module, node, f"blocker:{called}-execution"))
            if called in import_loaders:
                values = _string_values(node.args[0], string_bindings) if node.args else set()
                if not values and (
                    not node.args or not _reviewed_opaque_import(module, node.args[0])
                ):
                    blockers.add(
                        _location(module, node, "blocker:opaque-module-name")
                    )
            if called in loader_wrappers:
                values = {
                    value
                    for argument in node.args
                    for value in _string_values(argument, string_bindings)
                }
                if target_module in values:
                    blockers.add(
                        _location(module, node, "blocker:cross-function-loader")
                    )
            if called not in known_callback_targets and any(
                _is_module_expression(
                    argument,
                    target_module=target_module,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    string_bindings=string_bindings,
                )
                for argument in node.args
            ):
                blockers.add(
                    _location(module, node, "blocker:module-object-callback")
                )

        for node in ast.walk(module.tree):
            container_values: list[ast.AST] = []
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                container_values = list(node.elts)
            elif isinstance(node, ast.Dict):
                container_values = [*node.keys, *node.values]
            if any(
                value is not None
                and _is_module_expression(
                    value,
                    target_module=target_module,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    string_bindings=string_bindings,
                )
                for value in container_values
            ):
                blockers.add(
                    _location(module, node, "blocker:module-object-container")
                )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                returns_module = any(
                    isinstance(descendant, ast.Return)
                    and descendant.value is not None
                    and _is_module_expression(
                        descendant.value,
                        target_module=target_module,
                        module_expressions=module_expressions,
                        import_loaders=import_loaders,
                        module_registries=module_registries,
                        string_bindings=string_bindings,
                    )
                    for descendant in ast.walk(node)
                )
                contains_lambda = isinstance(node, ast.Lambda) or any(
                    isinstance(descendant, ast.Lambda)
                    for descendant in ast.walk(node)
                    if descendant is not node
                )
                closes_over_module = contains_lambda and any(
                    isinstance(descendant, ast.Name)
                    and descendant.id in module_expressions
                    for descendant in ast.walk(node)
                )
                if returns_module or closes_over_module:
                    blockers.add(
                        _location(module, node, "blocker:module-object-closure")
                    )

        for node in ast.walk(module.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in symbol_names:
                    references.add(_location(module, node, "reference"))
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                if _is_symbol_expression(
                    node,
                    target_module=target_module,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    getattr_functions=getattr_functions,
                    string_bindings=string_bindings,
                ):
                    references.add(_location(module, node, "attribute-reference"))
            elif isinstance(node, ast.Call):
                if _is_symbol_expression(
                    node,
                    target_module=target_module,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    getattr_functions=getattr_functions,
                    string_bindings=string_bindings,
                ):
                    references.add(_location(module, node, "reflective-reference"))
                if _is_string_patch_reference(
                    node,
                    target_module=target_module,
                    symbol=symbol,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    patch_functions=patch_functions,
                    patch_object_functions=patch_object_functions,
                    string_bindings=string_bindings,
                ):
                    references.add(_location(module, node, "patch-reference"))
                if _is_symbol_expression(
                    node.func,
                    target_module=target_module,
                    symbol=symbol,
                    symbol_names=symbol_names,
                    module_expressions=module_expressions,
                    import_loaders=import_loaders,
                    module_registries=module_registries,
                    getattr_functions=getattr_functions,
                    string_bindings=string_bindings,
                ):
                    calls.add(_location(module, node, "call"))
    return _TargetUsage(
        imports=tuple(sorted(imports)),
        references=tuple(sorted(references)),
        calls=tuple(sorted(calls)),
        blockers=tuple(sorted(blockers)),
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
        for location in (*usage.imports, *usage.references, *usage.calls, *usage.blockers)
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
    found = (*usage.imports, *usage.references, *usage.calls, *usage.blockers)
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
        found.extend((*usage.imports, *usage.references, *usage.calls, *usage.blockers))
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
                "gravity_insight.wrong": "def compact_pagination(value):\n    return value\n",
            },
            "wrong consumer": {
                NEW_PAGINATION_OWNER: (
                    "def compact_pagination(value):\n    return value\n"
                ),
                NEW_PAGINATION_CONSUMER: "",
                "gravity_insight.wrong": (
                    "from gravity_insight.pagination_completeness import "
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

    def test_compact_pagination_guard_rejects_dynamic_extra_consumer(self) -> None:
        sources = {
            NEW_PAGINATION_OWNER: (
                "def compact_pagination(value):\n"
                "    return value\n"
            ),
            NEW_PAGINATION_CONSUMER: (
                f"from {NEW_PAGINATION_OWNER} import compact_pagination\n"
                "result = compact_pagination(None)\n"
            ),
            "gravity_insight.extra_consumer": (
                "from importlib import import_module\n"
                f"module_name = {NEW_PAGINATION_OWNER!r}\n"
                "loader = import_module\n"
                "owner = loader(module_name)\n"
                "getattr(owner, 'compact_pagination')(None)\n"
            ),
        }
        with self.assertRaisesRegex(
            AssertionError,
            "compact_pagination must have only the exact source consumer",
        ):
            _compact_pagination_contract(_synthetic_modules(sources))

    def test_metadata_inventory_wrapper_has_no_callers(self) -> None:
        modules = _repository_modules()
        _metadata_inventory_contract(modules)

        field_and_attribute_only = {
            "gravity_insight.snapshot": (
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
            "gravity_insight.consumer": (
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
            "gravity_insight.consumer": (
                "from gravity_insight.agent_batch_sources import metadata_inventory\n"
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
            "gravity_insight.consumer": (
                "import gravity_insight.agent_batch_sources as sources\n"
                "getattr(sources, 'metadata_inventory')([])\n"
            )
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _assert_metadata_inventory_has_no_callers(sources)

    def test_metadata_inventory_guard_rejects_dynamic_terminal_caller(self) -> None:
        sources = {
            NEW_METADATA_OWNER: (
                "def metadata_inventory_state(warnings):\n"
                "    return (), True\n"
            ),
            "gravity_insight.extra_consumer": (
                "loader = __import__\n"
                f"module_name = {NEW_METADATA_OWNER!r}\n"
                "owner = loader(module_name, fromlist=['metadata_inventory'])\n"
                "getattr(owner, 'metadata_inventory')([])\n"
            ),
        }
        with self.assertRaisesRegex(AssertionError, "metadata_inventory.*references"):
            _metadata_inventory_contract(_synthetic_modules(sources))

    def test_dynamic_symbol_guard_covers_enumerated_loader_shapes(self) -> None:
        cases = {
            "import_module": (
                "from importlib import import_module as load\n"
                f"path = {NEW_METADATA_OWNER!r}\n"
                "module = load(path)\n"
                "getattr(module, 'metadata_inventory')([])\n"
            ),
            "dunder_import": (
                "load = __import__\n"
                f"path = {NEW_METADATA_OWNER!r}\n"
                "module = load(path, fromlist=['metadata_inventory'])\n"
                "function = module.metadata_inventory\n"
                "function([])\n"
            ),
            "sys_modules": (
                "import sys as runtime\n"
                "registry = runtime.modules\n"
                f"path = {NEW_METADATA_OWNER!r}\n"
                "module = registry[path]\n"
                "function = getattr(module, 'metadata_inventory')\n"
                "function([])\n"
            ),
            "string_patch": (
                "from unittest.mock import patch as replace\n"
                f"target = {f'{NEW_METADATA_OWNER}.metadata_inventory'!r}\n"
                "replace(target)\n"
            ),
            "module_object_patch": (
                "from importlib import import_module\n"
                "from unittest.mock import patch\n"
                f"path = {NEW_METADATA_OWNER!r}\n"
                "module = import_module(path)\n"
                "patch.object(module, 'metadata_inventory')\n"
            ),
        }
        for label, source in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                AssertionError, "metadata_inventory.*references"
            ):
                _assert_metadata_inventory_has_no_callers(
                    {"gravity_insight.extra_consumer": source},
                    target_module=NEW_METADATA_OWNER,
                )

    def test_dynamic_symbol_guard_blocks_untrackable_flows(self) -> None:
        cases = {
            "cross_function_loader": (
                "from importlib import import_module\n"
                "def acquire(name):\n    return import_module(name)\n"
                f"owner = acquire({NEW_METADATA_OWNER!r})\n"
                "getattr(owner, 'metadata_inventory')([])\n"
            ),
            "opaque_module_name": (
                "from importlib import import_module\n"
                "owner = import_module(runtime_name)\n"
                "getattr(owner, 'metadata_inventory')([])\n"
            ),
            "module_container": (
                "from importlib import import_module\n"
                f"owner = import_module({NEW_METADATA_OWNER!r})\n"
                "registry = [owner]\n"
                "getattr(registry[0], 'metadata_inventory')([])\n"
            ),
            "module_closure": (
                "from importlib import import_module\n"
                f"owner = import_module({NEW_METADATA_OWNER!r})\n"
                "def factory():\n    return lambda: owner\n"
                "getattr(factory()(), 'metadata_inventory')([])\n"
            ),
            "module_callback": (
                "from importlib import import_module\n"
                f"owner = import_module({NEW_METADATA_OWNER!r})\n"
                "def consume(value):\n"
                "    return getattr(value, 'metadata_inventory')([])\n"
                "dispatch(consume, owner)\n"
            ),
            "eval": "eval(\"metadata_inventory([])\")\n",
            "exec": "exec(\"metadata_inventory([])\")\n",
            "meta_path": "import sys\nsys.meta_path.insert(0, finder)\n",
        }
        for label, source in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                AssertionError, "metadata_inventory.*blocker"
            ):
                _assert_metadata_inventory_has_no_callers(
                    {"gravity_insight.extra_consumer": source},
                    target_module=NEW_METADATA_OWNER,
                )

    def test_dynamic_symbol_guard_blocks_native_extension_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "gravity_insight"
            owner = package / "agents" / "batch_sources.py"
            owner.parent.mkdir(parents=True)
            owner.write_text(
                "def metadata_inventory_state(warnings):\n    return (), True\n",
                encoding="utf-8",
            )
            (package / "opaque_loader.pyd").write_bytes(b"synthetic")
            with self.assertRaisesRegex(
                AssertionError, "metadata_inventory.*native-extension"
            ):
                _metadata_inventory_contract(_repository_modules(package))

    def test_compact_pagination_output_contract_is_locked(self) -> None:
        frozen_modules = _frozen_repository_modules()
        _, frozen_definition = _compact_pagination_contract(frozen_modules)
        frozen_compact_pagination = _load_isolated_function(frozen_definition)
        current_modules = _repository_modules()
        _, current_definition = _compact_pagination_contract(current_modules)
        current_compact_pagination = _load_isolated_function(current_definition)
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
                frozen_actual = json.dumps(
                    frozen_compact_pagination(value),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                current_actual = json.dumps(
                    current_compact_pagination(value),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self.assertEqual(expected, frozen_actual)
                self.assertEqual(frozen_actual, current_actual)

    def test_frozen_concept_oracle_tree_and_move_mapping_are_explicit(self) -> None:
        self.assertEqual(
            R17_ORACLE_TREE_OID,
            _git_text("rev-parse", f"{R17_ORACLE_BASELINE_COMMIT}^{{tree}}"),
        )
        scope = _frozen_migration_scope()
        move_mapping = {
            move["old_module"]: move["new_module"]
            for move in scope["one_to_one_moves"]
        }
        self.assertEqual(82, len(move_mapping))
        self.assertEqual(NEW_PAGINATION_CONSUMER, move_mapping[OLD_PAGINATION_CONSUMER])
        self.assertEqual(NEW_METADATA_OWNER, move_mapping[OLD_METADATA_OWNER])
        self.assertEqual(
            {
                "old_module": OLD_PAGINATION_OWNER,
                "new_module": NEW_PAGINATION_OWNER,
                "symbol": "compact_pagination",
            },
            scope["consolidate_delete"],
        )

    def test_frozen_concept_baseline_and_current_residue_gate_both_hold(self) -> None:
        frozen_modules = _frozen_repository_modules()
        _compact_pagination_contract(frozen_modules)
        _metadata_inventory_contract(frozen_modules)
        current_modules = _repository_modules()
        _compact_pagination_contract(current_modules)
        _metadata_inventory_contract(current_modules)

    def test_closed_owner_gate_rejects_dunder_dict_for_both_symbols(self) -> None:
        for target_module, symbol in _deleted_symbol_targets():
            source = (
                f"import {target_module} as owner\n"
                f"owner.__dict__[{symbol!r}]([])\n"
            )
            with self.subTest(symbol=symbol):
                usage = _target_usage(
                    _synthetic_modules({"gravity_insight.extra_consumer": source}),
                    target_module,
                    symbol,
                )
                self.assertTrue(usage.references)
                self.assertTrue(usage.calls)

    def test_closed_owner_gate_rejects_dunder_getattribute_for_both_symbols(self) -> None:
        for target_module, symbol in _deleted_symbol_targets():
            source = (
                f"import {target_module} as owner\n"
                f"owner.__getattribute__({symbol!r})([])\n"
            )
            with self.subTest(symbol=symbol):
                usage = _target_usage(
                    _synthetic_modules({"gravity_insight.extra_consumer": source}),
                    target_module,
                    symbol,
                )
                self.assertTrue(usage.references)
                self.assertTrue(usage.calls)

    def test_closed_owner_gate_rejects_requested_alias_flows_for_both_symbols(self) -> None:
        templates = {
            "dict alias": "d = owner.__dict__\nd[{symbol!r}]([])\n",
            "bound getattribute": (
                "f = owner.__getattribute__\nf({symbol!r})([])\n"
            ),
            "vars namespace": "vars(owner)[{symbol!r}]([])\n",
            "dict get": "owner.__dict__.get({symbol!r})([])\n",
        }
        for target_module, symbol in _deleted_symbol_targets():
            for label, template in templates.items():
                source = (
                    f"import {target_module} as owner\n"
                    + template.format(symbol=symbol)
                )
                with self.subTest(symbol=symbol, flow=label):
                    usage = _target_usage(
                        _synthetic_modules({"gravity_insight.extra_consumer": source}),
                        target_module,
                        symbol,
                    )
                    self.assertTrue(usage.references)
                    self.assertTrue(usage.calls)

    def test_closed_owner_gate_blocks_unknown_keys_but_ignores_unrelated_objects(self) -> None:
        for target_module, symbol in _deleted_symbol_targets():
            owner_source = (
                f"import {target_module} as owner\n"
                "key = runtime_key()\nowner.__dict__[key]\n"
            )
            ordinary_source = (
                "class Snapshot:\n    pass\n"
                "value = Snapshot()\n"
                f"value.__dict__.get({symbol!r})\n"
                f"vars(value).get({symbol!r})\n"
            )
            with self.subTest(symbol=symbol):
                owner_usage = _target_usage(
                    _synthetic_modules({"gravity_insight.owner_consumer": owner_source}),
                    target_module,
                    symbol,
                )
                ordinary_usage = _target_usage(
                    _synthetic_modules({"gravity_insight.ordinary": ordinary_source}),
                    target_module,
                    symbol,
                )
                self.assertTrue(owner_usage.blockers)
                self.assertEqual(_TargetUsage((), (), (), ()), ordinary_usage)

    def test_closed_owner_gate_blocks_owner_derived_value_escapes(self) -> None:
        templates = {
            "attribute store": "holder.value = owner.__dict__\n",
            "subscript store": "holder['value'] = owner.__getattribute__\n",
            "globals lookup": "globals()['owner']\n",
            "locals lookup": "lookup = locals\nlookup()['owner']\n",
            "namespace union": (
                "merged = owner.__dict__ | {{}}\nmerged[{symbol!r}]\n"
            ),
            "registry wrapper": (
                "import sys\n"
                "def acquire(name):\n    return sys.modules[name]\n"
                "dynamic_owner = acquire({target_module!r})\n"
                "dynamic_owner.__dict__[{symbol!r}]\n"
            ),
        }
        for target_module, symbol in _deleted_symbol_targets():
            for label, body in templates.items():
                source = (
                    f"import {target_module} as owner\n"
                    + body.format(target_module=target_module, symbol=symbol)
                )
                with self.subTest(symbol=symbol, flow=label):
                    usage = _target_usage(
                        _synthetic_modules({"gravity_insight.escape": source}),
                        target_module,
                        symbol,
                    )
                    self.assertTrue(usage.blockers)

    def test_closed_owner_gate_rejects_fully_composed_owner_and_symbol_names(self) -> None:
        cases = (
            (
                NEW_PAGINATION_OWNER,
                "compact_pagination",
                "'gravity_insight.' + 'pagination_' + 'completeness'",
                "'compact_' + 'pagination'",
            ),
            (
                NEW_METADATA_OWNER,
                "metadata_inventory",
                "'gravity_insight.' + 'agents.' + 'batch_' + 'sources'",
                "'metadata_' + 'inventory'",
            ),
        )
        for target_module, symbol, owner_expression, symbol_expression in cases:
            source = (
                f"owner_name = {owner_expression}\n"
                "owner = __import__(owner_name, fromlist=['target'])\n"
                f"symbol_name = {symbol_expression}\n"
                "owner.__dict__[symbol_name]([])\n"
            )
            with self.subTest(symbol=symbol):
                usage = _target_usage(
                    _synthetic_modules({"gravity_insight.composed": source}),
                    target_module,
                    symbol,
                )
                self.assertTrue(usage.references)
                self.assertTrue(usage.calls)
                self_usage = _target_usage(
                    _synthetic_modules(
                        {
                            target_module: (
                                "import sys\n"
                                f"sys.modules[__name__].__dict__[{symbol!r}]([])\n"
                            )
                        }
                    ),
                    target_module,
                    symbol,
                )
                self.assertTrue(self_usage.references)
                self.assertTrue(self_usage.calls)


R17_ORACLE_BASELINE_COMMIT = "ddbca7aca1b7baee2ee42e96f886d7ddaee84947"
R17_ORACLE_TREE_OID = "aebfca0423628ea36b48f227435abf6854400c00"
R17_DISPOSITION_LEDGER = "tests/fixtures/agent_module_reference_dispositions.json"
_FROZEN_MODULE_CACHE: list[_ModuleSource] | None = None
_CURRENT_MODULE_CACHE: list[_ModuleSource] | None = None
_TARGET_USAGE_CACHE: dict[tuple[int, str, str], _TargetUsage] = {}
_STRING_ANALYSIS_CACHE: dict[
    str, tuple[dict[str, set[str]], set[str], frozenset[str]]
] = {}


def _git_bytes(*args: str, input_bytes: bytes | None = None) -> bytes:
    import subprocess

    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _git_text(*args: str) -> str:
    return _git_bytes(*args).decode("ascii").strip()


def _frozen_tree_blobs(prefix: str) -> dict[str, bytes]:
    listing = _git_bytes(
        "ls-tree", "-r", "-z", R17_ORACLE_TREE_OID, "--", prefix
    )
    entries: list[tuple[str, str]] = []
    for raw_entry in listing.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        _mode, object_type, raw_oid = metadata.split(b" ")
        if object_type != b"blob":
            raise AssertionError(f"non-blob entry in frozen tree: {raw_path!r}")
        entries.append((raw_path.decode("utf-8"), raw_oid.decode("ascii")))
    request = "".join(f"{oid}\n" for _, oid in entries).encode("ascii")
    import subprocess

    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(request)
    if process.returncode:
        raise AssertionError(stderr.decode("utf-8", errors="replace"))
    blobs: dict[str, bytes] = {}
    offset = 0
    for path, expected_oid in entries:
        line_end = stdout.index(b"\n", offset)
        oid, object_type, raw_size = stdout[offset:line_end].split(b" ")
        if oid.decode("ascii") != expected_oid or object_type != b"blob":
            raise AssertionError(f"unexpected frozen object header for {path}")
        size = int(raw_size)
        start = line_end + 1
        end = start + size
        blobs[path] = stdout[start:end]
        if stdout[end : end + 1] != b"\n":
            raise AssertionError(f"unterminated frozen object for {path}")
        offset = end + 1
    return blobs


def _frozen_migration_scope() -> dict[str, Any]:
    blobs = _frozen_tree_blobs(R17_DISPOSITION_LEDGER)
    document = json.loads(blobs[R17_DISPOSITION_LEDGER].decode("utf-8"))
    scope = copy.deepcopy(document["scope"])

    def project(module: str) -> str:
        root, separator, relative = module.partition(".")
        if root != HISTORICAL_PACKAGE_ROOT or not separator:
            raise AssertionError(f"unexpected frozen module root: {module}")
        return f"{CURRENT_PACKAGE_ROOT}.{relative}"

    for move in scope["one_to_one_moves"]:
        move["old_module"] = project(move["old_module"])
        move["new_module"] = project(move["new_module"])
    consolidation = scope["consolidate_delete"]
    consolidation["old_module"] = project(consolidation["old_module"])
    consolidation["new_module"] = project(consolidation["new_module"])
    scope["retained_modules"] = [
        project(module) for module in scope["retained_modules"]
    ]
    return scope


def _frozen_repository_modules() -> list[_ModuleSource]:
    global _FROZEN_MODULE_CACHE
    if _FROZEN_MODULE_CACHE is not None:
        return _FROZEN_MODULE_CACHE
    modules: list[_ModuleSource] = []
    historical_root = f"src/{HISTORICAL_PACKAGE_ROOT}"
    for path, raw_source in sorted(_frozen_tree_blobs(historical_root).items()):
        suffix = Path(path).suffix.lower()
        if suffix not in {".py", ".pyd", ".so", ".dll", ".dylib"}:
            continue
        package_relative = Path(path).relative_to(historical_root)
        parts = list(package_relative.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        module = CURRENT_PACKAGE_ROOT + ("." + ".".join(parts) if parts else "")
        native = suffix != ".py"
        source = (
            ""
            if native
            else raw_source.decode("utf-8").replace(
                HISTORICAL_PACKAGE_ROOT,
                CURRENT_PACKAGE_ROOT,
            )
        )
        modules.append(
            _ModuleSource(
                module=module,
                relative=path,
                source=source,
                tree=ast.parse(source, filename=f"{R17_ORACLE_TREE_OID}:{path}"),
                is_package=is_package,
                is_native_extension=native,
            )
        )
    _FROZEN_MODULE_CACHE = modules
    return modules


def _repository_modules(package_root: Path = PACKAGE_ROOT) -> list[_ModuleSource]:
    global _CURRENT_MODULE_CACHE
    if package_root != PACKAGE_ROOT:
        return _uncached_repository_modules(package_root)
    if _CURRENT_MODULE_CACHE is None:
        _CURRENT_MODULE_CACHE = _uncached_repository_modules(package_root)
    return _CURRENT_MODULE_CACHE


def _deleted_symbol_targets() -> tuple[tuple[str, str], ...]:
    return (
        (NEW_PAGINATION_OWNER, "compact_pagination"),
        (NEW_METADATA_OWNER, "metadata_inventory"),
    )


@dataclass
class _ClosedOwnerFlow:
    target_module: str
    symbol: str
    module_expressions: set[str]
    import_loaders: set[str]
    module_registries: set[str]
    symbol_names: set[str]
    namespaces: set[str]
    attribute_readers: set[str]
    namespace_readers: set[str]
    getattr_functions: set[str]
    vars_functions: set[str]
    namespace_reflection_functions: set[str]
    patch_object_functions: set[str]
    string_bindings: dict[str, set[str]]
    closed_string_names: set[str]


_OWNER = "owner-module"
_NAMESPACE = "owner-namespace"
_ATTRIBUTE_READER = "owner-attribute-reader"
_NAMESPACE_READER = "owner-namespace-reader"
_TARGET_SYMBOL = "target-symbol"


def _assignment_expressions(tree: ast.Module) -> dict[str, list[ast.AST]]:
    result: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        targets: set[str] = set()
        value: ast.AST | None = None
        if isinstance(node, (ast.Assign, ast.NamedExpr)):
            target_nodes = node.targets if isinstance(node, ast.Assign) else [node.target]
            targets = {
                name for target in target_nodes for name in _bound_names(target)
            }
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = _bound_names(node.target)
            value = node.value
        if value is not None:
            for target in targets:
                result.setdefault(target, []).append(value)
    return result


def _finite_string_domain(
    node: ast.AST,
    bindings: Mapping[str, set[str]],
    closed_names: set[str],
) -> tuple[set[str], bool]:
    if isinstance(node, ast.Constant):
        return ({node.value} if isinstance(node.value, str) else set(), True)
    if isinstance(node, ast.Name):
        return set(bindings.get(node.id, ())), node.id in closed_names
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, left_closed = _finite_string_domain(node.left, bindings, closed_names)
        right, right_closed = _finite_string_domain(node.right, bindings, closed_names)
        return ({a + b for a in left for b in right}, left_closed and right_closed)
    if isinstance(node, ast.IfExp):
        body, body_closed = _finite_string_domain(node.body, bindings, closed_names)
        other, other_closed = _finite_string_domain(
            node.orelse, bindings, closed_names
        )
        return body | other, body_closed and other_closed
    if isinstance(node, ast.JoinedStr):
        values = {""}
        closed = True
        for part in node.values:
            expression = part.value if isinstance(part, ast.FormattedValue) else part
            chunk, chunk_closed = _finite_string_domain(
                expression, bindings, closed_names
            )
            values = {prefix + suffix for prefix in values for suffix in chunk}
            closed = closed and chunk_closed
        return values, closed
    return set(), False


def _closed_string_bindings(
    tree: ast.Module,
) -> tuple[dict[str, set[str]], set[str]]:
    assignments = _assignment_expressions(tree)
    values = {name: set() for name in assignments}
    closed: set[str] = set()
    while True:
        next_values: dict[str, set[str]] = {}
        next_closed: set[str] = set()
        for name, expressions in assignments.items():
            domains = [
                _finite_string_domain(expression, values, closed)
                for expression in expressions
            ]
            next_values[name] = {
                value for domain, _complete in domains for value in domain
            }
            if domains and all(complete for _domain, complete in domains):
                next_closed.add(name)
        if next_values == values and next_closed == closed:
            return values, closed
        values, closed = next_values, next_closed


def _closed_string_analysis(
    module: _ModuleSource,
) -> tuple[dict[str, set[str]], set[str], frozenset[str]]:
    cached = _STRING_ANALYSIS_CACHE.get(module.source)
    if cached is not None:
        return cached
    bindings, closed = _closed_string_bindings(module.tree)
    finite_values = {value for values in bindings.values() for value in values}
    for node in ast.walk(module.tree):
        if isinstance(
            node,
            (ast.Constant, ast.Name, ast.BinOp, ast.IfExp, ast.JoinedStr),
        ):
            values, _complete = _finite_string_domain(node, bindings, closed)
            finite_values.update(values)
    result = bindings, closed, frozenset(finite_values)
    _STRING_ANALYSIS_CACHE[module.source] = result
    return result


def _owner_kinds(node: ast.AST, flow: _ClosedOwnerFlow) -> set[str]:
    kinds: set[str] = set()
    if _is_module_expression(
        node,
        target_module=flow.target_module,
        module_expressions=flow.module_expressions,
        import_loaders=flow.import_loaders,
        module_registries=flow.module_registries,
        string_bindings=flow.string_bindings,
    ):
        kinds.add(_OWNER)
    if isinstance(node, ast.Name):
        if node.id in flow.symbol_names:
            kinds.add(_TARGET_SYMBOL)
        if node.id in flow.namespaces:
            kinds.add(_NAMESPACE)
        if node.id in flow.attribute_readers:
            kinds.add(_ATTRIBUTE_READER)
        if node.id in flow.namespace_readers:
            kinds.add(_NAMESPACE_READER)
        return kinds
    if isinstance(node, ast.Attribute):
        parent = _owner_kinds(node.value, flow)
        if _OWNER in parent:
            if node.attr == flow.symbol:
                kinds.add(_TARGET_SYMBOL)
            elif node.attr == "__dict__":
                kinds.add(_NAMESPACE)
            elif node.attr == "__getattribute__":
                kinds.add(_ATTRIBUTE_READER)
        if _NAMESPACE in parent and node.attr in {"get", "__getitem__"}:
            kinds.add(_NAMESPACE_READER)
        if _ATTRIBUTE_READER in parent and node.attr == "__call__":
            kinds.add(_ATTRIBUTE_READER)
        if _NAMESPACE_READER in parent and node.attr == "__call__":
            kinds.add(_NAMESPACE_READER)
        return kinds
    if isinstance(node, ast.Subscript):
        parent = _owner_kinds(node.value, flow)
        values, _closed = _finite_string_domain(
            node.slice, flow.string_bindings, flow.closed_string_names
        )
        if _NAMESPACE in parent and flow.symbol in values:
            kinds.add(_TARGET_SYMBOL)
        return kinds
    if not isinstance(node, ast.Call):
        return kinds
    function_kinds = _owner_kinds(node.func, flow)
    if function_kinds & {_ATTRIBUTE_READER, _NAMESPACE_READER} and node.args:
        values, _closed = _finite_string_domain(
            node.args[0], flow.string_bindings, flow.closed_string_names
        )
        if flow.symbol in values:
            kinds.add(_TARGET_SYMBOL)
    called = _dotted_name(node.func)
    if called in flow.getattr_functions and node.args:
        owner = _OWNER in _owner_kinds(node.args[0], flow)
        if owner and len(node.args) >= 2:
            values, _closed = _finite_string_domain(
                node.args[1], flow.string_bindings, flow.closed_string_names
            )
            if flow.symbol in values:
                kinds.add(_TARGET_SYMBOL)
            if "__dict__" in values:
                kinds.add(_NAMESPACE)
            if "__getattribute__" in values:
                kinds.add(_ATTRIBUTE_READER)
    if called in flow.vars_functions and node.args:
        if _OWNER in _owner_kinds(node.args[0], flow):
            kinds.add(_NAMESPACE)
    return kinds


def _build_closed_owner_flow(
    module: _ModuleSource, target_module: str, symbol: str
) -> _ClosedOwnerFlow:
    module_expressions: set[str] = set()
    import_loaders = {"__import__", "importlib.import_module"}
    module_registries = {"sys.modules"}
    symbol_names = {symbol} if module.module == target_module else set()
    getattr_functions = {
        "getattr", "hasattr", "setattr", "delattr",
        "builtins.getattr", "builtins.hasattr", "builtins.setattr",
        "builtins.delattr",
    }
    vars_functions = {"vars", "builtins.vars"}
    namespace_reflection_functions = {
        "globals", "locals", "builtins.globals", "builtins.locals"
    }
    patch_object_functions = {
        "patch.object", "mock.patch.object", "unittest.mock.patch.object"
    }
    cached_bindings, cached_closed_names, _finite_values = _closed_string_analysis(
        module
    )
    string_bindings = {
        name: set(values) for name, values in cached_bindings.items()
    }
    string_bindings["__name__"] = {module.module}
    closed_string_names = set(cached_closed_names)
    closed_string_names.add("__name__")
    for node in ast.walk(module.tree):
        if isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(module, node)
            for alias in node.names:
                bound = alias.asname or alias.name
                imported_module = f"{resolved}.{alias.name}" if resolved else alias.name
                if resolved == target_module and alias.name == symbol:
                    symbol_names.add(bound)
                elif imported_module == target_module:
                    module_expressions.add(bound)
                if resolved == "importlib" and alias.name == "import_module":
                    import_loaders.add(bound)
                elif resolved == "sys" and alias.name == "modules":
                    module_registries.add(bound)
                elif resolved == "builtins" and alias.name in {
                    "getattr", "hasattr", "setattr", "delattr"
                }:
                    getattr_functions.add(bound)
                elif resolved == "builtins" and alias.name == "vars":
                    vars_functions.add(bound)
                elif resolved == "builtins" and alias.name in {"globals", "locals"}:
                    namespace_reflection_functions.add(bound)
                elif resolved in {"unittest.mock", "mock"} and alias.name == "patch":
                    patch_object_functions.add(f"{bound}.object")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".", 1)[0]
                if alias.name == target_module:
                    module_expressions.add(alias.asname or alias.name)
                if alias.name == "importlib":
                    import_loaders.add(f"{bound}.import_module")
                elif alias.name == "sys":
                    module_registries.add(f"{bound}.modules")
                elif alias.name == "builtins":
                    getattr_functions.update(
                        f"{bound}.{name}"
                        for name in ("getattr", "hasattr", "setattr", "delattr")
                    )
                    vars_functions.add(f"{bound}.vars")
                    namespace_reflection_functions.update(
                        {f"{bound}.globals", f"{bound}.locals"}
                    )
    flow = _ClosedOwnerFlow(
        target_module=target_module,
        symbol=symbol,
        module_expressions=module_expressions,
        import_loaders=import_loaders,
        module_registries=module_registries,
        symbol_names=symbol_names,
        namespaces=set(),
        attribute_readers=set(),
        namespace_readers=set(),
        getattr_functions=getattr_functions,
        vars_functions=vars_functions,
        namespace_reflection_functions=namespace_reflection_functions,
        patch_object_functions=patch_object_functions,
        string_bindings=string_bindings,
        closed_string_names=closed_string_names,
    )
    assignments = _assignment_expressions(module.tree)
    while True:
        before = (
            len(flow.module_expressions), len(flow.symbol_names),
            len(flow.namespaces), len(flow.attribute_readers),
            len(flow.namespace_readers), len(flow.import_loaders),
            len(flow.module_registries), len(flow.getattr_functions),
            len(flow.vars_functions), len(flow.namespace_reflection_functions),
            len(flow.patch_object_functions),
        )
        for target, expressions in assignments.items():
            for value in expressions:
                kinds = _owner_kinds(value, flow)
                if _OWNER in kinds:
                    flow.module_expressions.add(target)
                if _TARGET_SYMBOL in kinds:
                    flow.symbol_names.add(target)
                if _NAMESPACE in kinds:
                    flow.namespaces.add(target)
                if _ATTRIBUTE_READER in kinds:
                    flow.attribute_readers.add(target)
                if _NAMESPACE_READER in kinds:
                    flow.namespace_readers.add(target)
                dotted = _dotted_name(value)
                for names in (
                    flow.import_loaders, flow.module_registries,
                    flow.getattr_functions, flow.vars_functions,
                    flow.namespace_reflection_functions,
                    flow.patch_object_functions,
                ):
                    if dotted in names if dotted is not None else False:
                        names.add(target)
        after = (
            len(flow.module_expressions), len(flow.symbol_names),
            len(flow.namespaces), len(flow.attribute_readers),
            len(flow.namespace_readers), len(flow.import_loaders),
            len(flow.module_registries), len(flow.getattr_functions),
            len(flow.vars_functions), len(flow.namespace_reflection_functions),
            len(flow.patch_object_functions),
        )
        if after == before:
            return flow


def _closed_owner_access_usage(
    modules: list[_ModuleSource], target_module: str, symbol: str
) -> _TargetUsage:
    references: set[str] = set()
    calls: set[str] = set()
    blockers: set[str] = set()
    for module in modules:
        if module.is_native_extension:
            continue
        owner_hint = target_module.rsplit(".", 1)[-1]
        _bindings, _closed, finite_values = _closed_string_analysis(module)
        dynamic_owner_syntax = any(
            marker in module.source
            for marker in (
                "import_module", "__import__", "modules", "__dict__",
                "__getattribute__", "getattr", "vars(", "globals(", "locals(",
            )
        )
        if (
            module.module != target_module
            and owner_hint not in module.source
            and symbol not in module.source
            and target_module not in finite_values
            and symbol not in finite_values
            and not dynamic_owner_syntax
        ):
            continue
        flow = _build_closed_owner_flow(module, target_module, symbol)
        tainted_names = (
            flow.module_expressions | flow.namespaces | flow.attribute_readers
            | flow.namespace_readers
        )
        for node in ast.walk(module.tree):
            kinds = _owner_kinds(node, flow)
            is_loaded_expression = isinstance(node, ast.Call) or (
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
            ) or isinstance(node, (ast.Attribute, ast.Subscript))
            if _TARGET_SYMBOL in kinds and is_loaded_expression:
                references.add(_location(module, node, "closed-owner-reference"))
            if isinstance(node, ast.Call):
                function_kinds = _owner_kinds(node.func, flow)
                if _TARGET_SYMBOL in function_kinds:
                    calls.add(_location(module, node, "closed-owner-call"))
                called = _dotted_name(node.func)
                if called in flow.namespace_reflection_functions and (
                    module.module == target_module
                    or flow.module_expressions
                    or flow.symbol_names
                ):
                    blockers.add(
                        _location(module, node, "blocker:owner-binding-namespace")
                    )
                reader_call = bool(
                    function_kinds & {_ATTRIBUTE_READER, _NAMESPACE_READER}
                )
                if reader_call:
                    if not node.args:
                        blockers.add(_location(module, node, "blocker:missing-owner-key"))
                    else:
                        _values, closed = _finite_string_domain(
                            node.args[0], flow.string_bindings,
                            flow.closed_string_names,
                        )
                        if not closed:
                            blockers.add(_location(module, node, "blocker:opaque-owner-key"))
                owner_accessor = called in flow.getattr_functions and node.args and (
                    _OWNER in _owner_kinds(node.args[0], flow)
                )
                if owner_accessor:
                    if len(node.args) < 2:
                        blockers.add(_location(module, node, "blocker:missing-owner-key"))
                    else:
                        _values, closed = _finite_string_domain(
                            node.args[1], flow.string_bindings,
                            flow.closed_string_names,
                        )
                        if not closed:
                            blockers.add(_location(module, node, "blocker:opaque-owner-key"))
                patch_accessor = (
                    called in flow.patch_object_functions
                    or (called or "").endswith(".setattr")
                ) and node.args and _OWNER in _owner_kinds(node.args[0], flow)
                if patch_accessor:
                    if len(node.args) < 2:
                        blockers.add(_location(module, node, "blocker:missing-owner-key"))
                    else:
                        _values, closed = _finite_string_domain(
                            node.args[1], flow.string_bindings,
                            flow.closed_string_names,
                        )
                        if not closed:
                            blockers.add(_location(module, node, "blocker:opaque-owner-key"))
                approved = (
                    reader_call or owner_accessor or patch_accessor
                    or called in flow.vars_functions
                    or called in flow.import_loaders
                )
                argument_kinds = set().union(
                    *(
                        [_owner_kinds(argument, flow) for argument in node.args]
                        + [_owner_kinds(keyword.value, flow) for keyword in node.keywords]
                    )
                ) if (node.args or node.keywords) else set()
                if not approved and argument_kinds & {
                    _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                }:
                    blockers.add(_location(module, node, "blocker:owner-value-callback"))
                argument_strings = set().union(
                    *(
                        [
                            _finite_string_domain(
                                argument, flow.string_bindings,
                                flow.closed_string_names,
                            )[0]
                            for argument in node.args
                        ]
                        + [
                            _finite_string_domain(
                                keyword.value, flow.string_bindings,
                                flow.closed_string_names,
                            )[0]
                            for keyword in node.keywords
                        ]
                    )
                ) if (node.args or node.keywords) else set()
                if not approved and flow.target_module in argument_strings:
                    blockers.add(
                        _location(module, node, "blocker:target-module-name-callback")
                    )
                if function_kinds & {_OWNER, _NAMESPACE}:
                    blockers.add(_location(module, node, "blocker:owner-value-call"))
            elif isinstance(node, ast.Subscript):
                parent = _owner_kinds(node.value, flow)
                values, closed = _finite_string_domain(
                    node.slice, flow.string_bindings, flow.closed_string_names
                )
                if (
                    _is_named_expression(node.value, flow.module_registries)
                    and flow.target_module not in values
                    and not closed
                ):
                    blockers.add(
                        _location(module, node, "blocker:opaque-module-registry")
                    )
                if _OWNER in parent or (
                    _NAMESPACE in parent and not closed
                ):
                    reason = (
                        "blocker:owner-module-subscript" if _OWNER in parent
                        else "blocker:opaque-owner-key"
                    )
                    blockers.add(_location(module, node, reason))
            elif isinstance(node, ast.Attribute):
                parent = _owner_kinds(node.value, flow)
                if _NAMESPACE in parent and node.attr not in {"get", "__getitem__"}:
                    blockers.add(_location(module, node, "blocker:owner-namespace-escape"))
                if parent & {_ATTRIBUTE_READER, _NAMESPACE_READER} and node.attr != "__call__":
                    blockers.add(_location(module, node, "blocker:owner-reader-escape"))
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                target_nodes = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if _owner_kinds(node.value, flow) & {
                    _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                } and any(not _closed_name_target(target) for target in target_nodes):
                    blockers.add(_location(module, node, "blocker:owner-value-store"))
            elif isinstance(node, ast.AugAssign):
                if _owner_kinds(node.target, flow) & {
                    _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                }:
                    blockers.add(_location(module, node, "blocker:owner-value-store"))
            elif isinstance(node, (ast.Yield, ast.YieldFrom)):
                if node.value is not None and _owner_kinds(node.value, flow) & {
                    _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                }:
                    blockers.add(_location(module, node, "blocker:owner-value-closure"))
            elif isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
                values = list(node.elts) if not isinstance(node, ast.Dict) else [
                    *node.keys, *node.values
                ]
                if any(
                    value is not None and _owner_kinds(value, flow) & {
                        _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                    }
                    for value in values
                ):
                    blockers.add(_location(module, node, "blocker:owner-value-container"))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                escapes = any(
                    isinstance(descendant, ast.Return)
                    and descendant.value is not None
                    and _owner_kinds(descendant.value, flow) & {
                        _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                    }
                    for descendant in ast.walk(node)
                )
                closes = any(
                    isinstance(descendant, ast.Name)
                    and descendant.id in tainted_names
                    for descendant in ast.walk(node)
                ) and (
                    isinstance(node, ast.Lambda)
                    or any(isinstance(value, ast.Lambda) for value in ast.walk(node))
                )
                if escapes or closes:
                    blockers.add(_location(module, node, "blocker:owner-value-closure"))
            elif isinstance(
                node,
                (
                    ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.IfExp,
                    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                    ast.Await, ast.Starred, ast.FormattedValue, ast.JoinedStr,
                ),
            ) and any(
                descendant is not node
                and _owner_kinds(descendant, flow) & {
                    _OWNER, _NAMESPACE, _ATTRIBUTE_READER, _NAMESPACE_READER
                }
                for descendant in ast.walk(node)
            ):
                blockers.add(
                    _location(module, node, "blocker:owner-value-operation")
                )
    return _TargetUsage((), tuple(sorted(references)), tuple(sorted(calls)), tuple(sorted(blockers)))


def _closed_name_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_closed_name_target(item) for item in node.elts)
    return False


def _target_usage(
    modules: list[_ModuleSource], target_module: str, symbol: str
) -> _TargetUsage:
    cacheable = modules is _CURRENT_MODULE_CACHE or modules is _FROZEN_MODULE_CACHE
    cache_key = (id(modules), target_module, symbol)
    if cacheable and cache_key in _TARGET_USAGE_CACHE:
        return _TARGET_USAGE_CACHE[cache_key]
    enumerated = _enumerated_target_usage(modules, target_module, symbol)
    closed = _closed_owner_access_usage(modules, target_module, symbol)
    result = _TargetUsage(
        imports=enumerated.imports,
        references=tuple(sorted(set(enumerated.references) | set(closed.references))),
        calls=tuple(sorted(set(enumerated.calls) | set(closed.calls))),
        blockers=tuple(sorted(set(enumerated.blockers) | set(closed.blockers))),
    )
    if cacheable:
        _TARGET_USAGE_CACHE[cache_key] = result
    return result


if __name__ == "__main__":
    unittest.main()
