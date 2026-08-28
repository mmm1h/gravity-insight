from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from gravity_sdk.journey_contract import journey_artifacts


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/gravity_sdk"
FIXTURE = ROOT / "tests/fixtures/mcp_removability_surfaces.json"


def _mcp_import(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == "gravity_sdk.mcp" or alias.name.startswith(
                "gravity_sdk.mcp."
            ):
                return alias.name
        return None
    if not isinstance(node, ast.ImportFrom):
        return None
    module = node.module or ""
    if module == "gravity_sdk.mcp" or module.startswith("gravity_sdk.mcp."):
        return module
    if node.level and (module == "mcp" or module.startswith("mcp.")):
        return module
    if module in {"", "gravity_sdk"} and any(
        alias.name == "mcp" for alias in node.names
    ):
        return f"{module}.mcp" if module else "mcp"
    return None


class MCPRemovabilityTests(unittest.TestCase):
    def test_removing_mcp_preserves_every_journey_surface_contract(self) -> None:
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["journeys"]
        actual = {
            artifact["contract"]["journey_id"]: artifact["contract"]["surfaces"]
            for artifact in journey_artifacts()
        }

        self.assertEqual(expected, actual)
        for journey_id, surfaces in actual.items():
            with self.subTest(journey=journey_id):
                states = {surfaces[name] for name in ("cli", "sdk", "plan")}
                self.assertEqual(1, len(states))
                self.assertIn(states.pop(), {"available", "declared", "missing"})

    def test_mcp_is_a_removable_leaf_with_no_runtime_reverse_imports(self) -> None:
        references = []
        for path in PACKAGE.rglob("*.py"):
            if path.is_relative_to(PACKAGE / "mcp"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                reference = _mcp_import(node)
                if reference is not None:
                    references.append(f"{path}:{node.lineno}:{reference}")

        self.assertEqual([], references)

    def test_reverse_import_detector_covers_absolute_and_relative_forms(self) -> None:
        sources = (
            "import gravity_sdk.mcp.server",
            "from gravity_sdk.mcp import MCPServer",
            "from gravity_sdk import mcp",
            "from . import mcp",
            "from .mcp import server",
        )
        for source in sources:
            with self.subTest(source=source):
                tree = ast.parse(source)
                self.assertTrue(any(_mcp_import(node) for node in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
