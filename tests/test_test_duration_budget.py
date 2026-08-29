from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
import unittest

import pytest

from scripts.check_test_duration_budget import (
    CALIBRATED_CI_ENVELOPE_SECONDS,
    CI_JOB_TIMEOUT_SECONDS,
    DurationRecorder,
    MAX_SINGLE_TEST_JOB_SHARE,
    PYTEST_ARGUMENTS,
    TEST_DURATION_LIMIT_SECONDS,
    DurationMeasurement,
    duration_budget_errors,
    run_gate,
)


class TestDurationBudgetTests(unittest.TestCase):
    def test_limit_is_four_minutes_and_covers_the_calibrated_ci_envelope(self) -> None:
        self.assertEqual(
            CI_JOB_TIMEOUT_SECONDS * MAX_SINGLE_TEST_JOB_SHARE,
            TEST_DURATION_LIMIT_SECONDS,
        )
        self.assertEqual(240.0, TEST_DURATION_LIMIT_SECONDS)
        self.assertAlmostEqual(0.20, MAX_SINGLE_TEST_JOB_SHARE)
        self.assertLess(CALIBRATED_CI_ENVELOPE_SECONDS, TEST_DURATION_LIMIT_SECONDS)
        self.assertEqual(("-q", "-n", "auto", "--dist", "loadscope"), PYTEST_ARGUMENTS)

    def test_recorder_sums_phases_and_orders_slowest_first(self) -> None:
        recorder = DurationRecorder()
        for nodeid, phase, duration in (
            ("tests/test_fast.py::test_fast", "setup", 0.1),
            ("tests/test_fast.py::test_fast", "call", 0.2),
            ("tests/test_fast.py::test_fast", "teardown", 0.1),
            ("tests/test_slow.py::test_slow", "call", 0.8),
        ):
            recorder.pytest_runtest_logreport(
                SimpleNamespace(nodeid=nodeid, when=phase, duration=duration)
            )
        self.assertEqual(
            (
                DurationMeasurement("tests/test_slow.py::test_slow", 0.8),
                DurationMeasurement("tests/test_fast.py::test_fast", 0.4),
            ),
            recorder.durations(),
        )

    def test_threshold_is_inclusive_and_failure_names_the_test(self) -> None:
        self.assertEqual(
            (),
            duration_budget_errors(
                (DurationMeasurement("tests/test_at_limit.py::test_at_limit", 240.0),)
            ),
        )
        errors = duration_budget_errors(
            (DurationMeasurement("tests/test_slow.py::test_slow", 240.001),)
        )
        self.assertEqual(1, len(errors))
        self.assertIn("tests/test_slow.py::test_slow", errors[0])
        self.assertIn("duration=240.001s limit=240.000s", errors[0])

    def test_gate_uses_parallel_collector_and_fails_closed_on_pytest_error(self) -> None:
        captured: list[str] = []

        def failed_runner(arguments: list[str], *, plugins: list[object]) -> int:
            captured.extend(arguments)
            recorder = plugins[0]
            recorder.pytest_runtest_logreport(
                SimpleNamespace(
                    nodeid="tests/test_broken.py::test_broken",
                    when="call",
                    duration=0.1,
                )
            )
            return int(pytest.ExitCode.TESTS_FAILED)

        output = StringIO()
        self.assertEqual(
            1,
            run_gate(("tests/test_broken.py",), pytest_runner=failed_runner, stream=output),
        )
        self.assertEqual([*PYTEST_ARGUMENTS, "tests/test_broken.py"], captured)
        self.assertIn("pytest exit_code=1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
