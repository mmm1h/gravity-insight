from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_insight.census.diffing import CensusFailureClass
from gravity_insight.census.status import census_status
from gravity_insight.cli import build_parser
from gravity_insight.documentation_status import (
    documentation_report,
    integrated_documentation_errors,
)
from gravity_insight.evidence_common import dimension, metric
from gravity_insight.journey_certification import journey_certifications
from gravity_insight.runtime_health import runtime_health_report


ROOT = Path(__file__).resolve().parents[1]


class EvidenceCommandRegistrationTests(unittest.TestCase):
    def test_all_insight_evidence_commands_are_offline_and_accept_json(self) -> None:
        parser = build_parser()
        for argv in (
            ["journey", "certifications", "--json"],
            ["maturity", "score", "--json"],
            ["runtime", "health", "--json"],
            ["docs", "check", "--json"],
        ):
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertFalse(args.network_required)
                self.assertTrue(args.json)

    def test_census_status_accepts_json(self) -> None:
        from gravity_insight.census.cli import build_parser as census_parser

        args = census_parser().parse_args(["status", "--json"])
        self.assertEqual("status", args.command)
        self.assertTrue(args.json)


class EvidenceCollectorTests(unittest.TestCase):
    def test_unmeasured_metric_never_becomes_zero_or_an_estimate(self) -> None:
        result = dimension(
            dimension_id="example",
            name="Example",
            maximum=10,
            evidence=[
                metric(
                    source="missing.json",
                    claim="missing evidence",
                    measured=False,
                    missing=("missing.json",),
                )
            ],
        )
        self.assertFalse(result["measured"])
        self.assertIsNone(result["score"])
        self.assertIsNone(result["calculation"])

    def test_journey_certifications_account_for_every_source_contract(self) -> None:
        result = journey_certifications(ROOT)
        source_count = 0
        for path in (ROOT / "src/gravity_insight/contracts/journeys").glob("*.json"):
            if '"artifact_kind": "journey"' in path.read_text(encoding="utf-8"):
                source_count += 1
        self.assertTrue(result["ok"])
        self.assertEqual(source_count, result["counts"]["source_total"])
        self.assertEqual(
            source_count,
            sum(result["counts"][name] for name in ("certified", "uncertified", "blocked")),
        )
        self.assertTrue(
            all(item["evidence"]["contract"].endswith(".json") for item in result["journeys"])
        )

    def test_census_status_reuses_the_closed_failure_classes(self) -> None:
        result = census_status(ROOT)
        self.assertEqual(
            [item.value for item in CensusFailureClass], result["failure_classes"]
        )
        self.assertTrue(result["baseline"]["complete"])
        self.assertFalse(result["current"]["measured"])
        self.assertIsNone(result["current"]["changed"])

    def test_runtime_health_and_documentation_gates_pass(self) -> None:
        health = runtime_health_report(ROOT)
        docs = documentation_report(ROOT)
        self.assertTrue(health["ok"], health["checks"])
        self.assertTrue(docs["ok"], docs["checks"])
        self.assertEqual(0, health["exit_code"])
        self.assertEqual(0, docs["exit_code"])

    def test_existing_documentation_gate_includes_supplemental_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            (root / "docs").mkdir()
            (root / "docs/index.md").write_text("# Index\n", encoding="utf-8")
            (root / "docs/orphan.md").write_text("# Orphan\n", encoding="utf-8")
            with patch(
                "gravity_insight.runtime_health.runtime_health_errors",
                return_value=[],
            ):
                errors = integrated_documentation_errors(root)
        self.assertIn(
            "docs check orphan_documents: docs/orphan.md",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
