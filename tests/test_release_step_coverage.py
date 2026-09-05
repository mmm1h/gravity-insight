from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts import release_step_coverage as coverage
from scripts.build_release_gate_receipt import ReleaseGateError, build_release_gate_receipt
from tests import test_release_gate as fixtures

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


def snapshot(**overrides):
    args = dict(sha=fixtures.SHA, run_id="123", run_attempt="1", event="push", now=NOW)
    args.update(overrides)
    return coverage.capture_coverage(
        {step: {"outcome": "success"} for step in coverage.PREREQUISITES}, **args
    )


def resolve(document, **overrides):
    args = dict(sha=fixtures.SHA, run_id="123", run_attempt="1", now=NOW)
    args.update(overrides)
    return coverage.resolve_coverage(document, **args)


class ReleaseCoverageTests(unittest.TestCase):
    def test_all_prerequisites_measured_in_current_push(self):
        result = resolve(snapshot())
        self.assertTrue(result["release_grade"])
        self.assertEqual(list(coverage.PREREQUISITES), result["ran_steps"])
        self.assertEqual("measured", result["status"])

    def test_skipped_missing_failed_and_tolerated_failure_are_distinct(self):
        steps = {step: {"outcome": "success"} for step in coverage.PREREQUISITES}
        steps.pop("checkout")
        steps["download_ci"] = {"outcome": "skipped"}
        steps["wheel_surface"] = {"outcome": "failure", "conclusion": "success"}
        receipt = coverage.capture_coverage(steps, sha=fixtures.SHA, run_id="123",
                                            run_attempt="1", event="push", now=NOW)
        result = resolve(receipt)
        self.assertEqual(["checkout"], result["missing_steps"])
        self.assertEqual(["download_ci"], result["skipped_steps"])
        self.assertEqual("invalid", result["steps"]["wheel_surface"]["status"])
        self.assertFalse(result["release_grade"])

    def test_context_mismatch_and_freshness_fail_closed(self):
        for overrides, status in (({"sha": "b" * 40}, "not_applicable"),
                                  ({"run_id": "124"}, "not_applicable"),
                                  ({"run_attempt": "2"}, "not_applicable"),
                                  ({"now": NOW + timedelta(days=2)}, "expired"),
                                  ({"now": NOW - timedelta(seconds=1)}, "invalid")):
            with self.subTest(overrides=overrides):
                result = resolve(snapshot(), **overrides)
                self.assertEqual(status, result["steps"]["checkout"]["status"])
                self.assertFalse(result["release_grade"])

    def test_dispatch_cannot_authorize_even_with_every_step_successful(self):
        result = resolve(snapshot(event="workflow_dispatch"))
        self.assertFalse(result["release_grade"])
        self.assertEqual("not_applicable", result["steps"]["checkout"]["status"])

    def test_missing_or_malformed_observations_fail_closed(self):
        for value in (None, [], "success", {}, {"value": True}):
            with self.subTest(value=value):
                receipt = snapshot()
                receipt["observations"]["checkout"] = value
                self.assertFalse(resolve(receipt)["release_grade"])
        receipt = snapshot()
        del receipt["observations"]["checkout"]
        self.assertEqual(["checkout"], resolve(receipt)["missing_steps"])

    def test_empty_or_unknown_outcomes_and_unknown_steps_fail_closed(self):
        for raw in ({}, {"conclusion": "success"}, {"outcome": "unknown"}, {"outcome": "cancelled"}):
            with self.subTest(raw=raw):
                receipt = coverage.capture_coverage({"checkout": raw}, sha=fixtures.SHA,
                           run_id="123", run_attempt="1", event="push", now=NOW)
                self.assertEqual("invalid", resolve(receipt)["steps"]["checkout"]["status"])
        receipt = snapshot()
        receipt["observations"]["surprise"] = receipt["observations"]["checkout"]
        self.assertFalse(resolve(receipt)["release_grade"])

    def test_claimed_green_summary_or_reduced_denominator_is_not_trusted(self):
        receipt = snapshot()
        receipt["expected_steps"] = []
        receipt["coverage"] = {"status": "measured", "release_grade": True}
        self.assertFalse(resolve(receipt)["release_grade"])
        receipt = snapshot()
        receipt["observations"]["checkout"]["value"] = {"outcome": "skipped", "present": True}
        self.assertFalse(resolve(receipt)["release_grade"])

    def test_nine_skipped_steps_rejected_before_missing_release_inputs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            steps = {step: {"outcome": "success" if i < 5 else "skipped"}
                     for i, step in enumerate(coverage.PREREQUISITES)}
            receipt = coverage.capture_coverage(steps, sha=fixtures.SHA, run_id="123",
                                                run_attempt="1", event="push")
            path = fixtures._write(root / "coverage.json", receipt)
            args = {name: root / "absent" for name in (
                "dist_dir", "sbom_dir", "main_receipt", "ci_receipt",
                "integrated_validation_receipt", "secret_scan_receipt",
                "dependency_audit_receipt", "surface_receipt", "consumer_receipt", "changelog_receipt")}
            with self.assertRaises(ReleaseGateError) as caught:
                build_release_gate_receipt(expected_sha=fixtures.SHA, release_tag=fixtures.TAG,
                    coverage_receipt=path, run_id="123", run_attempt="1", **args)
            for step in coverage.PREREQUISITES[5:]:
                self.assertIn(f"{step}=not_measured(skipped)", str(caught.exception))

    def test_cli_failure_removes_stale_passing_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            args = fixtures.AggregateReleaseGateTests()._fixture(Path(raw))
            output = fixtures._write(Path(raw) / "release-gate.json", {"status": "passed"})
            args["coverage_receipt"].unlink()
            command = [sys.executable, "scripts/build_release_gate_receipt.py",
                       "--expected-sha", fixtures.SHA, "--release-tag", fixtures.TAG,
                       "--output", str(output)]
            for key, value in args.items():
                command.extend(["--" + key.replace("_", "-"), str(value)])
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertIn("cannot read release coverage", result.stderr)
            self.assertFalse(output.exists())

    def test_final_checkpoint_reports_aggregate_failure_and_transport_exclusion(self):
        expected, excluded = coverage.inventory("final")
        steps = {step: {"outcome": "success"} for step in expected}
        steps["aggregate"] = {"outcome": "failure"}
        receipt = coverage.capture_coverage(steps, sha=fixtures.SHA, run_id="123",
                    run_attempt="1", event="push", phase="final", now=NOW)
        self.assertEqual("invalid", receipt["coverage"]["status"])
        self.assertEqual(["coverage_final", "upload_evidence"], list(excluded))

    def test_bad_collector_input_writes_invalid_diagnostic(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {"RELEASE_STEPS_JSON": "[]"}):
            path = Path(raw) / "coverage.json"
            coverage.main(["--output", str(path)])
            self.assertFalse(json.loads(path.read_text())["release_grade"])

    def test_workflow_exact_inventory_and_always_on_enforcement(self):
        workflow = yaml.safe_load((ROOT / coverage.WORKFLOW).read_text(encoding="utf-8"))
        steps = workflow["jobs"][coverage.JOB]["steps"]
        ids = [step.get("id") for step in steps]
        self.assertEqual(list(coverage.PREREQUISITES + coverage.TAIL), ids)
        by_id = {step["id"]: step for step in steps}
        for step in ("coverage_pre", "aggregate", "coverage_final", "upload_evidence"):
            self.assertEqual("always()", by_id[step]["if"])
        for step in ("coverage_pre", "coverage_final"):
            self.assertEqual("${{ toJSON(steps) }}", by_id[step]["env"]["RELEASE_STEPS_JSON"])
        self.assertIn("--coverage-receipt release-evidence/coverage-prepublish.json", by_id["aggregate"]["run"])
        self.assertIn("--run-attempt", by_id["aggregate"]["run"])
        # Exercise the actual YAML dispatch shape, not a guessed gate count.
        outcomes = {step["id"]: {"outcome": "skipped" if step.get("if") == "github.event_name == 'push'" else "success"}
                    for step in steps[:len(coverage.PREREQUISITES)]}
        receipt = coverage.capture_coverage(outcomes, sha=fixtures.SHA, run_id="123",
                    run_attempt="1", event="workflow_dispatch", now=NOW)
        self.assertEqual(list(coverage.PREREQUISITES[7:]), receipt["coverage"]["skipped_steps"])
        self.assertFalse(resolve(receipt)["release_grade"])
