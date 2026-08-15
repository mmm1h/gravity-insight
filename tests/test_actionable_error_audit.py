from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts.audit_actionable_errors import inventory


ROOT = Path(__file__).resolve().parents[1]


def test_actionable_error_inventory_is_complete_and_reproducible() -> None:
    rows = inventory(ROOT / "src" / "gravity_sdk")
    counts = Counter(item["grade"] for item in rows)
    assert len(rows) == 974
    assert counts == {"A": 56, "B": 386, "C": 532}
    assert sum(counts.values()) == len(rows)
