"""Focused cases for the unittest shard coordinator (not suite-count inputs)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_unittest_shards import (
    DiscoveredTest,
    WorkerResult,
    _audit_outcome,
    _audit_partition,
    _choose_worker_count,
    _collect_worker,
    _drop_negative_control,
    _partition_tests,
)
from scripts.run_integrated_validation import gate_specs


class UnittestShardRunnerCases(unittest.TestCase):
    def test_integrated_gate_uses_the_sharded_unittest_command(self) -> None:
        python = Path("worktree/.venv/Scripts/python.exe")
        gate = next(
            item
            for item in gate_specs(python, Path("tmp/integrated"))
            if item.name == "unittest_collector"
        )

        self.assertEqual(
            (
                str(python),
                "scripts/run_unittest_shards.py",
            ),
            gate.command,
        )

    def test_worker_count_is_cpu_adaptive_and_capped(self) -> None:
        self.assertEqual(
            8, _choose_worker_count(cpu_count=20, max_workers=8, unit_count=100)
        )
        self.assertEqual(
            2, _choose_worker_count(cpu_count=2, max_workers=8, unit_count=100)
        )
        self.assertEqual(
            1, _choose_worker_count(cpu_count=None, max_workers=8, unit_count=100)
        )

    def test_partition_is_complete_unique_balanced_and_deterministic(self) -> None:
        discovered = tuple(
            DiscoveredTest(f"{module}.Case.test_{index}", ordinal)
            for ordinal, (module, index) in enumerate(
                [
                    ("test_a", 1),
                    ("test_a", 2),
                    ("test_a", 3),
                    ("test_b", 1),
                    ("test_b", 2),
                    ("test_c", 1),
                    ("test_d", 1),
                ]
            )
        )

        shards = _partition_tests(discovered, 3)

        self.assertEqual([], _audit_partition([test.test_id for test in discovered], shards))
        self.assertLessEqual(max(map(len, shards)) - min(map(len, shards)), 1)
        self.assertEqual(
            (
                ("test_a.Case.test_1", "test_b.Case.test_1", "test_d.Case.test_1"),
                ("test_a.Case.test_2", "test_b.Case.test_2"),
                ("test_a.Case.test_3", "test_c.Case.test_1"),
            ),
            shards,
        )

    def test_partition_audit_rejects_missing_and_duplicate_ids(self) -> None:
        serial_ids = ["test_a.Case.test_one", "test_b.Case.test_two"]

        missing = _audit_partition(serial_ids, ((serial_ids[0],),))
        duplicated = _audit_partition(
            serial_ids, ((serial_ids[0], serial_ids[0], serial_ids[1]),)
        )

        self.assertTrue(any("partition total mismatch" in error for error in missing))
        self.assertTrue(any("partition set mismatch" in error for error in missing))
        self.assertTrue(any("duplicate ids" in error for error in duplicated))

    def test_negative_control_removes_exactly_the_requested_id(self) -> None:
        shards = (("test_a.Case.test_one",), ("test_b.Case.test_two",))

        dropped = _drop_negative_control(shards, "test_b.Case.test_two")

        self.assertEqual((("test_a.Case.test_one",), ()), dropped)

    def test_outcome_audit_fails_closed_on_count_exit_summary_and_id_drift(self) -> None:
        serial_ids = ["test_a.Case.test_one", "test_b.Case.test_two"]
        with tempfile.TemporaryDirectory() as raw:
            log = Path(raw) / "shard.log"
            log.write_text("worker failed\n", encoding="utf-8")
            result = WorkerResult(
                index=1,
                assigned_ids=(serial_ids[0],),
                actual_ids=(),
                exit_code=1,
                reported_count=None,
                runtime_seconds=None,
                log_path=log,
                process_id=123,
                timed_out=False,
                current_test_ids=(),
                errors=("shard 1 exited nonzero", "shard 1 produced no summary"),
            )

            errors = _audit_outcome(serial_ids, (result,))

        self.assertTrue(any("exited nonzero" in error for error in errors))
        self.assertTrue(any("Ran N total conservation failed" in error for error in errors))
        self.assertTrue(any("actual ids differ" in error for error in errors))

    def test_timed_out_worker_reports_current_test_without_termination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "shard-01.log").write_text("test started\n", encoding="utf-8")
            (root / "shard-01.ids.jsonl").write_text(
                '\n'.join(
                    [
                        '{"event": "scheduled", "test_id": "test_a.Case.test_hangs"}',
                        '{"event": "started", "test_id": "test_a.Case.test_hangs"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = _collect_worker(
                index=1,
                assigned_ids=("test_a.Case.test_hangs",),
                exit_code=124,
                root=root,
                process_id=456,
                timed_out=True,
                timeout_seconds=10,
            )

        self.assertTrue(result.timed_out)
        self.assertEqual(("test_a.Case.test_hangs",), result.current_test_ids)
        self.assertTrue(any("without process termination" in error for error in result.errors))
        self.assertTrue(any("pid=456" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
