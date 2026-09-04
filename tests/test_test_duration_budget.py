from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest

import pytest

from scripts.check_test_duration_budget import (
    CALIBRATED_CI_ENVELOPE_SECONDS,
    CI_JOB_TIMEOUT_SECONDS,
    CollectionRecorder,
    DurationRecorder,
    FULL_GATE_NODEIDS,
    LOCAL_FOCUSED_WALL_LIMIT_SECONDS,
    LOCAL_TO_CI_DURATION_RATIO,
    MAX_FULL_GATE_TESTS,
    MAX_LOCAL_FOCUSED_WALL_SECONDS,
    MAX_SLOW_TEST_SECONDS,
    MAX_SINGLE_TEST_JOB_SHARE,
    PYTEST_ARGUMENTS,
    PYTEST_COLLECTION_ARGUMENTS,
    SHARD_RECEIPT_SCHEMA,
    SLOW_TEST_LIMIT_SECONDS,
    TEST_DURATION_LIMIT_SECONDS,
    DurationMeasurement,
    active_duration_coordinate,
    audit_shard_receipts,
    declared_full_gate_nodeids,
    duration_budget_errors,
    local_equivalent_seconds,
    partition_nodeids,
    run_gate,
)


class TestDurationBudgetTests(unittest.TestCase):
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
        self.assertLessEqual(
            LOCAL_FOCUSED_WALL_LIMIT_SECONDS, MAX_LOCAL_FOCUSED_WALL_SECONDS
        )
        self.assertLessEqual(SLOW_TEST_LIMIT_SECONDS, MAX_SLOW_TEST_SECONDS)
        self.assertLessEqual(len(FULL_GATE_NODEIDS), MAX_FULL_GATE_TESTS)
        self.assertEqual(
            CI_JOB_TIMEOUT_SECONDS * MAX_SINGLE_TEST_JOB_SHARE,
            TEST_DURATION_LIMIT_SECONDS,
        )
        self.assertEqual(240.0, TEST_DURATION_LIMIT_SECONDS)
        self.assertAlmostEqual(0.20, MAX_SINGLE_TEST_JOB_SHARE)
        self.assertLess(CALIBRATED_CI_ENVELOPE_SECONDS, TEST_DURATION_LIMIT_SECONDS)
        self.assertEqual(
            (),
            duration_budget_errors(
                (
                    DurationMeasurement(
                        "tests/test_at_slow_limit.py::test_at_slow_limit",
                        SLOW_TEST_LIMIT_SECONDS,
                    ),
                    DurationMeasurement(
                        "tests/test_marked_slow.py::test_marked_slow", 40.0, True
                    ),
                )
            ),
        )
        unmarked = duration_budget_errors(
            (
                DurationMeasurement(
                    "tests/test_slow.py::test_slow",
                    SLOW_TEST_LIMIT_SECONDS + 0.001,
                ),
            )
        )
        self.assertIn("without @pytest.mark.full_gate", unmarked[0])
        errors = duration_budget_errors(
            (DurationMeasurement("tests/test_slow.py::test_slow", 240.001),)
        )
        self.assertEqual(1, len(errors))
        self.assertIn("tests/test_slow.py::test_slow", errors[0])
        self.assertIn("duration=240.001s limit=240.000s", errors[0])

    def test_gate_uses_parallel_collector_and_fails_closed_on_pytest_error(self) -> None:
        self.assertEqual(
            ("-q", "-o", "addopts=", "-n", "auto", "--dist", "loadfile"),
            PYTEST_ARGUMENTS,
        )
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

    def test_ci_duration_is_normalized_before_applying_the_local_slow_policy(self) -> None:
        ci_at_local_limit = 40.0 * LOCAL_TO_CI_DURATION_RATIO
        self.assertAlmostEqual(
            40.0,
            local_equivalent_seconds(
                ci_at_local_limit, duration_coordinate="ci"
            ),
        )
        self.assertEqual(
            (),
            duration_budget_errors(
                (DurationMeasurement("tests/test_scan.py::test_scan", 55.471),),
                duration_coordinate="ci",
            ),
        )
        errors = duration_budget_errors(
            (
                DurationMeasurement(
                    "tests/test_scan.py::test_scan",
                    ci_at_local_limit + 0.001,
                ),
            ),
            duration_coordinate="ci",
        )
        self.assertIn("local_equivalent=40.001s", errors[0])
        self.assertIn("local_slow_test_limit=40.000s", errors[0])
        self.assertEqual("local", active_duration_coordinate({}))
        self.assertEqual("ci", active_duration_coordinate({"GITHUB_ACTIONS": "true"}))

    def test_collection_recorder_and_partition_preserve_exact_nodeids(self) -> None:
        recorder = CollectionRecorder()
        recorder.pytest_collection_finish(
            SimpleNamespace(
                items=[
                    SimpleNamespace(nodeid="tests/test_b.py::Case::test_2"),
                    SimpleNamespace(nodeid="tests/test_a.py::Case::test_1"),
                    SimpleNamespace(nodeid="tests/test_c.py::test_3"),
                    SimpleNamespace(nodeid="tests/test_a.py::Case::test_4"),
                ]
            )
        )

        shards = partition_nodeids(recorder.nodeids, 2)

        self.assertEqual(
            (
                (
                    "tests/test_a.py::Case::test_1",
                    "tests/test_b.py::Case::test_2",
                ),
                (
                    "tests/test_a.py::Case::test_4",
                    "tests/test_c.py::test_3",
                ),
            ),
            shards,
        )
        self.assertEqual(
            sorted(recorder.nodeids), sorted(nodeid for shard in shards for nodeid in shard)
        )

    def test_shard_receipt_audit_fails_closed_on_missing_shard(self) -> None:
        collected = [
            "tests/test_a.py::Case::test_1",
            "tests/test_b.py::Case::test_2",
        ]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            receipt = {
                "schema_version": SHARD_RECEIPT_SCHEMA,
                "duration_coordinate": "ci",
                "local_to_ci_duration_ratio": LOCAL_TO_CI_DURATION_RATIO,
                "local_slow_test_limit_seconds": SLOW_TEST_LIMIT_SECONDS,
                "status": "passed",
                "shard_index": 1,
                "shard_count": 2,
                "collected_nodeids": collected,
                "selected_nodeids": [collected[0]],
                "actual_nodeids": [collected[0]],
                "errors": [],
            }
            (root / "pytest-shard-1.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            summary, errors = audit_shard_receipts(
                root, 2, expected_full_gate_nodeids=()
            )

        self.assertEqual("failed", summary["status"])
        self.assertTrue(any("missing=[2]" in error for error in errors))

    def test_shard_receipt_audit_proves_collection_selection_and_execution(self) -> None:
        collected = [
            "tests/test_a.py::Case::test_1",
            "tests/test_b.py::Case::test_2",
            "tests/test_c.py::test_3",
            "tests/test_d.py::Case::test_4",
        ]
        partitions = partition_nodeids(collected, 2)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index, selected in enumerate(partitions, 1):
                receipt = {
                    "schema_version": SHARD_RECEIPT_SCHEMA,
                    "duration_coordinate": "ci",
                    "local_to_ci_duration_ratio": LOCAL_TO_CI_DURATION_RATIO,
                    "local_slow_test_limit_seconds": SLOW_TEST_LIMIT_SECONDS,
                    "status": "passed",
                    "shard_index": index,
                    "shard_count": 2,
                    "collected_nodeids": collected,
                    "selected_nodeids": list(selected),
                    "actual_nodeids": list(selected),
                    "full_gate_nodeids": [],
                    "errors": [],
                }
                (root / f"pytest-shard-{index}.json").write_text(
                    json.dumps(receipt), encoding="utf-8"
                )

            summary, errors = audit_shard_receipts(
                root, 2, expected_full_gate_nodeids=()
            )

        self.assertEqual((), errors)
        self.assertEqual("passed", summary["status"])
        self.assertEqual(4, summary["collection_count"])
        self.assertEqual(4, summary["selected_total"])
        self.assertEqual(4, summary["actual_total"])

    def test_ci_full_suite_does_not_inherit_focused_filter(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(set(FULL_GATE_NODEIDS), set(declared_full_gate_nodeids(root)))
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertTrue(
            any("full_gate:" in marker for marker in config["tool"]["pytest"]["ini_options"]["markers"])
        )
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("not full_gate", workflow)
        self.assertIn("python scripts/check_test_duration_budget.py", workflow)
        self.assertIn("--audit-receipts tmp/pytest-shards", workflow)
        self.assertGreaterEqual(
            workflow.count(
                'run: python -m pytest -q -o addopts="" -n auto --dist loadfile'
            ),
            2,
        )
        self.assertIn("addopts=", PYTEST_ARGUMENTS)
        self.assertIn("addopts=", PYTEST_COLLECTION_ARGUMENTS)
        self.assertNotIn("-m", PYTEST_ARGUMENTS)
        self.assertNotIn("-m", PYTEST_COLLECTION_ARGUMENTS)


if __name__ == "__main__":
    unittest.main()
