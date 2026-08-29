from __future__ import annotations

import unittest

from scripts.check_installed_wheel_surface_matrix import (
    SURFACES,
    run_surface_matrix,
    semantic_signature,
)


class InstalledWheelSurfaceMatrixTests(unittest.TestCase):
    def test_semantic_signature_selects_cross_surface_contract(self) -> None:
        value = {
            "schema_version": "matrix.v1",
            "ok": False,
            "status": "blocked",
            "exit_code": 4,
            "journey": {"journey_id": "analysis.example", "version": 1},
            "can_run_status": "blocked",
            "reason_codes": ["BLOCKED"],
            "completeness": "unknown",
            "observation_count": 0,
            "network_called": False,
            "surface_private": "ignored",
        }
        signature = semantic_signature(value)
        self.assertNotIn("surface_private", signature)
        self.assertEqual("analysis.example", signature["journey_id"])

    def test_one_installed_wheel_runs_success_and_fail_closed_on_five_surfaces(self) -> None:
        result = run_surface_matrix()
        self.assertTrue(result["passed"])
        self.assertEqual(len(SURFACES), result["surface_count"])
        self.assertEqual(["success", "capability_gap"], [
            item["semantic_signature"]["status"] for item in result["cases"]
        ])
        self.assertEqual(0, result["network_calls"])
        self.assertEqual(64, len(result["wheel_sha256"]))


if __name__ == "__main__":
    unittest.main()
