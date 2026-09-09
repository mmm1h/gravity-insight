from __future__ import annotations

import copy
import json
import tempfile
from unittest.mock import patch
from pathlib import Path
import unittest

from gravity_insight.journey_ledger import (
    JourneyLedgerError,
    load_packaged_journey_ledger,
    FACTS_PATH, NOTES_PATH, load_journey_facts, load_journey_ledger,
    render_journey_ledger_markdown,
    render_journey_ledger_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "analysis-journeys.md"


class JourneyLedgerTests(unittest.TestCase):
    def test_current_ledger_preserves_every_field_and_inline_code_pipe(self):
        snapshot = load_journey_ledger()

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

    def test_packaged_snapshot_and_docs_are_deterministic_fact_projections(self):
        self.assertEqual(load_journey_ledger(), load_packaged_journey_ledger())
        self.assertEqual(LEDGER.read_text(encoding="utf-8"), render_journey_ledger_markdown())
        self.assertEqual(json.loads(render_journey_ledger_snapshot()), load_journey_ledger())

    def test_invalid_facts_and_annotation_join_fail_closed(self):
        facts = load_journey_facts()
        duplicate = copy.deepcopy(facts)
        duplicate["rows"].append(duplicate["rows"][0])
        bad_surface = copy.deepcopy(facts)
        bad_surface["rows"][0]["surfaces"] = "one / two"
        unknown = copy.deepcopy(facts)
        unknown["rows"][0]["guessed"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "facts.json"
            for value in (duplicate, bad_surface, unknown):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(), self.assertRaises(JourneyLedgerError):
                    load_journey_ledger(path)
            notes = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
            notes["notes"].pop(next(iter(notes["notes"])))
            path.write_text(json.dumps(notes), encoding="utf-8")
            with self.assertRaises(JourneyLedgerError):
                load_journey_ledger(annotations_path=path)

    def test_annotation_provenance_is_required_and_typed(self):
        notes = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
        missing = copy.deepcopy(notes)
        del missing["purpose"]
        invalid = copy.deepcopy(notes)
        invalid["baseline_commit"] = False
        extra = {**notes, "current_certification": True}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "annotations.json"
            for value in (missing, invalid, extra):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(), self.assertRaises(JourneyLedgerError):
                    load_journey_ledger(annotations_path=path)

    def test_migration_preserves_all_f4893384_row_fields_without_markdown(self):
        from gravity_insight.governance.module_graph import module_graph_canonical_sha256

        original = Path.read_text
        def without_markdown(path, *args, **kwargs):
            if path.suffix == ".md":
                raise FileNotFoundError(path)
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", without_markdown):
            rows = load_journey_ledger()["rows"]
        self.assertEqual(
            "36f77fd20e0bd03d0a894ca3bf97061a918f98abafb637bd5d2c8df0847c0d35",
            module_graph_canonical_sha256(rows),
        )

    def test_packaged_tamper_is_detected(self):
        snapshot = load_journey_ledger()
        tampered = copy.deepcopy(snapshot)
        tampered["rows"][0]["blocker_note"] = "changed"

        from gravity_insight.journey_ledger import _validate_snapshot

        with self.assertRaises(JourneyLedgerError):
            _validate_snapshot(tampered)


if __name__ == "__main__":
    unittest.main()
