"""Characterize contracts that the agent subpackage migration must preserve."""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pytest

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


_PROBE_ROOT = ROOT / "tests" / "fixtures" / "agent_module_migration_probes"


def _probe_source(name: str) -> str:
    return (_PROBE_ROOT / name).read_text(encoding="utf-8")


_LAZY_PROBE = _probe_source("lazy_root_exports.py.txt")
_SHADOWING_PROBE = _probe_source("shadowed_root_exports.py.txt")
_FAIL_CLOSED_PROBE = _probe_source("shadowed_export_fail_closed.py.txt")


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

    @pytest.mark.full_gate
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

    def test_sql_modules_import_in_every_order_without_eager_cycle(self) -> None:
        modules = (
            "gravity_insight.sql",
            "gravity_insight.sql.catalog",
            "gravity_insight.sql.products",
            "gravity_insight.sql.query",
            "gravity_insight.sql.verification",
        )
        definition = module_graph_definition()
        inventory, edge_kinds = module_graph_edge_kinds(PACKAGE_ROOT)
        graph = module_graph_for_profile(
            (name for name, _is_package in inventory.values()),
            edge_kinds,
            definition["profiles"]["eager-ast-only"],
        )
        self.assertEqual([], module_graph_cyclic_sccs(graph))

        probe = "\n".join(
            (
                "import importlib",
                "import itertools",
                "import sys",
                "import gravity_insight",
                f"modules = {modules!r}",
                "for order in itertools.permutations(modules):",
                "    for name in tuple(sys.modules):",
                "        if name == 'gravity_insight.sql' or name.startswith('gravity_insight.sql.'):",
                "            sys.modules.pop(name, None)",
                "    gravity_insight.__dict__.pop('sql', None)",
                "    for name in order:",
                "        importlib.import_module(name)",
                "print(sum(1 for _ in itertools.permutations(modules)))",
            )
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(
            str(len(tuple(itertools.permutations(modules)))),
            completed.stdout.strip(),
        )

    def test_unified_current_graph_matches_the_reviewed_baseline(self) -> None:
        expected = module_graph_baseline()
        self.assertEqual(
            "7a8ae828a7847aba1fafed9ec955cf0bb95925d078d9f0a14d056086ec273f12",
            module_graph_canonical_sha256(expected),
        )
        self.assertEqual(
            {
                "ast-only": 20,
                "ast+lazy-exports": 429,
                "canonical": 541,
                "eager-ast-only": 0,
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
            [541, 15, 8, 3, 2, 2],
            expected["profiles"]["canonical"]["cyclic_scc_sizes"],
        )
        self.assertEqual(expected, module_graph_measurement())


if __name__ == "__main__":
    unittest.main()
