from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = (
    ROOT / "src" / "gravity_sdk",
    ROOT / "src" / "gravity_sdk",
)
FORBIDDEN_BROWSER_IMPORTS = {
    "playwright",
    "pyppeteer",
    "selenium",
    "webbrowser",
}
FORBIDDEN_EDITOR_ROUTE = "pivotReport"


class GravityInsightBrowserIsolationTests(unittest.TestCase):
    def test_sdk_and_cli_cannot_depend_on_browser_automation_or_editor_routes(self) -> None:
        violations: list[str] = []

        for package_root in PRODUCTION_ROOTS:
            for path in sorted(package_root.rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots = {alias.name.split(".", 1)[0] for alias in node.names}
                        blocked = roots & FORBIDDEN_BROWSER_IMPORTS
                        if blocked:
                            violations.append(
                                f"{path.relative_to(ROOT)} imports {sorted(blocked)}"
                            )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        root = node.module.split(".", 1)[0]
                        if root in FORBIDDEN_BROWSER_IMPORTS:
                            violations.append(
                                f"{path.relative_to(ROOT)} imports {root}"
                            )
                    elif (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and FORBIDDEN_EDITOR_ROUTE in node.value
                    ):
                        violations.append(
                            f"{path.relative_to(ROOT)} embeds the report editor route"
                        )

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
