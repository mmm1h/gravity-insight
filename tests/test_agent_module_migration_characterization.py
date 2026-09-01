"""Characterize contracts that the agent subpackage migration must preserve."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.agent_migration_characterization import (
    KNOWN_ROOT_EXPORT_MODULE_COLLISIONS,
    PACKAGE_ROOT,
    REFERENCE_DISPOSITIONS,
    ROOT,
    agent_path_classification,
    agent_path_references,
    eager_import_cycles,
    eager_import_sccs,
    expected_public_exports,
    migration_module_names,
    module_inventory,
    root_export_module_collisions,
    unexpected_root_export_module_collisions,
)
from tests.repository_tree_gate import repository_tree_read


_LAZY_PROBE = r"""
import importlib
import importlib.util
import json
import sys

expected = json.load(sys.stdin)
assert len(expected) == 147, f"public snapshot count changed: {len(expected)}"

def fresh_package():
    for module in list(sys.modules):
        if module == "gravity_insight" or module.startswith("gravity_insight."):
            del sys.modules[module]
    return importlib.import_module("gravity_insight")

for name, (owner, attribute) in expected.items():
    gravity_insight = fresh_package()
    absolute_owner = importlib.util.resolve_name(owner, gravity_insight.__name__)
    assert absolute_owner not in sys.modules, (
        f"owner loaded with package for {name}: {absolute_owner}"
    )
    assert name not in gravity_insight.__dict__, f"root export was eager: {name}"
    first = getattr(gravity_insight, name)
    owner_module = sys.modules.get(absolute_owner)
    assert owner_module is not None, (
        f"owner was not imported for {name}: {absolute_owner}"
    )
    assert first is getattr(owner_module, attribute), (
        f"wrong owner identity for {name}: {absolute_owner}.{attribute}"
    )

    del sys.modules[absolute_owner]
    try:
        second = getattr(gravity_insight, name)
        assert second is first, f"cached identity changed for {name}"
        assert absolute_owner not in sys.modules, (
            f"owner reloaded on cached access for {name}: {absolute_owner}"
        )
    finally:
        sys.modules[absolute_owner] = owner_module

gravity_insight = fresh_package()
missing = "__characterization_missing_export__"
try:
    getattr(gravity_insight, missing)
except AttributeError as error:
    assert str(error) == f"module 'gravity_insight' has no attribute {missing!r}"
else:
    raise AssertionError("unknown root export did not raise AttributeError")

assert len(gravity_insight.__all__) == 148, (
    f"runtime __all__ count changed: {len(gravity_insight.__all__)}"
)
assert set(gravity_insight.__all__) == {*expected, "__version__"}
assert set(gravity_insight.__all__) <= set(dir(gravity_insight))
"""


_SHADOWING_PROBE = r"""
import importlib
import importlib.util
import json
import sys

payload = json.load(sys.stdin)
expected = payload["exports"]
names = payload["names"]
mode = sys.argv[1]

gravity_insight = importlib.import_module("gravity_insight")

def public_value(name):
    value = getattr(gravity_insight, name)
    owner, attribute = expected[name]
    owner_module = importlib.import_module(owner, gravity_insight.__name__)
    assert callable(value), f"root export is not callable for {name}: {type(value).__name__}"
    assert value is getattr(owner_module, attribute), f"wrong owner identity for {name}"
    return value

if mode == "child-first":
    children = {
        name: importlib.import_module(f"gravity_insight.{name}") for name in names
    }
    values = {name: public_value(name) for name in names}
    assert all(
        children[name] is sys.modules[f"gravity_insight.{name}"] for name in names
    )
elif mode == "export-first":
    values = {name: public_value(name) for name in names}
    for name in names:
        importlib.import_module(f"gravity_insight.{name}")
    assert all(public_value(name) is values[name] for name in names)
elif mode == "cross-order":
    values = {}
    for export_name, child_name in zip(names, reversed(names), strict=True):
        importlib.import_module(f"gravity_insight.{child_name}")
        values[export_name] = public_value(export_name)
    assert all(public_value(name) is values[name] for name in names)
else:
    raise AssertionError(f"unknown probe mode: {mode}")

print(json.dumps({
    "mode": mode,
    "types": [type(public_value(name)).__name__ for name in names],
    "callable": [callable(public_value(name)) for name in names],
}, sort_keys=True))
"""


_FAIL_CLOSED_PROBE = r"""
import importlib
from types import ModuleType

gravity_insight = importlib.import_module("gravity_insight")
owner = importlib.import_module("gravity_insight.business_pulse")
name = "__shadow_probe__"
setattr(owner, name, ModuleType(f"gravity_insight.{name}"))
gravity_insight._EXPORTS[name] = (".business_pulse", name)

try:
    getattr(gravity_insight, name)
except TypeError as error:
    assert str(error) == (
        "public export gravity_insight.__shadow_probe__ resolved to its shadowing module"
    )
else:
    raise AssertionError("shadowing owner module was returned silently")
"""


class AgentModuleMigrationCharacterizationTests(unittest.TestCase):
    def test_root_exports_are_lazy_cached_and_owned_in_an_isolated_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _LAZY_PROBE],
                input=json.dumps(expected_public_exports()),
                text=True,
                capture_output=True,
                cwd=temporary,
                timeout=60,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_shadowed_root_exports_are_order_independent_in_isolated_processes(
        self,
    ) -> None:
        payload = json.dumps({
            "exports": expected_public_exports(),
            "names": sorted(KNOWN_ROOT_EXPORT_MODULE_COLLISIONS),
        })
        for mode in ("child-first", "export-first", "cross-order"):
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as temporary,
            ):
                completed = subprocess.run(
                    [sys.executable, "-I", "-c", _SHADOWING_PROBE, mode],
                    input=payload,
                    text=True,
                    capture_output=True,
                    cwd=temporary,
                    timeout=60,
                )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_shadowed_root_export_resolution_fails_closed_on_module_value(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _FAIL_CLOSED_PROBE],
                text=True,
                capture_output=True,
                cwd=temporary,
                timeout=60,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_root_export_module_collision_set_cannot_grow(self) -> None:
        self.assertEqual(
            sorted(KNOWN_ROOT_EXPORT_MODULE_COLLISIONS),
            root_export_module_collisions(),
        )
        self.assertEqual([], unexpected_root_export_module_collisions())

    def test_root_export_module_collision_guard_detects_an_injected_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_insight"
            package.mkdir()
            (package / "future_collision.py").write_text("", encoding="utf-8")
            observed = unexpected_root_export_module_collisions(
                package,
                {"future_collision": [".owner", "future_collision"]},
            )
        self.assertEqual(["future_collision"], observed)

    def test_agent_deep_paths_are_explicitly_public_or_internal(self) -> None:
        with repository_tree_read(
            root=ROOT,
            purpose="agent deep-path src/tests repository scan",
        ):
            references = agent_path_references((ROOT / "src", ROOT / "tests"))
        unclassified = [
            f"{path.relative_to(ROOT)}:{line}: {reference}"
            for path, line, reference in references
            if agent_path_classification(reference) is None
        ]
        self.assertTrue(references, "agent deep-path scanner found no references")
        self.assertEqual([], unclassified)

    def test_eager_module_import_graph_has_no_migration_related_component(self) -> None:
        self.assertEqual([], eager_import_cycles(PACKAGE_ROOT))

    def test_retained_facade_dependencies_match_the_reviewed_module_symbol_set(self) -> None:
        # Lock direct import syntax, not an inferred domain or binding graph.
        dependencies: set[tuple[str, str]] = set()
        for path, (module, is_package) in module_inventory(PACKAGE_ROOT).items():
            if module != "gravity_insight.agents" and not module.startswith("gravity_insight.agents."):
                continue
            package = module if is_package else module.rpartition(".")[0]
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    base = (
                        importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                        if node.level else node.module
                    )
                    if base == "gravity_insight.agent":
                        dependencies.update((module, alias.name) for alias in node.names)
                    elif base == "gravity_insight" and any(alias.name == "agent" for alias in node.names):
                        dependencies.add((module, "<module>"))
                elif isinstance(node, ast.Import) and any(
                    alias.name == "gravity_insight.agent" for alias in node.names
                ):
                    dependencies.add((module, "<module>"))
        self.assertEqual(
            {
                ("gravity_insight.agents.batch", "discover_capabilities"),
                ("gravity_insight.agents.batch_questions", "DEFAULT_LIMIT"),
                ("gravity_insight.agents.host_selection", "SCHEMA_VERSION"),
                ("gravity_insight.agents.input_resolution", "discover_capabilities"),
                ("gravity_insight.agents.output", "SCHEMA_VERSION"),
            },
            dependencies,
        )

    def test_eager_detector_reports_a_migration_module_self_loop(self) -> None:
        files = {
            "__init__.py": "",
            "agents/__init__.py": "",
            "agents/batch.py": "import gravity_insight.agents.batch\n",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_insight"
            for relative, content in files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            expected = [["gravity_insight.agents.batch"]]
            self.assertEqual(expected, eager_import_sccs(package))
            self.assertEqual(expected, eager_import_cycles(package))

    def test_eager_detector_does_not_invent_a_package_parent_self_loop(self) -> None:
        files = {
            "__init__.py": "",
            "agents/__init__.py": "from . import batch\n",
            "agents/batch.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_insight"
            for relative, content in files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            self.assertEqual([], eager_import_sccs(package))
            self.assertEqual([], eager_import_cycles(package))

    def test_eager_detector_uses_the_exact_reviewed_migration_ledger(self) -> None:
        scope = json.loads(
            REFERENCE_DISPOSITIONS.read_text(encoding="utf-8")
        )["scope"]
        expected = {
            "gravity_insight" + module.removeprefix("gravity_sdk")
            for move in scope["one_to_one_moves"]
            for module in (move["old_module"], move["new_module"])
        }
        expected.update(
            "gravity_insight" + module.removeprefix("gravity_sdk")
            for module in (
                scope["consolidate_delete"]["old_module"],
                scope["consolidate_delete"]["new_module"],
            )
        )
        self.assertEqual(82, len(scope["one_to_one_moves"]))
        self.assertEqual(166, len(expected))
        self.assertEqual(expected, migration_module_names())
        self.assertTrue(
            {
                "gravity_insight" + module.removeprefix("gravity_sdk")
                for module in scope["retained_modules"]
            }.isdisjoint(migration_module_names())
        )

    def test_eager_detector_ignores_a_retained_only_component(self) -> None:
        retained = "agent_" + "runtime_contracts"
        files = {
            "__init__.py": "",
            f"{retained}.py": "from . import retained_peer\n",
            "retained_peer.py": f"from . import {retained}\n",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_insight"
            for relative, content in files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            retained_component = [[
                f"gravity_insight.{retained}",
                "gravity_insight.retained_peer",
            ]]
            self.assertEqual(retained_component, eager_import_sccs(package))
            self.assertEqual([], eager_import_cycles(package))

    def test_eager_detector_scopes_complete_graph_cycles_to_agent_modules(self) -> None:
        files = {
            "__init__.py": "",
            "agents/__init__.py": "",
            "agents/batch.py": "from ..sql import catalog\n",
            "sql/__init__.py": "from . import catalog\n",
            "sql/catalog.py": "from . import products\n",
            "sql/products.py": "from . import query\n",
            "sql/query.py": "from . import verification\n",
            "sql/verification.py": "from . import query\n",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_insight"
            for relative, content in files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            sql_component = [[
                "gravity_insight.sql",
                "gravity_insight.sql.catalog",
                "gravity_insight.sql.products",
                "gravity_insight.sql.query",
                "gravity_insight.sql.verification",
            ]]
            self.assertEqual(sql_component, eager_import_sccs(package))
            self.assertEqual([], eager_import_cycles(package))

            verification = package / "sql" / "verification.py"
            verification.write_text(
                "from . import query\nfrom ..agents import batch\n",
                encoding="utf-8",
            )
            crossing = eager_import_cycles(package)

        self.assertEqual([sorted([
            "gravity_insight.agents.batch", *sql_component[0],
        ])], crossing)


from tests.agent_migration_characterization import (
    module_graph_adjacency,
    module_graph_baseline,
    module_graph_canonical_sha256,
    module_graph_cyclic_sccs,
    module_graph_definition,
    module_graph_edge_kinds,
    module_graph_for_profile,
    module_graph_measurement,
)


class UnifiedModuleDependencyGraphTests(unittest.TestCase):
    @staticmethod
    def _write_package(root: Path, files: dict[str, str]) -> Path:
        package = root / "gravity_insight"
        for relative, content in files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return package

    def test_unified_graph_definition_is_locked(self) -> None:
        definition = module_graph_definition()
        self.assertEqual(
            "gravity-insight-runtime-possible-module-dependency-graph.v1",
            definition["definition_id"],
        )
        self.assertEqual(
            "b3e0b2a61cb32c8069acec07315c1c65b94a3506c05133c7878a7a2c967f6326",
            module_graph_canonical_sha256(definition),
        )
        self.assertEqual(
            [
                "ast_eager_import",
                "ast_delayed_import",
                "lazy_export_owner",
                "package_parent",
            ],
            definition["profiles"]["canonical"],
        )

    def test_plan_analysis_contract_has_no_package_internal_imports(self) -> None:
        path = PACKAGE_ROOT / "plan_analysis_contract.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        package_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (
                node.level > 0
                or (node.module or "").split(".", 1)[0] == "gravity_insight"
            ):
                package_imports.append(ast.unparse(node))
            elif isinstance(node, ast.Import) and any(
                alias.name.split(".", 1)[0] == "gravity_insight"
                for alias in node.names
            ):
                package_imports.append(ast.unparse(node))
        self.assertEqual([], package_imports)

    def test_unified_edge_kinds_follow_the_declared_runtime_rules(self) -> None:
        files = {
            "__init__.py": """
_EXPORTS = {
    "lazy": (".lazy_owner", "lazy"),
    "also_lazy": (".lazy_owner", "also_lazy"),
}
for name in ("looped",):
    _EXPORTS[name] = (".loop_owner", name)
__all__ = ["not_an_owner"]
import importlib
importlib.import_module("gravity_insight.dynamic_owner")
__import__("gravity_insight.dynamic_owner")
""",
            "consumer.py": """
from typing import TYPE_CHECKING
import gravity_insight.eager_owner as renamed
from .relative_owner import value as renamed_value
from .star_owner import *
from . import sibling as sibling_alias
if TYPE_CHECKING:
    from . import type_owner
if not TYPE_CHECKING:
    from . import runtime_owner
if unknown_condition:
    from . import conditional_owner
else:
    from . import alternate_owner
def run():
    from . import delayed_owner
""",
            "alternate_owner.py": "",
            "conditional_owner.py": "",
            "delayed_owner.py": "",
            "dynamic_owner.py": "",
            "eager_owner.py": "",
            "lazy_owner.py": "",
            "loop_owner.py": "",
            "relative_owner.py": "",
            "runtime_owner.py": "",
            "sibling.py": "",
            "star_owner.py": "",
            "type_owner.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._write_package(Path(raw), files)
            inventory, edges = module_graph_edge_kinds(package)
        eager_targets = {
            target
            for source, target in edges["ast_eager_import"]
            if source == "gravity_insight.consumer"
        }
        self.assertEqual(
            {
                "gravity_insight",
                "gravity_insight.alternate_owner",
                "gravity_insight.conditional_owner",
                "gravity_insight.eager_owner",
                "gravity_insight.relative_owner",
                "gravity_insight.runtime_owner",
                "gravity_insight.sibling",
                "gravity_insight.star_owner",
            },
            eager_targets,
        )
        self.assertEqual(
            {
                ("gravity_insight.consumer", "gravity_insight"),
                ("gravity_insight.consumer", "gravity_insight.delayed_owner"),
            },
            edges["ast_delayed_import"],
        )
        self.assertNotIn(
            ("gravity_insight.consumer", "gravity_insight.type_owner"),
            edges["ast_eager_import"],
        )
        self.assertEqual(
            {
                ("gravity_insight", "gravity_insight.lazy_owner"),
                ("gravity_insight", "gravity_insight.loop_owner"),
            },
            edges["lazy_export_owner"],
        )
        self.assertNotIn(
            ("gravity_insight", "gravity_insight.dynamic_owner"),
            edges["lazy_export_owner"],
        )
        self.assertEqual(len(inventory) - 1, len(edges["package_parent"]))

    def test_unified_scc_rule_counts_multi_node_cycles_and_self_loops(self) -> None:
        graph = {
            "gravity_insight.a": {"gravity_insight.a"},
            "gravity_insight.b": {"gravity_insight.c"},
            "gravity_insight.c": {"gravity_insight.b"},
            "gravity_insight.d": set(),
        }
        self.assertEqual(
            [
                ["gravity_insight.b", "gravity_insight.c"],
                ["gravity_insight.a"],
            ],
            module_graph_cyclic_sccs(graph),
        )

    def test_unified_profiles_are_cumulative(self) -> None:
        definition = module_graph_definition()
        files = {
            "__init__.py": '_EXPORTS = {"owner": (".owner", "value")}\n',
            "owner.py": "def run():\n    from . import delayed\n",
            "delayed.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._write_package(Path(raw), files)
            inventory, edges = module_graph_edge_kinds(package)
        nodes = [name for name, _is_package in inventory.values()]
        counts = {
            name: sum(
                len(targets)
                for targets in module_graph_for_profile(
                    nodes, edges, kinds,
                ).values()
            )
            for name, kinds in definition["profiles"].items()
        }
        self.assertLess(counts["eager-ast-only"], counts["ast-only"])
        self.assertLess(counts["ast-only"], counts["ast+lazy-exports"])
        self.assertLess(counts["ast+lazy-exports"], counts["canonical"])

    def test_unified_profile_graph_is_machine_readable(self) -> None:
        definition = module_graph_definition()
        files = {
            "__init__.py": "",
            "consumer.py": "import gravity_insight.owner\n",
            "owner.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._write_package(Path(raw), files)
            graph = module_graph_adjacency(package, definition, "ast-only")
        self.assertEqual("ast-only", graph["profile"])
        self.assertEqual(
            ["gravity_insight.owner"],
            graph["edges"]["gravity_insight.consumer"],
        )

    def test_unified_current_graph_matches_the_reviewed_baseline(self) -> None:
        expected = module_graph_baseline()
        self.assertEqual(
            "eaf9e7416be1d41d48939a3b22dfc26eb2f7e899d9ca5f56978adda486860e83",
            module_graph_canonical_sha256(expected),
        )
        self.assertEqual(
            {
                "ast-only": 20,
                "ast+lazy-exports": 428,
                "canonical": 534,
                "eager-ast-only": 5,
            },
            {
                profile: summary["largest_cyclic_scc_size"]
                for profile, summary in expected["profiles"].items()
            },
        )
        self.assertEqual(
            [20, 17, 11, 8, 6, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 1],
            expected["profiles"]["ast-only"]["cyclic_scc_sizes"],
        )
        self.assertEqual(
            [534, 15, 8, 3, 2, 2],
            expected["profiles"]["canonical"]["cyclic_scc_sizes"],
        )
        self.assertEqual(expected, module_graph_measurement())


if __name__ == "__main__":
    unittest.main()
