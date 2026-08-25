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
    is_native_extension: bool = False


def _module_name(path: Path, package_root: Path) -> tuple[str, bool]:
    relative = path.relative_to(package_root).with_suffix("")
    parts = [package_root.name, *relative.parts]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _repository_modules(package_root: Path = PACKAGE_ROOT) -> list[_ModuleSource]:
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
    "gravity_sdk": {"module_name"},
    "gravity_sdk.runtime": {"name"},
    "gravity_sdk.prober.cli": {'sdk.__name__ + ".errors"'},
    "gravity_sdk.prober.export_verify": {'f"{base}.{name}"'},
    "gravity_sdk.prober.transport": {
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


def _target_usage(
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
            "gravity_sdk.extra_consumer": (
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

    def test_metadata_inventory_guard_rejects_dynamic_terminal_caller(self) -> None:
        sources = {
            NEW_METADATA_OWNER: (
                "def metadata_inventory_state(warnings):\n"
                "    return (), True\n"
            ),
            "gravity_sdk.extra_consumer": (
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
                    {"gravity_sdk.extra_consumer": source},
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
                    {"gravity_sdk.extra_consumer": source},
                    target_module=NEW_METADATA_OWNER,
                )

    def test_dynamic_symbol_guard_blocks_native_extension_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "gravity_sdk"
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
