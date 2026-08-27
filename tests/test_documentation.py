from __future__ import annotations

import re
import unittest
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ARCHIVE = DOCS / "archive"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def local_markdown_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw_target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw_target.split("#", 1)[0].strip().strip("<>")
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append((path.parent / target).resolve())
    return targets


def reachable_markdown(start: Path, allowed: set[Path]) -> set[Path]:
    reachable: set[Path] = set()
    queue = deque([start.resolve()])
    while queue:
        current = queue.popleft()
        if current in reachable or current not in allowed or not current.is_file():
            continue
        reachable.add(current)
        queue.extend(target for target in local_markdown_targets(current) if target in allowed)
    return reachable


class DocumentationArchitectureTests(unittest.TestCase):
    def test_all_local_markdown_links_exist(self) -> None:
        sources = [ROOT / "README.md", ROOT / "MIGRATION.md", *DOCS.rglob("*.md")]
        missing: list[str] = []
        for source in sources:
            for target in local_markdown_targets(source):
                # Archived prose is frozen history and does not follow current source paths.
                if (
                    ARCHIVE.resolve() in source.resolve().parents
                    and target != DOCS.resolve()
                    and DOCS.resolve() not in target.parents
                ):
                    continue
                if not target.exists():
                    missing.append(f"{source.relative_to(ROOT)} -> {target}")
        self.assertEqual([], missing)

    def test_every_active_doc_is_reachable_from_the_docs_index(self) -> None:
        expected = {
            path.resolve()
            for path in DOCS.rglob("*.md")
            if ARCHIVE.resolve() not in path.resolve().parents
        }
        reachable = reachable_markdown(DOCS / "index.md", expected)
        unreachable = sorted(str(path.relative_to(ROOT)) for path in expected - reachable)
        self.assertEqual([], unreachable)

    def test_every_archived_doc_is_reachable_from_the_archive_index(self) -> None:
        expected = {path.resolve() for path in ARCHIVE.rglob("*.md")}
        reachable = reachable_markdown(ARCHIVE / "index.md", expected)
        unreachable = sorted(str(path.relative_to(ROOT)) for path in expected - reachable)
        self.assertEqual([], unreachable)

    def test_entry_documents_stay_small(self) -> None:
        budgets = {
            ROOT / "README.md": 100,
            DOCS / "index.md": 100,
            DOCS / "getting-started.md": 160,
            DOCS / "team-onboarding.md": 120,
            DOCS / "agent-workflow.md": 220,
            DOCS / "roadmap.md": 80,
            DOCS / "maintainers/index.md": 100,
            DOCS / "research.md": 80,
            ARCHIVE / "index.md": 80,
        }
        excess = {
            str(path.relative_to(ROOT)): len(path.read_text(encoding="utf-8").splitlines())
            for path, limit in budgets.items()
            if len(path.read_text(encoding="utf-8").splitlines()) > limit
        }
        self.assertEqual({}, excess)

    def test_active_human_docs_stay_within_consolidation_budget(self) -> None:
        files = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "MIGRATION.md"]
        files.extend(
            path
            for path in DOCS.rglob("*.md")
            if ARCHIVE.resolve() not in path.resolve().parents
            and (DOCS / "agent-skills").resolve() not in path.resolve().parents
        )
        lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files)
        size = sum(path.stat().st_size for path in files)
        self.assertLessEqual(lines, 5516)
        self.assertLessEqual(size, 450 * 1024)

    def test_entry_docs_do_not_state_catalog_totals(self) -> None:
        sources = [
            ROOT / "README.md",
            DOCS / "index.md",
            DOCS / "getting-started.md",
            DOCS / "team-onboarding.md",
            DOCS / "agent-workflow.md",
            DOCS / "roadmap.md",
        ]
        patterns = (
            re.compile(r"\b\d+\s*个\s*(?:stable\s+)?operations?\b", re.IGNORECASE),
            re.compile(r"\b\d+\s+(?:stable\s+)?operations?\b", re.IGNORECASE),
            re.compile(r"\b\d+\s+(?:read|governed)\b", re.IGNORECASE),
        )
        offenders = [
            str(path.relative_to(ROOT))
            for path in sources
            if any(pattern.search(path.read_text(encoding="utf-8")) for pattern in patterns)
        ]
        self.assertEqual([], offenders)

    def test_candidate_matrix_has_19_unique_operations(self) -> None:
        """Adding a row is a deliberate act, so the count is pinned.

        Went 18 -> 19 for issue #28's `sql.user-event.aggregate-join` verdict:
        the local failure classification is now precise, while upstream join
        support still needs one sanitized protocol sample or an owner contract.
        """

        rows = [
            line
            for line in (DOCS / "candidate-capability-matrix.md")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.startswith("| `")
        ]
        operations = [row.split("|", 2)[1].strip().strip("`") for row in rows]
        self.assertEqual(19, len(operations))
        self.assertEqual(19, len(set(operations)))

    def test_retired_document_paths_are_absent(self) -> None:
        retired = [
            DOCS / "roadmap.d",
            DOCS / "research",
            DOCS / "mcp-feasibility.md",
            DOCS / "capability-coverage.md",
        ]
        retired.extend(
            DOCS / "maintainers" / name
            for name in (
                "business-pulse-agent-surface.md",
                "dashboard-conditions.md",
                "material-performance.md",
                "multidim-agent-surface.md",
                "order-directory.md",
                "order-split-trace.md",
                "promotion-performance.md",
            )
        )
        self.assertEqual([], [str(path.relative_to(ROOT)) for path in retired if path.exists()])

    def test_current_markdown_does_not_reference_retired_locations(self) -> None:
        sources = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "MIGRATION.md"]
        sources.extend(
            path for path in DOCS.rglob("*.md") if ARCHIVE.resolve() not in path.resolve().parents
        )
        retired_refs = (
            "docs/roadmap.d/",
            "docs/research/",
            "docs/mcp-feasibility.md",
            "docs/capability-coverage.md",
            "docs/maintainers/business-pulse-agent-surface.md",
            "docs/maintainers/dashboard-conditions.md",
            "docs/maintainers/material-performance.md",
            "docs/maintainers/multidim-agent-surface.md",
            "docs/maintainers/order-directory.md",
            "docs/maintainers/order-split-trace.md",
            "docs/maintainers/promotion-performance.md",
        )
        offenders = [
            str(path.relative_to(ROOT))
            for path in sources
            if any(ref in path.read_text(encoding="utf-8") for ref in retired_refs)
        ]
        self.assertEqual([], offenders)

    def test_no_unresolved_merge_conflict_markers(self) -> None:
        # A botched conflict resolution once shipped `<<<<<<<` markers into the
        # journey ledger on dev, main and origin: the duplicate rows were caught
        # by the ledger parser, the leftover markers were caught by nothing.
        sources = [
            ROOT / "README.md",
            ROOT / "MIGRATION.md",
            *DOCS.rglob("*.md"),
            *(ROOT / "src").rglob("*.py"),
            *(ROOT / "src").rglob("*.json"),
            *(ROOT / "tests").rglob("*.py"),
            *(ROOT / "scripts").rglob("*.py"),
        ]
        offenders: list[str] = []
        for source in sources:
            for number, line in enumerate(
                source.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "=======":
                    offenders.append(f"{source.relative_to(ROOT)}:{number}")
        self.assertEqual([], offenders)

    def test_business_contracts_are_not_in_the_documentation_tree(self) -> None:
        legacy = DOCS / "data-contracts"
        self.assertEqual([], [path for path in legacy.rglob("*") if path.is_file()])
        self.assertTrue(
            (ROOT / "src/gravity_sdk/contracts/sql-products/catalog.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
