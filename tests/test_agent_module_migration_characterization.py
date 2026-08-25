"""Characterize contracts that the agent subpackage migration must preserve."""

from __future__ import annotations

import json
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
    expected_public_exports,
)


_LAZY_PROBE = r"""
import json
import sys
import types

expected = json.load(sys.stdin)
import gravity_sdk

preloaded = sorted(
    "gravity_sdk" + owner
    for owner, _ in expected.values()
    if "gravity_sdk" + owner in sys.modules
)
assert preloaded == [], f"owner modules loaded with package: {preloaded}"

modules = {}
sentinels = {}
for _, (owner, attribute) in expected.items():
    module = modules.setdefault(owner, types.ModuleType("gravity_sdk" + owner))
    sentinel = sentinels.setdefault((owner, attribute), object())
    setattr(module, attribute, sentinel)

calls = []
def fake_import(owner, package):
    calls.append((owner, package))
    assert owner in modules, f"unexpected owner import: {owner}"
    return modules[owner]

gravity_sdk.import_module = fake_import
for name, (owner, attribute) in expected.items():
    assert name not in gravity_sdk.__dict__, f"root export was eager: {name}"
    before = len(calls)
    first = getattr(gravity_sdk, name)
    assert calls[before:] == [(owner, "gravity_sdk")], (
        f"wrong owner for {name}: {calls[before:]}"
    )
    assert first is sentinels[(owner, attribute)]
    second = getattr(gravity_sdk, name)
    assert second is first and len(calls) == before + 1, f"cache miss: {name}"

missing = "__characterization_missing_export__"
try:
    getattr(gravity_sdk, missing)
except AttributeError as error:
    assert str(error) == f"module 'gravity_sdk' has no attribute {missing!r}"
else:
    raise AssertionError("unknown root export did not raise AttributeError")

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

    def test_eager_module_import_graph_has_no_strongly_connected_component(self) -> None:
        self.assertEqual([], eager_import_cycles(PACKAGE_ROOT))


if __name__ == "__main__":
    unittest.main()
