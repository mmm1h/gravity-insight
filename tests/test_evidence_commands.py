from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gravity_insight.census.diffing import CensusFailureClass
from gravity_insight.census.status import CURRENT_MAX_AGE, census_status
from gravity_insight.cli import build_parser
from gravity_insight.documentation_status import (
    documentation_report,
    integrated_documentation_errors,
)
from gravity_insight.evidence_common import (
    context_bound_measurement,
    dimension,
    metric,
    resolve_context_bound_measurement,
)
from gravity_insight.journey_certification import journey_certifications
from gravity_insight.maturity_dimensions_core import census_evidence
from gravity_insight.maturity import _maturity_measurement
from gravity_insight.maturity_dimensions_ops import ci_evidence
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
    def _current_census_evidence(
        self,
        directory: Path,
        *,
        observed_at: datetime,
        old_bundle_id: str,
        changed: bool = False,
    ) -> list[Path]:
        bundle_id = "1" * 64
        summary = {"complete": True, "request_attempts": 2, "request_limit": 10}
        step = {
            "schema_version": "gravity-census.step-output.v1",
            "operation": "fetch_public_static_graph",
            "status": "complete",
            "complete": True,
            "drift_conclusion_available": True,
            "failure_class": None,
            "observed_at": observed_at.isoformat(),
            "bundle_id": bundle_id,
            "request_budget": {"used": 2, "limit": 10, "remaining": 8},
            "summary": summary,
            "failure": None,
        }
        diff = {
            "schema_version": 1,
            "kind": "route_diff",
            "status": "complete",
            "drift_conclusion_available": True,
            "failure_class": None,
            "old_bundle_id": old_bundle_id,
            "new_bundle_id": bundle_id,
            "old_bundle_complete": True,
            "new_bundle_complete": True,
            "summary": {
                "added": int(changed),
                "removed": 0,
                "method_changed": 0,
                "path_changed": 0,
            },
        }
        snapshot = {
            "schema_version": 1,
            "fetched_at": observed_at.isoformat(),
            "bundle_id": bundle_id,
            "summary": summary,
        }
        paths = [
            directory / "census-step-output.json",
            directory / "route-diff.json",
            directory / "current-snapshot.json",
        ]
        for path, value in zip(paths, (step, diff, snapshot)):
            path.write_text(json.dumps(value), encoding="utf-8")
        return paths

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

    def test_metric_rejects_a_resolution_that_conflicts_with_measured(self) -> None:
        measurement = context_bound_measurement(
            {"changed": False},
            coordinate={"kind": "census_drift_observation", "clock": "UTC"},
            scope={"kind": "census_evidence_chain"},
            captured_at="2026-09-05T00:00:00+00:00",
            binds_to={"baseline_bundle_id": "a" * 64},
        )
        expired = resolve_context_bound_measurement(
            measurement,
            expected_coordinate=measurement["coordinate"],
            expected_scope=measurement["scope"],
            expected_bindings=measurement["binds_to"],
            now=datetime(2026, 9, 5, 0, 0, 2, tzinfo=timezone.utc),
            max_age=timedelta(seconds=1),
        )

        with self.assertRaisesRegex(ValueError, "measured flag conflicts"):
            metric(
                source="Census receipt",
                claim="Census evidence is current",
                measured=True,
                passed=1,
                total=1,
                measurement_resolution=expired,
            )

    def test_resolver_rejects_a_context_field_the_consumer_did_not_declare(self) -> None:
        measurement = context_bound_measurement(
            {"changed": False},
            coordinate={"kind": "census_drift_observation", "clock": "UTC"},
            scope={"kind": "census_evidence_chain", "directory": "tmp/census-current"},
            captured_at="2026-09-05T00:00:00+00:00",
            binds_to={
                "baseline_bundle_id": "a" * 64,
                "observed_bundle_id": "b" * 64,
            },
        )
        resolution = resolve_context_bound_measurement(
            measurement,
            expected_coordinate=measurement["coordinate"],
            expected_scope={"kind": "census_evidence_chain"},
            expected_bindings=measurement["binds_to"],
        )

        self.assertEqual("not_applicable", resolution["status"])
        self.assertEqual(
            {
                "field": "scope.directory",
                "expected": None,
                "observed": "tmp/census-current",
            },
            resolution["mismatches"][0],
        )
        self.assertIsNone(resolution["value"])

    def test_resolver_rejects_a_measurement_without_a_value_field(self) -> None:
        measurement = context_bound_measurement(
            {"gate_count": 2},
            coordinate={"kind": "integrated_validation", "commit_sha": "a" * 40},
            scope={"kind": "git_worktree", "root": ROOT.as_posix()},
            captured_at="2026-09-05T00:00:00+00:00",
            binds_to={"commit_sha": "a" * 40},
        )
        measurement.pop("value")

        resolution = resolve_context_bound_measurement(
            measurement,
            expected_coordinate={"kind": "integrated_validation", "commit_sha": "a" * 40},
            expected_scope={"kind": "git_worktree", "root": ROOT.as_posix()},
            expected_bindings={"commit_sha": "a" * 40},
        )

        self.assertEqual("invalid", resolution["status"])
        self.assertEqual("MEASUREMENT_CONTEXT_INVALID", resolution["reason_code"])

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
        result = census_status(ROOT, evidence_paths=())
        self.assertEqual(
            [item.value for item in CensusFailureClass], result["failure_classes"]
        )
        self.assertTrue(result["baseline"]["complete"])
        self.assertFalse(result["current"]["measured"])
        self.assertEqual("not_measured", result["current"]["status"])
        self.assertEqual(
            "MEASUREMENT_NOT_CAPTURED", result["current"]["reason_code"]
        )
        self.assertIsNone(result["current"]["changed"])

    def test_census_observation_is_current_through_the_26_hour_boundary(self) -> None:
        observed_at = datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
        baseline = census_status(ROOT, evidence_paths=())["baseline"]["bundle_id"]
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._current_census_evidence(
                Path(temporary), observed_at=observed_at, old_bundle_id=baseline
            )
            result = census_status(
                ROOT, paths, now=observed_at + CURRENT_MAX_AGE
            )

        self.assertTrue(result["current"]["measured"])
        self.assertEqual("current", result["current"]["freshness"]["status"])
        self.assertEqual(93600, result["current"]["freshness"]["max_age_seconds"])
        scored = dimension(
            dimension_id="upstream_drift_reliability_operations",
            name="Census",
            maximum=10,
            evidence=census_evidence(result),
        )
        self.assertEqual((True, 10.0), (scored["measured"], scored["score"]))

    def test_expired_census_observation_stays_distinct_from_never_measured(self) -> None:
        observed_at = datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
        baseline = census_status(ROOT, evidence_paths=())["baseline"]["bundle_id"]
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._current_census_evidence(
                Path(temporary), observed_at=observed_at, old_bundle_id=baseline
            )
            result = census_status(
                ROOT, paths, now=observed_at + CURRENT_MAX_AGE + timedelta(seconds=1)
            )

        self.assertFalse(result["current"]["measured"])
        self.assertEqual("expired", result["current"]["status"])
        self.assertEqual("MEASUREMENT_EXPIRED", result["current"]["reason_code"])
        self.assertEqual("expired", result["current"]["freshness"]["status"])
        self.assertEqual("expired", result["current"]["measurement"]["status"])
        self.assertEqual(93601.0, result["current"]["freshness"]["age_seconds"])
        self.assertIsNone(result["current"]["changed"])
        self.assertIn("no older than 26 hours", result["current"]["missing"][0])
        never = census_status(ROOT, evidence_paths=())
        self.assertEqual("not_measured", never["current"]["status"])
        self.assertNotEqual(result["current"]["status"], never["current"]["status"])

        scored = dimension(
            dimension_id="upstream_drift_reliability_operations",
            name="Census",
            maximum=10,
            evidence=census_evidence(result),
        )
        self.assertEqual("expired", scored["status"])

    def test_census_observation_rejects_future_time_and_baseline_mismatch(self) -> None:
        now = datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
        baseline = census_status(ROOT, evidence_paths=())["baseline"]["bundle_id"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            future_paths = self._current_census_evidence(
                directory,
                observed_at=now + timedelta(minutes=5, seconds=1),
                old_bundle_id=baseline,
            )
            future = census_status(ROOT, future_paths, now=now)
            mismatch_paths = self._current_census_evidence(
                directory,
                observed_at=now,
                old_bundle_id="f" * 64,
            )
            mismatch = census_status(ROOT, mismatch_paths, now=now)
            receipt_mismatch_paths = self._current_census_evidence(
                directory, observed_at=now, old_bundle_id=baseline
            )
            snapshot = json.loads(
                receipt_mismatch_paths[2].read_text(encoding="utf-8")
            )
            snapshot["bundle_id"] = "2" * 64
            receipt_mismatch_paths[2].write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
            receipt_mismatch = census_status(
                ROOT, receipt_mismatch_paths, now=now
            )

        self.assertFalse(future["current"]["measured"])
        self.assertEqual("invalid", future["current"]["status"])
        self.assertEqual(
            "MEASUREMENT_CAPTURED_IN_FUTURE", future["current"]["reason_code"]
        )
        self.assertEqual("future", future["current"]["freshness"]["status"])
        self.assertFalse(mismatch["current"]["measured"])
        self.assertEqual("not_applicable", mismatch["current"]["status"])
        self.assertEqual(
            "MEASUREMENT_CONTEXT_MISMATCH", mismatch["current"]["reason_code"]
        )
        self.assertEqual(
            "binds_to.baseline_bundle_id",
            mismatch["current"]["measurement"]["mismatches"][0]["field"],
        )
        self.assertIn("reviewed baseline", mismatch["current"]["missing"][0])
        self.assertFalse(receipt_mismatch["current"]["measured"])
        self.assertIn("same current bundle", receipt_mismatch["current"]["missing"][0])

    def test_malformed_census_evidence_is_invalid_instead_of_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fetch-step.json"
            path.write_text("{not-json", encoding="utf-8")
            result = census_status(ROOT, (path,))

        self.assertFalse(result["current"]["measured"])
        self.assertEqual("invalid", result["current"]["status"])
        self.assertEqual(
            "MEASUREMENT_CONTEXT_INVALID", result["current"]["reason_code"]
        )
        self.assertIn("valid JSON", result["current"]["missing"][0])

    def test_legacy_step_receipt_requires_a_same_directory_snapshot_binding(self) -> None:
        observed_at = datetime(2026, 9, 3, 1, tzinfo=timezone.utc)
        baseline = census_status(ROOT, evidence_paths=())["baseline"]["bundle_id"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = self._current_census_evidence(
                directory, observed_at=observed_at, old_bundle_id=baseline
            )
            step = json.loads(paths[0].read_text(encoding="utf-8"))
            step.pop("observed_at")
            step.pop("bundle_id")
            paths[0].write_text(json.dumps(step), encoding="utf-8")
            result = census_status(
                ROOT, paths, now=observed_at + timedelta(hours=1)
            )

        self.assertTrue(result["current"]["measured"])
        self.assertIn("current-snapshot.json", result["current"]["evidence"][2])

    def test_integrated_validation_head_mismatch_is_not_missing(self) -> None:
        old_head = "a" * 40
        current_head = "b" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = (
                root / "tmp/integrated-validation" / old_head / "receipt.json"
            )
            receipt_path.parent.mkdir(parents=True)
            receipt = {
                "schema_version": "gravity.integrated-validation-receipt.v2",
                "commit_sha": old_head,
                "finished_at": "2026-09-05T01:02:03+00:00",
                "trial": False,
                "complete_gate_set": True,
                "preconditions_after": {"clean": True},
                "gates": [{"name": "pytest_collector", "exit_code": 0}],
                "integrated_validation_green": True,
                "overall": "passed",
            }
            receipt["measurement"] = context_bound_measurement(
                {
                    "gate_count": 1,
                    "integrated_validation_green": True,
                    "overall": "passed",
                },
                coordinate={
                    "kind": "integrated_validation",
                    "commit_sha": old_head,
                    "worktree_state": "clean",
                    "complete_gate_set": True,
                    "trial": False,
                },
                scope={"kind": "git_worktree", "root": root.resolve().as_posix()},
                captured_at=receipt["finished_at"],
                binds_to={
                    "commit_sha": old_head,
                    "gate_names": ["pytest_collector"],
                },
            )
            receipt_path.write_text(
                json.dumps(receipt),
                encoding="utf-8",
            )
            evidence = ci_evidence(
                root,
                {"commit": current_head, "branch": "main", "dirty": False},
            )[0]

        self.assertFalse(evidence["measured"])
        self.assertEqual("not_applicable", evidence["measurement"]["status"])
        self.assertEqual(
            "MEASUREMENT_CONTEXT_MISMATCH",
            evidence["measurement"]["reason_code"],
        )
        self.assertEqual(
            {
                "field": "coordinate.commit_sha",
                "expected": current_head,
                "observed": old_head,
            },
            evidence["measurement"]["mismatches"][0],
        )
        self.assertEqual(
            f"tmp/integrated-validation/{old_head}/receipt.json", evidence["source"]
        )

    def test_integrated_validation_without_embedded_context_is_invalid(self) -> None:
        head = "1" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "tmp/integrated-validation" / head / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": "gravity.integrated-validation-receipt.v2",
                        "commit_sha": head,
                        "finished_at": "2026-09-05T01:02:03+00:00",
                        "trial": False,
                        "complete_gate_set": True,
                        "preconditions_after": {"clean": True},
                        "gates": [{"name": "pytest_collector", "exit_code": 0}],
                        "integrated_validation_green": True,
                        "overall": "passed",
                    }
                ),
                encoding="utf-8",
            )
            evidence = ci_evidence(
                root, {"commit": head, "branch": "main", "dirty": False}
            )[0]

        self.assertFalse(evidence["measured"])
        self.assertEqual("invalid", evidence["measurement"]["status"])
        self.assertEqual(
            "MEASUREMENT_CONTEXT_INVALID", evidence["measurement"]["reason_code"]
        )

    def test_integrated_validation_from_another_worktree_is_not_applicable(self) -> None:
        head = "2" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "tmp/integrated-validation" / head / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt = {
                "schema_version": "gravity.integrated-validation-receipt.v2",
                "commit_sha": head,
                "finished_at": "2026-09-05T01:02:03+00:00",
                "trial": False,
                "complete_gate_set": True,
                "preconditions_after": {"clean": True},
                "gates": [{"name": "pytest_collector", "exit_code": 0}],
                "integrated_validation_green": True,
                "overall": "passed",
            }
            receipt["measurement"] = context_bound_measurement(
                {
                    "gate_count": 1,
                    "integrated_validation_green": True,
                    "overall": "passed",
                },
                coordinate={
                    "kind": "integrated_validation",
                    "commit_sha": head,
                    "worktree_state": "clean",
                    "complete_gate_set": True,
                    "trial": False,
                },
                scope={
                    "kind": "git_worktree",
                    "root": (root.parent / "other-worktree").as_posix(),
                },
                captured_at=receipt["finished_at"],
                binds_to={
                    "commit_sha": head,
                    "gate_names": ["pytest_collector"],
                },
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            evidence = ci_evidence(
                root, {"commit": head, "branch": "main", "dirty": False}
            )[0]

        self.assertFalse(evidence["measured"])
        self.assertEqual("not_applicable", evidence["measurement"]["status"])
        self.assertEqual(
            "scope.root", evidence["measurement"]["mismatches"][0]["field"]
        )

    def test_integrated_validation_rejects_disagreement_with_nested_context(self) -> None:
        head = "e" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "tmp/integrated-validation" / head / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt = {
                "schema_version": "gravity.integrated-validation-receipt.v2",
                "commit_sha": head,
                "finished_at": "2026-09-05T01:02:03+00:00",
                "trial": False,
                "complete_gate_set": True,
                "preconditions_after": {"clean": True},
                "gates": [{"name": "pytest_collector", "exit_code": 0}],
                "integrated_validation_green": True,
                "overall": "passed",
            }
            receipt["measurement"] = context_bound_measurement(
                {"gate_count": 1, "integrated_validation_green": True, "overall": "passed"},
                coordinate={
                    "kind": "integrated_validation",
                    "commit_sha": "f" * 40,
                    "worktree_state": "clean",
                    "complete_gate_set": True,
                    "trial": False,
                },
                scope={"kind": "git_worktree", "root": root.as_posix()},
                captured_at=receipt["finished_at"],
                binds_to={"commit_sha": head, "gate_names": ["pytest_collector"]},
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            evidence = ci_evidence(
                root, {"commit": head, "branch": "main", "dirty": False}
            )[0]

        self.assertFalse(evidence["measured"])
        self.assertEqual("invalid", evidence["measurement"]["status"])
        self.assertEqual(
            "MEASUREMENT_CONTEXT_INVALID", evidence["measurement"]["reason_code"]
        )

    def test_maturity_value_carries_its_worktree_scope(self) -> None:
        captured_at = datetime(2026, 9, 5, 1, tzinfo=timezone.utc)
        repository = {"commit": "c" * 40, "branch": "main", "dirty": False}
        first_root = ROOT
        second_root = ROOT.parent / "gi-wt-ctx-secondary"
        total = {"score": 90.0, "max": 100, "measured": True}
        first = _maturity_measurement(
            first_root,
            repository,
            status="measured",
            total=total,
            captured_at=captured_at,
        )
        second = _maturity_measurement(
            second_root,
            repository,
            status="measured",
            total=total,
            captured_at=captured_at,
        )

        self.assertEqual(first["value"], second["value"])
        self.assertNotEqual(first["scope"]["root"], second["scope"]["root"])
        resolution = resolve_context_bound_measurement(
            first,
            expected_coordinate=second["coordinate"],
            expected_scope=second["scope"],
            expected_bindings=second["binds_to"],
        )
        self.assertEqual("not_applicable", resolution["status"])
        self.assertEqual("scope.root", resolution["mismatches"][0]["field"])

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

    def test_supplemental_checks_accept_an_unresolved_root(self) -> None:
        # The checks relative_to() each discovered path against root, and
        # relative_to compares text. On CI the temp dir arrives as a Windows 8.3
        # short name (RUNNER~1) while the walk yields the long name, so every
        # comparison raised ValueError. A path routed through a subdirectory
        # reproduces the same mismatch on any platform without needing a short
        # name, which this developer's own home directory is too short to produce.
        with tempfile.TemporaryDirectory() as temporary:
            resolved = Path(temporary).resolve()
            (resolved / ".git").mkdir()
            (resolved / "docs").mkdir()
            (resolved / "docs/index.md").write_text("# Index\n", encoding="utf-8")
            (resolved / "docs/orphan.md").write_text("# Orphan\n", encoding="utf-8")
            (resolved / "sub").mkdir()
            unresolved = resolved / "sub" / ".."
            self.assertNotEqual(str(unresolved), str(resolved))
            with patch(
                "gravity_insight.runtime_health.runtime_health_errors",
                return_value=[],
            ):
                errors = integrated_documentation_errors(unresolved)
        self.assertIn(
            "docs check orphan_documents: docs/orphan.md",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
