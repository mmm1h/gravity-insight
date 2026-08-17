from __future__ import annotations

from datetime import datetime, timezone
import unittest

from gravity_sdk.blob import BlobTransferError
from gravity_sdk.export_scope_total import classify_export_rows, pin_export_scope_total
from gravity_sdk.monetization_projection import SAFE_ROW_FIELDS


class _ListClient:
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = []

    def read(self, operation_id, inputs):
        self.calls.append((operation_id, dict(inputs)))
        return self.envelope


class ExportScopeTotalTests(unittest.TestCase):
    def test_pin_reads_one_static_page_and_keeps_create_time_total(self):
        client = _ListClient({
            "ok": True,
            "page": {"total_items": 1_212_315, "item_count": 1},
        })
        payload = {
            "app_id": 101,
            "field_map": {"AdEventTime": "事件发生时间", "ClientID": "客户ID"},
            "global_conditions": [{
                "field": "create_time",
                "operator": "RANGE_IN",
                "type": "event",
                "value": ["2026-08-16 00:00:00", "2026-08-16 23:59:59"],
            }],
            "local_conditions": [],
            "task_name": "agent-monetization-detail-export",
        }
        stamp = datetime(2026, 8, 17, 4, 0, tzinfo=timezone.utc)
        snapshot = pin_export_scope_total(
            client,
            "export.analysis.monetization_detail.start",
            payload,
            clock=lambda: stamp,
        )
        self.assertEqual(
            ("analysis.monetization_detail.list", {
                "app_id": "101",
                "date": "2026-08-16",
                "fields": list(SAFE_ROW_FIELDS),
                "page": 1,
                "page_size": 100,
            }),
            client.calls[0],
        )
        self.assertEqual(1_212_315, snapshot["known_total_items"])
        self.assertEqual("create_time_preflight", snapshot["known_total_freshness"])
        self.assertEqual("2026-08-17T04:00:00+00:00", snapshot["known_total_observed_at"])

    def test_other_export_routes_do_not_invent_a_denominator(self):
        client = _ListClient({"ok": True, "page": {"total_items": 9}})
        self.assertIsNone(
            pin_export_scope_total(client, "export.analysis.pay_event.start", {"app_id": 1})
        )
        self.assertEqual([], client.calls)

    def test_cap_hit_with_larger_pinned_total_is_truncated(self):
        audit = classify_export_rows(1_000_000, {"known_total_items": 1_212_315})
        self.assertEqual(
            (True, False, 212_315, 1_000_000, 1_212_315),
            (
                audit["truncated"],
                audit["complete"],
                audit["missing_rows"],
                audit["file_rows"],
                audit["known_total_items"],
            ),
        )

    def test_matching_below_cap_rows_are_complete(self):
        audit = classify_export_rows(217, {"known_total_items": 217})
        self.assertEqual((False, True, 0), (audit["truncated"], audit["complete"], audit["missing_rows"]))

    def test_mismatch_below_cap_is_not_complete_and_has_no_invented_gap(self):
        audit = classify_export_rows(110_966, {"known_total_items": 111_792})
        self.assertEqual(
            (False, False, None, 110_966, 111_792),
            (
                audit["truncated"],
                audit["complete"],
                audit["missing_rows"],
                audit["file_rows"],
                audit["known_total_items"],
            ),
        )

    def test_missing_total_cannot_be_classified(self):
        with self.assertRaises(BlobTransferError):
            classify_export_rows(1, {})


if __name__ == "__main__":
    unittest.main()
