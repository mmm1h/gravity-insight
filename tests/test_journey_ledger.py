from __future__ import annotations

import copy
from pathlib import Path
import unittest

from gravity_sdk.journey_ledger import (
    JourneyLedgerError,
    load_packaged_journey_ledger,
    parse_journey_ledger,
    render_journey_ledger_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "analysis-journeys.md"


class JourneyLedgerTests(unittest.TestCase):
    def test_current_ledger_preserves_every_field_and_inline_code_pipe(self):
        snapshot = parse_journey_ledger(LEDGER.read_text(encoding="utf-8"))

        self.assertEqual(69, snapshot["row_count"])
        self.assertFalse(snapshot["network_called"])
        self.assertEqual(
            len(snapshot["rows"]),
            len({row["legacy_display_key"] for row in snapshot["rows"]}),
        )
        title_package = next(
            row
            for row in snapshot["rows"]
            if "标题包" in row["display_name"]
        )
        self.assertIn(
            "`package_kind=regular\\|standard`",
            title_package["blocker_note"],
        )
        self.assertEqual("有", title_package["surfaces"]["cli"])
        first = snapshot["rows"][0]
        self.assertGreater(len(first["blocker_note"]), 1000)
        self.assertEqual(first["display_name"], first["legacy_display_key"])
        self.assertNotIn("journey_id", first)

    def test_packaged_snapshot_is_the_deterministic_docs_projection(self):
        text = LEDGER.read_text(encoding="utf-8")
        packaged = load_packaged_journey_ledger()
        parsed = parse_journey_ledger(text)

        self.assertEqual(parsed, packaged)
        self.assertEqual(
            render_journey_ledger_snapshot(text),
            render_journey_ledger_snapshot(text),
        )

    def test_malformed_or_ambiguous_tables_fail_closed(self):
        text = LEDGER.read_text(encoding="utf-8")
        cases = (
            text.replace(
                "`package_kind=regular\\|standard`",
                "`package_kind=regular\\|standard",
                1,
            ),
            text.replace(
                "| 看多步行为的转化漏斗 |",
                "| 看某事件随时间、分组和条件的变化 |",
                1,
            ),
            text.replace("有 / 有 / 有 / 有 |", "有 / 有 / 有 |", 1),
        )
        for value in cases:
            with self.subTest(), self.assertRaises(JourneyLedgerError):
                parse_journey_ledger(value)

    def test_packaged_tamper_is_detected(self):
        snapshot = parse_journey_ledger(LEDGER.read_text(encoding="utf-8"))
        tampered = copy.deepcopy(snapshot)
        tampered["rows"][0]["blocker_note"] = "changed"

        from gravity_sdk.journey_ledger import _validate_snapshot

        with self.assertRaises(JourneyLedgerError):
            _validate_snapshot(tampered)


if __name__ == "__main__":
    unittest.main()
