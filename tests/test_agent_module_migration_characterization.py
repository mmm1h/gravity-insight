"""Characterize contracts that the agent subpackage migration must preserve."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.agent_migration_characterization import (
    PACKAGE_ROOT,
    ROOT,
    agent_path_classification,
    agent_path_references,
    eager_import_cycles,
    eager_import_sccs,
    expected_public_exports,
)


_LAZY_PROBE = r"""
import importlib
import importlib.util
import json
import sys

expected = json.load(sys.stdin)
assert len(expected) == 147, f"public snapshot count changed: {len(expected)}"

def fresh_package():
    for module in list(sys.modules):
        if module == "gravity_sdk" or module.startswith("gravity_sdk."):
            del sys.modules[module]
    return importlib.import_module("gravity_sdk")

for name, (owner, attribute) in expected.items():
    gravity_sdk = fresh_package()
    absolute_owner = importlib.util.resolve_name(owner, gravity_sdk.__name__)
    assert absolute_owner not in sys.modules, (
        f"owner loaded with package for {name}: {absolute_owner}"
    )
    assert name not in gravity_sdk.__dict__, f"root export was eager: {name}"
    first = getattr(gravity_sdk, name)
    owner_module = sys.modules.get(absolute_owner)
    assert owner_module is not None, (
        f"owner was not imported for {name}: {absolute_owner}"
    )
    assert first is getattr(owner_module, attribute), (
        f"wrong owner identity for {name}: {absolute_owner}.{attribute}"
    )

    del sys.modules[absolute_owner]
    try:
        second = getattr(gravity_sdk, name)
        assert second is first, f"cached identity changed for {name}"
        assert absolute_owner not in sys.modules, (
            f"owner reloaded on cached access for {name}: {absolute_owner}"
        )
    finally:
        sys.modules[absolute_owner] = owner_module

gravity_sdk = fresh_package()
missing = "__characterization_missing_export__"
try:
    getattr(gravity_sdk, missing)
except AttributeError as error:
    assert str(error) == f"module 'gravity_sdk' has no attribute {missing!r}"
else:
    raise AssertionError("unknown root export did not raise AttributeError")

assert len(gravity_sdk.__all__) == 148, (
    f"runtime __all__ count changed: {len(gravity_sdk.__all__)}"
)
assert set(gravity_sdk.__all__) == {*expected, "__version__"}
assert set(gravity_sdk.__all__) <= set(dir(gravity_sdk))
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

    def test_agent_deep_paths_are_explicitly_public_or_internal(self) -> None:
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

    def test_eager_detector_scopes_complete_graph_cycles_to_agent_modules(self) -> None:
        files = {
            "__init__.py": "",
            "agents/__init__.py": "",
            "agents/bridge.py": "from ..sql import catalog\n",
            "sql/__init__.py": "from . import catalog\n",
            "sql/catalog.py": "from . import products\n",
            "sql/products.py": "from . import query\n",
            "sql/query.py": "from . import verification\n",
            "sql/verification.py": "from . import query\n",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "gravity_sdk"
            for relative, content in files.items():
                path = package / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            sql_component = [[
                "gravity_sdk.sql",
                "gravity_sdk.sql.catalog",
                "gravity_sdk.sql.products",
                "gravity_sdk.sql.query",
                "gravity_sdk.sql.verification",
            ]]
            self.assertEqual(sql_component, eager_import_sccs(package))
            self.assertEqual([], eager_import_cycles(package))

            verification = package / "sql" / "verification.py"
            verification.write_text(
                "from . import query\nfrom ..agents import bridge\n",
                encoding="utf-8",
            )
            crossing = eager_import_cycles(package)

        self.assertEqual([sorted([
            "gravity_sdk.agents.bridge", *sql_component[0],
        ])], crossing)


if __name__ == "__main__":
    unittest.main()
