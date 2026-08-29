from __future__ import annotations

import unittest

from scripts.check_cumulative_capabilities import (
    CATEGORIES,
    collect_revision_snapshot,
    compare_capability_snapshots,
)


def _snapshot(**changes: list[str]) -> dict[str, list[str]]:
    value = {category: [f"{category}.one"] for category in CATEGORIES}
    value.update(changes)
    return value


class CumulativeCapabilityTests(unittest.TestCase):
    def test_additive_changes_pass_without_an_allowlist(self) -> None:
        base = _snapshot()
        head = _snapshot(public_api=["public_api.one", "public_api.two"])
        result = compare_capability_snapshots(base, head, {"allowed_losses": []})
        self.assertTrue(result["passed"])
        self.assertEqual(["public_api.two"], result["comparisons"]["public_api"]["added"])

    def test_unrecorded_loss_fails_with_exact_identity(self) -> None:
        result = compare_capability_snapshots(
            _snapshot(), _snapshot(journeys=[]), {"allowed_losses": []}
        )
        self.assertFalse(result["passed"])
        self.assertEqual(
            [{"category": "journeys", "identifier": "journeys.one"}],
            result["unrecorded_losses"],
        )

    def test_approved_recorded_loss_passes(self) -> None:
        result = compare_capability_snapshots(
            _snapshot(),
            _snapshot(operations=[]),
            {
                "allowed_losses": [
                    {
                        "category": "operations",
                        "identifier": "operations.one",
                        "recorded_in": "docs/roadmap.md",
                        "owner_review": "approved",
                    }
                ]
            },
        )
        self.assertTrue(result["passed"])
        self.assertEqual(
            ["operations.one"],
            result["comparisons"]["operations"]["approved_losses"],
        )

    def test_pending_or_stale_records_do_not_bypass_the_gate(self) -> None:
        pending = compare_capability_snapshots(
            _snapshot(),
            _snapshot(products=[]),
            {
                "allowed_losses": [
                    {
                        "category": "products",
                        "identifier": "products.one",
                        "recorded_in": "docs/roadmap.md",
                        "owner_review": "pending",
                    }
                ]
            },
        )
        stale = compare_capability_snapshots(
            _snapshot(),
            _snapshot(),
            {
                "allowed_losses": [
                    {
                        "category": "products",
                        "identifier": "products.one",
                        "recorded_in": "docs/roadmap.md",
                        "owner_review": "approved",
                    }
                ]
            },
        )
        self.assertEqual(1, len(pending["unapproved_losses"]))
        self.assertEqual(1, len(stale["unused_allowlist_records"]))
        self.assertFalse(pending["passed"] or stale["passed"])

    def test_exact_head_snapshot_exposes_every_category(self) -> None:
        commit, snapshot = collect_revision_snapshot("HEAD")
        self.assertEqual(40, len(commit))
        self.assertEqual(set(CATEGORIES), set(snapshot))
        self.assertTrue(all(snapshot[category] for category in CATEGORIES))


if __name__ == "__main__":
    unittest.main()
