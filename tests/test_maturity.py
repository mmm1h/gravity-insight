from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from gravity_insight.maturity import _quality_profile
from gravity_insight.maturity_dimensions_core import _operation_evidence
from gravity_insight.maturity_dimensions_ops import _quality_metrics
from scripts import generate_method_gap_report


ROOT = Path(__file__).resolve().parents[1]


class QualityProfileCollectionTests(unittest.TestCase):
    def test_compiler_report_is_diagnostic_stderr_only(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        report = {
            "schema_version": "gravity.skill-method-complete-report.v1",
            "summary": {},
            "skills": [],
        }
        with (
            mock.patch.object(
                generate_method_gap_report, "library_report", return_value=report
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            generate_method_gap_report.emit_compiler_report(
                ROOT / "tmp" / "method-report-stderr-test"
            )

        self.assertEqual("", stdout.getvalue())
        self.assertTrue(stderr.getvalue().startswith("METHOD_COMPLETE_REPORT={"))

    def test_stdout_contamination_is_reported_to_both_dimensions(self) -> None:
        completed = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout='METHOD_COMPLETE_REPORT={"summary": {}}\n{"operation_count": 1}\n',
            stderr="",
        )
        with mock.patch(
            "gravity_insight.maturity.subprocess.run", return_value=completed
        ):
            profile, failure = _quality_profile(ROOT)

        self.assertIsNone(profile)
        self.assertIn("stdout was not a JSON document", failure)
        self.assertIn("line 1, column 1", failure)
        for evidence in (
            _operation_evidence(None, profile_failure=failure),
            _quality_metrics(None, profile_failure=failure),
        ):
            self.assertIn(failure, evidence[0]["missing"])
            self.assertFalse(evidence[0]["measured"])

    def test_json_object_is_collected_without_a_failure(self) -> None:
        completed = subprocess.CompletedProcess(
            args=(), returncode=0, stdout='{"operation_count": 1}', stderr=""
        )
        with mock.patch(
            "gravity_insight.maturity.subprocess.run", return_value=completed
        ):
            profile, failure = _quality_profile(ROOT)

        self.assertEqual({"operation_count": 1}, profile)
        self.assertIsNone(failure)

    def test_nonzero_collection_exit_is_reported(self) -> None:
        completed = subprocess.CompletedProcess(
            args=(), returncode=7, stdout="", stderr="quality scan failed"
        )
        with mock.patch(
            "gravity_insight.maturity.subprocess.run", return_value=completed
        ):
            profile, failure = _quality_profile(ROOT)

        self.assertIsNone(profile)
        self.assertEqual(
            "isolated quality-profile process exited with code 7", failure
        )


if __name__ == "__main__":
    unittest.main()
