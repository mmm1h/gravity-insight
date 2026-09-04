from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from scripts.refresh_validation_harnesses import ordered_steps, run_steps


class ValidationHarnessRefreshTests(unittest.TestCase):
    def test_write_and_check_orders_are_explicit(self) -> None:
        write = ordered_steps(sys.executable, check=False)
        check = ordered_steps(sys.executable, check=True)
        self.assertEqual("-m", write[0][1])
        self.assertEqual("tests.agent_migration_characterization", write[0][2])
        self.assertEqual("refresh", write[0][-1])
        self.assertEqual(
            "scripts/audit_agent_module_references.py", write[1][1]
        )
        self.assertEqual(("domain-boundary", "baseline", "--write"), write[1][2:])
        self.assertEqual("scripts/generate_repository_map.py", write[2][1])
        self.assertEqual(
            "scripts/generate_agent_module_reference_dispositions.py", write[3][1]
        )
        self.assertEqual("check", check[0][-1])
        self.assertEqual(("domain-boundary", "check"), check[1][2:])
        self.assertEqual("--check", check[2][-1])
        self.assertEqual("--check", check[3][-1])

    @patch("scripts.refresh_validation_harnesses.subprocess.run")
    def test_failure_stops_before_the_dependent_checkpoint(self, run) -> None:
        run.return_value.returncode = 1
        results = run_steps(ordered_steps("python", check=True))
        self.assertEqual(1, len(results))
        self.assertEqual(
            "tests.agent_migration_characterization",
            results[0]["command"][2],
        )
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
