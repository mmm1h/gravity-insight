"""Regression gates for the governed four-layer Runtime boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_agent_module_references import (
    DOMAIN_BOUNDARY_BASELINE_PATH,
    DOMAIN_BOUNDARY_SCHEMA_VERSION,
    ROOT,
    domain_boundary_baseline_document,
    domain_boundary_errors,
    domain_boundary_measurement,
    evaluate_domain_boundary,
)


class DomainBoundaryTests(unittest.TestCase):
    @staticmethod
    def _package(root: Path, files: dict[str, str]) -> Path:
        package = root / "gravity_insight"
        for relative, source in files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return package

    def test_checked_in_baseline_matches_the_current_ratchet(self) -> None:
        errors, measurement = domain_boundary_errors(ROOT)
        baseline = json.loads(DOMAIN_BOUNDARY_BASELINE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(DOMAIN_BOUNDARY_SCHEMA_VERSION, baseline["schema_version"])
        self.assertEqual([], errors)
        self.assertEqual(
            measurement["graph"]["largest_cyclic_scc_size"],
            baseline["maximum_ast_only_scc_size"],
        )
        self.assertEqual(
            measurement["direction"]["violation_count"],
            baseline["maximum_direction_violation_count"],
        )
        self.assertEqual(
            measurement["classification"]["coverage"],
            baseline["minimum_classification_coverage"],
        )
        self.assertEqual(
            measurement["graph"]["node_count"],
            measurement["classification"]["classified_module_count"]
            + measurement["classification"]["unclassified_module_count"],
        )
        self.assertEqual(
            measurement["classification"]["unclassified_module_count"],
            len(measurement["classification"]["unclassified_modules"]),
        )

    def test_query_match_leaf_keeps_the_existing_public_import(self) -> None:
        from gravity_insight.agents.query_match import query_match as owner
        from gravity_insight.find import query_match as public

        self.assertIs(owner, public)

    def test_reverse_dependency_increases_direction_violation_count(self) -> None:
        files = {
            "__init__.py": "",
            "contracts/__init__.py": "",
            "contracts/value.py": "",
            "mcp/__init__.py": "",
            "mcp/tool.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), files)
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "contracts/value.py").write_text(
                "from gravity_insight.mcp import tool\n", encoding="utf-8"
            )
            observed = domain_boundary_measurement(package)

        self.assertEqual(1, observed["direction"]["violation_count"])
        self.assertIn(
            "domain boundary dependency-direction violations increased: current=1, maximum=0",
            evaluate_domain_boundary(observed, baseline),
        )

    def test_new_direct_root_module_fails_with_its_exact_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), {"__init__.py": ""})
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "new_domain.py").write_text("VALUE = 1\n", encoding="utf-8")
            observed = domain_boundary_measurement(package)

        self.assertIn(
            "new unclassified modules may not enter the gravity_insight root package "
            "without an exact reasoned exemption: gravity_insight.new_domain",
            evaluate_domain_boundary(observed, baseline),
        )

    def test_new_unclassified_module_fails_classification_coverage_ratchet(self) -> None:
        files = {
            "__init__.py": "",
            "owner/__init__.py": "",
            "owner/existing.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), files)
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "owner/new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
            observed = domain_boundary_measurement(package)

        errors = evaluate_domain_boundary(observed, baseline)
        self.assertIn(
            "domain boundary classification coverage decreased: "
            "current=1/4, minimum=1/3",
            errors,
        )
        self.assertIn(
            "new non-root modules must be assigned a layer or carry an exact "
            "reasoned unclassified exemption: gravity_insight.owner.new_module",
            errors,
        )

    def test_reasoned_unclassified_exemption_does_not_hide_coverage_loss(self) -> None:
        files = {
            "__init__.py": "",
            "owner/__init__.py": "",
            "owner/existing.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), files)
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "owner/new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
            observed = domain_boundary_measurement(package)
        baseline["unclassified_module_exemptions"] = [
            {
                "module": "gravity_insight.owner.new_module",
                "reason": "Owner decision is pending.",
            }
        ]

        errors = evaluate_domain_boundary(observed, baseline)

        self.assertTrue(any("classification coverage decreased" in error for error in errors))
        self.assertFalse(any("new non-root modules" in error for error in errors))

    def test_new_layered_module_improves_coverage_without_an_exemption(self) -> None:
        files = {
            "__init__.py": "",
            "contracts/__init__.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), files)
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "contracts/value.py").write_text("VALUE = 1\n", encoding="utf-8")
            observed = domain_boundary_measurement(package)

        self.assertEqual([], evaluate_domain_boundary(observed, baseline))
        self.assertEqual(
            {"classified_module_count": 3, "module_count": 3},
            observed["classification"]["coverage"],
        )

    def test_larger_ast_only_cycle_fails_the_scc_ratchet(self) -> None:
        files = {
            "__init__.py": "",
            "owner/__init__.py": "",
            "owner/a.py": "",
            "owner/b.py": "",
        }
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), files)
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "owner/a.py").write_text(
                "from . import b\n", encoding="utf-8"
            )
            (package / "owner/b.py").write_text(
                "from . import a\n", encoding="utf-8"
            )
            observed = domain_boundary_measurement(package)

        self.assertEqual(2, observed["graph"]["largest_cyclic_scc_size"])
        self.assertIn(
            "domain boundary largest AST-only SCC increased: current=2, maximum=0",
            evaluate_domain_boundary(observed, baseline),
        )

    def test_root_exemption_requires_a_non_empty_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(
                Path(raw), {"__init__.py": "", "accepted.py": ""}
            )
            observed = domain_boundary_measurement(package)
        baseline = domain_boundary_baseline_document(observed)
        baseline["protected_root_modules"] = ["gravity_insight"]
        baseline["unclassified_module_exemptions"] = [
            {"module": "gravity_insight.accepted", "reason": ""}
        ]

        errors = evaluate_domain_boundary(observed, baseline)

        self.assertIn(
            "domain boundary unclassified exemption 0 needs a module and non-empty reason",
            errors,
        )
        self.assertIn("gravity_insight.accepted", errors[-1])

    def test_baseline_refresh_cannot_loosen_existing_ratchets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._package(Path(raw), {"__init__.py": ""})
            baseline = domain_boundary_baseline_document(
                domain_boundary_measurement(package)
            )
            (package / "owner.py").write_text(
                "import gravity_insight\n", encoding="utf-8"
            )
            (package / "__init__.py").write_text(
                "from . import owner\n", encoding="utf-8"
            )
            observed = domain_boundary_measurement(package)
        observed["direction"]["violation_count"] = 1

        refreshed = domain_boundary_baseline_document(observed, baseline)

        self.assertEqual(0, refreshed["maximum_ast_only_scc_size"])
        self.assertEqual(0, refreshed["maximum_direction_violation_count"])
        self.assertEqual(
            {"classified_module_count": 1, "module_count": 1},
            refreshed["minimum_classification_coverage"],
        )


if __name__ == "__main__":
    unittest.main()
