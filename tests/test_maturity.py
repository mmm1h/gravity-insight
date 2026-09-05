from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from gravity_insight.maturity import _profile_measurement, _quality_profile, _total
from gravity_insight.evidence_common import dimension
from gravity_insight.maturity_dimensions_core import _operation_evidence
from gravity_insight.maturity_dimensions_ops import _quality_metrics
from scripts import generate_method_gap_report


ROOT = Path(__file__).resolve().parents[1]


class QualityProfileCollectionTests(unittest.TestCase):
    def test_child_overrides_host_gbk_on_both_streams(self) -> None:
        script = (
            "import json,sys; "
            "print(chr(0x4e2d), file=sys.stderr); "
            "print(json.dumps({'label': chr(0x4e2d)}, ensure_ascii=False))"
        )
        with (
            mock.patch.dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="gbk"),
            mock.patch("gravity_insight.maturity._QUALITY_PROFILE_SCRIPT", script),
        ):
            profile, failure = _quality_profile(ROOT)
        self.assertEqual({"label": chr(0x4e2d)}, profile)
        self.assertIsNone(failure)

    def test_missing_stdout_and_process_errors_are_not_measured(self) -> None:
        outcomes = [
            subprocess.CompletedProcess((), 0, None, ""),
            subprocess.CompletedProcess((), 0, "", ""),
            subprocess.CompletedProcess((), 9, "", ""),
            subprocess.TimeoutExpired("python", 120),
            OSError("cannot launch"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid"),
        ]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                settings = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with mock.patch("gravity_insight.maturity.subprocess.run", **settings):
                    profile, failure = _quality_profile(ROOT)
                receipt = _profile_measurement(ROOT, {"commit": "a" * 40, "dirty": False}, profile, failure)
                self.assertEqual("not_measured", receipt["resolution"]["status"])
                self.assertEqual("MEASUREMENT_NOT_CAPTURED", receipt["resolution"]["reason_code"])
                self.assertIsNone(receipt["measurement"])
                self.assertTrue(receipt["collection_failure"])
                for evidence in (_operation_evidence(profile, profile_failure=failure), _quality_metrics(profile, profile_failure=failure)):
                    result = dimension(dimension_id="quality", name="quality", maximum=10, evidence=evidence)
                    self.assertEqual("not_measured", result["status"])
                    self.assertIsNone(result["score"])
                    self.assertIsNone(_total([result])["score"])

    def test_measured_zero_is_distinct_from_collection_failure(self) -> None:
        profile = {"operation_count": 1, "compiler_check": "FAIL", "provenance_covered": 0}
        receipt = _profile_measurement(ROOT, {"commit": "a" * 40, "dirty": True}, profile, None)
        self.assertEqual("gravity.context-bound-measurement.v1", receipt["measurement"]["schema_version"])
        self.assertEqual("measured", receipt["resolution"]["status"])
        result = dimension(dimension_id="quality", name="quality", maximum=10, evidence=_operation_evidence(profile))
        self.assertEqual("measured", result["status"])
        self.assertEqual(0, result["score"])

    def test_compiler_report_is_diagnostic_stderr_only(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        report = {
            "schema_version": "gravity.skill-method-complete-report.v1",
            "source": {"manifest_count": 0, "sha256": "0" * 64},
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
