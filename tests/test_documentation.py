from __future__ import annotations

import json
import re
import tempfile
import unittest
from collections import deque
from pathlib import Path

from gravity_insight.documentation_gate import (
    CANONICAL_MAX_BYTES,
    CANONICAL_MAX_LINES,
    current_markdown_files,
    documentation_errors,
    documentation_tree_errors,
    validate_architecture_binding,
    validate_mermaid,
)
from tests.repository_tree_gate import repository_tree_read


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
        sources = [ROOT / "README.md", *DOCS.rglob("*.md")]
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
                if (
                    source == ROOT / "README.md"
                    and target == ROOT / "specs/agent-runtime/architecture-source.md"
                ):
                    # The release/CI migration owns this explicitly frozen hand-off.
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

    def test_historical_archive_is_absent(self) -> None:
        self.assertEqual([], [path for path in ARCHIVE.rglob("*.md")])

    def test_entry_documents_stay_small(self) -> None:
        budgets = {
            ROOT / "README.md": 100,
            DOCS / "index.md": 100,
            DOCS / "team-onboarding.md": 120,
            DOCS / "agent-workflow.md": 220,
            DOCS / "roadmap.md": 80,
            DOCS / "maintainers/index.md": 100,
        }
        excess = {
            str(path.relative_to(ROOT)): len(path.read_text(encoding="utf-8").splitlines())
            for path, limit in budgets.items()
            if len(path.read_text(encoding="utf-8").splitlines()) > limit
        }
        self.assertEqual({}, excess)

    def test_active_human_docs_stay_within_consolidation_budget(self) -> None:
        files = [ROOT / "README.md", ROOT / "AGENTS.md"]
        files.extend(
            path
            for path in DOCS.rglob("*.md")
            if ARCHIVE.resolve() not in path.resolve().parents
            and (DOCS / "agent-skills").resolve() not in path.resolve().parents
        )
        lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files)
        size = sum(path.stat().st_size for path in files)
        self.assertLessEqual(lines, 5547)
        self.assertLessEqual(size, 450 * 1024)

    def test_entry_docs_do_not_state_catalog_totals(self) -> None:
        sources = [
            ROOT / "README.md",
            DOCS / "index.md",
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
            DOCS / "getting-started.md",
            DOCS / "research.md",
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
        sources = [ROOT / "README.md", ROOT / "AGENTS.md"]
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
        with repository_tree_read(
            root=ROOT,
            purpose="merge-conflict marker repository scan",
        ):
            sources = [
                ROOT / "README.md",
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
            (ROOT / "src/gravity_insight/contracts/sql-products/catalog.json").is_file()
        )

    def test_current_documentation_governance_gate_passes(self) -> None:
        self.assertEqual([], documentation_errors(ROOT))

    def test_tree_gate_reports_links_orphans_and_obsolete_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "index.md").write_text(
                "# Index\n\n[Missing](missing.md)\n", encoding="utf-8"
            )
            (docs / "orphan.md").write_text(
                "# Orphan\n\npython -m gravity_sdk --help\n", encoding="utf-8"
            )

            errors = documentation_tree_errors(root)

        self.assertIn(
            f"broken local link: docs/index.md -> {(docs / 'missing.md').resolve()}",
            errors,
        )
        self.assertIn("orphan documentation: docs/orphan.md", errors)
        self.assertIn("obsolete gravity-sdk command: docs/orphan.md:3", errors)

    def test_canonical_architecture_uses_upper_bounds_not_exact_sizes(self) -> None:
        result = validate_architecture_binding(ROOT)
        self.assertLessEqual(result["lines"], CANONICAL_MAX_LINES)
        self.assertLessEqual(result["bytes"], CANONICAL_MAX_BYTES)

    def test_canonical_architecture_mermaid_is_valid(self) -> None:
        self.assertGreaterEqual(
            validate_mermaid((DOCS / "architecture.md").read_text(encoding="utf-8")),
            1,
        )

    def test_released_requirement_ledgers_are_not_current_documents(self) -> None:
        current = {
            path.relative_to(ROOT).as_posix()
            for path in current_markdown_files(ROOT)
        }
        self.assertFalse(
            any(path.startswith("specs/agent-runtime/R") for path in current)
        )

    def test_vendor_neutral_ct_references_are_current_and_exact(self) -> None:
        names = (
            "CT01-external-method-inventory.md",
            "CT02-skill-library-validation.md",
            "CT03-skill-library-specification.md",
            "CT04-agent-skill-distribution.md",
        )
        markdown = (ROOT / "specs/agent-runtime/index.md").read_text(encoding="utf-8")
        index = json.loads(
            (ROOT / "specs/agent-runtime/index.json").read_text(encoding="utf-8")
        )
        library = next(
            component
            for component in index["components"]
            if component["id"] == "external-method-library"
        )
        self.assertEqual(list(names), library["governance_references"])
        for name in names:
            self.assertTrue((ROOT / "specs/agent-runtime" / name).is_file())
            self.assertIn(f"]({name})", markdown)


if __name__ == "__main__":
    unittest.main()
