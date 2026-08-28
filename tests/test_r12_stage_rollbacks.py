from __future__ import annotations

import unittest

from scripts.validate_r12_stage_rollbacks import STAGES, validate_stage_rollback


class R12StageRollbackTests(unittest.TestCase):
    def test_r12_a_rolls_back_to_its_pre_stage_tree(self) -> None:
        receipt = validate_stage_rollback(STAGES[0])
        self.assertEqual(receipt["baseline_tree"], receipt["rolled_back_tree"])

    def test_r12_b_rolls_back_to_the_complete_r12_a_tree(self) -> None:
        receipt = validate_stage_rollback(STAGES[1])
        self.assertEqual(receipt["baseline_tree"], receipt["rolled_back_tree"])

    def test_r12_c_rolls_back_to_the_complete_r12_a_b_tree(self) -> None:
        receipt = validate_stage_rollback(STAGES[2])
        self.assertEqual(receipt["baseline_tree"], receipt["rolled_back_tree"])


if __name__ == "__main__":
    unittest.main()
