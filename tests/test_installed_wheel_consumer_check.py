from __future__ import annotations

import unittest

from scripts.check_installed_wheel_consumer import parse_unittest_summary


class InstalledWheelConsumerCheckTests(unittest.TestCase):
    def test_unittest_summary_preserves_counts_and_failure(self) -> None:
        passed = parse_unittest_summary("Ran 11 tests in 1.2s\n\nOK (skipped=2)\n")
        failed = parse_unittest_summary("Ran 11 tests in 1.2s\n\nFAILED (failures=1)\n")
        self.assertEqual(
            {"tests_run": 11, "skipped": 2, "ok": True}, passed
        )
        self.assertEqual(
            {"tests_run": 11, "skipped": 0, "ok": False}, failed
        )


if __name__ == "__main__":
    unittest.main()
