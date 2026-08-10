from __future__ import annotations

import re
import unittest
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def local_markdown_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw_target.split("#", 1)[0].strip().strip("<>")
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append((path.parent / target).resolve())
    return targets


class DocumentationArchitectureTests(unittest.TestCase):
    def test_all_local_markdown_links_exist(self) -> None:
        sources = [ROOT / "README.md", ROOT / "MIGRATION.md", *DOCS.rglob("*.md")]
        missing: list[str] = []
        for source in sources:
            for target in local_markdown_targets(source):
                if not target.exists():
                    missing.append(f"{source.relative_to(ROOT)} -> {target}")
        self.assertEqual([], missing)

    def test_every_doc_is_reachable_from_the_docs_index(self) -> None:
        start = (DOCS / "index.md").resolve()
        reachable: set[Path] = set()
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current in reachable or not current.is_file():
                continue
            reachable.add(current)
            for target in local_markdown_targets(current):
                if DOCS.resolve() in target.parents and target.suffix == ".md":
                    queue.append(target)
        expected = {path.resolve() for path in DOCS.rglob("*.md")}
        unreachable = sorted(str(path.relative_to(ROOT)) for path in expected - reachable)
        self.assertEqual([], unreachable)

    def test_entry_documents_stay_small(self) -> None:
        budgets = {
            ROOT / "README.md": 100,
            DOCS / "index.md": 100,
            DOCS / "getting-started.md": 160,
            DOCS / "agent-workflow.md": 220,
        }
        excess = {
            str(path.relative_to(ROOT)): len(path.read_text(encoding="utf-8").splitlines())
            for path, limit in budgets.items()
            if len(path.read_text(encoding="utf-8").splitlines()) > limit
        }
        self.assertEqual({}, excess)

    def test_business_contracts_are_not_in_the_documentation_tree(self) -> None:
        legacy = DOCS / "data-contracts"
        self.assertEqual([], [path for path in legacy.rglob("*") if path.is_file()])
        self.assertTrue(
            (ROOT / "src/gravity_sdk/contracts/sql-products/catalog.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
